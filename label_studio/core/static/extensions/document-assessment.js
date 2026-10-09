// Standalone API v1 example. Serve with Label Studio; no React bundle is required.
(() => {
  const { React, registerInterface } = window.LabelStudioInterfaces;
  const h = React.createElement;
  function DocumentAssessment({ api, values, config, readOnly, task }) {
    const { quality = "quality", score = "score", comment = "comment" } = config;
    return h(
      "fieldset",
      { disabled: readOnly, className: "lsx-assessment" },
      h("legend", null, config.title || "Document assessment"),
      h("p", null, task.data.text),
      h(
        "label",
        null,
        "Quality",
        h(
          "select",
          {
            value: values[quality]?.[0] || "",
            onChange: (event) => api.setValue(quality, event.target.value ? [event.target.value] : null),
          },
          h("option", { value: "" }, "Choose quality"),
          h("option", { value: "Good" }, "Good"),
          h("option", { value: "Poor" }, "Poor"),
        ),
      ),
      h(
        "label",
        null,
        "Score",
        h("input", {
          type: "number",
          min: 0,
          max: 10,
          value: values[score] ?? "",
          onChange: (event) => {
            const value = event.target.value === "" ? null : Number(event.target.value);
            if (value === null || (value >= 0 && value <= 10)) api.setValue(score, value);
            else api.notify("Score must be between 0 and 10");
          },
        }),
      ),
      h(
        "label",
        null,
        "Comment",
        h("textarea", {
          value: values[comment]?.[0] || "",
          onChange: (event) => api.setValue(comment, event.target.value),
        }),
      ),
    );
  }
  registerInterface("external-document-assessment", { apiVersion: 1, Component: DocumentAssessment });
})();
