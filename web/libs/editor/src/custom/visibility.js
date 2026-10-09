import { getParent, hasParent } from "mobx-state-tree";

/**
 * Fork helpers for visibility-aware hotkeys.
 *
 * `isVisible` (VisibilityMixin) is already transitive — a node inside a hidden
 * `View` reports `isVisible === false`. Hotkey handlers, however, are bound once
 * per annotation and never consult visibility, so a hidden control still fires
 * its handler and mutates the result. These helpers let `setupHotKeys` gate
 * every bound handler: hidden controls become no-ops, which also allows reusing
 * the same key on different wizard pages.
 */

/**
 * Walk the MST parent chain (skipping the `children` array level via depth=2)
 * and report whether any ancestor — or the node itself — is currently hidden
 * by a `visibleWhen` condition.
 */
export function isHiddenInUI(node) {
  let cur = node;

  try {
    while (cur) {
      if (cur.isVisible === false) return true;
      if (!hasParent(cur, 2)) break;
      cur = getParent(cur, 2);
    }
  } catch (_e) {
    // Detached node (e.g. Taxonomy choices live in a SharedStore) — treat as visible.
  }
  return false;
}

/**
 * Wrap a tag's `onHotKey` so it no-ops while the tag is hidden.
 * Used by `setupHotKeys` instead of binding `node.onHotKey` directly.
 */
export function guardedHotkey(node) {
  return (event, key) => {
    if (isHiddenInUI(node) || isInterfaceOutput(node)) return;
    return node.onHotKey(event, key);
  };
}

// React owns these controls' interaction; their invisible native UI must not
// acquire automatically assigned shortcuts alongside the custom component.
function isInterfaceOutput(node) {
  const names = new Set(
    [...(node.annotation?.names.values() ?? [])]
      .filter((tag) => tag.outputNames && !tag.isNavigation)
      .flatMap((tag) => tag.outputNames),
  );
  let cur = node;
  while (cur) {
    if (names.has(cur.name)) return true;
    if (!hasParent(cur, 2)) break;
    cur = getParent(cur, 2);
  }
  return false;
}

/**
 * Evaluate whether a node's *own* `visibleWhen`/`whenChoiceValue` condition
 * fails, independently of its ancestors' visibility.
 *
 * Wizard page wrappers (`visibleWhen` + `whenTagName` pointing at a
 * `reactcode` model) are page-navigation gating, not semantic hiding —
 * they are treated as "never failing" here so a control on an inactive page
 * can still serve as the driver tag of a `choice-selected`/`whenChoiceValue`
 * condition on another page.
 */
function ownConditionFails(node, annotation) {
  const visiblewhen = node.visiblewhen;

  if (visiblewhen === "choice-selected" || visiblewhen === "choice-unselected") {
    const whentagname = node.whentagname;
    const tag = whentagname ? annotation.names.get(whentagname) : undefined;

    if (tag?.isNavigation) return false;

    let res;

    if (!whentagname) {
      res = [...annotation.names.values()].some((c) => c.type === "choices" && c.selectedValues?.().length);
    } else if (!tag) {
      res = false;
    } else {
      res =
        isSemanticallyVisible(tag) &&
        (tag.hasChoiceSelection?.(node.whenchoicevalue?.split(","), tag.selectedValues?.()) ?? false);
    }
    return visiblewhen === "choice-selected" ? res === false : res === true;
  }

  if (visiblewhen) {
    const area = annotation.highlightedNode;

    if (visiblewhen === "no-region-selected") return !!area;
    if (visiblewhen === "region-selected") {
      const tagName = node.whentagname;

      if (!area || (tagName && area.labeling?.from_name?.name !== tagName)) return true;
      if (node.whenlabelvalue) return !node.whenlabelvalue.split(",").some((value) => area.hasLabel(value));
      if (node.whenrole) return !node.whenrole.split(",").some((value) => area.chatmessage?.role === value);
      return false;
    }
    return false;
  }

  if (node.whenchoicevalue?.length) {
    for (const choices of annotation.names.values()) {
      if (choices?.selectedValues?.()?.includes(node.whenchoicevalue)) return false;
    }
    return true;
  }
  return false;
}

/**
 * `true` when a node reports `isVisible === false` solely because of wizard
 * page gating — i.e. no ancestor (nor the node itself) has a *failing* real
 * `visibleWhen`/`whenChoiceValue` condition of its own.
 *
 * Used to relax `VisibilityMixin`'s "hide dependents of a hidden driver tag"
 * rule: a driver tag parked on an inactive wizard page is still evaluated
 * against its actual selection instead of force-hiding every dependent.
 * A driver tag hidden by a genuine condition keeps the upstream behaviour.
 */
export function isHiddenOnlyByWizard(node) {
  try {
    return hasWizardAncestor(node) && isSemanticallyVisible(node);
  } catch (_e) {
    return false;
  }
}

export function hasWizardAncestor(node) {
  let cur = node;
  while (cur) {
    const driver = cur.whentagname && node.annotation?.names.get(cur.whentagname);
    if (driver?.isNavigation && ["choice-selected", "choice-unselected"].includes(cur.visiblewhen)) return true;
    if (!hasParent(cur, 2)) break;
    cur = getParent(cur, 2);
  }
  return false;
}

// Ignore navigation gates while preserving real conditions, including hidden drivers.
// A cycle is an invalid condition dependency and is treated as not applicable.
const evaluating = new Set();
export function isSemanticallyVisible(node) {
  if (!node?.annotation || evaluating.has(node)) return false;
  evaluating.add(node);
  try {
    let cur = node;
    while (cur) {
      if (ownConditionFails(cur, node.annotation)) return false;
      if (!hasParent(cur, 2)) break;
      cur = getParent(cur, 2);
    }
    return true;
  } finally {
    evaluating.delete(node);
  }
}
