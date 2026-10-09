import { act } from "react";
import { createRoot } from "react-dom/client";
import { destroy } from "mobx-state-tree";
import { createAnnotation } from "./support";
import { createInterfaceAPI } from "../api";
import { HtxReactCode } from "../ReactCode";
import { registerInterface, loadInterface, getInterface } from "../registry";
import { readFileSync } from "node:fs";
import { guardedHotkey } from "../visibility";

const CONFIG = `<View>
  <Text name="document" value="$text"/>
  <ReactCode name="assessment" component="document-assessment" outputs="quality,score,comment"/>
  <View style="display:none">
    <Choices name="quality" toName="document" required="true"><Choice value="Good"/><Choice value="Poor"/></Choices>
    <Number name="score" toName="document" min="0" max="10"/>
    <TextArea name="comment" toName="document"/>
  </View>
</View>`;

describe("interface API v1", () => {
  it("writes and reopens native choices, number and text; replaces and clears answers", () => {
    const ann = createAnnotation(CONFIG);
    const item = ann.names.get("assessment");
    expect(item.type).toBe("reactcode");
    expect(item.currentpage).toBeUndefined();
    const api = createInterfaceAPI(item);
    expect(api.task.data.text).toBe("Example document");
    api.setValue("quality", ["Good"]);
    api.setValue("score", 8);
    api.setValue("comment", "First");
    api.setValue("comment", "Updated");
    expect(api.getValue("comment")).toEqual(["Updated"]);
    expect(ann.validate()).toBe(true);
    const result = ann.serializeAnnotation();
    expect(result.map((r) => r.type).sort()).toEqual(["choices", "number", "textarea"]);
    const reopened = createAnnotation(CONFIG, result);
    const restored = createInterfaceAPI(reopened.names.get("assessment"));
    expect(restored.getValue("quality")).toEqual(["Good"]);
    expect(restored.getValue("score")).toBe(8);
    expect(restored.getValue("comment")).toEqual(["Updated"]);
    api.clearValue("quality");
    api.clearValue("score");
    api.clearValue("comment");
    expect(ann.serializeAnnotation()).toEqual([]);
    expect(ann.validate()).toBe(false);
  });

  it("rejects undeclared, invalid and read-only writes without modifying results", () => {
    const ann = createAnnotation(CONFIG);
    const api = createInterfaceAPI(ann.names.get("assessment"));
    expect(() => api.setValue("other", "value")).toThrow("Undeclared");
    expect(() => api.setValue("quality", ["Unknown"])).toThrow("Invalid choices");
    expect(() => api.setValue("quality", ["Good", "Poor"])).toThrow("one choice");
    expect(() => api.setValue("score", Number.NaN)).toThrow("Invalid number");
    expect(() => api.setValue("score", 100)).toThrow("Invalid number");
    expect(() => api.setValue("comment", {})).toThrow("Invalid text");
    api.setValue("quality", ["Good"]);
    ann.setReadonly(true);
    expect(api.readOnly).toBe(true);
    expect(() => api.clearValue("quality")).toThrow("read-only");
    expect(api.getValue("quality")).toEqual(["Good"]);
  });

  it("blocks unavailable interfaces and malformed configuration and integrates validators", () => {
    const ann = createAnnotation(CONFIG);
    const item = ann.names.get("assessment");
    const api = createInterfaceAPI(item);
    api.setValue("quality", ["Good"]);
    const remove = api.registerValidator(() => "Please check the document");
    expect(ann.validate()).toBe(false);
    remove();
    expect(ann.validate()).toBe(true);
    item.setRuntimeError("Module failed");
    expect(ann.validate()).toBe(false);
    expect(createAnnotation(CONFIG.replace('component="document-assessment"', 'component="missing"')).validate()).toBe(
      false,
    );
    expect(createAnnotation(CONFIG.replace('outputs="quality,score,comment"', 'options="broken"')).validate()).toBe(
      false,
    );
  });

  it("cleans resources and prevents a disposed API from writing to a new task", async () => {
    const ann = createAnnotation(CONFIG);
    const item = ann.names.get("assessment");
    const api = createInterfaceAPI(item);
    const dispose = mock();
    item.trackDisposer(dispose);
    await new Promise((resolve) => setTimeout(resolve, 0));
    destroy(ann.store);
    expect(dispose).toHaveBeenCalledTimes(1);
    expect(() => api.setValue("quality", ["Good"])).toThrow("no longer attached");
  });

  it("renders plain React components reactively and enforces read-only UI", () => {
    const ann = createAnnotation(CONFIG);
    const item = ann.names.get("assessment");
    const api = createInterfaceAPI(item);
    const host = document.createElement("div");
    const root = createRoot(host);
    globalThis.IS_REACT_ACT_ENVIRONMENT = true;
    act(() => {
      root.render(<HtxReactCode item={item} />);
    });
    expect(host.querySelector("select").value).toBe("");
    act(() => api.setValue("quality", ["Good"]));
    expect(host.querySelector("select").value).toBe("Good");
    act(() => ann.setReadonly(true));
    expect(host.querySelector("fieldset").disabled).toBe(true);
    act(() => root.unmount());
  });

  it("isolates stale APIs when switching annotations in the same editor", () => {
    const ann = createAnnotation(CONFIG);
    const api = createInterfaceAPI(ann.names.get("assessment"));
    const next = ann.store.annotationStore.addAnnotation({ result: [] });
    ann.store.annotationStore.selectAnnotation(next.id);
    expect(() => api.setValue("quality", ["Good"])).toThrow("no longer attached");
    expect(next.serializeAnnotation()).toEqual([]);
  });

  it("binds real keyboard events and removes all aliases on disposal", () => {
    const ann = createAnnotation(CONFIG);
    const api = createInterfaceAPI(ann.names.get("assessment"));
    const handler = mock();
    const dispose = api.bindHotkey("alt+right,alt+left", handler);
    const press = (keyCode) =>
      document.body.dispatchEvent(
        new window.KeyboardEvent("keydown", { bubbles: true, cancelable: true, keyCode, altKey: true }),
      );
    press(39);
    press(37);
    expect(handler).toHaveBeenCalledTimes(2);
    dispose();
    press(39);
    press(37);
    expect(handler).toHaveBeenCalledTimes(2);
  });

  it("does not dispatch extension shortcuts on an inactive wizard page", () => {
    const config = CONFIG.replace(
      '<ReactCode name="assessment" component="document-assessment" outputs="quality,score,comment"/>',
      '<ReactCode name="navigation" component="wizard" steps="one,two"/>' +
        '<View visibleWhen="choice-selected" whenTagName="navigation" whenChoiceValue="one">' +
        '<ReactCode name="assessment" component="document-assessment" outputs="quality,score,comment"/></View>',
    );
    const ann = createAnnotation(config);
    const api = createInterfaceAPI(ann.names.get("assessment"));
    const handler = mock();
    const dispose = api.bindHotkey("f9", handler);
    const press = () =>
      document.body.dispatchEvent(new window.KeyboardEvent("keydown", { bubbles: true, keyCode: 120, altKey: false }));
    press();
    expect(handler).toHaveBeenCalledTimes(1);
    ann.names.get("navigation").goTo(2);
    press();
    expect(handler).toHaveBeenCalledTimes(1);
    dispose();
  });

  it("routes a real shared numeric shortcut only to the active wizard page", () => {
    const ann = createAnnotation(`<View><Text name="document" value="$text"/>
      <ReactCode name="navigation" component="wizard" steps="one,two"/>
      <View visibleWhen="choice-selected" whenTagName="navigation" whenChoiceValue="one">
        <Choices name="first" toName="document"><Choice value="A" hotkey="1"/></Choices>
      </View>
      <View visibleWhen="choice-selected" whenTagName="navigation" whenChoiceValue="two">
        <Choices name="second" toName="document"><Choice value="B" hotkey="1"/></Choices>
      </View></View>`);
    const press = () =>
      document.body.dispatchEvent(new window.KeyboardEvent("keydown", { bubbles: true, keyCode: 49 }));
    press();
    expect(ann.names.get("first").selectedValues()).toEqual(["A"]);
    expect(ann.names.get("second").selectedValues()).toEqual([]);
    ann.names.get("navigation").goTo(2);
    press();
    expect(ann.names.get("first").selectedValues()).toEqual(["A"]);
    expect(ann.names.get("second").selectedValues()).toEqual(["B"]);
  });

  it("supports native undo and redo for component answers", () => {
    const ann = createAnnotation(CONFIG);
    const api = createInterfaceAPI(ann.names.get("assessment"));
    ann.reinitHistory();
    api.setValue("quality", ["Good"]);
    api.setValue("quality", ["Poor"]);
    expect(api.getValue("quality")).toEqual(["Poor"]);
    ann.undo();
    expect(api.getValue("quality")).toEqual(["Good"]);
    ann.redo();
    expect(api.getValue("quality")).toEqual(["Poor"]);
  });

  it("does not let invisible native output controls acquire active shortcuts", () => {
    const ann = createAnnotation(CONFIG);
    const choice = ann.names.get("quality").findLabel("Good");
    guardedHotkey(choice)({});
    expect(choice.sel).toBe(false);
  });

  it("isolates component render failures and blocks submission", () => {
    registerInterface("broken-ui", {
      apiVersion: 1,
      Component: () => {
        throw new Error("Rendering failed");
      },
    });
    const ann = createAnnotation(CONFIG.replace('component="document-assessment"', 'component="broken-ui"'));
    createInterfaceAPI(ann.names.get("assessment")).setValue("quality", ["Good"]);
    const host = document.createElement("div");
    const root = createRoot(host);
    const consoleError = spyOn(console, "error").mockImplementation(() => {});
    try {
      act(() => {
        root.render(<HtxReactCode item={ann.names.get("assessment")} />);
      });
      expect(host.querySelector('[role="alert"]').textContent).toContain("Rendering failed");
      expect(ann.validate()).toBe(false);
    } finally {
      act(() => root.unmount());
      consoleError.mockRestore();
    }
  });
});

