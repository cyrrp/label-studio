if (typeof globalThis.structuredClone === "undefined") {
  globalThis.structuredClone = (obj) => JSON.parse(JSON.stringify(obj));
}
mockModule("keymaster", () => {
  let scope = "all";
  const keymaster = () => {};
  keymaster.unbind = () => {};
  keymaster.setScope = (s) => { scope = s ?? scope; };
  keymaster.getScope = () => scope;
  return { __esModule: true, default: keymaster };
});
import ToolsManager from "../../tools/Manager";
spyOn(ToolsManager, "setRoot").mockImplementation(mock());
spyOn(ToolsManager, "removeAllTools").mockImplementation(mock());
spyOn(ToolsManager, "allInstances").mockReturnValue([]);
spyOn(ToolsManager, "resetActiveDrawings").mockImplementation(mock());
spyOn(ToolsManager, "getInstance").mockReturnValue({ addTool: mock(), removeAllTools: mock(), allTools: mock(() => []), findSelectedTool: mock(() => null) });
const mockInvoke = mock();
const mockInvokeFirst = mock();
const mockHasEvent = mock(() => false);
mockModule("../../components/Infomodal/Infomodal", () => ({ __esModule: true, __skipMerge: true, default: { warning: mock(), error: mock() } }));

// exact App.jsx registration order
import "../../tags/object";
import "../../tags/control";
import "../../tags/visual";
import "../../tags/Custom";
import "../index";
import Registry from "../../core/Registry";
import AppStore from "../../stores/AppStore";
import { readFileSync } from "node:fs";

const CONFIG = readFileSync("D:/Repos/label-studio/tmp/project1_config_wizard.xml", "utf-8");

it("full registration order resolves our model + real config", () => {
  const model = Registry.getModelByTag("custominterface");
  console.log("model has steps prop?", "steps" in (model.properties ?? {}));
  const store = AppStore.create(
    { config: CONFIG, task: { id: 1, data: JSON.stringify({ image: "x.jpg" }) }, interfaces: ["basic"] },
    { events: { hasEvent: mockHasEvent, invoke: mockInvoke, invokeFirst: mockInvokeFirst }, messages: {}, settings: {}, forceAutoAnnotation: false, forceAutoAcceptSuggestions: false },
  );
  store.initializeStore({});
  const ann = store.annotationStore.addAnnotation({ result: [] });
  store.annotationStore.selectAnnotation(ann.id);
  const wz = ann.names.get("wz");
  console.log("wz:", wz && wz.type, "steps:", wz?.steps, "page:", wz?.currentpage);
  expect(wz).toBeDefined();
  expect(wz.totalSteps).toBe(4);
  wz.nextWithValidation(); // modality required — should BLOCK
  expect(wz.currentpage).toBe(1);
});
