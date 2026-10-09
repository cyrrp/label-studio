if (typeof globalThis.structuredClone === "undefined") {
  globalThis.structuredClone = (obj) => JSON.parse(JSON.stringify(obj));
}
mockModule("keymaster", () => {
  let scope = "all";
  const keymaster = () => {};
  keymaster.unbind = () => {};
  keymaster.setScope = (s) => {
    scope = s ?? scope;
  };
  keymaster.getScope = () => scope;
  return { __esModule: true, default: keymaster };
});
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
  default: { warning: mock(), error: mock() },
}));

// exact App.jsx registration order
import "../../tags/object";
import "../../tags/control";
import "../../tags/visual";
import "../index";
import Registry from "../../core/Registry";
import { ConfigValidator } from "../../core/DataValidator/ConfigValidator";
import Tree from "../../core/Tree";
import AppStore from "../../stores/AppStore";
import { readFileSync } from "node:fs";

const CONFIG = readFileSync(new URL("./fixtures/document-wizard.xml", import.meta.url), "utf-8");

it("validates concrete ReactCode models before creating annotation instances", () => {
  const store = { task: { dataObj: {} } };
  const validate = (config) => ConfigValidator.validate(Tree.treeToModel(config, store));
  expect(validate('<View><ReactCode name="ui" component="document-assessment" /></View>')).toEqual([]);
  expect(validate('<View><ReactCode name="wz" component="wizard" steps="one,two" /></View>')).toEqual([]);
  expect(validate('<View><ReactCode name="wz" component="wizard" showSummary="invalid" /></View>')).toEqual(
    expect.arrayContaining([expect.objectContaining({ error: "ERR_BAD_TYPE", field: "showsummary" })]),
  );
  expect(validate('<View><UnknownInterface name="ui" /></View>')).toEqual(
    expect.arrayContaining([expect.objectContaining({ error: "ERR_UNKNOWN_TAG" })]),
  );
});

it("full registration order resolves our model + real config", () => {
  const model = Registry.getModelByTag("reactcode");
  expect(model).toBeDefined();
  expect(Registry.models.custominterface).toBeUndefined();
  const store = AppStore.create(
    { config: CONFIG, task: { id: 1, data: JSON.stringify({ image: "x.jpg" }) }, interfaces: ["basic"] },
    {
      events: { hasEvent: mockHasEvent, invoke: mockInvoke, invokeFirst: mockInvokeFirst },
      messages: {},
      settings: {},
      forceAutoAnnotation: false,
      forceAutoAcceptSuggestions: false,
    },
  );
  store.initializeStore({});
  const ann = store.annotationStore.addAnnotation({ result: [] });
  store.annotationStore.selectAnnotation(ann.id);
  const wz = ann.names.get("wz");
  expect(wz).toBeDefined();
  expect(ConfigValidator.validate(Tree.treeToModel(CONFIG, store))).toEqual([]);
  expect(wz.totalSteps).toBe(4);
  wz.nextWithValidation(); // modality required — should BLOCK
  expect(wz.currentpage).toBe(1);
});
