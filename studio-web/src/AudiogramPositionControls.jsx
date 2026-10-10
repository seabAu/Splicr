import React, { useRef } from "react";
import { handlePoint, pointerFraction, positionLocked, positionPatch } from "./audiogramPosition.js";

export function AudiogramPositionHandle({ spec, layout, target, onChange }) {
  const gesture = useRef(null);
  const point = handlePoint(spec, layout, target);
  const locked = positionLocked(spec, target);
  const move = (event) => {
    const start = gesture.current;
    if (!start || event.pointerId !== start.pointerId) return;
    const next = pointerFraction(event.clientX, event.clientY, start.rect);
    if (next) onChange(positionPatch(start.spec, start.layout, target, next));
  };
  const finish = (event) => {
    if (gesture.current?.pointerId !== event.pointerId) return;
    gesture.current = null;
    if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
  };
  return (
    <button
      className={`audiogram-position-handle is-${target}`}
      type="button"
      aria-label={`Move audiogram ${target}`}
      aria-disabled={locked}
      aria-describedby="audiogram-position-help"
      title={locked ? "Position is formula-controlled; edit the formula first." : `Drag ${target}, or use arrow keys (Shift for larger steps)`}
      style={{ left: `${point.x * 100}%`, top: `${point.y * 100}%` }}
      onPointerDown={(event) => {
        if (locked || event.button !== 0) return;
        event.preventDefault();
        event.currentTarget.focus();
        event.currentTarget.setPointerCapture(event.pointerId);
        gesture.current = { pointerId: event.pointerId, rect: event.currentTarget.parentElement.getBoundingClientRect(), spec, layout };
      }}
      onPointerMove={move}
      onPointerUp={(event) => { move(event); finish(event); }}
      onPointerCancel={finish}
      onLostPointerCapture={() => { gesture.current = null; }}
      onKeyDown={(event) => {
        const direction = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] }[event.key];
        if (!direction || locked) return;
        event.preventDefault();
        const step = event.shiftKey ? 0.05 : 0.01;
        onChange(positionPatch(spec, layout, target, { x: point.x + direction[0] * step, y: point.y + direction[1] * step }));
      }}
    >{target === "pivot" ? "+" : "⊙"}</button>
  );
}