describe("external interface modules", () => {
  it("runs the shipped external example using the host React instance", async () => {
    window.APP_SETTINGS.custom_interface_modules = {
      "external-document-assessment": "/static/extensions/document-assessment.js",
    };
    const loaded = loadInterface("external-document-assessment");
    const source = readFileSync(
      new URL("../../../../../../label_studio/core/static/extensions/document-assessment.js", import.meta.url),
      "utf-8",
    );
    new Function("window", source)(window);
    document.querySelector('script[src$="/static/extensions/document-assessment.js"]').onload();
    await loaded;
    const ann = createAnnotation(
      CONFIG.replace('component="document-assessment"', 'component="external-document-assessment"'),
    );
    const host = document.createElement("div");
    const root = createRoot(host);
    act(() => {
      root.render(<HtxReactCode item={ann.names.get("assessment")} />);
    });
    expect(host.querySelector("legend").textContent).toBe("Document assessment");
    act(() => root.unmount());
  });
  it("requires a compatible API and prevents duplicate registration", () => {
    expect(() => registerInterface("bad-version", { apiVersion: 2, Component: () => null })).toThrow("Unsupported");
    expect(() => registerInterface("document-assessment", { apiVersion: 1, Component: () => null })).toThrow(
      "already registered",
    );
  });

  it("loads once and resolves the same component contract as built-ins", async () => {
    window.APP_SETTINGS.custom_interface_modules = { "external-assessment": "/static/extensions/assessment.js" };
    const promise = loadInterface("external-assessment");
    expect(loadInterface("external-assessment")).toBe(promise);
    const script = document.querySelector('script[src$="/static/extensions/assessment.js"]');
    window.LabelStudioInterfaces.registerInterface("external-assessment", {
      apiVersion: 1,
      Component: getInterface("document-assessment").Component,
    });
    script.onload();
    const definition = await promise;
    expect(definition.Component).toBe(getInterface("document-assessment").Component);
    const ann = createAnnotation(CONFIG.replace('component="document-assessment"', 'component="external-assessment"'));
    createInterfaceAPI(ann.names.get("assessment")).setValue("quality", ["Good"]);
    expect(ann.validate()).toBe(true);
  });

  it("reports failed registration/network loads and rejects unconfigured or cross-origin modules", async () => {
    window.APP_SETTINGS.custom_interface_modules = {
      "no-registration": "/static/empty.js",
      "network-error": "/static/missing.js",
      "wrong-origin": "https://example.com/module.js",
    };
    const noRegistration = loadInterface("no-registration");
    document.querySelector('script[src$="/static/empty.js"]').onload();
    await expect(noRegistration).rejects.toThrow("did not register");
    const network = loadInterface("network-error");
    document.querySelector('script[src$="/static/missing.js"]').onerror();
    await expect(network).rejects.toThrow("Unable to load");
    await expect(loadInterface("wrong-origin")).rejects.toThrow("same-origin");
    await expect(loadInterface("not-configured")).rejects.toThrow("Unknown interface");
  });
});
