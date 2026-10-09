import { getParent, hasParent, types } from "mobx-state-tree";
import Tree from "../core/Tree";
import { InterfaceModel } from "./InterfaceModel";
import InfoModal from "../components/Infomodal/Infomodal";
import { isSemanticallyVisible } from "./visibility";

// Legacy XML attributes live with the wizard, not the generic interface model.
const WizardMixin = types
  .model({
    steps: types.optional(types.string, ""),
    steplabels: types.optional(types.string, ""),
    nextlabel: types.optional(types.string, "Next →"),
    prevlabel: types.optional(types.string, "← Back"),
    nexthotkey: types.optional(types.string, "alt+right"),
    prevhotkey: types.optional(types.string, "alt+left"),
    validateonnext: types.optional(types.boolean, true),
    showprogress: types.optional(types.boolean, true),
    skipempty: types.optional(types.boolean, false),
    showsummary: types.optional(types.boolean, false),
    summarylabel: types.optional(types.string, "Review answers"),
  })
  .volatile(() => ({
    currentpage: 1,
  }))
  .views((self) => ({
    get stepsList() {
      return self.steps
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean);
    },
    get stepLabels() {
      const labels = self.steplabels
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean);

      return labels.length === self.stepsList.length ? labels : self.stepsList;
    },
    get totalSteps() {
      return self.stepsList.length;
    },
    get currentStep() {
      return self.stepsList[self.currentpage - 1] ?? null;
    },
    get isNavigation() {
      return true;
    },
    get isSelected() {
      return self.currentpage > 0;
    },
    // -- choices-like interface for `visibleWhen` lookups (Visibility.js) --
    selectedValues() {
      return self.currentStep ? [self.currentStep] : [];
    },
    hasChoiceSelection(choiceValue, selectedValues = []) {
      if (choiceValue?.length) {
        const sel = selectedValues.length ? selectedValues : self.selectedValues();

        return choiceValue.some((v) => sel.includes(v.trim()));
      }
      return self.isSelected;
    },
    /**
     * Values of the nearest ancestor View whose visibility is driven by this
     * wizard (`visibleWhen="choice-selected" whenTagName=<this name>`), or null
     * when the node is not gated by the wizard at all.
     */
    wizardPageOf(node) {
      let cur = node;

      try {
        while (cur) {
          if (cur.visiblewhen === "choice-selected" && cur.whentagname === self.name) {
            return (cur.whenchoicevalue ?? "")
              .split(",")
              .map((s) => s.trim())
              .filter(Boolean);
          }
          if (!hasParent(cur, 2)) break;
          cur = getParent(cur, 2);
        }
      } catch (_e) {
        // detached node
      }
      return null;
    },
    /**
     * Controls living on the given wizard page (their visibility is bound to
     * this wizard). A page View without `whenChoiceValue` matches every step.
     */
    controlsForStep(stepValue) {
      const res = [];
      const annotation = self.annotation;

      if (!annotation?.root) return res;

      Tree.traverseTree(annotation.root, (node) => {
        if (node === self || typeof node.validate !== "function") return;
        const pages = self.wizardPageOf(node);

        if (pages && (pages.length === 0 || pages.includes(stepValue))) res.push(node);
      });
      return res;
    },
    stepStatus(stepValue) {
      const controls = self
        .controlsForStep(stepValue)
        .filter((node) => node.isControlTag && isSemanticallyVisible(node));
      if (!controls.length) return "skipped";
      if (controls.some((node) => node.required && !node.holdsState)) return "todo";
      return controls.some((node) => node.holdsState) ? "done" : "todo";
    },
    get summary() {
      return self.stepsList.map((step, index) => ({
        page: index + 1,
        label: self.stepLabels[index],
        status: self.stepStatus(step),
        answers: self
          .controlsForStep(step)
          .filter((node) => node.isControlTag && isSemanticallyVisible(node) && node.selectedValues)
          .map((node) => ({ name: node.name, value: node.selectedValues() })),
      }));
    },
  }))
  .actions((self) => {
    const validateInterface = self.validate;
    return {
      goTo(page) {
        self.currentpage = Math.max(1, Math.min(Number.isFinite(page) ? Math.floor(page) : 1, self.totalSteps || 1));
      },
      next() {
        let page = self.currentpage + 1;
        while (self.skipempty && page < self.totalSteps && self.stepStatus(self.stepsList[page - 1]) === "skipped")
          page++;
        self.goTo(page);
      },
      prev() {
        let page = self.currentpage - 1;
        while (self.skipempty && page > 1 && self.stepStatus(self.stepsList[page - 1]) === "skipped") page--;
        self.goTo(page);
      },
      nextWithValidation() {
        if (self.validateonnext && !self.annotation?.isReadOnly()) {
          for (const c of self.controlsForStep(self.currentStep)) {
            if (c.validate?.() === false) return false;
          }
        }
        self.next();
        return true;
      },
      goToStep(target) {
        target = Math.max(1, Math.min(Number.isFinite(target) ? Math.floor(target) : 1, self.totalSteps || 1));
        if (self.annotation?.isReadOnly()) return self.goTo(target);
        if (target <= self.currentpage) return self.goTo(target);
        while (self.currentpage < target) {
          if (!self.nextWithValidation()) return;
        }
      },
      /**
       * Called by `annotation.validate()` on submit. Steps through every page so
       * `isVisible`-aware control validation runs against each page in turn —
       * this is what enforces required answers on pages the user never visited.
       * Stops (and lands) on the first failing page.
       */
      validate() {
        if (!validateInterface()) return false;
        if (!self.totalSteps || new Set(self.stepsList).size !== self.totalSteps) {
          InfoModal.warning("Wizard steps must be non-empty and unique");
          return false;
        }
        const originalPage = self.currentpage;
        if (!self.totalSteps || !self.annotation) return true;

        for (let i = 1; i <= self.totalSteps; i++) {
          self.goTo(i);
          for (const c of self.controlsForStep(self.currentStep)) {
            if (c.validate?.() === false) return false;
          }
        }
        self.goTo(originalPage);
        return true;
      },
      // API compat with control tags — this tag never produces results
      updateResult() {},
      setResult() {},
      beforeSend() {},
    };
  });

export const WizardInterfaceModel = types.compose("WizardInterfaceModel", InterfaceModel, WizardMixin);
