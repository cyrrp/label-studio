import { getParent, hasParent, types } from "mobx-state-tree";
import { observer } from "mobx-react";

import Registry from "../core/Registry";
import Tree from "../core/Tree";
import { AnnotationMixin } from "../mixins/AnnotationMixin";
import { FF_DEV_3391, isFF } from "../utils/feature-flags";
import { guidGenerator } from "../utils/unique";
import { CUSTOM_COMPONENTS } from "./components";

/**
 * `<CustomInterface>` — real implementation for the OSS fork.
 *
 * Upstream registers an "Enterprise only" placeholder in `tags/Custom.jsx`
 * guarded by `!Registry.models.custominterface`; this module replaces the
 * registered model/view, so the placeholder never activates. The tag is a
 * dispatcher: `component` selects a React component from `custom/components`.
 *
 * The model doubles as a choices-like state holder: it exposes
 * `selectedValues()`/`hasChoiceSelection()` driven by the current wizard page,
 * so plain `visibleWhen="choice-selected" whenTagName="<name>"` blocks act as
 * wizard pages without any upstream changes.
 *
 * @example
 * <CustomInterface component="wizard" name="wz"
 *                  steps="modality,details,extra"
 *                  steplabels="Модальность,Детали,Комментарии"
 *                  nextlabel="Далее →" prevlabel="← Назад"/>
 * <View visibleWhen="choice-selected" whenTagName="wz" whenChoiceValue="modality">…</View>
 */
const TagAttrs = types.model({
  toname: types.maybe(types.string),
  component: types.optional(types.string, ""),
  // Inline text content of the tag lands here (see Tree.tagIntoObject)
  value: types.optional(types.string, ""),
  // JSON escape hatch for component-specific settings
  options: types.optional(types.string, ""),

  // wizard component attrs
  steps: types.optional(types.string, ""),
  steplabels: types.optional(types.string, ""),
  nextlabel: types.optional(types.string, "Next →"),
  prevlabel: types.optional(types.string, "← Back"),
  nexthotkey: types.optional(types.string, "alt+right"),
  prevhotkey: types.optional(types.string, "alt+left"),
  validateonnext: types.optional(types.boolean, true),
  showprogress: types.optional(types.boolean, true),
});

const Model = types
  .model({
    // Mirrors ObjectBase (tags/object/Base.js): under FF_DEV_3391 `id` is the
    // identifier and the parser pre-fills it with `name`; otherwise `name`
    // itself is the identifier so `annotation.names` stays keyed by name.
    ...(isFF(FF_DEV_3391)
      ? {
          id: types.identifier,
          name: types.maybe(types.string),
        }
      : {
          id: types.optional(types.string, guidGenerator),
          name: types.optional(types.identifier, guidGenerator),
        }),
    type: "custominterface",
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
    // Always "visible" itself; never produces a result
    get isVisible() {
      return true;
    },
    get isSelected() {
      return self.currentpage > 0;
    },
    get isIndependent() {
      return true;
    },
    get holdsState() {
      return true;
    },
    get optionsObj() {
      try {
        return self.options ? JSON.parse(self.options) : {};
      } catch (_e) {
        return {};
      }
    },
    // -- choices-like interface for `visibleWhen` lookups (Visibility.js) --
    selectedValues() {
      return self.currentStep ? [self.currentStep] : [];
    },
    hasChoiceSelection(choiceValue, selectedValues = []) {
      if (choiceValue?.length) {
        const sel = selectedValues.length ? selectedValues : self.selectedValues();

        return choiceValue.some((v) => sel.includes(v));
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
  }))
  .actions((self) => ({
    goTo(page) {
      self.currentpage = Math.max(1, Math.min(page, self.totalSteps || 1));
    },
    next() {
      self.goTo(self.currentpage + 1);
    },
    prev() {
      self.goTo(self.currentpage - 1);
    },
    nextWithValidation() {
      if (self.validateonnext) {
        for (const c of self.controlsForStep(self.currentStep)) {
          if (c.validate?.() === false) return false;
        }
      }
      self.next();
      return true;
    },
    goToStep(target) {
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
      if (!self.totalSteps || !self.annotation) return true;

      for (let i = 1; i <= self.totalSteps; i++) {
        self.goTo(i);
        for (const c of self.controlsForStep(self.currentStep)) {
          if (c.validate?.() === false) return false;
        }
      }
      return true;
    },
    // API compat with control tags — this tag never produces results
    updateResult() {},
    setResult() {},
    beforeSend() {},
  }));

// NOTE: composed name must stay "CustomInterfaceModel" — the OSS stub registers
// it as an object type under this name, and views_models lookup is by type name.
const CustomInterfaceModel = types.compose("CustomInterfaceModel", TagAttrs, Model, AnnotationMixin);

const HtxCustomInterface = observer(({ item }) => {
  const Comp = CUSTOM_COMPONENTS[item.component];

  if (!Comp) {
    return (
      <div className="lsx-custom lsx-custom--unknown">
        CustomInterface: unknown component <code>{item.component || "(empty)"}</code>. Available:{" "}
        {Object.keys(CUSTOM_COMPONENTS).join(", ")}
      </div>
    );
  }

  return <Comp item={item} />;
});

Registry.addTag("custominterface", CustomInterfaceModel, HtxCustomInterface);

export { CustomInterfaceModel, HtxCustomInterface };
