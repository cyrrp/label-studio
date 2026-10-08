/**
 * Tests for the fork's CustomInterface dispatcher + wizard component:
 * step navigation, visibleWhen page switching, per-page validation and
 * visibility-gated hotkeys.
 */
if (typeof globalThis.structuredClone === "undefined") {
  globalThis.structuredClone = (obj) => JSON.parse(JSON.stringify(obj));
}

mockModule("keymaster", () => {
  let scope = "all";
  const keymaster = () => {};
  keymaster.unbind = () => {};
  keymaster.setScope = (nextScope) => {
    scope = nextScope ?? scope;
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
  default: {
    warning: mock(),
    error: mock(),
  },
}));

import "../../tags/visual/View";
import "../../tags/control/Choices";
import "../../tags/control/Choice";
import "../../tags/object/RichText";
import "../index"; // registers real custominterface + object type fallback
import AppStore from "../../stores/AppStore";
import { guardedHotkey, isHiddenInUI } from "../visibility";

const CONFIG = `<View>
  <Text name="t" value="hello"/>
  <CustomInterface component="wizard" name="wz" steps="s1,s2" steplabels="One,Two"/>
  <View visibleWhen="choice-selected" whenTagName="wz" whenChoiceValue="s1">
    <Choices name="c1" toName="t" choice="single" required="true">
      <Choice value="A" hotkey="1"/>
      <Choice value="B" hotkey="2"/>
    </Choices>
  </View>
  <View visibleWhen="choice-selected" whenTagName="wz" whenChoiceValue="s2">
    <Choices name="c2" toName="t" choice="single" required="true">
      <Choice value="X" hotkey="1"/>
    </Choices>
  </View>
</View>`;

function createStore(config = CONFIG) {
  return AppStore.create(
    {
      config,
      task: { id: 1, data: JSON.stringify({}) },
      interfaces: ["basic"],
    },
    {
      events: {
        hasEvent: mockHasEvent,
        invoke: mockInvoke,
        invokeFirst: mockInvokeFirst,
      },
      messages: {},
      settings: {},
      forceAutoAnnotation: false,
      forceAutoAcceptSuggestions: false,
    },
  );
}

function setup() {
  const store = createStore();

  store.initializeStore({});
  const ann = store.annotationStore.addAnnotation({ result: [] });

  store.annotationStore.selectAnnotation(ann.id);
  return ann;
}

describe("custominterface wizard", () => {
  beforeEach(() => {
    clearAllMocks();
    mockHasEvent.mockReturnValue(false);
    window.localStorage.setItem("annotation-store-viewing-all", "false");
  });

  it("registers the tag into annotation.names and starts on page 1", () => {
    const ann = setup();
    const wz = ann.names.get("wz");

    expect(wz).toBeDefined();
    expect(wz.type).toBe("custominterface");
    expect(wz.currentpage).toBe(1);
    expect(wz.currentStep).toBe("s1");
    expect(wz.stepLabels).toEqual(["One", "Two"]);
  });

  it("does not land in toNames (no result produced)", () => {
    const ann = setup();

    expect(ann.toNames.get("t").find((n) => n.type === "custominterface")).toBeUndefined();
  });

  it("switches page visibility via visibleWhen when navigating", () => {
    const ann = setup();
    const wz = ann.names.get("wz");

    expect(ann.names.get("c1").isVisible).toBe(true);
    expect(ann.names.get("c2").isVisible).toBe(false);

    wz.next();

    expect(wz.currentpage).toBe(2);
    expect(ann.names.get("c1").isVisible).toBe(false);
    expect(ann.names.get("c2").isVisible).toBe(true);

    wz.prev();
    expect(wz.currentpage).toBe(1);
    expect(ann.names.get("c1").isVisible).toBe(true);
  });

  it("clamps navigation to [1, steps]", () => {
    const ann = setup();
    const wz = ann.names.get("wz");

    wz.prev();
    expect(wz.currentpage).toBe(1);
    wz.next();
    wz.next();
    expect(wz.currentpage).toBe(2);
  });

  it("blocks Next on an unfilled required control of the current page", () => {
    const ann = setup();
    const wz = ann.names.get("wz");
    const c1 = ann.names.get("c1");

    expect(wz.nextWithValidation()).toBe(false);
    expect(wz.currentpage).toBe(1);

    c1.findLabel("A").toggleSelected();
    expect(wz.nextWithValidation()).toBe(true);
    expect(wz.currentpage).toBe(2);
  });

  it("validate() walks all pages and lands on the failing one", () => {
    const ann = setup();
    const wz = ann.names.get("wz");

    ann.names.get("c1").findLabel("A").toggleSelected();
    wz.goTo(2); // c2 required but empty

    expect(wz.validate()).toBe(false);
    expect(wz.currentpage).toBe(2); // stays on the failing page

    ann.names.get("c2").findLabel("X").toggleSelected();
    expect(wz.validate()).toBe(true);
  });

  it("isHiddenInUI detects controls on hidden pages", () => {
    const ann = setup();
    const choiceA = ann.names.get("c1").findLabel("A");
    const choiceX = ann.names.get("c2").findLabel("X");

    expect(isHiddenInUI(choiceA)).toBe(false);
    expect(isHiddenInUI(choiceX)).toBe(true);
  });

  it("guardedHotkey no-ops for hidden controls — same key, different pages", () => {
    const ann = setup();
    const wz = ann.names.get("wz");
    const choiceA = ann.names.get("c1").findLabel("A");
    const choiceX = ann.names.get("c2").findLabel("X");

    // both bound to "1" — only the visible one fires
    guardedHotkey(choiceA)({});
    guardedHotkey(choiceX)({});
    expect(choiceA.sel).toBe(true);
    expect(choiceX.sel).toBe(false);

    wz.goTo(2);
    guardedHotkey(choiceX)({});
    expect(choiceX.sel).toBe(true);
  });
});
