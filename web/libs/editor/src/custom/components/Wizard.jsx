import { observer } from "mobx-react";
import { useEffect, useState } from "react";

/**
 * Wizard navigation component for `<ReactCode component="wizard">`.
 *
 * Renders a step indicator + Back/Next buttons. The current page lives in the
 * tag model (`item.currentpage`); pages themselves are ordinary `View`s gated
 * by `visibleWhen="choice-selected" whenTagName=<wizard name>`. "Next" runs
 * per-page required validation before advancing; submit-time validation is
 * enforced by the model's `validate()` which walks all pages.
 */
export const HtxWizard = observer(({ item, api }) => {
  const [summary, setSummary] = useState(false);
  const steps = item.stepsList;
  const labels = item.stepLabels;
  const total = item.totalSteps;
  const page = Math.min(item.currentpage, Math.max(total, 1));
  useEffect(() => {
    const control = item
      .controlsForStep(item.currentStep)
      .find((control) => control.isVisible !== false && control.elementRef?.current);
    control?.elementRef.current
      .querySelector("input:not(:disabled),textarea:not(:disabled),select:not(:disabled),button:not(:disabled)")
      ?.focus();
  }, [item, page]);
  useEffect(() => {
    const disposers = [];
    if (item.nexthotkey) disposers.push(api.bindHotkey(item.nexthotkey, () => item.nextWithValidation()));
    if (item.prevhotkey) disposers.push(api.bindHotkey(item.prevhotkey, () => item.prev()));
    return () => disposers.forEach((dispose) => dispose());
  }, [api, item, item.nexthotkey, item.prevhotkey]);

  if (!total) {
    return <div className="lsx-wizard lsx-wizard--empty">Wizard: no steps configured</div>;
  }

  return (
    <div className="lsx-wizard">
      {item.showprogress && (
        <div className="lsx-wizard__steps">
          {steps.map((step, i) => {
            const idx = i + 1;
            const state = idx === page && !summary ? "current" : item.stepStatus(step);

            return (
              <button
                key={step}
                type="button"
                className={`lsx-wizard__step lsx-wizard__step--${state}`}
                aria-current={idx === page && !summary ? "step" : undefined}
                onClick={() => {
                  setSummary(false);
                  item.goToStep(idx);
                }}
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
        <button
          type="button"
          className="lsx-wizard__btn"
          onClick={() => {
            setSummary(false);
            item.prev();
          }}
          disabled={page <= 1}
        >
          {item.prevlabel}
        </button>
        <span className="lsx-wizard__counter" aria-live="polite">
          {page} / {total}
        </span>
        {page < total && (
          <button
            type="button"
            className="lsx-wizard__btn lsx-wizard__btn--primary"
            onClick={() => {
              setSummary(false);
              item.nextWithValidation();
            }}
          >
            {item.nextlabel}
          </button>
        )}
        {item.showsummary && page === total && (
          <button
            type="button"
            className="lsx-wizard__btn"
            onClick={() => {
              if (api.readOnly || item.validate()) setSummary(!summary);
            }}
          >
            {item.summarylabel}
          </button>
        )}
      </div>
      {summary && (
        <div className="lsx-wizard__summary">
          {item.summary.map((step) => (
            <section key={step.page}>
              <button
                type="button"
                onClick={() => {
                  setSummary(false);
                  item.goToStep(step.page);
                }}
              >
                {step.label}
              </button>
              {step.status === "skipped" ? (
                <p>Not applicable</p>
              ) : (
                <dl>
                  {step.answers.map((answer) => (
                    <div key={answer.name}>
                      <dt>{answer.name}</dt>
                      <dd>{JSON.stringify(answer.value ?? null)}</dd>
                    </div>
                  ))}
                </dl>
              )}
            </section>
          ))}
        </div>
      )}
    </div>
  );
});
