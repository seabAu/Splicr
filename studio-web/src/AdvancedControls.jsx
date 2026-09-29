import React, { useEffect, useMemo, useState } from "react";
import { RotateCcw, SlidersHorizontal } from "lucide-react";

import {
  conditionsMatch,
  controlDefaults,
  controlValueError,
  countNonDefaultControls,
  groupedVisibleControls,
  randomControlValue,
} from "./advancedControls.js";

function titleFor(definition) {
  return definition.label || definition.key.replaceAll("_", " ");
}

function JsonControl({ definition, value, disabled, onChange, onDraftValidity }) {
  const serialized = value === undefined ? "" : JSON.stringify(value, null, 2);
  const [draft, setDraft] = useState(serialized);
  const [error, setError] = useState("");

  useEffect(() => {
    setDraft(serialized);
    setError("");
    onDraftValidity(true);
  }, [serialized]);

  return (
    <>
      <textarea
        rows="4"
        value={draft}
        disabled={disabled}
        aria-invalid={Boolean(error)}
        onChange={(event) => {
          const next = event.target.value;
          setDraft(next);
          if (!next.trim() && !definition.required) {
            setError("");
            onDraftValidity(true);
            onChange(undefined);
            return;
          }
          try {
            onChange(JSON.parse(next));
            setError("");
            onDraftValidity(true);
          } catch {
            setError("Enter valid JSON before starting the take.");
            onDraftValidity(false);
          }
        }}
      />
      {error && <small className="advanced-control-error" role="alert">{error}</small>}
    </>
  );
}

function ControlInput({ definition, value, values, onChange, onDraftValidity }) {
  const conditionDisabled = !conditionsMatch(definition.enabled_when, values);
  const disabled = definition.read_only || conditionDisabled;
  const id = `advanced-control-${definition.key}`;
  const label = titleFor(definition);
  const validationError = controlValueError(definition, value);

  if (definition.sensitive) {
    return (
      <div className="advanced-control sensitive-control" role="note">
        <strong>{label}</strong>
        <span>Set this credential in Connections. Secrets are never stored in jobs or profiles.</span>
      </div>
    );
  }

  if (definition.value_type === "boolean") {
    return (
      <label className="advanced-control advanced-check" htmlFor={id}>
        <input
          id={id}
          type="checkbox"
          checked={Boolean(value)}
          disabled={disabled}
          onChange={(event) => onChange(event.target.checked)}
        />
        <span><strong>{label}</strong>{definition.description && <small>{definition.description}</small>}</span>
      </label>
    );
  }

  const input = definition.choices?.length ? (
    <select
      id={id}
      value={value === undefined ? "__splicr_unset__" : JSON.stringify(value)}
      disabled={disabled}
      required={definition.required}
      onChange={(event) => onChange(
        event.target.value === "__splicr_unset__" ? undefined : JSON.parse(event.target.value),
      )}
    >
      {!definition.required && value === undefined && <option value="__splicr_unset__">Use engine default</option>}
      {definition.choices.map((choice) => (
        <option key={JSON.stringify(choice)} value={JSON.stringify(choice)}>{String(choice)}</option>
      ))}
    </select>
  ) : definition.value_type === "json" ? (
    <JsonControl
      definition={definition}
      value={value}
      disabled={disabled}
      onChange={onChange}
      onDraftValidity={onDraftValidity}
    />
  ) : (
    <span className="advanced-input-with-unit">
      <input
        id={id}
        type={["integer", "number"].includes(definition.value_type) ? "number" : "text"}
        value={value ?? ""}
        min={definition.minimum ?? undefined}
        max={definition.maximum ?? undefined}
        step={definition.step ?? (definition.value_type === "integer" ? 1 : "any")}
        required={definition.required}
        disabled={disabled}
        onChange={(event) => {
          if (!event.target.value) onChange(undefined);
          else if (["integer", "number"].includes(definition.value_type)) onChange(Number(event.target.value));
          else onChange(event.target.value);
        }}
      />
      {definition.unit && <i>{definition.unit}</i>}
      {definition.randomizable && (
        <button
          className="advanced-randomize"
          type="button"
          disabled={disabled}
          onClick={() => onChange(randomControlValue(definition))}
        >
          Generate another
        </button>
      )}
    </span>
  );

  return (
    <label className="control advanced-control" htmlFor={id}>
      <span>{label}{definition.required && <sup aria-label="required">*</sup>}</span>
      {input}
      {definition.description && <small>{definition.description}</small>}
      {conditionDisabled && <small>Available when its related engine setting is enabled.</small>}
      {definition.read_only && <small>This value is owned by the selected Voice Profile.</small>}
      {validationError && <small className="advanced-control-error" role="alert">{validationError}</small>}
    </label>
  );
}

export function AdvancedControls({
  definitions = [],
  values = {},
  context = {},
  onChange,
  onValidityChange = () => {},
}) {
  const [invalidDrafts, setInvalidDrafts] = useState(() => new Set());
  const allValues = { ...context, ...values };
  const groups = useMemo(() => groupedVisibleControls(definitions, allValues), [definitions, allValues]);
  const activeCount = countNonDefaultControls(definitions, values);
  const schemaValid = definitions.every((definition) => (
    !conditionsMatch(definition.visible_when, allValues)
    || definition.sensitive
    || !controlValueError(definition, values[definition.key])
  ));

  useEffect(() => {
    setInvalidDrafts(new Set());
  }, [definitions]);

  useEffect(() => {
    onValidityChange(schemaValid && invalidDrafts.size === 0);
  }, [schemaValid, invalidDrafts, onValidityChange]);

  if (!definitions.length) return null;

  const setValue = (key, value) => {
    const next = { ...values };
    if (value === undefined) delete next[key];
    else next[key] = value;
    onChange(next);
  };
  const reportDraftValidity = (key, valid) => setInvalidDrafts((current) => {
    const hasKey = current.has(key);
    if (hasKey === !valid) return current;
    const next = new Set(current);
    if (valid) next.delete(key);
    else next.add(key);
    return next;
  });

  return (
    <details className="advanced-controls">
      <summary>
        <span><SlidersHorizontal size={17} /><strong>Advanced engine controls</strong></span>
        <span>{activeCount ? `${activeCount} customized` : "Using recommended defaults"}</span>
      </summary>
      <div className="advanced-controls-body">
        <div className="advanced-controls-intro">
          <p>These controls come directly from the selected engine and are saved with profiles and takes.</p>
          <button className="ghost-button small" type="button" onClick={() => onChange(controlDefaults(definitions))}>
            <RotateCcw size={14} />Reset defaults
          </button>
        </div>
        {groups.map(([group, controls]) => (
          <fieldset className="advanced-control-group" key={group}>
            <legend>{group}</legend>
            <div className="advanced-control-grid">
              {controls.map((definition) => (
                <ControlInput
                  key={definition.key}
                  definition={definition}
                  value={values[definition.key]}
                  values={allValues}
                  onChange={(value) => setValue(definition.key, value)}
                  onDraftValidity={(valid) => reportDraftValidity(definition.key, valid)}
                />
              ))}
            </div>
          </fieldset>
        ))}
      </div>
    </details>
  );
}
