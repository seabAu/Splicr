import React, { useEffect, useMemo, useState } from "react";
import {
  CheckCircle2,
  Clapperboard,
  Clock3,
  Download,
  Film,
  ImagePlus,
  LoaderCircle,
  Pause,
  Play,
  RefreshCw,
  SlidersHorizontal,
  Sparkles,
  Waves,
} from "lucide-react";

import { api } from "./api.js";

const TERMINAL = new Set(["completed", "failed", "cancelled"]);

function formatDuration(value) {
  if (!Number.isFinite(value)) return "0:00";
  const hours = Math.floor(value / 3600);
  const minutes = Math.floor((value % 3600) / 60);
  const seconds = Math.round(value % 60);
  return hours
    ? `${hours}:${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`
    : `${minutes}:${String(seconds).padStart(2, "0")}`;
}

function sourceLabel(source) {
  const stamp = new Date(source.created_at);
  const date = Number.isNaN(stamp.getTime()) ? source.job_id.slice(0, 8) : stamp.toLocaleString();
  return `${source.provider} · ${source.voice} · ${formatDuration(source.duration_seconds)} · ${date}`;
}

function AudiogramEmpty({ loading, ffmpegAvailable, onNavigate }) {
  return (
    <section className="audiogram-empty surface">
      {loading ? <LoaderCircle className="spin" size={30} /> : <Clapperboard size={32} />}
      <div>
        <h2>{loading ? "Finding completed takes…" : "No finished audio to visualize"}</h2>
        <p>
          Audiograms are built from completed narration or dialogue takes. Render one first and it
          will appear here automatically.
        </p>
        {!ffmpegAvailable && <strong>FFmpeg is not available on this machine.</strong>}
      </div>
      {!loading && (
        <button className="primary-button" type="button" onClick={() => onNavigate("narrate")}>
          Create a take
        </button>
      )}
    </section>
  );
}

function LiveCanvas({ spec, waveform, layout, background }) {
  if (!layout) return <div className="audiogram-canvas-shell audiogram-canvas-loading" />;
  const width = 1000;
  const height = Math.round((width * layout.canvas_height) / layout.canvas_width);
  const visualizerHeight = (layout.visualizer_height / layout.canvas_height) * height;
  const top = (layout.visualizer_y / layout.canvas_height) * height;
  const hasSignal = waveform?.some((value) => value > 0.001);
  const samples = hasSignal ? waveform : Array.from({ length: 120 }, (_, index) => (
    0.18 + Math.abs(Math.sin(index * 0.31) * Math.cos(index * 0.073)) * 0.72
  ));
  const points = samples.map((value, index) => {
    const x = samples.length === 1 ? width / 2 : (index / (samples.length - 1)) * width;
    const y = top + visualizerHeight / 2 - value * visualizerHeight * 0.44;
    return [x, y];
  });
  const mirror = [...points].reverse().map(([x, y]) => [
    x,
    top + visualizerHeight - (y - top),
  ]);
  const area = `M ${points.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(" L ")} L ${mirror.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(" L ")} Z`;
  const line = `M ${points.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(" L ")}`;
  const blur = spec.blur ? `blur(${Math.min(spec.blur, 8)}px)` : undefined;

  return (
    <div className={`audiogram-canvas-shell ${layout.background_mode === "transparent" ? "is-transparent" : ""}`} style={{
      aspectRatio: `${layout.canvas_width} / ${layout.canvas_height}`,
      backgroundColor: layout.background_mode === "transparent" ? undefined : spec.background_color,
    }}>
      {layout.background_mode === "image" && background && (
        <img
          className="audiogram-background-preview"
          src={background.url}
          alt=""
          style={{
            objectFit: layout.background_fit === "stretch" ? "fill" : layout.background_fit,
            objectPosition: `${layout.background_position_x * 100}% ${layout.background_position_y * 100}%`,
          }}
        />
      )}
      <svg viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" aria-label="Live audiogram composition preview">
        {layout.background_mode === "solid" && <rect width={width} height={height} fill={spec.background_color} />}
        {spec.source === "spectrum" ? (
          samples.map((value, index) => (
            <rect
              key={index}
              x={(index / samples.length) * width}
              y={top + visualizerHeight * (1 - value)}
              width={width / samples.length + 1}
              height={visualizerHeight * value}
              fill={spec.foreground_color}
              opacity={0.2 + value * 0.8}
            />
          ))
        ) : spec.source === "frequency" ? (
          <path d={line} fill="none" stroke={spec.foreground_color} strokeWidth="5" style={{ filter: blur }} />
        ) : spec.source === "vectorscope" ? (
          <ellipse
            cx={width / 2}
            cy={top + visualizerHeight / 2}
            rx={visualizerHeight * 0.35}
            ry={visualizerHeight * 0.43}
            fill="none"
            stroke={spec.foreground_color}
            strokeWidth="5"
            style={{ filter: blur }}
          />
        ) : (
          <path d={area} fill={spec.foreground_color} opacity={spec.trail ? 0.72 : 0.92} style={{ filter: blur }} />
        )}
      </svg>
      <span><Waves size={14} /> Live layout preview</span>
    </div>
  );
}

