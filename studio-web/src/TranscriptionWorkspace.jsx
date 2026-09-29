import React, { useEffect, useMemo, useRef, useState } from "react";
import {
  Captions,
  CheckCircle2,
  Download,
  FileAudio,
  Languages,
  LoaderCircle,
  Pause,
  RefreshCw,
  Sparkles,
  Upload,
} from "lucide-react";

import { api } from "./api.js";

const TERMINAL = new Set(["completed", "failed", "cancelled"]);

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

function outputLabel(name) {
  return {
    transcript: "Transcript",
    segments: "Timing data",
    srt: "SRT",
    vtt: "WebVTT",
    chapters: "Guessed chapters",
  }[name] || name;
}

function TranscriptionJobCard({ job, onAction }) {
  if (!job) return null;
  const running = !TERMINAL.has(job.status);
  return (
    <section className={`surface transcription-job status-${job.status}`} aria-live="polite">
      <div className="conversion-job-heading">
        <span className="conversion-job-icon">
          {job.status === "completed" ? <CheckCircle2 size={19} /> : <RefreshCw className={running ? "spin" : ""} size={19} />}
        </span>
        <div>
          <p className="eyebrow">Latest transcription</p>
          <h2>{job.phase.replaceAll("_", " ")}</h2>
          <small>{job.source_name}</small>
        </div>
        <strong>{Math.round(job.progress * 100)}%</strong>
      </div>
      <div className="progress-track"><i style={{ width: `${job.progress * 100}%` }} /></div>
      <dl className="transcription-facts">
        <div><dt>Audio processed</dt><dd>{duration(job.processed_seconds)}{job.duration_seconds ? ` / ${duration(job.duration_seconds)}` : ""}</dd></div>
        <div><dt>Segments</dt><dd>{job.segment_count}</dd></div>
        <div><dt>Language</dt><dd>{job.detected_language || "Detecting…"}</dd></div>
      </dl>
      {job.error_detail && <div className="inline-error"><strong>{job.error_code}</strong><span>{job.error_detail}</span></div>}
      <div className="conversion-job-actions">
        {running && <button className="secondary-button danger" type="button" onClick={() => onAction(job, "cancel")}><Pause size={15} />Cancel</button>}
        {(job.status === "failed" || job.status === "cancelled") && <button className="secondary-button" type="button" onClick={() => onAction(job, "retry")}><RefreshCw size={15} />Retry</button>}
        {Object.entries(job.output_urls).map(([name, url]) => <a className="secondary-button" href={url} download key={name}><Download size={15} />{outputLabel(name)}</a>)}
      </div>
    </section>
  );
}

