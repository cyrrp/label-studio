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
import "../index";
import AppStore from "../../stores/AppStore";
import { readFileSync } from "node:fs";

const CONFIG = readFileSync(new URL("./fixtures/document-wizard.xml", import.meta.url), "utf-8");

function realAnnotation(config = CONFIG) {
  const store = AppStore.create(
    { config, task: { id: 1, data: JSON.stringify({ image: "x.jpg" }) }, interfaces: ["basic"] },
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
  return ann;
}

it("saves all four pages regardless of the current page", () => {
  const ann = realAnnotation();
  ann.names.get("modality").findLabel("Оригинал").toggleSelected();
  ann.names.get("defects").findLabel("Нет печати").toggleSelected();
  ann.names.get("readability").findLabel("Блики").toggleSelected();
  ann.names.get("resident").findLabel("Паспорт РФ").toggleSelected();
  expect(ann.validate()).toBe(true);
  expect(ann.names.get("wz").currentpage).toBe(1);
  expect(
    ann
      .serializeAnnotation()
      .map((r) => r.from_name)
      .sort(),
  ).toEqual(["defects", "modality", "readability", "resident"]);
});

it("excludes old answers when their real conditions no longer apply and restores them when applicable again", () => {
  const ann = realAnnotation();
  const modality = ann.names.get("modality");
  modality.findLabel("Оригинал").toggleSelected();
  ann.names.get("defects").findLabel("Нет печати").toggleSelected();
  ann.names.get("readability").findLabel("Блики").toggleSelected();
  ann.names.get("resident").findLabel("Паспорт РФ").toggleSelected();
  modality.findLabel("Не определяю").toggleSelected();
  expect(ann.serializeAnnotation().map((r) => r.from_name)).toEqual(["modality"]);
  expect(ann.validate()).toBe(false); // conditional comment is now required
  ann.names.get("comment_modality").addText("Image cannot be assessed");
  expect(ann.validate()).toBe(true);
  expect(
    ann
      .serializeAnnotation()
      .map((r) => r.from_name)
      .sort(),
  ).toEqual(["comment_modality", "modality"]);
  modality.findLabel("Оригинал").toggleSelected();
  expect(
    ann
      .serializeAnnotation()
      .map((r) => r.from_name)
      .sort(),
  ).toEqual(["defects", "modality", "readability", "resident"]);
});

it("tracks actual completion and optionally skips inapplicable middle pages", () => {
  const ann = realAnnotation(
    CONFIG.replace(
      'steps="modality,defects,readability,resident"',
      'skipEmpty="true" steps="modality,defects,readability,resident"',
    ),
  );
  const wz = ann.names.get("wz");
  ann.names.get("modality").findLabel("Не определяю").toggleSelected();
  ann.names.get("comment_modality").addText("Unreadable");
  expect(wz.stepStatus("modality")).toBe("done");
  expect(wz.stepStatus("defects")).toBe("skipped");
  expect(wz.nextWithValidation()).toBe(true);
  expect(wz.currentpage).toBe(4);
  wz.prev();
  expect(wz.currentpage).toBe(1);
  expect(wz.summary[1].answers).toEqual([]);
});

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
  expect(ann.names.get("defects").isVisible).toBe(true);
});
