/**
 * Minimal bun:test preload for the fork's `libs/editor/src/custom/` tests.
 *
 * The upstream 1.23.x line has no bun test harness (it was added on develop
 * later). This file provides only what the custom tests need:
 *   - DOM globals via jsdom (installed as a jest transitive dep)
 *   - `mock` / `spyOn` / `mockModule` globals used by test files verbatim
 *   - `window.APP_SETTINGS` (ApiConfig reads it at module-eval time)
 *   - a stub `fetch`
 *   - a Bun.plugin loader that stubs css/asset imports in the module graph
 */
import { expect, mock, spyOn } from "bun:test";
import { JSDOM } from "jsdom";
import React from "react";

(globalThis as any).React = React;

const dom = new JSDOM("", { url: "http://localhost/" });

for (const key of Object.getOwnPropertyNames(dom.window)) {
  if (!(key in globalThis)) {
    try {
      (globalThis as any)[key] = (dom.window as any)[key];
    } catch {
      /* non-configurable props are skipped */
    }
  }
}
(globalThis as any).window = dom.window;
(globalThis as any).document = dom.window.document;
(globalThis as any).navigator = dom.window.navigator;

(globalThis as any).mock = mock;
(globalThis as any).spyOn = spyOn;
(globalThis as any).clearAllMocks = () => mock.restore();
(globalThis as any).mockModule = (specifier: string, factory: () => unknown) => mock.module(specifier, factory as any);
(globalThis as any).expect = expect;

(dom.window as any).APP_SETTINGS = { hostname: "http://localhost", feature_flags: {} };
(globalThis as any).APP_SETTINGS = (dom.window as any).APP_SETTINGS;
(globalThis as any).requestAnimationFrame = (cb: FrameRequestCallback) => setTimeout(cb, 0) as unknown as number;
(globalThis as any).cancelAnimationFrame = (id: number) => clearTimeout(id);
(globalThis as any).fetch = mock(async () => new Response("{}", { status: 200 }));

import { mockFF } from "../../libs/editor/__mocks__/global";
(globalThis as any).mockFF = mockFF;

if (typeof Bun !== "undefined" && typeof Bun.plugin === "function") {
  Bun.plugin({
    name: "custom-test-style-and-asset-mocks",
    setup(build) {
      build.onLoad({ filter: /\.(css|scss|sass|less)$/ }, () => ({
        loader: "js",
        contents: "export default new Proxy({}, { get: (_, key) => key });",
      }));
      build.onLoad({ filter: /\.(svg|png|jpg|jpeg|gif|webp|woff2?|ttf)$/ }, () => ({
        loader: "js",
        contents:
          "import React from 'react'; export const ReactComponent = React.forwardRef((props, ref) => React.createElement('svg', { ...props, ref })); export default '';",
      }));
    },
  });
}
