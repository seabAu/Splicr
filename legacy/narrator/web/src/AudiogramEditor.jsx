import React, { useEffect, useState } from "react";
import {
  getTakes,
  getAudiogramDefaults,
  getAudiogramSource,
  getAudiogramLayout,
  fetchAudiogramPreviewPng,
  getAudiogramCommand,
  getAudiogramEstimate,
  getAudiogramPreviewReason,
  startAudiogramPreviewMotion,
  startAudiogramExport,
  getExpressionsReference,
  validateExpression,
} from "./api";
import FileBrowser from "./FileBrowser";
import JobLog from "./JobLog";
import { Popover, PopoverTrigger, PopoverContent } from "@/components/ui/popover";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { FunctionIcon } from "@/components/ui/icons";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";

// The preview picture is a PNG rendered server-side by draw_frame() --
// the SAME function the real export uses -- never reimplemented in the
// browser. That's a deliberate carry-over from the desktop's own design
// note: a mockup that could disagree with the real renderer is worse
// than no preview at all. The guide overlay (box/center/pivot) is SVG
// drawn from layout()'s real pixel numbers, fetched from the server for
// the same reason -- so the guides can't drift from where the waveform
// actually lands either.

const PW = 480;
const PH = 270;
const RESOLUTIONS = ["1280x720", "1920x1080", "2560x1440", "3840x2160"];

