"""This file and its contents are licensed under the Apache License 2.0. Please see the included NOTICE for copyright information and LICENSE for a copy of the license.
"""
"""Annotator agreement (inter-annotator agreement, IAA) for tasks.

Community Edition implementation of per-task agreement. Everything agreement
related lives in this module:

* :func:`annotation_agreement` - pairwise score between two annotation results.
* :func:`get_task_agreement` - mean pairwise score over a task's finished
  annotator annotations, stored on ``Task.precomputed_agreement``.
* :func:`get_tasks_agreement_queryset` - queryset annotator used by
  ``settings.GET_TASKS_AGREEMENT_QUERYSET``; consumers are
  ``data_manager.managers.annotated_completed_at_considering_agreement_threshold``
  and ``projects.functions.next_task`` (both gated on ``lse_project``).
* :func:`update_task_agreement` / :func:`update_tasks_agreement` - persist the
  computed score without going through ``Task.save()``.
* ``on_annotation_*`` receivers - recompute triggers wired in
  ``tasks.apps.TasksConfig.ready()``.

Scale convention
----------------
``Task.precomputed_agreement`` stores the raw score in ``[0, 1]`` (this matches
the EE metric contract: custom agreement metrics return "a float between 0 and
1" and EE docs quote pair scores of ``0``/``1``). The interfaces Enterprise
exposes as percentages - the Data Manager ``agreement`` column/filter and the
``lse_project.agreement_threshold`` comparisons done on the ``_agreement``
annotation - use ``[0, 100]``. The ``x100`` conversion happens in
:func:`get_tasks_agreement_queryset` and
``data_manager.managers.annotate_agreement``, never in storage.

Scope decisions (vs Enterprise)
-------------------------------
* Ground truth annotations do NOT participate: EE's task agreement compares
  annotators only.
* Cancelled annotations and annotations with ``result=None`` are excluded.
* Two annotations are a "pair" even when created by the same user (EE averages
  over annotation pairs, not user pairs).
* Region matching is greedy IoU >= 0.5 on bounding boxes (rectanglelabels
  directly, polygonlabels/ellipselabels via their bounding box); matched
  regions score by label-set Jaccard, unmatched regions score 0. This is a
  pragmatic subset of EE's metric suite (no kappa, no exact-match mode, no
  per-label weights from ``project.control_weights``).
"""
import itertools
import logging
from typing import Any, Dict, List, Optional, Tuple

import ujson as json
from django.db.models import Count, ExpressionWrapper, F, FloatField, Q, QuerySet, Value

logger = logging.getLogger(__name__)

# Regions are matched between two annotations when their IoU is at least this
REGION_IOU_THRESHOLD = 0.5

# Annotation fields whose change can alter the agreement score
AGREEMENT_RELEVANT_FIELDS = {'result', 'was_cancelled', 'ground_truth', 'completed_by', 'task', 'task_id'}

# Filter applied to annotations that participate in task agreement:
# finished annotator work only (no skips, no empty results, no ground truths)
Q_AGREEMENT_ANNOTATIONS = (
    Q(annotations__was_cancelled=False)
    & Q(annotations__result__isnull=False)
    & Q(annotations__ground_truth=False)
)

# Scalar payload keys tried when ``value[<type>]`` is missing
_SCALAR_PAYLOAD_KEYS = ('selected', 'rating', 'number', 'datetime', 'text')


def _norm_result(result: Any) -> List[dict]:
    """Normalize ``Annotation.result`` to a list of result-item dicts."""
    if result is None:
        return []
    if isinstance(result, str):
        try:
            result = json.loads(result)
        except (ValueError, TypeError):
            return []
    if isinstance(result, dict):
        result = [result]
    if not isinstance(result, list):
        return []
    return [item for item in result if isinstance(item, dict)]


def _hashable(value: Any) -> Any:
    """Make a JSON payload value usable as a set member (for Jaccard)."""
    try:
        hash(value)
        return value
    except TypeError:
        pass
    if isinstance(value, (list, tuple)):
        return tuple(_hashable(v) for v in value)
    if isinstance(value, dict):
        return tuple(sorted((k, _hashable(v)) for k, v in value.items()))
    return repr(value)


def _result_item_payload(item: dict) -> frozenset:
    """Extract the comparable label/value payload of a result item as a frozenset.

    For most controls the payload lives at ``value[item['type']]``
    (``value['choices']``, ``value['labels']``, ``value['rectanglelabels']``,
    ``value['taxonomy']``, ``value['textarea']``...). Scalars
    (``value['rating']``, ``value['number']``, ``value['selected']``) become
    single-element sets so a Jaccard on them degrades to exact equality.
    """
    value = item.get('value')
    if not isinstance(value, dict):
        return frozenset()

    result_type = item.get('type') or ''
    payload = value.get(result_type)

    if payload is None:
        for key in _SCALAR_PAYLOAD_KEYS:
            if key in value:
                payload = value[key]
                break

    if payload is None:
        return frozenset()
    if isinstance(payload, (list, tuple)):
        return frozenset(_hashable(v) for v in payload)
    return frozenset((_hashable(payload),))


