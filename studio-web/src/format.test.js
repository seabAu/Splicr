import assert from "node:assert/strict";
import test from "node:test";

import { percent, statusLabel, textStats } from "./format.js";

test("textStats counts UTF-8 bytes rather than UTF-16 code units", () => {
  assert.deepEqual(textStats("Hi 🙂"), { characters: 5, words: 2, bytes: 7 });
});

test("percent clamps progress", () => {
  assert.equal(percent(0.456), "46%");
  assert.equal(percent(2), "100%");
});

test("statusLabel makes API states readable", () => {
  assert.equal(statusLabel("in_progress"), "In progress");
});