function RenderStatus({ job, onAction }) {
  if (!job) return null;
  const busy = !TERMINAL.has(job.status);
  return (
    <section className={`audiogram-job-card surface status-${job.status}`}>
      <div className="audiogram-job-heading">
        <span className="render-kind-icon">{job.kind === "preview" ? <Play size={18} /> : <Film size={18} />}</span>
        <div>
          <p className="eyebrow">{job.kind === "preview" ? "Motion proof" : "Full video"}</p>
          <h2>{job.status.replaceAll("_", " ")}</h2>
        </div>
        <strong>{Math.round(job.progress * 100)}%</strong>
      </div>
      <div className="progress-track"><i style={{ width: `${job.progress * 100}%` }} /></div>
      <p className="audiogram-job-meta">
        <Clock3 size={14} /> {formatDuration(job.render_seconds)} rendered from a {formatDuration(job.duration_seconds)} take
      </p>
      {job.error_detail && <p className="inline-error">{job.error_detail}</p>}
      {job.output_url && job.spec.output_format !== "png_sequence" && (
        <video className="audiogram-player" controls preload="metadata" src={`${job.output_url}?v=${job.updated_at}`} />
      )}
      <div className="audiogram-job-actions">
        {busy && (
          <button className="secondary-button danger" type="button" onClick={() => onAction(job, "cancel")}>
            <Pause size={15} /> Cancel render
          </button>
        )}
        {(job.status === "failed" || job.status === "cancelled") && (
          <button className="secondary-button" type="button" onClick={() => onAction(job, "retry")}>
            <RefreshCw size={15} /> Retry
          </button>
        )}
        {job.output_url && (
          <a className="secondary-button" href={job.output_url} download>
            <Download size={15} /> Download {job.spec.output_format.toUpperCase()}
          </a>
        )}
      </div>
    </section>
  );
}

