import React, { useRef, useState } from "react";
import { refineLine } from "./api";
import { Popover, PopoverContent, PopoverAnchor } from "@/components/ui/popover";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Button } from "@/components/ui/button";
import { Plus, Trash } from "@/components/ui/icons";

// Turns are edited as a structured list (one text box per turn), not one
// big blob of tagged text -- that structure is what a right-click "refine
// this selection" popup needs: it has to know WHICH turn a selection
// belongs to, and to rewrite just that turn's text box without touching
// its siblings. Tagged text remains the interchange format at the
// boundaries (script generation in, rendering out) -- see toTurns/
// fromTurns in Dialogue.jsx.

let nextId = 1;
// Turns arriving from the script-generation job have no id -- this
// assigns one, once, so the list has stable React keys across edits
// instead of one being derived from array position (which breaks
// selection state whenever a turn above is added or removed).
export function withIds(turns) {
  return turns.map((t) => ({ ...t, id: t.id ?? nextId++ }));
}

function SpeakerLabel({ speaker, hosts }) {
  const name = speaker === "Person1" ? hosts.host1 : hosts.host2;
  // The two hosts get distinct colours so a long script is scannable at
  // a glance; these are the only two literal colours left in this file,
  // since neither maps onto a semantic theme variable (they aren't
  // "primary" or "accent" -- they're just two distinguishable hues).
  const cls = speaker === "Person1" ? "text-[#6fb3e0]" : "text-[#d68fd6]";
  return (
    <span className={`text-xs font-bold uppercase tracking-wide ${cls}`}>
      {name}
    </span>
  );
}

// The floating micro-prompt: appears beside the mouse on right-click over
// a selection, focused immediately, Enter to submit, Escape to cancel --
// the same mechanics as VS Code's inline Copilot edit or a Google Docs
// inline suggestion, deliberately, since that's the interaction being
// matched.
function RefinePopup({ x, y, busy, error, onSubmit, onCancel }) {
  // Anchored to the cursor position via a zero-size virtual anchor, so
  // Radix can do its own collision detection -- the previous version was
  // a fixed-position div that would render partly off-screen if you
  // right-clicked near the bottom or right edge. Radix also focuses the
  // input on open, traps focus while open, restores it on close, and
  // handles Escape/outside-click dismissal, none of which the
  // hand-rolled version did.
  return (
    <Popover open onOpenChange={(open) => !open && onCancel()}>
      <PopoverAnchor
        style={{ position: "fixed", left: x, top: y, width: 0, height: 0 }}
      />
      <PopoverContent align="start" side="bottom" className="w-72">
        <Input
          autoFocus
          type="text"
          placeholder="How should this change?"
          disabled={busy}
          onKeyDown={(e) => {
            if (e.key === "Enter" && e.target.value.trim()) {
              onSubmit(e.target.value.trim());
            }
          }}
        />
        {busy && <p className="mt-1 text-xs text-muted-foreground">Rewriting…</p>}
        {error && <p className="mt-1 text-xs text-destructive">{error}</p>}
      </PopoverContent>
    </Popover>
  );
}

/**
 * `turns`: [{id, speaker, text}], already assigned ids via withIds().
 * `onChange(turns)`: called with the full updated array on any edit.
 * `hosts`: {host1, host2} display names for the speaker labels.
 * `provider`, `model`: which LLM answers a refine request.
 */