def _item_bbox(item: dict) -> Optional[Tuple[float, float, float, float]]:
    """Bounding box ``(x1, y1, x2, y2)`` for region result items, else ``None``.

    Covered: rectanglelabels (x/y/width/height), polygonlabels (bounding box of
    ``value['points']``), ellipselabels (x/y center + radiusX/radiusY).
    """
    value = item.get('value')
    if not isinstance(value, dict):
        return None

    try:
        if all(k in value for k in ('x', 'y', 'width', 'height')):
            x, y, w, h = float(value['x']), float(value['y']), float(value['width']), float(value['height'])
            return (x, y, x + w, y + h)

        points = value.get('points')
        if isinstance(points, list) and points:
            xs = [float(p[0]) for p in points]
            ys = [float(p[1]) for p in points]
            return (min(xs), min(ys), max(xs), max(ys))

        if all(k in value for k in ('x', 'y', 'radiusX', 'radiusY')):
            x, y = float(value['x']), float(value['y'])
            rx, ry = float(value['radiusX']), float(value['radiusY'])
            return (x - rx, y - ry, x + rx, y + ry)
    except (TypeError, ValueError, IndexError):
        return None

    return None


def _iou(a: Tuple[float, float, float, float], b: Tuple[float, float, float, float]) -> float:
    ix1, iy1 = max(a[0], b[0]), max(a[1], b[1])
    ix2, iy2 = min(a[2], b[2]), min(a[3], b[3])
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    if inter <= 0:
        return 0.0
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def _jaccard(a: frozenset, b: frozenset) -> float:
    if not a and not b:
        return 1.0  # both empty: identical payloads
    union = a | b
    if not union:
        return 1.0
    return len(a & b) / len(union)


def _region_unit_score(items_a: List[dict], items_b: List[dict]) -> float:
    """Score a control whose result items are regions.

    Greedy matching of region pairs by IoU >= REGION_IOU_THRESHOLD; a matched
    pair scores the Jaccard of its label payload sets, unmatched regions score
    0. Denominator is the union size (len_a + len_b - matched).
    """
    boxes_a = [_item_bbox(item) for item in items_a]
    boxes_b = [_item_bbox(item) for item in items_b]

    candidates = []
    for i, box_a in enumerate(boxes_a):
        if box_a is None:
            continue
        for j, box_b in enumerate(boxes_b):
            if box_b is None:
                continue
            iou = _iou(box_a, box_b)
            if iou >= REGION_IOU_THRESHOLD:
                candidates.append((iou, i, j))

    candidates.sort(key=lambda c: c[0], reverse=True)

    used_a, used_b = set(), set()
    matched_score = 0.0
    matched = 0
    for _, i, j in candidates:
        if i in used_a or j in used_b:
            continue
        used_a.add(i)
        used_b.add(j)
        matched += 1
        matched_score += _jaccard(_result_item_payload(items_a[i]), _result_item_payload(items_b[j]))

    union_size = len(items_a) + len(items_b) - matched
    if union_size <= 0:
        return 0.0
    return matched_score / union_size


def _unit_score(items_a: List[dict], items_b: List[dict]) -> float:
    """Score a single (from_name, type) control group between two annotations.

    * Control present in only one annotation -> 0.
    * Region items -> IoU matching.
    * Otherwise -> Jaccard over the union of each annotation's payload sets.
    """
    if not items_a or not items_b:
        return 0.0

    if any(_item_bbox(item) is not None for item in itertools.chain(items_a, items_b)):
        return _region_unit_score(items_a, items_b)

    payload_a = frozenset().union(*(_result_item_payload(item) for item in items_a)) if items_a else frozenset()
    payload_b = frozenset().union(*(_result_item_payload(item) for item in items_b)) if items_b else frozenset()
    return _jaccard(payload_a, payload_b)


def _group_units(result: List[dict]) -> Dict[Tuple[str, str], List[dict]]:
    """Group result items by (from_name, type); each group is one comparison unit."""
    units: Dict[Tuple[str, str], List[dict]] = {}
    for item in result:
        key = (item.get('from_name') or '', item.get('type') or '')
        units.setdefault(key, []).append(item)
    return units


def annotation_agreement(result_a: Any, result_b: Any) -> float:
    """Pairwise agreement between two annotation results, in ``[0, 1]``.

    The pair score is the mean over the union of (from_name, type) control
    units of each unit's score. Two empty results count as full agreement
    (both annotators submitted nothing), an empty vs non-empty result as 0.
    """
    units_a = _group_units(_norm_result(result_a))
    units_b = _group_units(_norm_result(result_b))

    if not units_a and not units_b:
        return 1.0

    scores = [_unit_score(units_a.get(key, []), units_b.get(key, [])) for key in set(units_a) | set(units_b)]
    return sum(scores) / len(scores) if scores else 0.0


