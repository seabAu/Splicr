const clamp = (value, low = 0, high = 1) => Math.max(low, Math.min(high, value));

export function pointerFraction(clientX, clientY, rect) {
  if (!(rect.width > 0 && rect.height > 0)) return null;
  return { x: clamp((clientX - rect.left) / rect.width), y: clamp((clientY - rect.top) / rect.height) };
}

export function positionLocked(spec, target) {
  const fields = target === "pivot" ? ["pivot_x", "pivot_y"] : [
    ...(spec.geometry === "polar" ? ["center_x", "center_y"] : ["linear_x", "linear_y", "linear_width", "linear_height"]),
    "rotation", "pivot_x", "pivot_y",
  ];
  return fields.some((field) => typeof spec[field] === "string");
}

function rotate(point, pivot, degrees) {
  const angle = degrees * Math.PI / 180;
  const dx = point.x - pivot.x;
  const dy = point.y - pivot.y;
  return { x: pivot.x + dx * Math.cos(angle) - dy * Math.sin(angle), y: pivot.y + dx * Math.sin(angle) + dy * Math.cos(angle) };
}

function linearFractions(spec, layout) {
  const x = clamp(spec.linear_x ?? 0);
  const fallbackY = Number.isFinite(spec.visualizer_height) && Number.isFinite(spec.vertical_position)
    ? (layout.canvas_height - spec.visualizer_height) * spec.vertical_position / layout.canvas_height
    : layout.visualizer_y / layout.canvas_height;
  const y = clamp(spec.linear_y ?? fallbackY);
  const fallbackHeight = Number.isFinite(spec.visualizer_height)
    ? spec.visualizer_height / layout.canvas_height : layout.visualizer_height / layout.canvas_height;
  return {
    x, y,
    width: Math.max(2 / layout.canvas_width, Math.min(clamp(spec.linear_width ?? 1, 0.01, 1), 1 - x)),
    height: Math.max(2 / layout.canvas_height, Math.min(clamp(spec.linear_height ?? fallbackHeight, 0.01, 1), 1 - y)),
  };
}

export function handlePoint(spec, layout, target) {
  const width = layout.canvas_width;
  const height = layout.canvas_height;
  const pivot = {
    x: typeof spec.pivot_x === "number" ? spec.pivot_x * width : layout.pivot_x,
    y: typeof spec.pivot_y === "number" ? spec.pivot_y * height : layout.pivot_y,
  };
  if (target === "pivot") return { x: pivot.x / width, y: pivot.y / height };
  let center = { x: layout.center_x, y: layout.center_y };
  if (!positionLocked(spec, "center")) {
    if (spec.geometry === "polar") {
      center = { x: spec.center_x * width, y: spec.center_y * height };
    } else {
      const linear = linearFractions(spec, layout);
      center = {
        x: (linear.x + linear.width / 2) * width,
        y: (linear.y + linear.height / 2) * height,
      };
    }
  }
  const point = rotate(center, pivot, typeof spec.rotation === "number" ? spec.rotation : layout.rotation);
  return { x: point.x / width, y: point.y / height };
}

export function positionPatch(spec, layout, target, point) {
  if (positionLocked(spec, target)) return {};
  if (target === "pivot") return { pivot_x: clamp(point.x), pivot_y: clamp(point.y) };
  // Undo rotation in canvas pixels, not fractions: portrait and landscape canvases differ.
  const width = layout.canvas_width;
  const height = layout.canvas_height;
  const unrotated = rotate(
    { x: point.x * width, y: point.y * height },
    { x: spec.pivot_x * width, y: spec.pivot_y * height },
    -(spec.rotation || 0),
  );
  if (spec.geometry === "polar") return { center_x: clamp(unrotated.x / width), center_y: clamp(unrotated.y / height) };
  const linear = linearFractions(spec, layout);
  const spanX = linear.width;
  const spanY = linear.height;
  return {
    linear_x: clamp(unrotated.x / width - spanX / 2, 0, Math.max(0, 1 - spanX)),
    linear_y: clamp(unrotated.y / height - spanY / 2, 0, Math.max(0, 1 - spanY)),
    linear_width: spanX,
    linear_height: spanY,
  };
}
