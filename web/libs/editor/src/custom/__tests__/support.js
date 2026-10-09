/**
 * Tests for the fork's ReactCode dispatcher + wizard component:
 * step navigation, visibleWhen page switching, per-page validation and
 * visibility-gated hotkeys.
 */
if (typeof globalThis.structuredClone === "undefined") {
  globalThis.structuredClone = (obj) => JSON.parse(JSON.stringify(obj));
}

import ToolsManager from "../../tools/Manager";
spyOn(ToolsManager, "setRoot").mockImplementation(mock());
spyOn(ToolsManager, "removeAllTools").mockImplementation(mock());
spyOn(ToolsManager, "allInstances").mockReturnValue([]);
spyOn(ToolsManager, "resetActiveDrawings").mockImplementation(mock());
spyOn(ToolsManager, "getInstance").mockReturnValue({
  addTool: mock(),
  removeAllTools: mock(),
  allTools: mock(() => []),
  findSelectedTool: mock(() => null),
});

const mockInvoke = mock();
const mockInvokeFirst = mock();
const mockHasEvent = mock(() => false);
mockModule("../../components/Infomodal/Infomodal", () => ({
  __esModule: true,
  __skipMerge: true,
  default: {
    warning: mock(),
    error: mock(),
  },
}));

import "../../tags/visual/View";
import "../../tags/control/Choices";
import "../../tags/control/Choice";
import "../../tags/object/RichText";
import "../../tags/control/TextArea/TextArea";
import "../../tags/control/Number";
import "../index"; // registers real reactcode + object type fallback
import AppStore from "../../stores/AppStore";

export function createAnnotation(config, result = []) {
  const store = AppStore.create(
    { config, task: { id: 1, data: JSON.stringify({ text: "Example document" }) }, interfaces: ["basic"] },
    {
      events: { hasEvent: mockHasEvent, invoke: mockInvoke, invokeFirst: mockInvokeFirst },
      messages: {},
      settings: {},
      forceAutoAnnotation: false,
      forceAutoAcceptSuggestions: false,
    },
  );
  store.initializeStore({});
  const ann = store.annotationStore.addAnnotation({ result });
  store.annotationStore.selectAnnotation(ann.id);
  if (result.length) {
    ann.deserializeResults(result);
    ann.updateObjects();
  }
  return ann;
}