def get_task_agreement(task) -> Optional[float]:
    """Mean pairwise agreement over the task's finished annotator annotations.

    Returns ``None`` when the task has fewer than two eligible annotations
    (non-cancelled, non-empty ``result``, non-ground-truth, authored), i.e.
    the score is not computable. Score is in ``[0, 1]``.
    """
    annotations = list(
        task.annotations.filter(was_cancelled=False, ground_truth=False, completed_by__isnull=False)
        .exclude(result__isnull=True)
        .values_list('result', flat=True)
    )

    if len(annotations) < 2:
        return None

    pair_scores = [
        annotation_agreement(annotations[i], annotations[j])
        for i in range(len(annotations))
        for j in range(i + 1, len(annotations))
    ]
    return sum(pair_scores) / len(pair_scores) if pair_scores else None


def update_task_agreement(task) -> Optional[float]:
    """Recompute ``task.precomputed_agreement`` and persist it.

    Uses ``queryset.update`` instead of ``task.save()`` to avoid re-entering
    save signals / FSM transitions / counter updates. The in-memory instance is
    kept in sync when it's a real Task object.
    """
    from tasks.models import Task

    task_id = task.pk if hasattr(task, 'pk') else task
    if task_id is None:
        return None

    task = task if isinstance(task, Task) else Task.objects.get(pk=task_id)
    agreement = get_task_agreement(task)
    Task.objects.filter(pk=task_id).update(precomputed_agreement=agreement)
    task.precomputed_agreement = agreement
    return agreement


def update_tasks_agreement(tasks_or_ids) -> int:
    """Recompute ``precomputed_agreement`` for a queryset/iterable of tasks or ids."""
    from tasks.models import Task

    if tasks_or_ids is None:
        return 0
    if isinstance(tasks_or_ids, Task):
        tasks_or_ids = [tasks_or_ids.pk]

    if isinstance(tasks_or_ids, (QuerySet,)):
        task_ids = list(tasks_or_ids.values_list('pk', flat=True))
    else:
        task_ids = [t.pk if isinstance(t, Task) else t for t in tasks_or_ids]

    updated = 0
    for task_id in set(task_ids):
        if task_id is None:
            continue
        try:
            update_task_agreement(task_id)
            updated += 1
        except Task.DoesNotExist:
            continue
    return updated


def get_tasks_agreement_queryset(queryset):
    """Annotate tasks with ``_agreement`` (percent, 0-100) and ``annotator_count``.

    Consumed via ``settings.GET_TASKS_AGREEMENT_QUERYSET`` by
    ``data_manager.managers.annotated_completed_at_considering_agreement_threshold``
    and ``projects.functions.next_task``; both compare ``_agreement`` against
    ``lse_project.agreement_threshold`` which is a percentage, hence the *100
    on the stored ``[0, 1]`` score. ``annotator_count`` counts distinct
    annotators with finished non-ground-truth annotations (NULL completed_by
    is ignored by COUNT DISTINCT).
    """
    return queryset.annotate(
        _agreement=ExpressionWrapper(F('precomputed_agreement') * Value(100.0), output_field=FloatField()),
        annotator_count=Count('annotations__completed_by', distinct=True, filter=Q_AGREEMENT_ANNOTATIONS),
    )


def _recompute_for_task(task_id) -> None:
    from tasks.models import Task

    try:
        update_task_agreement(Task.objects.get(pk=task_id))
    except Task.DoesNotExist:
        return
    except Exception as exc:  # pragma: no cover - defensive: never break saves
        logger.warning(f'Failed to update agreement for task {task_id}: {exc}', exc_info=True)


def on_annotation_saved_update_agreement(sender, instance, update_fields=None, **kwargs):
    """post_save on Annotation: recompute when agreement-relevant fields changed."""
    if update_fields is not None and AGREEMENT_RELEVANT_FIELDS.isdisjoint(update_fields):
        return
    task_id = getattr(instance, 'task_id', None)
    if task_id:
        _recompute_for_task(task_id)


def on_annotation_deleted_update_agreement(sender, instance, **kwargs):
    """post_delete on Annotation: recompute for the remaining annotations."""
    task_id = getattr(instance, 'task_id', None)
    if task_id:
        _recompute_for_task(task_id)


def on_annotations_bulk_created_update_agreement(sender, objs, **kwargs):
    """post_bulk_create on AnnotationManager: bulk imports bypass post_save."""
    task_ids = {getattr(obj, 'task_id', None) for obj in (objs or [])}
    task_ids.discard(None)
    for task_id in task_ids:
        _recompute_for_task(task_id)
