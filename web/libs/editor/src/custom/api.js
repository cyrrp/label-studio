import { getRoot, isAlive } from "mobx-state-tree";
import { Hotkey } from "../core/Hotkey";
import InfoModal from "../components/Infomodal/Infomodal";
import { guidGenerator } from "../utils/unique";
import { isHiddenInUI, isSemanticallyVisible } from "./visibility";

const copy = (value) => (value === undefined ? undefined : JSON.parse(JSON.stringify(value)));

/** API v1 writes native task-level controls; no private MST nodes cross the API. */
export function createInterfaceAPI(item) {
  const owner = item.annotation;
  const resources = new Set();
  const annotation = () => {
    if (!isAlive(item) || !isAlive(owner) || item.annotation !== owner)
      throw new Error("Interface is no longer attached to an annotation");
    return owner;
  };
  const control = (name) => {
    const ann = annotation();
    if (!item.outputNames.includes(name)) throw new Error(`Undeclared output: ${name}`);
    const tag = ann.names.get(name);
    if (!tag || !["choices", "textarea", "number"].includes(tag.type) || tag.perregion || tag.peritem) {
      throw new Error(`Output ${name} must reference a task-level Choices, TextArea or Number`);
    }
    return tag;
  };
  const track = (dispose) => {
    let active = true;
    const release = item.trackDisposer(() => {
      if (active) {
        active = false;
        dispose();
      }
    });
    const cleanup = () => {
      resources.delete(cleanup);
      release();
    };
    resources.add(cleanup);
    return cleanup;
  };
  const api = {
    apiVersion: 1,
    get name() {
      return item.name;
    },
    get task() {
      const task = getRoot(annotation()).task;
      return { id: task?.id, data: copy(task?.dataObj ?? {}) };
    },
    get config() {
      return copy(item.optionsObj);
    },
    get readOnly() {
      return annotation().isReadOnly();
    },
    get outputs() {
      return [...item.outputNames];
    },
    getValue(name) {
      return copy(control(name).selectedValues());
    },
    setValue(name, value) {
      annotation();
      item.writeOutput(name, value);
    },
    clearValue(name) {
      annotation();
      item.writeOutput(name, null);
    },
    validateOutputs() {
      return item.outputNames.every((name) => control(name).validate() !== false);
    },
    isApplicable(name) {
      return isSemanticallyVisible(control(name));
    },
    registerValidator(validate) {
      annotation();
      return track(item.registerValidator(validate));
    },
    notify(message) {
      InfoModal.warning(String(message));
    },
    // Every alias gets its own binding: core Hotkey's cleanup expects individual keys.
    bindHotkey(keys, callback) {
      annotation();
      const hotkeys = Hotkey(`custom-interface:${guidGenerator()}`);
      for (const key of keys
        .split(",")
        .map((key) => key.trim())
        .filter(Boolean)) {
        hotkeys.addKey(key, (event) => {
          if (
            !isAlive(item) ||
            !item.annotation ||
            item.annotation !== owner ||
            isHiddenInUI(item) ||
            getRoot(item).annotationStore.selected !== owner
          )
            return;
          callback(event);
        });
      }
      const dispose = () => hotkeys.unbindAll();
      return track(dispose);
    },
    dispose() {
      for (const cleanup of [...resources]) cleanup();
    },
  };
  return Object.freeze(api);
}

export function writeNativeOutput(item, name, value) {
  const api = createInterfaceAPI(item);
  // Validate the declaration/type before modifying anything.
  api.getValue(name);
  const ann = item.annotation;
  const tag = ann.names.get(name);
  if (ann.isReadOnly() || tag.readonly || tag.isReadOnly?.()) throw new Error("Annotation is read-only");
  if (tag.type === "choices" && value !== null) {
    if (!Array.isArray(value) || value.some((v) => typeof v !== "string" || !tag.findLabel(v))) {
      throw new Error(`Invalid choices for ${name}`);
    }
    if (tag.choice !== "multiple" && value.length > 1) throw new Error(`Output ${name} accepts one choice`);
  }
  if (
    tag.type === "textarea" &&
    value !== null &&
    typeof value !== "string" &&
    (!Array.isArray(value) || value.some((v) => typeof v !== "string"))
  )
    throw new Error(`Invalid text for ${name}`);
  if (tag.type === "number" && value !== null && (typeof value !== "number" || !Number.isFinite(value))) {
    throw new Error(`Invalid number for ${name}`);
  }
  if (tag.type === "number" && value !== null && tag.validateValue(value) === false)
    throw new Error(`Invalid number for ${name}`);
  if (tag.type === "textarea" && value !== null) {
    const texts = Array.isArray(value) ? value : [value];
    if (tag.maxsubmissions && texts.length > Number(tag.maxsubmissions))
      throw new Error(`Too many text entries for ${name}`);
    if (tag.skipduplicates && new Set(texts.map((text) => text.toLowerCase())).size !== texts.length)
      throw new Error(`Duplicate text entries for ${name}`);
  }
  const empty = value === null || value === "" || (Array.isArray(value) && !value.length);
  if (empty) {
    if (tag.result) ann.deleteArea(tag.result.area);
    if (tag.type === "choices") tag.setResult([]);
    else tag.needsUpdate();
  } else if (tag.type === "choices") {
    tag.setResult(value);
    tag.updateResult();
  } else if (tag.type === "textarea") {
    tag.updateFromResult(Array.isArray(value) ? value : [value]);
    tag.setValue("");
    tag.onChange();
  } else tag.setNumber(value);
}
