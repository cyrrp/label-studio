import { act } from "react";
import { createRoot } from "react-dom/client";
import { Provider } from "mobx-react";
import { destroy, getEnv } from "mobx-state-tree";
import { createAnnotation } from "./support";
import { HtxReactCode } from "../ReactCode";
import { HtxChoices } from "../../tags/control/Choices";
import { Hotkey } from "../../core/Hotkey";

const CONFIG = `<View><Text name="document" value="$text"/>
  <ReactCode name="navigation" component="wizard" steps="one,two"
    nextHotkey="enter,alt+right" prevHotkey="shift+enter,alt+left"/>
  <View visibleWhen="choice-selected" whenTagName="navigation" whenChoiceValue="one">
    <Choices name="first" toName="document" required="true">
      <Choice value="A" hotkey="1"/><Choice value="B" hotkey="2"/>
    </Choices>
  </View>
  <View visibleWhen="choice-selected" whenTagName="navigation" whenChoiceValue="two">
    <Choices name="second" toName="document" choice="multiple">
      <Choice value="X" hotkey="1"/><Choice value="Y" hotkey="2"/>
    </Choices>
  </View></View>`;

function press(keyCode, options = {}) {
  act(() => {
    const target = document.activeElement;
    target.dispatchEvent(new window.KeyboardEvent("keydown", { bubbles: true, cancelable: true, keyCode, ...options }));
    target.dispatchEvent(new window.KeyboardEvent("keyup", { bubbles: true, keyCode, ...options }));
  });
}

function renderEditor(ann, root) {
  act(() => {
    root.render(
      <Provider store={ann.store}>
        <div key={ann.id}>
          <HtxReactCode item={ann.names.get("navigation")} />
          <HtxChoices item={ann.names.get("first")} />
          <HtxChoices item={ann.names.get("second")} />
        </div>
      </Provider>,
    );
  });
}

it.each(["single", "single-radio"])(
  "keeps %s shortcuts working through wizard steps and task submission",
  async (choice) => {
    const ann = createAnnotation(
      CONFIG.replace('name="first" toName="document"', `name="first" toName="document" choice="${choice}"`),
    );
    const store = ann.store;
    store.addInterface("submit");
    store.attachHotkeys();
    const host = document.createElement("div");
    document.body.appendChild(host);
    const root = createRoot(host);
    globalThis.IS_REACT_ACT_ENVIRONMENT = true;
    try {
      renderEditor(ann, root);
      const navigation = ann.names.get("navigation");
      expect(document.activeElement).toBe(ann.names.get("first").elementRef.current.querySelector("input"));
      press(49);
      expect(ann.names.get("first").selectedValues()).toEqual(["A"]);
      press(13);
      expect(navigation.currentpage).toBe(2);
      expect(document.activeElement).toBe(ann.names.get("second").elementRef.current.querySelector("input"));
      press(49);
      expect(ann.names.get("second").selectedValues()).toEqual(["X"]);
      press(13, { shiftKey: true });
      expect(navigation.currentpage).toBe(1);
      press(50);
      expect(ann.names.get("first").selectedValues()).toEqual(["B"]);

      press(13);
      const invoke = getEnv(store).events.invoke;
      invoke.mockClear();
      press(13, { ctrlKey: true });
      expect(invoke).toHaveBeenCalledWith("submitAnnotation", store, ann);
      await act(async () => {
        await new Promise((resolve) => setTimeout(resolve, 250));
      });

      // Load the next task using the same store lifecycle as the Data Manager SDK.
      act(() => root.render(null));
      act(() => {
        store.resetState();
        store.assignTask({ id: 2, data: { text: "Next document" } });
        store.initializeStore({ annotations: [{ result: [] }] });
      });
      const next = store.annotationStore.selected;
      renderEditor(next, root);
      expect(next.names.get("navigation").currentpage).toBe(1);
      press(49);
      expect(next.names.get("first").selectedValues()).toEqual(["A"]);
      press(13);
      expect(next.names.get("navigation").currentpage).toBe(2);
      press(50);
      expect(next.names.get("second").selectedValues()).toEqual(["Y"]);
    } finally {
      act(() => root.unmount());
      host.remove();
      await new Promise((resolve) => setTimeout(resolve, 0));
      destroy(store);
      Hotkey.unbindAll();
    }
  },
);

it.each(["text", "number", "textarea", "select"])("keeps labeling shortcuts inactive while editing %s", (type) => {
  const element = document.createElement(["textarea", "select"].includes(type) ? type : "input");
  if (element.tagName === "INPUT") element.type = type;
  document.body.appendChild(element);
  const hotkeys = Hotkey(`keyboard-focus-${type}`);
  const handler = mock();
  hotkeys.addKey("1", handler);
  hotkeys.addKey("enter", handler);
  hotkeys.addKey("ctrl+enter", handler);
  Hotkey.setScope(Hotkey.DEFAULT_SCOPE);
  try {
    element.focus();
    press(49);
    press(13);
    press(13, { ctrlKey: true });
    expect(handler).not.toHaveBeenCalled();
    element.blur();
    press(49);
    expect(handler).toHaveBeenCalledTimes(1);
  } finally {
    hotkeys.unbindAll();
    element.remove();
  }
});

it("honors disabled hotkeys while a checkbox is focused", () => {
  const input = document.createElement("input");
  input.type = "checkbox";
  document.body.appendChild(input);
  const hotkeys = Hotkey("keyboard-focus-disabled");
  const handler = mock();
  hotkeys.addKey("1", handler);
  try {
    input.focus();
    Hotkey.setScope("__none__");
    press(49);
    expect(handler).not.toHaveBeenCalled();
    Hotkey.setScope(Hotkey.DEFAULT_SCOPE);
    press(49);
    expect(handler).toHaveBeenCalledTimes(1);
  } finally {
    Hotkey.setScope(Hotkey.DEFAULT_SCOPE);
    hotkeys.unbindAll();
    input.remove();
  }
});