export default function TurnEditor({ turns, onChange, hosts, provider,
                                     model }) {
  const [popup, setPopup] = useState(null);
  // {turnId, x, y, before, selected, after, busy, error}
  const boxRefs = useRef({});

  const closePopup = () => setPopup(null);

  const updateTurnText = (id, text) =>
    onChange(turns.map((t) => (t.id === id ? { ...t, text } : t)));

  const deleteTurn = (id) =>
    onChange(turns.filter((t) => t.id !== id));

  const insertTurnAfter = (id) => {
    const idx = turns.findIndex((t) => t.id === id);
    const prevSpeaker = turns[idx]?.speaker || "Person1";
    const speaker = prevSpeaker === "Person1" ? "Person2" : "Person1";
    const fresh = { id: nextId++, speaker, text: "" };
    const copy = turns.slice();
    copy.splice(idx + 1, 0, fresh);
    onChange(copy);
  };

  const swapSpeaker = (id) =>
    onChange(
      turns.map((t) =>
        t.id === id
          ? { ...t, speaker: t.speaker === "Person1" ? "Person2" : "Person1" }
          : t
      )
    );

  const handleContextMenu = (e, turn) => {
    const box = boxRefs.current[turn.id];
    if (!box) return;
    const start = box.selectionStart;
    const end = box.selectionEnd;
    if (start === end) return; // no selection -- let the normal menu show
    e.preventDefault();
    const before = turn.text.slice(0, start);
    const selected = turn.text.slice(start, end);
    const after = turn.text.slice(end);
    setPopup({
      turnId: turn.id,
      x: e.clientX,
      y: e.clientY,
      before,
      selected,
      after,
      busy: false,
      error: "",
    });
  };

  const submitRefine = async (instruction) => {
    if (!popup) return;
    if (!provider) {
      setPopup({ ...popup, error: "Choose a provider above first." });
      return;
    }
    setPopup({ ...popup, busy: true, error: "" });
    const idx = turns.findIndex((t) => t.id === popup.turnId);
    const turn = turns[idx];
    const neighborBefore = turns[idx - 1]
      ? { speaker: turns[idx - 1].speaker, text: turns[idx - 1].text }
      : null;
    const neighborAfter = turns[idx + 1]
      ? { speaker: turns[idx + 1].speaker, text: turns[idx + 1].text }
      : null;
    try {
      const { replacement } = await refineLine({
        provider,
        model: model || "",
        speaker: turn.speaker,
        before: popup.before,
        selected: popup.selected,
        after: popup.after,
        instruction,
        neighbor_before: neighborBefore,
        neighbor_after: neighborAfter,
      });
      updateTurnText(turn.id, popup.before + replacement + popup.after);
      closePopup();
    } catch (e) {
      setPopup({ ...popup, busy: false, error: String(e.message || e) });
    }
  };

  // No manual Escape/outside-click listeners here any more: Radix's
  // Popover does both itself, and keeping these would double-fire
  // closePopup on every dismissal.

  return (
    <div className="flex flex-col gap-1.5">
      <p className="hint">
        Select a phrase and right-click to rewrite just that part — say how
        it should change and press Enter.
      </p>
      {turns.map((turn) => (
        <div
          className="rounded-md border border-border bg-card p-2"
          key={turn.id}
        >
          <div className="mb-1 flex items-center justify-between">
            <Button
              variant="ghost"
              size="sm"
              title="Switch speaker"
              onClick={() => swapSpeaker(turn.id)}
            >
              <SpeakerLabel speaker={turn.speaker} hosts={hosts} />
            </Button>
            <Button
              variant="ghost"
              size="sm"
              title="Delete this line"
              aria-label="Delete this line"
              onClick={() => deleteTurn(turn.id)}
            >
              <Trash className="h-3.5 w-3.5" />
            </Button>
          </div>
          <Textarea
            ref={(el) => (boxRefs.current[turn.id] = el)}
            rows={Math.max(2, Math.ceil(turn.text.length / 70))}
            value={turn.text}
            onChange={(e) => updateTurnText(turn.id, e.target.value)}
            onContextMenu={(e) => handleContextMenu(e, turn)}
          />
          <Button
            variant="ghost"
            size="sm"
            className="mt-1 self-start border border-dashed border-border"
            title="Insert a new line after this one"
            onClick={() => insertTurnAfter(turn.id)}
          >
            <Plus className="h-3 w-3" /> line
          </Button>
        </div>
      ))}
      {turns.length === 0 && (
        <p className="hint">No turns yet — write a script above.</p>
      )}
      {popup && (
        <RefinePopup
          x={popup.x}
          y={popup.y}
          busy={popup.busy}
          error={popup.error}
          onSubmit={submitRefine}
          onCancel={closePopup}
        />
      )}
    </div>
  );
}
