import { types } from "mobx-state-tree";
import { AnnotationMixin } from "../mixins/AnnotationMixin";
import { FF_DEV_3391, isFF } from "../utils/feature-flags";
import { guidGenerator } from "../utils/unique";
import InfoModal from "../components/Infomodal/Infomodal";
import { getInterface } from "./registry";
import { createInterfaceAPI, writeNativeOutput } from "./api";
import { isSemanticallyVisible } from "./visibility";

export const InterfaceModel = types
  .compose(
    "ReactCodeModel",
    AnnotationMixin,
    types.model({
      ...(isFF(FF_DEV_3391)
        ? { id: types.identifier, name: types.maybe(types.string) }
        : { id: types.optional(types.string, guidGenerator), name: types.optional(types.identifier, guidGenerator) }),
      type: types.optional(types.literal("reactcode"), "reactcode"),
      component: types.optional(types.string, ""),
      toname: types.maybe(types.string),
      value: types.optional(types.string, ""),
      options: types.optional(types.string, ""),
      outputs: types.optional(types.string, ""),
    }),
  )
  .volatile(() => ({ runtimeErrors: new Map(), validators: new Set(), disposers: new Set() }))
  .views((self) => ({
    get runtimeError() {
      return self.runtimeErrors.get(self.annotation?.id);
    },
    get isIndependent() {
      return true;
    },
    get isVisible() {
      return true;
    },
    get holdsState() {
      return true;
    },
    get isNavigation() {
      return false;
    },
    get optionsObj() {
      const options = self.options ? JSON.parse(self.options) : {};
      if (!options || typeof options !== "object" || Array.isArray(options))
        throw new Error("Interface options must be a JSON object");
      return options;
    },
    get outputNames() {
      return self.outputs
        .split(",")
        .map((name) => name.trim())
        .filter(Boolean);
    },
  }))
  .actions((self) => ({
    setRuntimeError(error) {
      const id = self.annotation?.id;
      const errors = new Map(self.runtimeErrors);
      if (error) errors.set(id, String(error));
      else errors.delete(id);
      self.runtimeErrors = errors;
    },
    registerValidator(validate) {
      if (typeof validate !== "function") throw new Error("Validator must be a function");
      const entry = { validate, annotationId: self.annotation?.id };
      self.validators.add(entry);
      return () => self.validators.delete(entry);
    },
    trackDisposer(dispose) {
      self.disposers.add(dispose);
      return () => {
        self.disposers.delete(dispose);
        dispose();
      };
    },
    beforeDestroy() {
      for (const dispose of self.disposers) dispose();
      self.disposers.clear();
    },
    writeOutput(name, value) {
      writeNativeOutput(self, name, value);
    },
    validate() {
      try {
        // Skip inapplicable branches, but still validate inactive wizard pages.
        if (!isSemanticallyVisible(self)) return true;
        if (self.runtimeError) throw new Error(self.runtimeError);
        const definition = getInterface(self.component);
        if (!definition) throw new Error(`Interface ${self.component} is not loaded`);
        self.optionsObj;
        const api = createInterfaceAPI(self);
        if (!api.validateOutputs()) return false;
        const validators = [...self.validators]
          .filter((entry) => entry.annotationId === self.annotation?.id)
          .map((entry) => entry.validate);
        for (const validate of [definition.validate, ...validators].filter(Boolean)) {
          const result = validate(api);
          if (result?.then) throw new Error("Interface validation must be synchronous");
          if (result === false) return false;
          if (typeof result === "string") throw new Error(result);
        }
        return true;
      } catch (error) {
        InfoModal.warning(error.message);
        return false;
      }
    },
    updateResult() {},
    setResult() {},
    beforeSend() {},
  }));