export function AudiogramWorkspace({ onNavigate }) {
  const [capabilities, setCapabilities] = useState(null);
  const [sources, setSources] = useState([]);
  const [backgrounds, setBackgrounds] = useState([]);
  const [sourceId, setSourceId] = useState("");
  const [waveform, setWaveform] = useState([]);
  const [spec, setSpec] = useState(null);
  const [jobs, setJobs] = useState([]);
  const [estimate, setEstimate] = useState(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");

  const load = async () => {
    const [nextCapabilities, nextSources, nextBackgrounds, nextJobs] = await Promise.all([
      api.audiogramCapabilities(), api.audiogramSources(), api.audiogramBackgrounds(), api.audiogramJobs(),
    ]);
    setCapabilities(nextCapabilities);
    setSpec((current) => current || nextCapabilities.defaults);
    setSources(nextSources);
    setBackgrounds(nextBackgrounds);
    setJobs(nextJobs);
    setSourceId((current) => (
      nextSources.some((item) => item.job_id === current) ? current : nextSources[0]?.job_id || ""
    ));
  };

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    load()
      .catch((reason) => { if (!cancelled) setError(reason.message); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    if (!sourceId) {
      setWaveform([]);
      return undefined;
    }
    let cancelled = false;
    api.timeline(sourceId, 180)
      .then((timeline) => { if (!cancelled) setWaveform(timeline.waveform); })
      .catch(() => { if (!cancelled) setWaveform([]); });
    return () => { cancelled = true; };
  }, [sourceId]);

  useEffect(() => {
    if (!jobs.some((job) => !TERMINAL.has(job.status))) return undefined;
    const timer = window.setInterval(() => {
      api.audiogramJobs().then(setJobs).catch((reason) => setError(reason.message));
    }, 700);
    return () => window.clearInterval(timer);
  }, [jobs]);

  useEffect(() => {
    if (!sourceId || !spec) return undefined;
    const timer = window.setTimeout(() => {
      api.estimateAudiogram({ source_job_id: sourceId, kind: "export", spec })
        .then(setEstimate)
        .catch(() => setEstimate(null));
    }, 250);
    return () => window.clearTimeout(timer);
  }, [sourceId, spec]);

  const source = sources.find((item) => item.job_id === sourceId) || null;
  const background = backgrounds.find((item) => item.id === spec?.background_asset_id) || null;
  const activeJob = jobs.find((job) => job.source_job_id === sourceId) || jobs[0] || null;
  const alphaFormats = capabilities?.alpha_output_formats || [];
  const update = (key, value) => setSpec((current) => ({ ...current, [key]: value }));
  const render = async (kind) => {
    if (!sourceId || !spec) return;
    setBusy(kind);
    setError("");
    try {
      const created = await api.createAudiogram({ source_job_id: sourceId, kind, spec });
      setJobs((current) => [created, ...current.filter((job) => job.id !== created.id)]);
    } catch (reason) {
      setError(reason.message);
    } finally {
      setBusy("");
    }
  };
  const jobAction = async (job, action) => {
    setError("");
    try {
      const updated = await api.audiogramJobAction(job.id, action);
      setJobs((current) => current.map((item) => item.id === updated.id ? updated : item));
    } catch (reason) {
      setError(reason.message);
    }
  };
  const uploadBackground = async (event) => {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    setBusy("background");
    setError("");
    try {
      const asset = await api.uploadAudiogramBackground(file);
      setBackgrounds((current) => [asset, ...current.filter((item) => item.id !== asset.id)]);
      setSpec((current) => ({
        ...current,
        background_mode: "image",
        background_asset_id: asset.id,
        output_format: (capabilities?.alpha_output_formats || []).includes(current.output_format) ? "mp4" : current.output_format,
      }));
    } catch (reason) {
      setError(reason.message);
    } finally {
      setBusy("");
    }
  };

  if (!sources.length && !spec) {
    return (
      <main className="audiogram-workspace">
        <header className="workspace-header"><div><p className="eyebrow">Motion toolkit</p><h1>Audiogram</h1></div></header>
        {error && <p className="inline-error">{error}</p>}
        <AudiogramEmpty loading={loading} ffmpegAvailable={capabilities?.ffmpeg_available !== false} onNavigate={onNavigate} />
      </main>
    );
  }

  return (
    <main className="audiogram-workspace">
      <header className="workspace-header audiogram-header">
        <div>
          <p className="eyebrow">Motion toolkit</p>
          <h1>Turn a finished take into a living waveform.</h1>
          <p>Fast, durable FFmpeg renders for previews, podcasts, and long-form video.</p>
        </div>
        <label className="control audiogram-source-picker">
          <span>Audio take</span>
          <select value={sourceId} onChange={(event) => setSourceId(event.target.value)}>
            {sources.map((item) => <option key={item.job_id} value={item.job_id}>{sourceLabel(item)}</option>)}
          </select>
        </label>
      </header>

      {error && <p className="inline-error">{error}</p>}
      {!capabilities?.ffmpeg_available && (
        <p className="audiogram-runtime-warning">FFmpeg is not on PATH. The editor remains available, but rendering is disabled until it is installed.</p>
      )}
      {!sources.length ? (
        <AudiogramEmpty loading={loading} ffmpegAvailable={capabilities?.ffmpeg_available !== false} onNavigate={onNavigate} />
      ) : spec && (
        <div className="audiogram-layout">
          <section className="audiogram-stage-stack">
            <div className="surface audiogram-stage">
              <div className="section-heading compact">
                <div><p className="eyebrow">Composition</p><h2>{spec.width} × {spec.height}</h2></div>
                <span>{source ? formatDuration(source.duration_seconds) : "—"} · {spec.fps} fps</span>
              </div>
              <LiveCanvas
                spec={spec}
                waveform={waveform}
                layout={estimate?.layout || capabilities.default_layout}
                background={background}
              />
              <div className="audiogram-render-bar">
                <div>
                  <Sparkles size={16} />
                  <span>
                    <strong>{estimate ? `About ${formatDuration(estimate.estimated_render_seconds)}` : "Estimating…"}</strong>
                    Estimated locally; hardware and effects change actual time.
                  </span>
                </div>
                <button className="secondary-button" type="button" disabled={!!busy || !capabilities?.ffmpeg_available || spec.output_format === "png_sequence"} onClick={() => render("preview")}>
                  {busy === "preview" ? <LoaderCircle className="spin" size={15} /> : <Play size={15} />} 8-second proof
                </button>
                <button className="primary-button" type="button" disabled={!!busy || !capabilities?.ffmpeg_available} onClick={() => render("export")}>
                  {busy === "export" ? <LoaderCircle className="spin" size={15} /> : <Film size={15} />} Render full video
                </button>
              </div>
            </div>
            <RenderStatus job={activeJob} onAction={jobAction} />
          </section>

          <aside className="surface audiogram-controls">
            <div className="section-heading compact">
              <div><p className="eyebrow">Fast renderer</p><h2>Visual design</h2></div>
              <SlidersHorizontal size={17} />
            </div>
            <div className="audiogram-control-grid">
              <label><span>Visualizer</span><select value={spec.source} onChange={(event) => update("source", event.target.value)}>{capabilities.sources.map((item) => <option key={item} value={item}>{item}</option>)}</select></label>
              <label><span>Output</span><select value={spec.output_format} onChange={(event) => {
                const output = event.target.value;
                const alpha = alphaFormats.includes(output);
                setSpec((current) => ({
                  ...current,
                  output_format: output,
                  background_mode: alpha ? "transparent" : (current.background_mode === "transparent" ? "solid" : current.background_mode),
                  background_asset_id: alpha ? null : current.background_asset_id,
                }));
              }}>{capabilities.output_formats.map((item) => <option key={item} value={item}>{item.replaceAll("_", " ").toUpperCase()}</option>)}</select></label>
              <label><span>Canvas</span><select value={`${spec.width}x${spec.height}`} onChange={(event) => { const [width, height] = event.target.value.split("x").map(Number); setSpec((current) => ({ ...current, width, height, visualizer_height: Math.min(current.visualizer_height, height) })); }}><option value="1280x720">HD · 16:9</option><option value="1920x1080">Full HD · 16:9</option><option value="1080x1080">Square · 1:1</option><option value="1080x1920">Vertical · 9:16</option></select></label>
              <label><span>Wave shape</span><select value={spec.waveform_mode} onChange={(event) => update("waveform_mode", event.target.value)}>{capabilities.waveform_modes.map((item) => <option key={item} value={item}>{item}</option>)}</select></label>
              <label><span>Foreground</span><input type="color" value={spec.foreground_color} onChange={(event) => update("foreground_color", event.target.value.toUpperCase())} /></label>
              <label><span>Background</span><select aria-label="Background mode" value={spec.background_mode} onChange={(event) => {
                const mode = event.target.value;
                setSpec((current) => ({
                  ...current,
                  background_mode: mode,
                  background_asset_id: mode === "image" ? (current.background_asset_id || backgrounds[0]?.id || null) : null,
                  output_format: mode === "transparent" ? (alphaFormats.find((item) => item !== "png_sequence") || alphaFormats[0] || current.output_format) : (alphaFormats.includes(current.output_format) ? "mp4" : current.output_format),
                }));
              }}><option value="solid">Solid / chroma</option><option value="image" disabled={!backgrounds.length}>Still image</option><option value="transparent" disabled={!alphaFormats.length}>Transparent overlay</option></select></label>
              <label><span>Backing color</span><input type="color" value={spec.background_color} onChange={(event) => update("background_color", event.target.value.toUpperCase())} /></label>
              <label className="wide audiogram-background-upload">
                <span>Managed still image</span>
                <input type="file" accept="image/png,image/jpeg,image/webp" onChange={uploadBackground} />
                <span className="secondary-button">
                  {busy === "background" ? <LoaderCircle className="spin" size={15} /> : <ImagePlus size={15} />}
                  {busy === "background" ? "Importing…" : "Import PNG, JPEG, or WebP"}
                </span>
              </label>
              {spec.background_mode === "image" && (
                <>
                  <label className="wide"><span>Background asset</span><select value={spec.background_asset_id || ""} onChange={(event) => update("background_asset_id", event.target.value)}>{backgrounds.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
                  <label><span>Image fit</span><select value={spec.background_fit} onChange={(event) => update("background_fit", event.target.value)}>{capabilities.background_fits.map((item) => <option key={item} value={item}>{item}</option>)}</select></label>
                  <label className="wide"><span>Horizontal focus <strong>{Math.round(spec.background_position_x * 100)}%</strong></span><input type="range" min="0" max="1" step="0.01" value={spec.background_position_x} onChange={(event) => update("background_position_x", Number(event.target.value))} /></label>
                  <label className="wide"><span>Vertical focus <strong>{Math.round(spec.background_position_y * 100)}%</strong></span><input type="range" min="0" max="1" step="0.01" value={spec.background_position_y} onChange={(event) => update("background_position_y", Number(event.target.value))} /></label>
                </>
              )}
              <label className="wide"><span>Visualizer height <strong>{spec.visualizer_height}px</strong></span><input type="range" min="64" max={spec.height} step="2" value={spec.visualizer_height} onChange={(event) => update("visualizer_height", Number(event.target.value))} /></label>
              <label className="wide"><span>Vertical position <strong>{Math.round(spec.vertical_position * 100)}%</strong></span><input type="range" min="0" max="1" step="0.01" value={spec.vertical_position} onChange={(event) => update("vertical_position", Number(event.target.value))} /></label>
              <label><span>Amplitude</span><select value={spec.amplitude_scale} onChange={(event) => update("amplitude_scale", event.target.value)}>{capabilities.amplitude_scales.map((item) => <option key={item} value={item}>{item}</option>)}</select></label>
              <label><span>Frame rate</span><select value={spec.fps} onChange={(event) => update("fps", Number(event.target.value))}><option value="24">24 fps</option><option value="30">30 fps</option><option value="60">60 fps</option></select></label>
              <label className="wide"><span>Glow / blur <strong>{spec.blur.toFixed(1)}</strong></span><input type="range" min="0" max="20" step="0.5" value={spec.blur} onChange={(event) => update("blur", Number(event.target.value))} /></label>
              <label className="wide"><span>Edge detail <strong>{spec.sharpen.toFixed(2)}</strong></span><input type="range" min="0" max="1" step="0.05" value={spec.sharpen} onChange={(event) => update("sharpen", Number(event.target.value))} /></label>
              <label className="check wide"><input type="checkbox" checked={spec.trail} onChange={(event) => update("trail", event.target.checked)} /><span>Blend adjacent frames into a motion trail</span></label>
              <label className="check wide"><input type="checkbox" checked={spec.burn_captions} onChange={(event) => update("burn_captions", event.target.checked)} /><span>Burn captions into the rendered video <small>Uses exact engine timing when available and labels checkpoint estimates in the subtitle artifact.</small></span></label>
              <label><span>Encoder speed</span><select value={spec.preset} onChange={(event) => update("preset", event.target.value)}>{capabilities.presets.map((item) => <option key={item} value={item}>{item}</option>)}</select></label>
              <label><span>Quality · CRF <strong>{spec.crf}</strong></span><input type="range" min="12" max={spec.output_format === "webm" ? "50" : "40"} step="1" value={spec.crf} onChange={(event) => update("crf", Number(event.target.value))} /></label>
            </div>
            <div className="audiogram-parity-note">
              <CheckCircle2 size={16} />
              <p><strong>Built for long-form work.</strong> Renders are persisted, restart safely, preserve the take audio, and become Studio artifacts. The live preview, estimate, and final render share one layout contract; alpha-capable FFmpeg installs also expose WebM, ProRes 4444, and PNG sequences.</p>
            </div>
          </aside>
        </div>
      )}
    </main>
  );
}
