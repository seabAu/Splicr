import React, { useEffect, useState } from "react";
import { convertOptions, startConvert } from "./api";
import FileBrowser from "./FileBrowser";
import JobLog from "./JobLog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

// Splitting by size can only be approached, not set directly: ffmpeg
// controls duration, so the backend measures the converted file's real
// bitrate, estimates, then verifies and re-splits if a part came out over.
export default function Convert({ onJob }) {
  const [options, setOptions] = useState(null);
  const [source, setSource] = useState("");
  const [picking, setPicking] = useState(false);
  const [jobId, setJobId] = useState(null);
  const [status, setStatus] = useState("");
  const [form, setForm] = useState({
    format: "",
    quality_pct: 70,
    sample_rate: 48000,
    bit_depth: 16,
    channels: 0,
    split_mode: "none",
    split_minutes: 20,
    split_mb: 25,
  });
  const [error, setError] = useState("");

  useEffect(() => {
    convertOptions()
      .then((o) => {
        setOptions(o);
        setForm((f) => ({ ...f, format: f.format || o.formats[0] }));
      })
      .catch((e) => setError(String(e.message || e)));
  }, []);

  const set = (key, value) => setForm((f) => ({ ...f, [key]: value }));

  if (!options) return <p className="hint">Loading…</p>;

  return (
    <div className="convert">
      <div className="row">
        <code>{source || "no file chosen"}</code>
        <Button onClick={() => setPicking(true)}>Choose audio…</Button>
      </div>
      {picking && (
        <FileBrowser
          onPick={(p) => {
            setSource(p);
            setPicking(false);
          }}
          onClose={() => setPicking(false)}
        />
      )}

      <div className="settings">
        <div className="field">
          <Label htmlFor="cv-format">Format</Label>
          <Select value={form.format} onValueChange={(v) => set("format", v)}>
            <SelectTrigger id="cv-format">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {options.formats.map((f) => (
                <SelectItem key={f} value={f}>
                  {f}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="field">
          <Label htmlFor="cv-quality">Quality ({form.quality_pct}%)</Label>
          {/* A range slider isn't a text field -- the Input component's
             border/height/padding are wrong for it, so it keeps a plain
             element with its own minimal styling. */}
          <input
            id="cv-quality"
            type="range"
            className="w-full accent-[hsl(var(--primary))]"
            min="0"
            max="100"
            step="10"
            value={form.quality_pct}
            onChange={(e) => set("quality_pct", Number(e.target.value))}
          />
        </div>
        <div className="field">
          <Label htmlFor="cv-rate">Sample rate</Label>
          <Select
            value={String(form.sample_rate)}
            onValueChange={(v) => set("sample_rate", Number(v))}
          >
            <SelectTrigger id="cv-rate">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {options.sample_rates.map((r) => (
                <SelectItem key={r} value={String(r)}>
                  {r} Hz
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="field">
          <Label htmlFor="cv-depth">Bit depth (WAV/FLAC)</Label>
          <Select
            value={String(form.bit_depth)}
            onValueChange={(v) => set("bit_depth", Number(v))}
          >
            <SelectTrigger id="cv-depth">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {options.bit_depths.map((b) => (
                <SelectItem key={b} value={String(b)}>
                  {b}-bit
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="field">
          <Label htmlFor="cv-ch">Channels</Label>
          <Select
            value={String(form.channels)}
            onValueChange={(v) => set("channels", Number(v))}
          >
            <SelectTrigger id="cv-ch">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="0">Keep as-is</SelectItem>
              <SelectItem value="1">Mono</SelectItem>
              <SelectItem value="2">Stereo</SelectItem>
            </SelectContent>
          </Select>
        </div>
      </div>

      <fieldset className="split">
        <legend>Split into parts</legend>
        {/* Radix RadioGroup gives this arrow-key navigation between
           options and a single tab stop for the whole group, which
           loose native radios sharing a name do not. */}
        <RadioGroup
          value={form.split_mode}
          onValueChange={(v) => set("split_mode", v)}
        >
          {[
            ["none", "Don't split"],
            ["time", "Every N minutes"],
            ["size", "Keep each part under N MB"],
          ].map(([value, label]) => (
            <div key={value} className="flex items-center gap-2">
              <RadioGroupItem value={value} id={`cv-split-${value}`} />
              <Label htmlFor={`cv-split-${value}`}>{label}</Label>
            </div>
          ))}
        </RadioGroup>
        {form.split_mode === "time" && (
          <Input
            type="number"
            className="mt-2 w-32"
            min="1"
            value={form.split_minutes}
            onChange={(e) => set("split_minutes", Number(e.target.value))}
          />
        )}
        {form.split_mode === "size" && (
          <Input
            type="number"
            className="mt-2 w-32"
            min="1"
            step="0.5"
            value={form.split_mb}
            onChange={(e) => set("split_mb", Number(e.target.value))}
          />
        )}
        {form.split_mode === "size" && (
          <p className="hint">
            Only length can be set directly, so this is worked out from the
            converted file’s real bitrate and then checked — if a part still
            comes out over, it splits again more finely.
          </p>
        )}
      </fieldset>

      <Button
        variant="primary"
        disabled={!source}
        onClick={() => {
          setStatus("");
          startConvert({ source, ...form })
            .then((job) => setJobId(job.id))
            .catch((e) => setError(String(e.message || e)));
        }}
      >
        Convert
      </Button>
      {error && <p className="error">{error}</p>}
      <JobLog
        jobId={jobId}
        onFinished={(snap) => {
          onJob?.();
          if (snap.status === "done") setStatus("Done.");
          else if (snap.status === "failed")
            setStatus(snap.error || "Conversion failed.");
        }}
      />
      {status && <p className={status === "Done." ? "ok" : "error"}>{status}</p>}
    </div>
  );
}
