import assert from "node:assert/strict";
import test from "node:test";

import {
  conditionsMatch,
  controlDefaults,
  controlValueError,
  countNonDefaultControls,
  groupedVisibleControls,
  reconcileControlValues,
} from "./advancedControls.js";

const definitions = [
  { key: "temperature", value_type: "number", default: 0.7, group: "Generation", choices: [] },
  { key: "normalize", value_type: "boolean", default: true, group: "Audio", choices: [] },
  { key: "mode", value_type: "string", default: "natural", group: "Generation", choices: ["natural", "dramatic"] },
  { key: "seed", value_type: "integer", default: null, group: "Generation", choices: [], visible_when: [{ key: "mode", equals: "dramatic" }] },
];

test("control defaults and reconciliation preserve valid schema and internal values", () => {
  assert.deepEqual(controlDefaults(definitions), { temperature: 0.7, normalize: true, mode: "natural" });
  assert.deepEqual(
    reconcileControlValues(definitions, {
      temperature: 0.4,
      normalize: "yes",
      mode: "invalid",
      stale: 12,
      __splicr_checkpoint: 3,
    }),
    { temperature: 0.4, normalize: true, mode: "natural", __splicr_checkpoint: 3 },
  );
});

test("legacy providers keep variables when they do not declare a schema", () => {
  assert.deepEqual(
    reconcileControlValues([], { arbitrary: { nested: true } }, true),
    { arbitrary: { nested: true } },
  );
  assert.deepEqual(
    reconcileControlValues([], { arbitrary: true, __splicr_checkpoint: 2 }),
    { __splicr_checkpoint: 2 },
  );
});

test("conditions and active counts use JSON value equality", () => {
  const values = { ...controlDefaults(definitions), mode: "dramatic", seed: 42 };
  assert.equal(conditionsMatch([{ key: "mode", equals: "dramatic" }], values), true);
  assert.equal(countNonDefaultControls(definitions, values), 2);
  assert.deepEqual(groupedVisibleControls(definitions, values).map(([name, rows]) => [name, rows.length]), [
    ["Generation", 3],
    ["Audio", 1],
  ]);
});

test("local validation explains required values and numeric bounds", () => {
  assert.equal(
    controlValueError({ key: "seed", label: "Seed", required: true }, undefined),
    "Seed is required.",
  );
  assert.equal(
    controlValueError({ key: "speed", label: "Speed", value_type: "number", minimum: 0.5, maximum: 2 }, 3),
    "Speed must be at most 2.",
  );
  assert.equal(
    controlValueError({ key: "speed", value_type: "number", minimum: 0.5 }, 1),
    "",
  );
});
