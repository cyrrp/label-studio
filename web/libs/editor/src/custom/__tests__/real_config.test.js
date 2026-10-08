/**
 * Sanity test: the real wizard label config from project 1 must parse and navigate.
 */
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

import "../../tags/visual/View";
import "../../tags/visual/Header";
import "../../tags/control/Choices";
import "../../tags/control/Choice";
import "../../tags/control/TextArea/TextArea";
import "../../tags/object/Image/Image.js";
import "../../tags/Custom";
import "../index";
import AppStore from "../../stores/AppStore";
import { readFileSync } from "node:fs";

const CONFIG = readFileSync("D:/Repos/label-studio/tmp/project1_config_wizard.xml", "utf-8");

it("real project config parses and wizard works", () => {
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
  console.log("names:", [...ann.names.keys()]);
  expect(wz).toBeDefined();
  expect(ann.names.get("modality").isVisible).toBe(true);
  expect(ann.names.get("defects").isVisible).toBe(false);
  wz.next();
  expect(wz.currentpage).toBe(2);
  // modality not selected → inner gate keeps defects hidden
  expect(ann.names.get("defects").isVisible).toBe(false);
});

it("selecting modality then Next shows page 2 content", () => {
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

  ann.names.get("modality").findLabel("Оригинал").toggleSelected();
  expect(ann.names.get("modality").selectedValues()).toContain("Оригинал");

  expect(wz.nextWithValidation()).toBe(true);
  expect(wz.currentpage).toBe(2);
  console.log("defects visible:", ann.names.get("defects").isVisible);
  expect(ann.names.get("defects").isVisible).toBe(true);
});
