import assert from "node:assert/strict";
import test from "node:test";
import { handlePoint, pointerFraction, positionLocked, positionPatch } from "./audiogramPosition.js";

const spec = { geometry: "polar", center_x: 0.5, center_y: 0.5, pivot_x: 0.5, pivot_y: 0.5, rotation: 0 };
const layout = { canvas_width: 1000, canvas_height: 500, center_x: 500, center_y: 250, pivot_x: 500, pivot_y: 250, visualizer_x: 300, visualizer_y: 150, visualizer_width: 400, visualizer_height: 200, rotation: 0 };
const close = (actual, expected) => assert.ok(Math.abs(actual - expected) < 1e-10, `${actual} != ${expected}`);

test("pointer coordinates account for resized canvas and clamp outside captures", () => {
  const rect = { left: 20, top: 40, width: 200, height: 100 };
  assert.deepEqual(pointerFraction(120, 65, rect), { x: 0.5, y: 0.25 });
  assert.deepEqual(pointerFraction(-30, 220, rect), { x: 0, y: 1 });
  assert.equal(pointerFraction(0, 0, { ...rect, width: 0 }), null);
});

test("polar and pivot movement are bounded and preserve unrelated settings", () => {
  assert.deepEqual(positionPatch(spec, layout, "center", { x: 0.2, y: 0.8 }), { center_x: 0.2, center_y: 0.8 });
  assert.deepEqual(positionPatch(spec, layout, "pivot", { x: -1, y: 2 }), { pivot_x: 0, pivot_y: 1 });
  assert.deepEqual(spec.center_x, 0.5);
});

test("rotated centers use pixel-space inverse transform on non-square canvases", () => {
  const rotated = { ...spec, center_x: 0.6, center_y: 0.5, rotation: 90 };
  const point = handlePoint(rotated, layout, "center");
  close(point.x, 0.5);
  close(point.y, 0.7);
  const patch = positionPatch(rotated, layout, "center", point);
  close(patch.center_x, 0.6);
  close(patch.center_y, 0.5);
});

test("linear translation preserves effective size and clamps inside canvas", () => {
  const linear = { ...spec, geometry: "linear", linear_x: null, linear_y: null, linear_width: 0.4, linear_height: 0.4 };
  assert.deepEqual(positionPatch(linear, layout, "center", { x: 0.99, y: -1 }), { linear_x: 0.6, linear_y: 0, linear_width: 0.4, linear_height: 0.4 });
  const clamped = handlePoint({ ...linear, linear_x: 0.9, linear_width: 1 }, layout, "center");
  close(clamped.x, 0.95);
  const edge = positionPatch({ ...linear, linear_x: 1 }, layout, "center", { x: 0.5, y: 0.5 });
  close(edge.linear_width, 2 / layout.canvas_width);
});

test("direct movement cannot replace positional formulas", () => {
  for (const field of ["center_x", "rotation", "pivot_y"]) {
    const animated = { ...spec, [field]: "0.5 + 0.1*sin(t)" };
    assert.equal(positionLocked(animated, "center"), true);
    assert.deepEqual(positionPatch(animated, layout, "center", { x: 0, y: 0 }), {});
  }
  assert.equal(positionLocked({ ...spec, opacity: "0.5 + 0.5*sin(t)" }, "center"), false);
  assert.equal(positionLocked({ ...spec, rotation: "30*t" }, "pivot"), false);
  assert.equal(positionLocked({ ...spec, pivot_x: "t" }, "pivot"), true);
  assert.equal(positionLocked({ ...spec, geometry: "linear", linear_width: "0.5+t" }, "center"), true);
});