export function TranscriptionWorkspace({ tabs }) {
  const [capabilities, setCapabilities] = useState(null);
  const [sources, setSources] = useState([]);
  const [sourceKey, setSourceKey] = useState("");
  const [providerId, setProviderId] = useState("");
  const [options, setOptions] = useState(null);
  const [jobs, setJobs] = useState([]);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const fileInput = useRef(null);

  const load = async () => {
    const [nextCapabilities, nextSources, nextJobs] = await Promise.all([
      api.transcriptionCapabilities(),
      api.transcriptionSources(),
      api.transcriptionJobs(),
    ]);
    setCapabilities(nextCapabilities);
    setOptions((current) => current || nextCapabilities.defaults);
    setSources(nextSources);
    setJobs(nextJobs);
    setProviderId((current) => current || nextCapabilities.providers[0]?.id || "");
    setSourceKey((current) => {
      if (nextSources.some((item) => `${item.kind}:${item.id}` === current)) return current;
      const first = nextSources[0];
      return first ? `${first.kind}:${first.id}` : "";
    });
  };

  useEffect(() => { load().catch((reason) => setError(reason.message)); }, []);
  useEffect(() => {
    if (!jobs.some((job) => !TERMINAL.has(job.status))) return undefined;
    const timer = window.setInterval(() => {
      api.transcriptionJobs().then(setJobs).catch((reason) => setError(reason.message));
    }, 650);
    return () => window.clearInterval(timer);
  }, [jobs]);

  const selected = sources.find((item) => `${item.kind}:${item.id}` === sourceKey) || null;
  const provider = capabilities?.providers.find((item) => item.id === providerId) || null;
  const activeJob = useMemo(() => {
    if (!selected) return jobs[0] || null;
    return jobs.find((job) => selected.kind === "take" ? job.source_job_id === selected.id : job.input_id === selected.id) || jobs[0] || null;
  }, [jobs, selected]);
  const update = (key, value) => setOptions((current) => ({ ...current, [key]: value }));

  const upload = async (file) => {
    if (!file) return;
    setBusy("upload");
    setError("");
    try {
      const item = await api.uploadConversionInput(file);
      await load();
      setSourceKey(`upload:${item.id}`);
    } catch (reason) { setError(reason.message); }
    finally {
      setBusy("");
      if (fileInput.current) fileInput.current.value = "";
    }
  };

  const start = async () => {
    if (!selected || !options || !provider) return;
    setBusy("transcribe");
    setError("");
    try {
      const source = selected.kind === "take" ? { source_job_id: selected.id } : { input_id: selected.id };
      const created = await api.createTranscription({ ...source, provider_id: provider.id, options });
      setJobs((current) => [created, ...current.filter((job) => job.id !== created.id)]);
    } catch (reason) { setError(reason.message); }
    finally { setBusy(""); }
  };

  const act = async (job, action) => {
    setError("");
    try {
      const updated = await api.transcriptionJobAction(job.id, action);
      setJobs((current) => current.map((item) => item.id === updated.id ? updated : item));
    } catch (reason) { setError(reason.message); }
  };

  return (
    <main className="conversion-workspace transcription-workspace">
      <header className="workspace-header conversion-header">
        <div><p className="eyebrow">Audio utility</p><h1>Transcribe</h1><p>Turn managed audio into readable text, timing data, subtitles, and draft chapter marks.</p></div>
        <button className="secondary-button" type="button" onClick={() => fileInput.current?.click()} disabled={!!busy}>{busy === "upload" ? <LoaderCircle className="spin" size={16} /> : <Upload size={16} />}{busy === "upload" ? "Uploading…" : "Import audio"}</button>
        <input ref={fileInput} className="visually-hidden" type="file" accept="audio/*,.m4a,.mka,.webm,.mp4,.mov" onChange={(event) => upload(event.target.files?.[0])} />
      </header>
      {tabs}
      {error && <p className="inline-error conversion-error">{error}</p>}
      {provider && !provider.available && <div className="inline-error conversion-error"><strong>{provider.label} is not configured.</strong><span>Open Components and select the Python executable from an environment containing faster-whisper, then restart SPLICR.</span></div>}

      <div className="conversion-layout">
        <div className="conversion-main-stack">
          <section className="surface conversion-source-card">
            <div className="section-heading"><div><p className="eyebrow">01 · Source</p><h2>Choose audio</h2></div><FileAudio size={20} /></div>
            {sources.length ? <label className="control"><span>Completed take or imported file</span><select value={sourceKey} onChange={(event) => setSourceKey(event.target.value)}>{sources.map((item) => <option key={`${item.kind}:${item.id}`} value={`${item.kind}:${item.id}`}>{item.kind === "take" ? "Take" : "Upload"} · {item.name} · {bytes(item.size_bytes)}</option>)}</select></label> : <button className="conversion-drop" type="button" onClick={() => fileInput.current?.click()}><Upload size={25} /><strong>Import an audio file</strong><span>Or finish a narration take first.</span></button>}
          </section>

          {capabilities && options && <section className="surface transcription-settings-card">
            <div className="section-heading"><div><p className="eyebrow">02 · Recognition</p><h2>Model & language</h2></div><Languages size={20} /></div>
            <div className="control-grid three">
              <label className="control"><span>ASR provider</span><select value={providerId} onChange={(event) => setProviderId(event.target.value)}>{capabilities.providers.map((item) => <option key={item.id} value={item.id}>{item.label}{item.available ? "" : " · setup required"}</option>)}</select></label>
              <label className="control"><span>Model size</span><select value={options.model} onChange={(event) => update("model", event.target.value)}>{(provider?.controls.find((item) => item.key === "model")?.choices || ["base"]).map((item) => <option key={item} value={item}>{item}</option>)}</select></label>
              <label className="control"><span>Language</span><input value={options.language || ""} onChange={(event) => update("language", event.target.value || null)} placeholder="Auto-detect" /></label>
            </div>
            <details className="advanced-disclosure transcription-advanced">
              <summary><span><strong>Advanced recognition</strong><small>Hardware, timing precision, and pause thresholds</small></span><span>Show controls</span></summary>
              <div className="control-grid three">
                <label className="control"><span>Device</span><select value={options.device} onChange={(event) => update("device", event.target.value)}><option value="auto">Auto</option><option value="cpu">CPU</option><option value="cuda">CUDA</option></select></label>
                <label className="control"><span>Compute type</span><select value={options.compute_type} onChange={(event) => update("compute_type", event.target.value)}>{["default", "int8", "int8_float16", "float16", "float32"].map((item) => <option key={item} value={item}>{item}</option>)}</select></label>
                <label className="control"><span>Paragraph pause</span><input type="number" min="0.25" max="30" step="0.25" value={options.paragraph_gap_seconds} onChange={(event) => update("paragraph_gap_seconds", Number(event.target.value))} /><small>Seconds before a new readable paragraph.</small></label>
                <label className="control"><span>Guessed chapter pause</span><input type="number" min="0.25" max="30" step="0.25" value={options.chapter_pause_seconds} onChange={(event) => update("chapter_pause_seconds", Number(event.target.value))} /><small>Long silences suggest—not prove—a chapter break.</small></label>
                <label className="check-control"><input type="checkbox" checked={options.vad_filter} onChange={(event) => update("vad_filter", event.target.checked)} /><span><strong>Voice activity filter</strong><small>Reduce extended silence before recognition.</small></span></label>
                <label className="check-control"><input type="checkbox" checked={options.word_timestamps} onChange={(event) => update("word_timestamps", event.target.checked)} /><span><strong>Word timings</strong><small>Retain detailed timing for later editing.</small></span></label>
              </div>
            </details>
          </section>}

          {options && <section className="surface transcription-output-card">
            <div className="section-heading"><div><p className="eyebrow">03 · Outputs</p><h2>Transcript package</h2></div><Captions size={20} /></div>
            <div className="transcription-output-options">
              <label className="check-control"><input type="checkbox" checked={options.include_srt} onChange={(event) => update("include_srt", event.target.checked)} /><span><strong>SRT subtitles</strong><small>UTF-8 segment cues.</small></span></label>
              <label className="check-control"><input type="checkbox" checked={options.include_vtt} onChange={(event) => update("include_vtt", event.target.checked)} /><span><strong>WebVTT subtitles</strong><small>Browser-friendly caption cues.</small></span></label>
              <label className="check-control"><input type="checkbox" checked={options.line_timestamps} onChange={(event) => update("line_timestamps", event.target.checked)} /><span><strong>Per-line timestamps</strong><small>Timestamp each transcript utterance instead of regrouping paragraphs.</small></span></label>
              <label className="check-control warning-choice"><input type="checkbox" checked={options.guessed_chapters} onChange={(event) => update("guessed_chapters", event.target.checked)} /><span><strong>Guessed chapters</strong><small>Draft marks inferred only from pauses; always review them.</small></span></label>
            </div>
            <div className="render-row"><span><Sparkles size={16} />The job, progress, settings, and final files survive a restart. Partial files are never published as complete.</span><button className="primary-button" type="button" disabled={!selected || !provider?.available || !!busy} onClick={start}>{busy === "transcribe" ? <LoaderCircle className="spin" size={16} /> : <Captions size={16} />}{busy === "transcribe" ? "Starting…" : "Transcribe audio"}</button></div>
          </section>}
        </div>

        <aside className="conversion-activity">
          <TranscriptionJobCard job={activeJob} onAction={act} />
          <section className="surface conversion-history">
            <p className="eyebrow">Recent</p><h2>Transcription history</h2>
            {jobs.length ? jobs.slice(0, 8).map((job) => <button key={job.id} className={activeJob?.id === job.id ? "active" : ""} type="button" onClick={() => setSourceKey(`${job.source_job_id ? "take" : "upload"}:${job.source_job_id || job.input_id}`)}><span>{job.source_name}</span><small>{job.status} · {job.options.model}</small></button>) : <p className="muted-copy">No transcriptions yet.</p>}
          </section>
        </aside>
      </div>
    </main>
  );
}
