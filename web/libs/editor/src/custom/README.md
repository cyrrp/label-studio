# React interfaces in the OSS fork

`ReactCode` selects registered React components. This is the
fork's API v1, not an implementation of the Enterprise inline-code API. XML does
not execute JavaScript or JSX. Wizard configurations use the same tag. Replace `<CustomInterface>` with
`<ReactCode>` in existing configurations; the old tag is no longer registered.

## Built-in components

Import `registerInterface` from `custom/registry` and register a component before
the editor renders:

```jsx
registerInterface("my-interface", {
  apiVersion: 1,
  Component: MyInterface,
  validate: (api) => api.getValue("quality").length > 0 || "Choose quality",
});
```

Use `<ReactCode name="form" component="my-interface" outputs="quality"
options='{"title":"Check document"}'/>`. `options` must be a JSON object.
`outputs` lists existing control names that this component may read and write.
Components get `{ api, values, config, readOnly, task }`; these props update when
answers, the selected annotation or read-only mode change. Components may use
normal React state and hooks. Local state is not an annotation or draft.

## Native outputs

The first version supports task-level `Choices`, `TextArea` and `Number` outputs.
Declare those controls in XML with normal `name` and `toName` attributes. To let
React render their UI, put the controls in `<View style="display:none">`.
Do not hide output declarations with `visibleWhen` unless their answers really
are conditional: semantic hiding excludes answers from export.

See [examples/document-assessment.xml](examples/document-assessment.xml). Set
task data to `{"text":"Example document"}`. It uses the built-in
`document-assessment` component. No custom result types or backend migrations are
needed: results have the native `from_name`, `to_name`, `type` and `value` fields.

| API | Behavior |
| --- | --- |
| `api.task` | Copy of `{ id, data }` for the current task |
| `api.config` | Copy of parsed options |
| `api.readOnly` | Current annotation's read-only state |
| `api.outputs` | Declared output names |
| `api.getValue(name)` | Choices/text array or number/null |
| `api.setValue(name, value)` | Set choices array, text string/array or finite number |
| `api.clearValue(name)` | Remove the answer |
| `api.isApplicable(name)` | Evaluate semantic conditions, ignoring wizard navigation |
| `api.validateOutputs()` | Run native validators; may show native warnings |
| `api.registerValidator(fn)` | Register synchronous validator; returns cleanup |
| `api.bindHotkey(keys, callback)` | Bind comma-separated aliases; returns cleanup |
| `api.notify(message)` | Show a warning message |

Validators receive `api` and return `true`/undefined, `false`, or an error string.
Promises are rejected: the native submit pipeline validates synchronously.
Writes reject undeclared outputs, invalid values, region/item controls and
read-only annotations. APIs are bound to their annotation and cannot write to a
different annotation after selection changes. Resources registered through the
API are cleaned on unmount; still return their cleanup from `useEffect` when
replacing an effect. Render failures are isolated and prevent submission.

## External modules without rebuilding Label Studio

Set the server environment variable (PowerShell):

```powershell
$env:CUSTOM_INTERFACE_MODULES = '{"external-document-assessment":"/static/extensions/document-assessment.js"}'
```

Restart the backend so it exports this setting to `APP_SETTINGS`. Serve trusted
classic JavaScript bundles from the same origin as Label Studio. The included
`label_studio/core/static/extensions/document-assessment.js` is a runnable example;
production deployments must include it in their static assets (`collectstatic`).
In the example XML, change `component` to `external-document-assessment`.

The module registers through the host:

```js
const { React, registerInterface } = window.LabelStudioInterfaces;
registerInterface("external-document-assessment", { apiVersion: 1, Component });
```

Use this React instance for hooks and element creation. Do not bundle another
React copy. A precompiled JSX bundle can use the classic transform with this
React binding; the provided example uses `React.createElement` and needs no build.
Modules are loaded once per browser page. Load failures, absent registrations and
unsupported API versions block submission rather than silently accepting an
incomplete form. Reload the browser to pick up a changed module. These are trusted
application scripts, with the application's browser privileges; this is not a
sandbox for untrusted code. Remote origins and inline XML scripts are unsupported.

## Wizard

`component="wizard"` uses its own model; generic interfaces have no page state.
Existing `steps`, `stepLabels`, `nextLabel`, `prevLabel`, `nextHotkey`, `prevHotkey`,
`validateOnNext` and `showProgress` attributes remain supported. Pages are ordinary
Views referencing the wizard via `visibleWhen="choice-selected"`.

All applicable page answers are serialized, even when their page is inactive.
Actual conditional branches retain native exclusion semantics. Submit validates
every page, lands on the first error and restores the original page on success.
Read-only mode allows navigation without required validation. Step indicators
derive completion from applicable control answers, not position in the sequence.
They indicate presence of answers, not the outcome of every custom validator.

Optional attributes: `skipEmpty="true"` skips inapplicable intermediate pages;
the final page remains a navigation endpoint. `showSummary="true"` adds a summary
button on the final page; `summaryLabel` changes its caption. The standard submit
button still saves the annotation. Page position is transient and is not saved.

## Validation

Run custom test files separately with `bun test <file>` from `web/`; the old
test harness uses module mocks. XML fixtures are committed with the tests.
Production builds use `bunx nx run editor:build:production` followed by
`bunx nx run labelstudio:build:production`.
