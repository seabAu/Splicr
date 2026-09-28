import React, { useEffect, useMemo, useRef, useState } from "react";
import {
  CheckCircle2,
  Download,
  FileAudio,
  Gauge,
  LoaderCircle,
  Pause,
  RefreshCw,
  Scissors,
  Upload,
  WandSparkles,
} from "lucide-react";

import { api } from "./api.js";

const TERMINAL = new Set(["completed", "failed", "cancelled"]);
const BITRATES = {
  mp3: [64, 80, 96, 112, 128, 160, 192, 224, 256, 320, 320],
  m4a: [48, 64, 80, 96, 112, 128, 144, 160, 176, 192, 192],
};

function bytes(value) {
  if (!Number.isFinite(value)) return "0 B";
  if (value >= 1_000_000_000) return `${(value / 1_000_000_000).toFixed(1)} GB`;
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1)} MB`;
  if (value >= 1_000) return `${(value / 1_000).toFixed(0)} KB`;
  return `${value} B`;
}

function duration(value) {
  const total = Math.max(0, Math.round(value || 0));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const seconds = total % 60;
  return hours
    ? `${hours}:${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`
    : `${minutes}:${String(seconds).padStart(2, "0")}`;
}

function qualityLabel(spec) {
  if (spec.output_format === "wav") return `${spec.bit_depth}-bit PCM`;
  if (spec.output_format === "flac") return `Lossless · compression ${Math.min(8, Math.floor((spec.quality_pct + 5) / 10))}`;
  const values = BITRATES[spec.output_format];
  const index = Math.min(10, Math.max(0, Math.floor((spec.quality_pct + 5) / 10)));
  return `${values[index]} kbps`;
}

function ConversionJobCard({ job, onAction }) {
  if (!job) return null;
  const running = !TERMINAL.has(job.status);
  return (
    <section className={`surface conversion-job status-${job.status}`}>
      <div className="conversion-job-heading">
        <span className="conversion-job-icon">
          {job.status === "completed" ? <CheckCircle2 size={19} /> : <RefreshCw className={running ? "spin" : ""} size={19} />}
        </span>
        <div>
          <p className="eyebrow">Latest conversion</p>
          <h2>{job.status.replaceAll("_", " ")}</h2>
          <small>{job.source_name} · {duration(job.duration_seconds)}</small>
        </div>
        <strong>{Math.round(job.progress * 100)}%</strong>
      </div>
      <div className="progress-track"><i style={{ width: `${job.progress * 100}%` }} /></div>
      {job.error_detail && <p className="inline-error">{job.error_detail}</p>}
      {job.output_url && (
        <audio className="conversion-player" controls preload="metadata" src={`${job.output_url}?v=${job.updated_at}`} />
      )}
      <div className="conversion-job-actions">
        {running && (
          <button className="secondary-button danger" type="button" onClick={() => onAction(job, "cancel")}>
            <Pause size={15} /> Cancel
          </button>
        )}
        {(job.status === "failed" || job.status === "cancelled") && (
          <button className="secondary-button" type="button" onClick={() => onAction(job, "retry")}>
            <RefreshCw size={15} /> Retry
          </button>
        )}
        {job.output_url && (
          <a className="secondary-button" href={job.output_url} download>
            <Download size={15} /> Full {job.spec.output_format.toUpperCase()}
          </a>
        )}
      </div>
      {!!job.part_urls.length && (
        <div className="conversion-parts">
          <span><Scissors size={14} /> {job.part_urls.length} split parts</span>
          <div>
            {job.part_urls.map((url, index) => (
              <a key={url} href={url} download>Part {index + 1}</a>
            ))}
          </div>
        </div>
      )}
    </section>
  );
}

export function ConversionWorkspace() {
  const [capabilities, setCapabilities] = useState(null);
  const [sources, setSources] = useState([]);
  const [sourceKey, setSourceKey] = useState("");
  const [spec, setSpec] = useState(null);
  const [jobs, setJobs] = useState([]);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const fileInput = useRef(null);

  const load = async () => {
    const [nextCapabilities, nextSources, nextJobs] = await Promise.all([
      api.conversionCapabilities(),
      api.conversionSources(),
      api.conversionJobs(),
    ]);
    setCapabilities(nextCapabilities);
    setSpec((current) => current || nextCapabilities.defaults);
    setSources(nextSources);
    setJobs(nextJobs);
    setSourceKey((current) => {
      if (nextSources.some((item) => `${item.kind}:${item.id}` === current)) return current;
      const first = nextSources[0];
      return first ? `${first.kind}:${first.id}` : "";
    });
  };

  useEffect(() => {
    load().catch((reason) => setError(reason.message));
  }, []);

  useEffect(() => {
    if (!jobs.some((job) => !TERMINAL.has(job.status))) return undefined;
    const timer = window.setInterval(() => {
      api.conversionJobs().then(setJobs).catch((reason) => setError(reason.message));
    }, 650);
    return () => window.clearInterval(timer);
  }, [jobs]);

  const selected = sources.find((item) => `${item.kind}:${item.id}` === sourceKey) || null;
  const activeJob = useMemo(() => {
    if (!selected) return jobs[0] || null;
    return jobs.find((job) => (
      selected.kind === "take" ? job.source_job_id === selected.id : job.input_id === selected.id
    )) || jobs[0] || null;
  }, [jobs, selected]);
  const update = (key, value) => setSpec((current) => ({ ...current, [key]: value }));

  const upload = async (file) => {
    if (!file) return;
    setBusy("upload");
    setError("");
    try {
      const item = await api.uploadConversionInput(file);
      await load();
      setSourceKey(`upload:${item.id}`);
    } catch (reason) {
      setError(reason.message);
    } finally {
      setBusy("");
      if (fileInput.current) fileInput.current.value = "";
    }
  };

  const start = async () => {
    if (!selected || !spec) return;
    setBusy("convert");
    setError("");
    try {
      const source = selected.kind === "take"
        ? { source_job_id: selected.id }
        : { input_id: selected.id };
      const created = await api.createConversion({ ...source, spec });
      setJobs((current) => [created, ...current.filter((job) => job.id !== created.id)]);
    } catch (reason) {
      setError(reason.message);
    } finally {
      setBusy("");
    }
  };

  const act = async (job, action) => {
    setError("");
    try {
      const updated = await api.conversionJobAction(job.id, action);
      setJobs((current) => current.map((item) => item.id === updated.id ? updated : item));
    } catch (reason) {
      setError(reason.message);
    }
  };

  return (
    <main className="conversion-workspace">
      <header className="workspace-header conversion-header">
        <div><p className="eyebrow">Audio utility</p><h1>Convert</h1><p>Prepare, normalize, and split audio without leaving the Studio.</p></div>
        <button className="secondary-button" type="button" onClick={() => fileInput.current?.click()} disabled={!!busy}>
          {busy === "upload" ? <LoaderCircle className="spin" size={16} /> : <Upload size={16} />}
          {busy === "upload" ? "Uploading…" : "Import audio"}
        </button>
        <input ref={fileInput} className="visually-hidden" type="file" accept="audio/*,.m4a,.mka,.webm,.mp4,.mov" onChange={(event) => upload(event.target.files?.[0])} />
      </header>

      {error && <p className="inline-error conversion-error">{error}</p>}
      {capabilities && !capabilities.ffmpeg_available && (
        <p className="inline-error conversion-error">FFmpeg and FFprobe are required for conversion.</p>
      )}

      <div className="conversion-layout">
        <div className="conversion-main-stack">
          <section className="surface conversion-source-card">
            <div className="section-heading"><div><p className="eyebrow">01 · Source</p><h2>Choose audio</h2></div><FileAudio size={20} /></div>
            {sources.length ? (
              <label className="control">
                <span>Completed take or imported file</span>
                <select value={sourceKey} onChange={(event) => setSourceKey(event.target.value)}>
                  {sources.map((item) => (
                    <option key={`${item.kind}:${item.id}`} value={`${item.kind}:${item.id}`}>
                      {item.kind === "take" ? "Take" : "Upload"} · {item.name} · {bytes(item.size_bytes)}
                    </option>
                  ))}
                </select>
              </label>
            ) : (
              <button className="conversion-drop" type="button" onClick={() => fileInput.current?.click()}>
                <Upload size={25} /><strong>Import an audio file</strong><span>Or finish a narration take first.</span>
              </button>
            )}
          </section>

          {spec && (
            <section className="surface conversion-settings-card">
              <div className="section-heading"><div><p className="eyebrow">02 · Output</p><h2>Format & fidelity</h2></div><Gauge size={20} /></div>
              <div className="control-grid three">
                <label className="control"><span>Format</span><select value={spec.output_format} onChange={(event) => update("output_format", event.target.value)}>{capabilities.output_formats.map((item) => <option key={item} value={item}>{item.toUpperCase()}</option>)}</select></label>
                <label className="control"><span>Sample rate</span><select value={spec.sample_rate} onChange={(event) => update("sample_rate", Number(event.target.value))}>{capabilities.sample_rates.map((item) => <option key={item} value={item}>{(item / 1000).toFixed(item % 1000 ? 2 : 0)} kHz</option>)}</select></label>
                <label className="control"><span>Channels</span><select value={spec.channels} onChange={(event) => update("channels", Number(event.target.value))}><option value="0">Keep source</option><option value="1">Mono</option><option value="2">Stereo</option></select></label>
                <label className="control"><span>Bit depth</span><select disabled={!(["wav", "flac"].includes(spec.output_format))} value={spec.bit_depth} onChange={(event) => update("bit_depth", Number(event.target.value))}>{capabilities.bit_depths.map((item) => <option key={item} value={item}>{item}-bit</option>)}</select></label>
                <label className="control conversion-quality"><span><span>Quality / compression</span><strong>{qualityLabel(spec)}</strong></span><input type="range" min="0" max="100" step="10" disabled={spec.output_format === "wav"} value={spec.quality_pct} onChange={(event) => update("quality_pct", Number(event.target.value))} /></label>
                <label className="check-control"><input type="checkbox" checked={spec.normalize_loudness} onChange={(event) => update("normalize_loudness", event.target.checked)} /><span><strong>Normalize loudness</strong><small>EBU R128 · −16 LUFS</small></span></label>
              </div>
            </section>
          )}

          {spec && (
            <section className="surface conversion-split-card">
              <div className="section-heading"><div><p className="eyebrow">03 · Delivery</p><h2>Optional splitting</h2></div><Scissors size={20} /></div>
              <div className="conversion-split-options">
                {[['none', 'One continuous file'], ['time', 'Every N minutes'], ['size', 'Keep parts under N MB']].map(([value, label]) => (
                  <label key={value} className={spec.split_mode === value ? "active" : ""}><input type="radio" name="split-mode" value={value} checked={spec.split_mode === value} onChange={() => update("split_mode", value)} /><span>{label}</span></label>
                ))}
              </div>
              {spec.split_mode !== "none" && (
                <label className="control conversion-split-value">
                  <span>{spec.split_mode === "time" ? "Minutes per part" : "Maximum megabytes per part"}</span>
                  <input type="number" min="0.1" step={spec.split_mode === "time" ? "0.5" : "1"} value={spec.split_mode === "time" ? spec.split_minutes : spec.split_megabytes} onChange={(event) => update(spec.split_mode === "time" ? "split_minutes" : "split_megabytes", Number(event.target.value))} />
                  {spec.split_mode === "size" && <small>SPLICR measures the encoded file, verifies every part, and tightens the split if needed.</small>}
                </label>
              )}
              <div className="render-row"><span><WandSparkles size={16} />Conversion jobs survive restarts and finished take outputs join the artifact history.</span><button className="primary-button" type="button" disabled={!selected || !!busy || !capabilities.ffmpeg_available} onClick={start}>{busy === "convert" ? <LoaderCircle className="spin" size={16} /> : <RefreshCw size={16} />}{busy === "convert" ? "Starting…" : "Convert audio"}</button></div>
            </section>
          )}
        </div>

        <aside className="conversion-activity">
          <ConversionJobCard job={activeJob} onAction={act} />
          <section className="surface conversion-history">
            <p className="eyebrow">Recent</p>
            <h2>Conversion history</h2>
            {jobs.length ? jobs.slice(0, 8).map((job) => (
              <button key={job.id} className={activeJob?.id === job.id ? "active" : ""} type="button" onClick={() => {
                const kind = job.source_job_id ? "take" : "upload";
                setSourceKey(`${kind}:${job.source_job_id || job.input_id}`);
              }}>
                <span>{job.source_name}</span><small>{job.status} · {job.spec.output_format.toUpperCase()}</small>
              </button>
            )) : <p className="muted-copy">No conversions yet.</p>}
          </section>
        </aside>
      </div>
    </main>
  );
}
