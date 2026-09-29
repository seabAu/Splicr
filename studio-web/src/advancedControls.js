const INTERNAL_PREFIX = "__splicr_";

function signature(value) {
  return JSON.stringify(value);
}

export function matchesControlType(definition, value) {
  if (value === null || value === undefined) return !definition.required;
  if (definition.value_type === "string") return typeof value === "string";
  if (definition.value_type === "boolean") return typeof value === "boolean";
  if (definition.value_type === "integer") return Number.isInteger(value);
  if (definition.value_type === "number") return typeof value === "number" && Number.isFinite(value);
  return true;
}

export function controlDefaults(definitions = []) {
  return Object.fromEntries(
    definitions
      .filter((definition) => definition.default !== null && definition.default !== undefined)
      .map((definition) => [definition.key, structuredClone(definition.default)]),
  );
}

export function reconcileControlValues(definitions = [], current = {}, allowUnknown = false) {
  if (!definitions.length) {
    return Object.fromEntries(
      Object.entries(current || {}).filter(([key]) => allowUnknown || key.startsWith(INTERNAL_PREFIX)),
    );
  }
  const next = controlDefaults(definitions);
  const known = new Map(definitions.map((definition) => [definition.key, definition]));
  for (const [key, value] of Object.entries(current || {})) {
    const definition = known.get(key);
    if (key.startsWith(INTERNAL_PREFIX) || allowUnknown) next[key] = value;
    else if (
      definition
      && !definition.sensitive
      && matchesControlType(definition, value)
      && (!definition.choices?.length || definition.choices.some((choice) => signature(choice) === signature(value)))
    ) next[key] = value;
  }
  return next;
}

export function conditionsMatch(conditions = [], values = {}) {
  return conditions.every((condition) => signature(values[condition.key]) === signature(condition.equals));
}

export function controlValueError(definition, value) {
  const label = definition.label || definition.key;
  if (value === undefined || value === null || value === "") {
    return definition.required ? `${label} is required.` : "";
  }
  if (!matchesControlType(definition, value)) {
    return `${label} must be a valid ${definition.value_type}.`;
  }
  if (definition.choices?.length && !definition.choices.some((choice) => signature(choice) === signature(value))) {
    return `${label} must use one of the available options.`;
  }
  if (typeof value === "number" && definition.minimum !== null && definition.minimum !== undefined && value < definition.minimum) {
    return `${label} must be at least ${definition.minimum}.`;
  }
  if (typeof value === "number" && definition.maximum !== null && definition.maximum !== undefined && value > definition.maximum) {
    return `${label} must be at most ${definition.maximum}.`;
  }
  return "";
}

export function countNonDefaultControls(definitions = [], values = {}) {
  return definitions.filter((definition) => {
    if (definition.sensitive || !(definition.key in values)) return false;
    return signature(values[definition.key]) !== signature(definition.default);
  }).length;
}

export function groupedVisibleControls(definitions = [], values = {}) {
  const groups = new Map();
  for (const definition of definitions) {
    if (!conditionsMatch(definition.visible_when, values)) continue;
    const group = definition.group || "General";
    if (!groups.has(group)) groups.set(group, []);
    groups.get(group).push(definition);
  }
  return [...groups.entries()];
}
