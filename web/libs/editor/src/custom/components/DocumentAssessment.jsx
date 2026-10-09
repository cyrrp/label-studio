/** Example UI with native Choices, Number and TextArea outputs. */
export function DocumentAssessment({ api, values, config, readOnly, task }) {
  const { quality = "quality", score = "score", comment = "comment" } = config;
  return (
    <fieldset disabled={readOnly} className="lsx-assessment">
      <legend>{config.title ?? "Document assessment"}</legend>
      {task.data.text && <p>{task.data.text}</p>}
      <label>
        Quality
        <select
          value={values[quality]?.[0] ?? ""}
          onChange={(event) => api.setValue(quality, event.target.value ? [event.target.value] : null)}
        >
          <option value="">Choose quality</option>
          <option value="Good">Good</option>
          <option value="Poor">Poor</option>
        </select>
      </label>
      <label>
        Score
        <input
          type="number"
          min="0"
          max="10"
          value={values[score] ?? ""}
          onChange={(event) => {
            const value = event.target.value === "" ? null : Number(event.target.value);
            if (value === null || (value >= 0 && value <= 10)) api.setValue(score, value);
            else api.notify("Score must be between 0 and 10");
          }}
        />
      </label>
      <label>
        Comment
        <textarea value={values[comment]?.[0] ?? ""} onChange={(event) => api.setValue(comment, event.target.value)} />
      </label>
    </fieldset>
  );
}
