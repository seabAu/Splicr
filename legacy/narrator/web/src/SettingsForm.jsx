import React, { useEffect, useRef, useState } from "react";
import FileBrowser from "./FileBrowser";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

// Generated from /api/schema, never hand-written. Adding a field to
// render_config.py makes it appear here with the right control, range and
// description -- which is the entire reason the schema exists.
//
// One exception: "voice" isn't just a string, it's engine-dependent --
// what counts as a valid value, and whether typing a new one even makes
// sense, both depend on which engine is currently selected. The schema
// has no way to express that relationship (it only has kind/choices for
// a field considered alone), so this is the one field handled specially
// here rather than generically, mirroring exactly what the desktop's own
// voice Combobox does: a fixed-voice engine (Kokoro, edge-tts) gets a
// closed dropdown of its real preset voices; an engine that designs a
// voice from a description (Qwen3, Audio8) gets a free-typing field with
// its example descriptions offered as suggestions, not a hard-limited
// list, since a new description IS a valid, new value.

function findEngineSpec(engines, engineName) {
  return (engines || []).find((e) => e.name === engineName) || null;
}

function VoiceField({ field, value, onChange, engines, engineName }) {
  const id = `f-${field.key}`;
  const spec = findEngineSpec(engines, engineName);

  // A voice value from the PREVIOUS engine rarely means anything to the
  // new one -- a Kokoro preset id shown to Qwen3, or vice versa -- so
  // when the engine actually changes (not on first mount, and not when
  // a saved project sets engine+voice together to an already-matching
  // pair), reset to that engine's first real voice. Mirrors the
  // desktop's own refresh_voices(), just without its "remember my last
  // pick per engine" persistence layer.
  // A voice value left over from a DIFFERENT engine rarely means
  // anything to this one -- a Kokoro preset id shown to Qwen3, or a
  // preset that simply isn't in this engine's list. Reset to this
  // engine's first voice when that happens, mirroring the desktop's own
  // refresh_voices(). Restricted to non-editable engines and to values
  // that don't already belong to the new engine's real preset list --
  // an editable engine accepts any typed description as a legitimate
  // value (there's no fixed set to check membership against), and this
  // must NOT fire just because a saved project set engine+voice together
  // to an already-matching pair (e.g. loaded from the Library) -- only
  // when the value truly doesn't belong to the current engine.
  const prevEngine = useRef(engineName);
  useEffect(() => {
    if (prevEngine.current === engineName) return;
    prevEngine.current = engineName;
    if (!spec || spec.editable) return;
    const stillValid = spec.voices.some((v) => v.id === value);
    if (!stillValid) onChange(field.key, spec.voices[0]?.id || "");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [engineName]);

  if (!spec) {
    // No engine chosen yet (or the engines list hasn't loaded) -- fall
    // back to plain text rather than showing an empty, useless dropdown.
    return (
      <div className="field field-row" title={field.description}>
        <Label htmlFor={id}>{field.key}</Label>
        <Input
          id={id}
          type="text"
          value={value ?? ""}
          onChange={(e) => onChange(field.key, e.target.value)}
          placeholder="Choose an engine above first"
        />
      </div>
    );
  }

  if (!spec.editable) {
    // A fixed set of real preset voices -- only these are valid, so a
    // closed dropdown (matching the desktop's readonly Combobox).
    return (
      <div className="field field-row" title={field.description}>
        <Label htmlFor={id}>{field.key}</Label>
        {/* No empty-string item: Radix reserves "" and rejects it as an
           Item value. "Nothing chosen" is expressed by leaving value
           undefined and letting the placeholder show. */}
        <Select
          value={value || undefined}
          onValueChange={(v) => onChange(field.key, v)}
        >
          <SelectTrigger id={id}>
            <SelectValue placeholder="Choose a voice…" />
          </SelectTrigger>
          <SelectContent>
            {spec.voices.map((v) => (
              <SelectItem key={v.id} value={v.id}>
                {v.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
    );
  }

  // An editable engine: any typed description is a legitimate value (it
  // designs a new voice from it), so this is a real text field -- but
  // its saved/example voices are offered as suggestions via a datalist,
  // which still lets the browser autocomplete/filter as you type without
  // limiting what can be entered, the same dual behaviour the desktop's
  // editable Combobox has.
  const listId = `${id}-options`;
  return (
    <div className="field field-row" title={field.description}>
      <Label htmlFor={id}>{field.key}</Label>
      <Input
        id={id}
        type="text"
        list={listId}
        value={value ?? ""}
        onChange={(e) => onChange(field.key, e.target.value)}
        placeholder="Describe the voice, or pick a saved one"
      />
      <datalist id={listId}>
        {spec.voices.map((v) => (
          <option key={v.id} value={v.id}>
            {v.label}
          </option>
        ))}
      </datalist>
    </div>
  );
}

function Field({ field, value, onChange, onBrowse, engines, engineName }) {
  const id = `f-${field.key}`;
  const common = { id, value: value ?? "", onChange: (e) => onChange(field.key, e.target.value) };

  if (field.key === "voice") {
    return (
      <VoiceField
        field={field}
        value={value}
        onChange={onChange}
        engines={engines}
        engineName={engineName}
      />
    );
  }

  let control;
  if (field.kind === "bool") {
    // Radix reports the new state directly, rather than an event whose
    // target must be read -- and it can report "indeterminate", which
    // this app never uses, so anything non-true is treated as false.
    control = (
      <Checkbox
        id={id}
        checked={!!value}
        onCheckedChange={(checked) => onChange(field.key, checked === true)}
      />
    );
  } else if (field.kind === "choice") {
    control = (
      <Select
        value={value === undefined || value === null || value === ""
              ? undefined
              : String(value)}
        onValueChange={(v) => onChange(field.key, v)}
      >
        <SelectTrigger id={id}>
          <SelectValue placeholder="--" />
        </SelectTrigger>
        <SelectContent>
          {(field.choices || []).map((c) => (
            <SelectItem key={String(c)} value={String(c)}>
              {String(c)}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    );
  } else if (field.kind === "int" || field.kind === "float") {
    control = (
      <Input
        {...common}
        type="number"
        min={field.min}
        max={field.max}
        step={field.kind === "int" ? 1 : "any"}
      />
    );
  } else if (field.kind === "path") {
    control = (
      <span className="field-path">
        <code className="field-path-value">{value || "(not set)"}</code>
        <Button type="button" size="sm" onClick={() => onBrowse(field)}>
          Choose…
        </Button>
      </span>
    );
  } else {
    control = <Input {...common} type="text" />;
  }

  return (
    <div className="field field-row" title={field.description}>
      <Label htmlFor={id}>
        {field.key}
        {field.required && <span className="req"> *</span>}
      </Label>
      {control}
    </div>
  );
}

export default function SettingsForm({ fields, cfg, onChange, advanced, engines,
                                       hide = [] }) {
  // Required fields first; everything else behind a toggle, so the common
  // case isn't a wall of twenty-six inputs. `hide` skips fields the
  // caller already presents elsewhere (they stay in cfg regardless).
  const shown = (advanced ? fields : fields.filter((f) => f.required))
    .filter((f) => !hide.includes(f.key));
  const [browsing, setBrowsing] = useState(null); // the field being browsed

  return (
    <div className="settings">
      {shown.map((field) => (
        <Field
          key={field.key}
          field={field}
          value={cfg[field.key]}
          onChange={onChange}
          onBrowse={setBrowsing}
          engines={engines}
          engineName={cfg.engine}
        />
      ))}
      {browsing && (
        <FileBrowser
          onlyDirs={browsing.path_kind === "dir"}
          onPick={(p) => {
            onChange(browsing.key, p);
            setBrowsing(null);
          }}
          onClose={() => setBrowsing(null)}
        />
      )}
    </div>
  );
}