function useDebounced(value, ms) {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setDebounced(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return debounced;
}

function isFormulaValue(v) {
  return typeof v === "string" && /[a-zA-Z(]/.test(v);
}

function currentToken(text) {
  let token = "";
  for (let i = text.length - 1; i >= 0; i--) {
    const ch = text[i];
    if (/[a-zA-Z0-9_]/.test(ch)) token = ch + token;
    else break;
  }
  return token;
}

// A small "ƒx" toggle next to an animatable field opens this, rather
// than one always-open panel for every animatable value at once -- each
// popover is scoped to the one field it's attached to, closes on
// Escape/outside-click, and starts closed. The filter-as-you-type
// reference list and live validation are the same behaviour the old
// single panel had, just contained to one field now.
function FormulaPopover({ cfgKey, cfg, onChange, onClose }) {
  const initial = isFormulaValue(cfg[cfgKey]) ? cfg[cfgKey] : "";
  const [formula, setFormula] = useState(initial);
  const [msg, setMsg] = useState({ text: "", ok: true });
  const [refItems, setRefItems] = useState([]);

  useEffect(() => {
    getExpressionsReference(currentToken(formula))
      .then((r) => setRefItems(r.items))
      .catch(() => {});
    if (!formula.trim()) {
      setMsg({ text: "Leave empty to use a plain number.", ok: true });
      return;
    }
    const t = setTimeout(() => {
      validateExpression(formula)
        .then((r) => setMsg({ text: r.message, ok: r.ok }))
        .catch((e) => setMsg({ text: String(e.message || e), ok: false }));
    }, 200);
    return () => clearTimeout(t);
  }, [formula]);

  // Escape and outside-click dismissal come from Radix's Popover now,
  // so no document-level listeners here.

  const insert = (name) => {
    const token = currentToken(formula);
    const base = token ? formula.slice(0, -token.length) : formula;
    setFormula(base + name);
  };

  const apply = () => {
    if (!formula.trim()) {
      onChange(cfgKey, 0.0);
      onClose();
      return;
    }
    if (!msg.ok) return;
    onChange(cfgKey, formula);
    onClose();
  };

  const clear = () => {
    onChange(cfgKey, 0.0);
    onClose();
  };

  return (
    <>
      <p className="text-xs text-muted-foreground">
        A formula, worked out fresh for every frame.
      </p>
      <Input
        autoFocus
        className="mt-1.5 font-mono"
        value={formula}
        onChange={(e) => setFormula(e.target.value)}
        onKeyDown={(e) => e.key === "Enter" && apply()}
      />
      <p
        className={`mt-1 text-xs ${
          msg.ok ? "text-muted-foreground" : "text-destructive"
        }`}
      >
        {msg.text}
      </p>
      <ul className="mt-1 max-h-28 overflow-y-auto rounded-md border border-border font-mono text-[11px]">
        {refItems.map((item) => (
          <li
            key={item.name}
            className="cursor-pointer px-1.5 py-0.5 hover:bg-secondary"
            onClick={() => insert(item.name)}
          >
            {item.kind === "variable" ? "var " : "func"}{" "}
            <b>{item.name}</b> {item.detail}
          </li>
        ))}
      </ul>
      <div className="mt-2 flex gap-1.5">
        <Button size="sm" variant="primary" onClick={apply}>
          Apply
        </Button>
        {isFormulaValue(cfg[cfgKey]) && (
          <Button size="sm" onClick={clear}>
            Clear
          </Button>
        )}
        <Button size="sm" variant="ghost" onClick={onClose}>
          Cancel
        </Button>
      </div>
    </>
  );
}

function NumberField({ label, cfgKey, cfg, onChange, lo, hi, step, animatable }) {
  const canAnimate = animatable && animatable.includes(cfgKey);
  const isFormula = isFormulaValue(cfg[cfgKey]);
  const [open, setOpen] = useState(false);

  return (
    <div className="ag-field ag-field-animatable">
      <Label>{label}</Label>
      <span className="ag-field-control">
        {isFormula ? (
          <code
            className="w-20 cursor-pointer rounded bg-accent px-2 py-1 text-center text-xs text-accent-foreground"
            title={cfg[cfgKey]}
            onClick={() => setOpen(true)}
          >
            ƒ(t)
          </code>
        ) : (
          <Input
            type="number"
            className="h-7 w-20 px-1.5 text-xs"
            min={lo}
            max={hi}
            step={step}
            value={cfg[cfgKey]}
            onChange={(e) => {
              const v = Number(e.target.value);
              if (!Number.isNaN(v))
                onChange(cfgKey, Math.max(lo, Math.min(hi, v)));
            }}
          />
        )}
        {canAnimate && (
          // The trigger IS the fx button, so Radix returns focus to it
          // when the popover closes -- the hand-rolled version left
          // focus wherever it happened to be.
          <Popover open={open} onOpenChange={setOpen}>
            <PopoverTrigger asChild>
              <Button
                type="button"
                size="sm"
                variant={isFormula ? "default" : "ghost"}
                className={isFormula ? "border-primary text-primary" : ""}
                title={isFormula ? "Edit the formula" : "Turn into a formula"}
                aria-label={isFormula ? "Edit the formula" : "Turn into a formula"}
              >
                <FunctionIcon className="h-3.5 w-3.5" />
              </Button>
            </PopoverTrigger>
            <PopoverContent align="end" className="w-72">
              <FormulaPopover
                cfgKey={cfgKey}
                cfg={cfg}
                onChange={onChange}
                onClose={() => setOpen(false)}
              />
            </PopoverContent>
          </Popover>
        )}
      </span>
    </div>
  );
}

export default function AudiogramEditor() {
  const [takes, setTakes] = useState([]);
  const [manifest, setManifest] = useState("");
  const [cfg, setCfg] = useState(null);
  const [animatable, setAnimatable] = useState([]);
  const [codecs, setCodecs] = useState([]);
  const [previewMaxSeconds, setPreviewMaxSeconds] = useState(8);
  const [sourceNote, setSourceNote] = useState("");
  const [sourceWarning, setSourceWarning] = useState(false);
  const [pickingSource, setPickingSource] = useState(false);
  const [previewUrl, setPreviewUrl] = useState(null);
  const [guide, setGuide] = useState(null);
  const [status, setStatus] = useState("");
  const [statusOk, setStatusOk] = useState(true);

  const note = (text, ok = true) => {
    setStatus(text);
    setStatusOk(ok);
  };

  useEffect(() => {
    getAudiogramDefaults()
      .then((d) => {
        setCfg(d.cfg);
        setAnimatable(d.animatable);
        setCodecs(d.codecs);
        setPreviewMaxSeconds(d.preview_max_seconds);
      })
      .catch((e) => note(String(e.message || e), false));
    getTakes()
      .then((r) => {
        setTakes(r.takes);
        setManifest((prev) =>
          prev || (r.takes.length ? r.takes[r.takes.length - 1].manifest : "")
        );
      })
      .catch(() => {});
  }, []);

  const set = (key, value) => setCfg((c) => ({ ...c, [key]: value }));

  // Debounced: every keystroke on a spinbox would otherwise fire a
  // server round-trip per character.
  const debouncedCfg = useDebounced(cfg, 150);

  useEffect(() => {
    if (!debouncedCfg) return;
    let cancelled = false;
    fetchAudiogramPreviewPng(debouncedCfg, PW, PH)
      .then((url) => {
        if (!cancelled) setPreviewUrl((old) => {
          if (old) URL.revokeObjectURL(old);
          return url;
        });
      })
      .catch((e) => !cancelled && note(String(e.message || e), false));
    getAudiogramLayout(debouncedCfg, PW, PH)
      .then((g) => !cancelled && setGuide(g))
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [debouncedCfg]);

  useEffect(() => {
    getAudiogramSource(manifest)
      .then((r) => {
        setSourceNote(r.note);
        setSourceWarning(r.warning);
      })
      .catch(() => {});
  }, [manifest, cfg?.audio_source]);

  if (!cfg) return <p className="hint">Loading…</p>;

  const box = guide?.box || [0, 0, 0, 0];
  const center = guide?.center || [0, 0];
  const pivot = guide?.pivot || [0, 0];

  return (
    <div className="audiogram-editor">
      <div className="row">
        <Label>Waveform from</Label>
        <span className={sourceWarning ? "warn" : "hint"}>{sourceNote}</span>
        <Button onClick={() => setPickingSource(true)}>Choose…</Button>
        {cfg.audio_source && (
          <Button onClick={() => set("audio_source", "")}>Use the take</Button>
        )}
      </div>
      {pickingSource && (
        <FileBrowser
          onPick={(p) => {
            set("audio_source", p);
            setPickingSource(false);
          }}
          onClose={() => setPickingSource(false)}
        />
      )}

      <div className="row">
<Label>Take</Label>
        <Select
          value={manifest || undefined}
          onValueChange={setManifest}
          disabled={takes.length === 0}
        >
          <SelectTrigger className="w-auto min-w-[16rem]">
            <SelectValue
              placeholder={takes.length === 0 ? "no takes yet" : "Choose a take…"}
            />
          </SelectTrigger>
          <SelectContent>
            {takes.map((t) => (
              <SelectItem key={t.manifest} value={t.manifest}>
                {t.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <div className="ag-body">
        <div className="ag-left">
          <ShapeSection cfg={cfg} set={set} animatable={animatable} />
          <PositionSection cfg={cfg} set={set} animatable={animatable} />
          <AppearanceSection cfg={cfg} set={set} animatable={animatable} />
        </div>

        <div className="ag-right">
          <Label className="ag-heading">Preview</Label>
          <div className="ag-preview-wrap">
            {previewUrl ? (
              <img
                src={previewUrl}
                width={PW}
                height={PH}
                className="ag-preview-img"
                alt="audiogram preview"
              />
            ) : (
              <div
                className="ag-preview-img ag-preview-loading"
                style={{ width: PW, height: PH }}
              />
            )}
            <svg
              className="ag-preview-overlay"
              width={PW}
              height={PH}
              viewBox={`0 0 ${PW} ${PH}`}
            >
              <rect
                x={box[0]} y={box[1]}
                width={box[2] - box[0]} height={box[3] - box[1]}
                fill="none" stroke="#4ea3ff" strokeDasharray="4,3"
              />
              <circle cx={center[0]} cy={center[1]} r={4}
                     fill="none" stroke="#4dff88" strokeWidth={2} />
              <text x={center[0] + 8} y={center[1] - 10} fill="#4dff88"
                   fontSize={9}>audiogram centre</text>
              {/* The pivot is where ROTATION turns around -- always
                 relative to the whole frame, not the audiogram's own
                 box (matching the desktop). At rotation 0 it does
                 nothing, so it's shown faded rather than hidden --
                 dropping it outright would make it harder to find
                 when you actually want to set it. */}
              <g opacity={cfg.rotation ? 1 : 0.35}>
                <line x1={pivot[0] - 7} x2={pivot[0] + 7}
                     y1={pivot[1]} y2={pivot[1]} stroke="#ff7b4d" strokeWidth={2} />
                <line x1={pivot[0]} x2={pivot[0]}
                     y1={pivot[1] - 7} y2={pivot[1] + 7} stroke="#ff7b4d" strokeWidth={2} />
                <text x={pivot[0] + 9} y={pivot[1] + 9} fill="#ff7b4d"
                     fontSize={9}>
                  rotation pivot{!cfg.rotation ? " (unused at 0°)" : ""}
                </text>
              </g>
            </svg>
          </div>
          <p className="hint">
            Dashed box: the audiogram's area. Green: the audiogram's own
            centre. Orange: where rotation turns around — this is
            relative to the whole frame, not the audiogram's box, so it
            can land far from the waveform when they don't overlap; that's
            expected, not a bug.
            {guide &&
              ` Cropped export would cover ${(guide.crop_fraction * 100).toFixed(0)}% of the frame` +
                (guide.rotation_disables_crop
                  ? " (rotation disables cropping)."
                  : ".")}
          </p>

          {status && <p className={statusOk ? "ok" : "error"}>{status}</p>}

          <ExportSection
            cfg={cfg} manifest={manifest} codecs={codecs} note={note}
          />
          <MotionSection
            cfg={cfg} manifest={manifest}
            previewMaxSeconds={previewMaxSeconds} note={note}
          />
          <CommandSection cfg={cfg} set={set} manifest={manifest} />
        </div>
      </div>
    </div>
  );
}

function ShapeSection({ cfg, set, animatable }) {
  return (
    <fieldset className="ag-group">
      <legend>Shape</legend>
      <div className="ag-field">
        <Label>Geometry</Label>
        <Select value={cfg.geometry} onValueChange={(v) => set("geometry", v)}>
          <SelectTrigger className="w-28">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="linear">linear</SelectItem>
            <SelectItem value="polar">polar</SelectItem>
          </SelectContent>
        </Select>
      </div>
      <div className="ag-field">
        <Label>Layers</Label>
        <div className="ag-checks">
          {[
            ["show_bars", "Bars"],
            ["show_line", "Line"],
            ["show_fill", "Fill"],
          ].map(([key, label]) => (
            <div key={key} className="flex items-center gap-1.5">
              <Checkbox
                id={`ag-${key}`}
                checked={!!cfg[key]}
                onCheckedChange={(c) => set(key, c === true)}
              />
              <Label htmlFor={`ag-${key}`}>{label}</Label>
            </div>
          ))}
        </div>
      </div>
      <NumberField label="Bars" cfgKey="bars" cfg={cfg} onChange={set}
                  lo={4} hi={512} step={4} />
      <NumberField label="Bar width" cfgKey="bar_width" cfg={cfg}
                  onChange={set} lo={0.05} hi={1.0} step={0.05} />
      <NumberField label="Line width" cfgKey="line_width" cfg={cfg}
                  onChange={set} lo={1} hi={40} step={1} animatable={animatable} />
      <NumberField label="Smoothing" cfgKey="smoothing" cfg={cfg}
                  onChange={set} lo={0.0} hi={0.95} step={0.05} />
      <div className="mt-1 flex items-center gap-1.5">
        <Checkbox
          id="ag-mirror"
          checked={!!cfg.mirror}
          onCheckedChange={(c) => set("mirror", c === true)}
        />
        <Label htmlFor="ag-mirror">Mirror (grow both ways)</Label>
      </div>
    </fieldset>
  );
}

function PositionSection({ cfg, set, animatable }) {
  return (
    <fieldset className="ag-group">
      <legend>Position and size</legend>
      <NumberField label="X" cfgKey="x" cfg={cfg} onChange={set} lo={0} hi={1} step={0.01} animatable={animatable} />
      <NumberField label="Y" cfgKey="y" cfg={cfg} onChange={set} lo={0} hi={1} step={0.01} animatable={animatable} />
      <NumberField label="Width" cfgKey="width" cfg={cfg} onChange={set} lo={0.02} hi={1} step={0.01} animatable={animatable} />
      <NumberField label="Height" cfgKey="height" cfg={cfg} onChange={set} lo={0.02} hi={1} step={0.01} animatable={animatable} />
      <NumberField label="Centre X" cfgKey="center_x" cfg={cfg} onChange={set} lo={0} hi={1} step={0.01} animatable={animatable} />
      <NumberField label="Centre Y" cfgKey="center_y" cfg={cfg} onChange={set} lo={0} hi={1} step={0.01} animatable={animatable} />
      <NumberField label="Inner radius" cfgKey="inner_radius" cfg={cfg} onChange={set} lo={0} hi={0.6} step={0.01} animatable={animatable} />
      <NumberField label="Outer radius" cfgKey="outer_radius" cfg={cfg} onChange={set} lo={0.02} hi={0.7} step={0.01} animatable={animatable} />
      <NumberField label="Pivot X" cfgKey="pivot_x" cfg={cfg} onChange={set} lo={0} hi={1} step={0.01} animatable={animatable} />
      <NumberField label="Pivot Y" cfgKey="pivot_y" cfg={cfg} onChange={set} lo={0} hi={1} step={0.01} animatable={animatable} />
      <NumberField label="Rotation" cfgKey="rotation" cfg={cfg} onChange={set} lo={-180} hi={180} step={5} animatable={animatable} />
    </fieldset>
  );
}

function AppearanceSection({ cfg, set, animatable }) {
  return (
    <fieldset className="ag-group">
      <legend>Appearance</legend>
      <div className="ag-field">
        <Label>Colour (#rrggbb)</Label>
        <Input value={cfg.color} onChange={(e) => set("color", e.target.value)} />
      </div>
      <div className="ag-field">
        <Label>Line colour</Label>
        <Input value={cfg.line_color}
              onChange={(e) => set("line_color", e.target.value)}
              placeholder="blank = same as Colour" />
      </div>
      <div className="ag-field">
        <Label>Fill colour</Label>
        <Input value={cfg.fill_color}
              onChange={(e) => set("fill_color", e.target.value)}
              placeholder="blank = same as Colour" />
      </div>
      <NumberField label="Fill opacity" cfgKey="fill_opacity" cfg={cfg} onChange={set} lo={0} hi={1} step={0.05} />
      <NumberField label="Opacity" cfgKey="opacity" cfg={cfg} onChange={set} lo={0} hi={1} step={0.05} animatable={animatable} />
    </fieldset>
  );
}


function CommandSection({ cfg, set, manifest }) {
  const [command, setCommand] = useState("");
  const [override, setOverride] = useState(cfg.filter_override || "");
  const debouncedOverride = useDebounced(override, 200);
  const debouncedCfg = useDebounced(cfg, 200);

  useEffect(() => {
    getAudiogramCommand(manifest, 1920, 1080, debouncedOverride)
      .then((r) => setCommand(r.command))
      .catch(() => {});
  }, [manifest, debouncedOverride, debouncedCfg]);

  useEffect(() => {
    set("filter_override", override.trim());
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [debouncedOverride]);

  return (
    <fieldset className="ag-group">
      <legend>The ffmpeg command</legend>
      <p className="hint">
        What the fast path will run. Put your own filter graph below to
        use it instead; clear it to go back to the built one.
      </p>
      <Textarea className="ag-command" rows={4} readOnly value={command} />
      <div className="row">
        <Label>Your filter graph</Label>
        <Input value={override} onChange={(e) => setOverride(e.target.value)} />
      </div>
    </fieldset>
  );
}

function ExportSection({ cfg, manifest, codecs, note }) {
  const [codec, setCodec] = useState("webm");
  const [resolution, setResolution] = useState("1920x1080");
  const [crop, setCrop] = useState(true);
  const [jobId, setJobId] = useState(null);
  const [busy, setBusy] = useState(false);
  const [estimate, setEstimate] = useState("");
  const [width, height] = resolution.split("x").map(Number);
  const debouncedCfg = useDebounced(cfg, 300);

  useEffect(() => {
    getAudiogramEstimate(manifest, width, height, cfg.fps || 30, crop, codec)
      .then((r) => setEstimate(r.text))
      .catch(() => {});
  }, [manifest, resolution, crop, codec, cfg.fps, debouncedCfg]);

  const start = async () => {
    setBusy(true);
    note("Rendering the overlay — progress is below.");
    try {
      const job = await startAudiogramExport({
        cfg, manifest, codec, width, height, crop,
      });
      setJobId(job.id);
    } catch (e) {
      note(String(e.message || e), false);
      setBusy(false);
    }
  };

  return (
    <fieldset className="ag-group">
      <legend>Bake to a transparent overlay</legend>
      <p className="hint">
        Renders once here so your editor only composites it — no
        waveform recomputed per frame.
      </p>
      <div className="ag-field">
        <Label>Format</Label>
        <Select value={codec} onValueChange={setCodec}>
          <SelectTrigger className="w-auto min-w-[12rem]">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {codecs.map((c) => (
              <SelectItem key={c.key} value={c.key}>
                {c.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
      <div className="ag-field">
        <Label>Resolution</Label>
        <Select value={resolution} onValueChange={setResolution}>
          <SelectTrigger className="w-36">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {RESOLUTIONS.map((r) => (
              <SelectItem key={r} value={r}>
                {r}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
      <div className="mt-1 flex items-center gap-1.5">
        <Checkbox
          id="ag-crop"
          checked={crop}
          onCheckedChange={(c) => setCrop(c === true)}
        />
        <Label htmlFor="ag-crop">
          Crop to the audiogram's area (much faster and smaller)
        </Label>
      </div>
      <Button disabled={busy} onClick={start}>
        Render overlay…
      </Button>
      {estimate && <p className="hint">{estimate}</p>}
      <JobLog
        jobId={jobId}
        onFinished={(snap) => {
          setBusy(false);
          if (snap.status === "done") {
            note(snap.outcome || "Done.");
          } else if (snap.status === "failed") {
            note(snap.error || "Export failed.", false);
          }
        }}
      />
    </fieldset>
  );
}

function MotionSection({ cfg, manifest, previewMaxSeconds, note }) {
  const [seconds, setSeconds] = useState(5);
  const [jobId, setJobId] = useState(null);
  const [busy, setBusy] = useState(false);
  const [reason, setReason] = useState("");

  useEffect(() => {
    getAudiogramPreviewReason()
      .then((r) => setReason(r.text))
      .catch(() => {});
  }, [cfg]);

  const start = async () => {
    setBusy(true);
    note("Rendering a short preview…");
    try {
      const job = await startAudiogramPreviewMotion(manifest, seconds);
      setJobId(job.id);
    } catch (e) {
      note(String(e.message || e), false);
      setBusy(false);
    }
  };

  return (
    <fieldset className="ag-group">
      <legend>See it moving</legend>
      <p className="hint">
        A still frame can't show smoothing, blur or motion at all. This
        renders a few seconds so you can watch it.
      </p>
      <div className="row">
        <Label>Seconds</Label>
        <Input
          type="number"
          min={1}
          max={previewMaxSeconds}
          value={seconds}
          onChange={(e) => setSeconds(Number(e.target.value))}
        />
        <Button disabled={busy} onClick={start}>
          Preview motion
        </Button>
      </div>
      <p className="hint">{reason}</p>
      <JobLog
        jobId={jobId}
        onFinished={(snap) => {
          setBusy(false);
          if (snap.status === "done") {
            note(`Preview ready (${snap.result?.engine} renderer).`);
          } else if (snap.status === "failed") {
            note(snap.error || "Preview failed.", false);
          }
        }}
      />
    </fieldset>
  );
}
