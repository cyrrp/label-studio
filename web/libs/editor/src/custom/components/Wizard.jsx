import { observer } from "mobx-react";
import { useEffect, useMemo } from "react";

import { Hotkey } from "../../core/Hotkey";

function isAnnotationReadOnly(annotation) {
  return typeof annotation?.isReadOnly === "function" && annotation.isReadOnly();
}

/**
 * Wizard navigation component for `<CustomInterface component="wizard">`.
 *
 * Renders a step indicator + Back/Next buttons. The current page lives in the
 * tag model (`item.currentpage`); pages themselves are ordinary `View`s gated
 * by `visibleWhen="choice-selected" whenTagName=<wizard name>`. "Next" runs
 * per-page required validation before advancing; submit-time validation is
 * enforced by the model's `validate()` which walks all pages.
 */
export const HtxWizard = observer(({ item }) => {
  const steps = item.stepsList;
  const labels = item.stepLabels;
  const total = item.totalSteps;
  const page = Math.min(item.currentpage, Math.max(total, 1));
  const readOnly = isAnnotationReadOnly(item.annotation);

  const hotkeys = useMemo(() => Hotkey(`custom-wizard:${item.id}`), [item.id]);

  useEffect(() => {
    if (item.nexthotkey) hotkeys.addKey(item.nexthotkey, () => item.nextWithValidation());
    if (item.prevhotkey) hotkeys.addKey(item.prevhotkey, () => item.prev());

    return () => hotkeys.unbindAll();
  }, [item.nexthotkey, item.prevhotkey]);

  if (!total) {
    return <div className="lsx-wizard lsx-wizard--empty">Wizard: no steps configured</div>;
  }

  return (
    <div className="lsx-wizard">
      {item.showprogress && (
        <div className="lsx-wizard__steps">
          {steps.map((step, i) => {
            const idx = i + 1;
            const state = idx === page ? "current" : idx < page ? "done" : "todo";

            return (
              <button
                key={step}
                type="button"
                className={`lsx-wizard__step lsx-wizard__step--${state}`}
                disabled={readOnly}
                onClick={() => item.goToStep(idx)}
                title={labels[i]}
              >
                <span className="lsx-wizard__num">{idx}</span>
                <span className="lsx-wizard__label">{labels[i]}</span>
              </button>
            );
          })}
        </div>
      )}

      <div className="lsx-wizard__nav">
        <button type="button" className="lsx-wizard__btn" onClick={() => item.prev()} disabled={readOnly || page <= 1}>
          {item.prevlabel}
        </button>
        <span className="lsx-wizard__counter">
          {page} / {total}
        </span>
        {page < total && (
          <button
            type="button"
            className="lsx-wizard__btn lsx-wizard__btn--primary"
            onClick={() => item.nextWithValidation()}
            disabled={readOnly}
          >
            {item.nextlabel}
          </button>
        )}
      </div>
    </div>
  );
});
