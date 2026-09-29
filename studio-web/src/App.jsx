import React, { useEffect, useMemo, useRef, useState } from "react";
import {
  AudioLines,
  AlertTriangle,
  BookOpen,
  Boxes,
  ChevronRight,
  CircleUserRound,
  Clapperboard,
  Download,
  FileAudio,
  FileText,
  Gauge,
  Library,
  MessageSquareText,
  Mic2,
  PanelLeftClose,
  PanelLeftOpen,
  Pause,
  Play,
  Plus,
  RefreshCw,
  RotateCcw,
  Search,
  Scissors,
  Settings2,
  SlidersHorizontal,
  Sparkles,
  Square,
  Upload,
  WandSparkles,
  Waves,
  Workflow,
  X,
} from "lucide-react";

import { api } from "./api.js";
import { AdvancedControls } from "./AdvancedControls.jsx";
import { reconcileControlValues } from "./advancedControls.js";
import { AudiogramWorkspace } from "./AudiogramWorkspace.jsx";
import { ConversionWorkspace } from "./ConversionWorkspace.jsx";
import { ComponentsWorkspace } from "./ComponentsWorkspace.jsx";
import { DialogueWorkspace } from "./DialogueWorkspace.jsx";
import { formatCount, percent, statusLabel, textStats } from "./format.js";
import { ErrorCenter, ProfileManager, ResourceManager } from "./StudioTools.jsx";
import { LanguageWorkspace } from "./LanguageWorkspace.jsx";
import { PublishingWorkspace } from "./PublishingWorkspace.jsx";
import { TimelineWorkspace } from "./TimelineWorkspace.jsx";
import { VoiceStudio } from "./VoiceStudio.jsx";

const NAVIGATION = [
  {
    label: "Create",
    items: [
      { id: "narrate", label: "Narrate", icon: AudioLines, ready: true },
      { id: "library", label: "Library", icon: Library, ready: true },
      { id: "dialogue", label: "Dialogue", icon: MessageSquareText, ready: true },
    ],
  },
  {
    label: "Edit",
    items: [
      { id: "timeline", label: "Timeline", icon: Scissors, ready: true },
      { id: "audiogram", label: "Audiogram", icon: Clapperboard, ready: true },
      { id: "publish", label: "Publish", icon: Upload, ready: true },
    ],
  },
  {
    label: "Studio",
    items: [
      { id: "voices", label: "Voice studio", icon: Mic2, ready: true },
      { id: "pronunciation", label: "Pronunciation", icon: FileAudio, ready: true },
      { id: "components", label: "Components", icon: Boxes, ready: true },
      { id: "convert", label: "Convert", icon: RefreshCw, ready: true },
    ],
  },
];

const PACE = ["very_slow", "slow", "normal", "fast", "very_fast"];
const NONVERBAL = ["never", "rare", "occasional", "frequent", "very_frequent"];
const TERMINAL = new Set(["completed", "failed", "cancelled"]);

function designedVoiceTake(profile) {
  if (!profile || profile.kind !== "designed") return null;
  const legacy = profile.metadata?.legacy_voice_metadata;
  const value = profile.settings?.design_take ?? profile.settings?.take ?? legacy?.take ?? 1;
  return Number.isInteger(value) && value >= 1 && value <= 99 ? value : 1;
}

function Control({ label, help, children, wide = false }) {
  return (
    <label className={`control${wide ? " control-wide" : ""}`}>
      <span>{label}</span>
      {children}
      {help && <small>{help}</small>}
    </label>
  );
}

function RangeControl({ label, values, value, onChange }) {
  const index = Math.max(0, values.indexOf(value));
  return (
    <label className="control range-control">
      <span className="range-heading">
        <span>{label}</span>
        <strong>{statusLabel(values[index])}</strong>
      </span>
      <input
        type="range"
        min="0"
        max={values.length - 1}
        step="1"
        value={index}
        onChange={(event) => onChange(values[Number(event.target.value)])}
      />
      <span className="range-ends">
        <small>{statusLabel(values[0])}</small>
        <small>{statusLabel(values.at(-1))}</small>
      </span>
    </label>
  );
}

function Shell({ active, onChange, collapsed, setCollapsed, onOpenErrors, unreadErrors, children }) {
  return (
    <div className={`studio-shell${collapsed ? " nav-collapsed" : ""}`}>
      <aside className="studio-nav">
        <div className="brand-row">
          <div className="brand-mark"><Waves size={21} /></div>
          {!collapsed && (
            <div><strong>SPLICR</strong><span>Studio</span></div>
          )}
          <button
            className="icon-button nav-toggle"
            onClick={() => setCollapsed((value) => !value)}
            aria-label={collapsed ? "Expand navigation" : "Collapse navigation"}
          >
            {collapsed ? <PanelLeftOpen size={18} /> : <PanelLeftClose size={18} />}
          </button>
        </div>
        <nav aria-label="Studio workspaces">
          {NAVIGATION.map((group) => (
            <section className="nav-group" key={group.label}>
              {!collapsed && <p>{group.label}</p>}
              {group.items.map((item) => {
                const Icon = item.icon;
                return (
                  <button
                    key={item.id}
                    className={active === item.id ? "active" : ""}
                    onClick={() => onChange(item.id)}
                    title={collapsed ? item.label : undefined}
                  >
                    <Icon size={18} />
                    {!collapsed && <span>{item.label}</span>}
                    {!collapsed && !item.ready && <i>Next</i>}
                  </button>
                );
              })}
            </section>
          ))}
        </nav>
        <div className="nav-footer">
          <button onClick={onOpenErrors} title="Open error center"><AlertTriangle size={17} />{!collapsed && <span>Errors</span>}{unreadErrors > 0 && <i>{unreadErrors > 99 ? "99+" : unreadErrors}</i>}</button>
          <a href="/" title="Open classic SPLICR"><RotateCcw size={17} />{!collapsed && "Classic UI"}</a>
          <a href="/auth/settings" title="Account settings"><CircleUserRound size={17} />{!collapsed && "Account"}</a>
        </div>
      </aside>
      <div className="studio-main">{children}</div>
    </div>
  );
}

function WorkspacePlaceholder({ workspace }) {
  const item = NAVIGATION.flatMap((group) => group.items).find((entry) => entry.id === workspace);
  const Icon = item?.icon || Workflow;
  return (
    <main className="placeholder-workspace">
      <div className="placeholder-card">
        <span className="placeholder-icon"><Icon size={28} /></span>
        <p className="eyebrow">Narrator workspace</p>
        <h1>{item?.label || "Workspace"}</h1>
        <p>
          This workspace is present in the new Studio shell and is next in the compatibility
          migration. The preserved Narrator implementation remains untouched while its API and
          data model are adapted to shared Studio projects and artifacts.
        </p>
        <div className="migration-track">
          <span className="done">Shell</span><ChevronRight size={15} />
          <span className="active">API adaptation</span><ChevronRight size={15} />
          <span>Parity</span>
        </div>
        <a className="secondary-button" href="/">Continue in classic SPLICR</a>
      </div>
    </main>
  );
}

function ChunkPreview({ preview, activeChunk, setActiveChunk }) {
  if (!preview) return null;
  const selected = preview.chunks.find((chunk) => chunk.index === activeChunk) || preview.chunks[0];
  return (
    <section className="preview-panel">
      <div className="section-heading compact">
        <div>
          <p className="eyebrow">Preflight</p>
          <h2>{preview.chunks.length} planned chunks</h2>
        </div>
        <span>{formatCount(preview.total_words)} words · {formatCount(preview.total_bytes)} bytes</span>
      </div>
      <div className="chunk-stage">
        {preview.warnings?.length > 0 && (
          <div className="planner-warnings" role="status">
            {preview.warnings.map((warning) => <span key={warning}>{warning}</span>)}
          </div>
        )}
        <div className="chunk-inspector">
          <span>Chunk {selected.index + 1} · {selected.boundary}</span>
          <p>{selected.text}</p>
          <small>
            Source {formatCount(selected.start_char)}–{formatCount(selected.end_char)} · {formatCount(selected.character_count)} characters
            {selected.token_count !== null ? ` · ${formatCount(selected.token_count)} tokens` : ""}
          </small>
          <small>
            Provider headroom: {Object.entries(selected.limit_headroom || {}).map(([name, value]) => `${formatCount(value)} ${name}`).join(" · ")}
          </small>
        </div>
        <div className="chunk-strip" aria-label="Planned document chunks">
          {preview.chunks.map((chunk) => (
            <button
              key={chunk.index}
              className={chunk.index === selected.index ? "active" : ""}
              onMouseEnter={() => setActiveChunk(chunk.index)}
              onFocus={() => setActiveChunk(chunk.index)}
              onClick={() => setActiveChunk(chunk.index)}
              title={`${chunk.word_count} words, ${chunk.byte_count} bytes`}
            >
              <span>{chunk.index + 1}</span>
              <i className={`weight-${Math.max(1, Math.min(10, Math.ceil(chunk.byte_count / 380)))}`} />
            </button>
          ))}
        </div>
      </div>
    </section>
  );
}

function JobCard({ job, onAction, onRefresh }) {
  const [subtitleBusy, setSubtitleBusy] = useState("");
  const [subtitleError, setSubtitleError] = useState("");
  if (!job) {
    return (
      <section className="activity-card empty-state">
        <span><Gauge size={24} /></span>
        <h2>No active render</h2>
        <p>Preview the document, then start a take. Progress and playable output will stay here.</p>
      </section>
    );
  }
  const progress = job.progress || 0;
  const exportSubtitles = async (format) => {
    setSubtitleBusy(format);
    setSubtitleError("");
    try {
      const result = await api.exportJobSubtitles(job.id, format);
      window.location.assign(result.download_url);
    } catch (reason) {
      setSubtitleError(reason.message);
    } finally {
      setSubtitleBusy("");
    }
  };
  return (
    <section className="activity-card">
      <div className="activity-heading">
        <div>
          <p className="eyebrow">Active take</p>
          <h2>{job.provider} · {job.voice}</h2>
        </div>
        <span className={`status status-${job.status}`}>{statusLabel(job.status)}</span>
      </div>
      <div className="progress-ring-row">
        <div className="progress-meter">
          <strong>{percent(progress)}</strong>
          <progress max="1" value={progress} aria-label="Synthesis progress" />
        </div>
        <div className="progress-copy">
          <strong>{job.completed_chunks} of {job.total_chunks} chunks</strong>
          <span>{formatCount(job.current_char)} of {formatCount(job.total_chars)} characters</span>
          <small>{job.current_excerpt || "Waiting for the next checkpoint…"}</small>
        </div>
      </div>
      {job.error_detail && (
        <div className="job-error">
          <strong>{job.error_code || "Render paused"}</strong>
          <span>{job.error_detail}</span>
        </div>
      )}
      {(job.audio_url || job.partial_audio_url) && (
        <div className="player-card">
          <audio controls preload="metadata" src={`${job.audio_url || job.partial_audio_url}?v=${encodeURIComponent(job.updated_at)}`} />
          {job.audio_url && <a href={job.audio_url} download={job.download_filename}><Download size={16} />Download master WAV</a>}
          {job.checkpoint_export_url && (
            <a href={job.checkpoint_export_url} download>
              <Download size={16} />
              {job.status === "completed" ? "Export checkpoint WAVs + manifest" : "Export completed checkpoints (partial)"}
            </a>
          )}
          {job.completed_chunks > 0 && (
            <details className="job-caption-export">
              <summary><FileText size={16} />Export captions</summary>
              <button type="button" disabled={!!subtitleBusy} onClick={() => exportSubtitles("srt")}>{subtitleBusy === "srt" ? "Exporting…" : "SRT"}</button>
              <button type="button" disabled={!!subtitleBusy} onClick={() => exportSubtitles("vtt")}>{subtitleBusy === "vtt" ? "Exporting…" : "WebVTT"}</button>
            </details>
          )}
          {subtitleError && <small className="inline-error">{subtitleError}</small>}
        </div>
      )}
      <div className="job-actions">
        {job.status === "paused" && (
          <button className="primary-button small" onClick={() => onAction("resume")}><Play size={15} />Resume</button>
        )}
        {job.status === "failed" && (
          <button className="primary-button small" onClick={() => onAction("retry")}><Play size={15} />Retry</button>
        )}
        {job.status === "running" && (
          <button className="secondary-button small" onClick={() => onAction("pause")}><Pause size={15} />Pause</button>
        )}
        {!TERMINAL.has(job.status) && job.status !== "cancelled" && (
          <button className="ghost-button small danger" onClick={() => onAction("cancel")}><Square size={14} />Cancel</button>
        )}
        <button className="icon-button" onClick={onRefresh} aria-label="Refresh job"><RefreshCw size={16} /></button>
      </div>
    </section>
  );
}

function RecentJobs({ jobs, currentId, onSelect }) {
  return (
    <section className="recent-card">
      <div className="section-heading compact">
        <div><p className="eyebrow">Local history</p><h2>Recent takes</h2></div>
        <span>{jobs.length}</span>
      </div>
      <div className="recent-list">
        {jobs.length === 0 && <p className="muted">No jobs yet.</p>}
        {jobs.slice(0, 6).map((job) => (
          <button key={job.id} className={currentId === job.id ? "active" : ""} onClick={() => onSelect(job)}>
            <span className={`job-dot status-${job.status}`} />
            <span><strong>{job.voice}</strong><small>{job.completed_chunks}/{job.total_chunks} chunks</small></span>
            <time>{statusLabel(job.status)}</time>
          </button>
        ))}
      </div>
    </section>
  );
}

function LibraryWorkspace({ onOpen }) {
  const [projects, setProjects] = useState([]);
  const [profiles, setProfiles] = useState([]);
  const [batches, setBatches] = useState([]);
  const [selectedProjects, setSelectedProjects] = useState([]);
  const [profileId, setProfileId] = useState("");
  const [batchName, setBatchName] = useState("Narration batch");
  const [activeBatchId, setActiveBatchId] = useState("");
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [working, setWorking] = useState("");
  const [error, setError] = useState("");

  const refresh = async () => {
    setLoading(true);
    setError("");
    try {
      const [nextProjects, nextProfiles, nextBatches] = await Promise.all([
        api.projects(), api.profiles(), api.batches(),
      ]);
      setProjects(nextProjects);
      setProfiles(nextProfiles);
      setBatches(nextBatches);
      setProfileId((current) => current || nextProfiles[0]?.id || "");
      setActiveBatchId((current) => current || nextBatches[0]?.id || "");
    }
    catch (reason) { setError(reason.message); }
    finally { setLoading(false); }
  };

  useEffect(() => { refresh(); }, []);
  const activeBatch = batches.find((batch) => batch.id === activeBatchId) || batches[0] || null;
  const batchIsLive = activeBatch && ["preparing", "queued", "running", "paused"].includes(activeBatch.status);
  useEffect(() => {
    if (!batchIsLive) return undefined;
    let stopped = false;
    const poll = async () => {
      try {
        const updated = await api.batch(activeBatch.id);
        if (stopped) return;
        setBatches((current) => [updated, ...current.filter((item) => item.id !== updated.id)]);
        if (["completed", "cancelled"].includes(updated.status)) {
          const nextProjects = await api.projects();
          if (!stopped) setProjects(nextProjects);
        }
      } catch (reason) {
        if (!stopped) setError(reason.message);
      }
    };
    const timer = window.setInterval(poll, 750);
    poll();
    return () => { stopped = true; window.clearInterval(timer); };
  }, [activeBatch?.id, batchIsLive]);
  const visible = projects.filter((project) => {
    const haystack = `${project.name} ${project.source_name || ""} ${project.source_preview}`.toLowerCase();
    return haystack.includes(query.trim().toLowerCase());
  });

  const open = async (project) => {
    setError("");
    try { onOpen(await api.project(project.id)); }
    catch (reason) { setError(reason.message); }
  };

  const toggleProject = (projectId) => {
    setSelectedProjects((current) => current.includes(projectId)
      ? current.filter((id) => id !== projectId)
      : [...current, projectId]);
  };

  const createBatch = async () => {
    if (!selectedProjects.length || !profileId) return;
    setWorking("create");
    setError("");
    try {
      const created = await api.createBatch({
        name: batchName.trim() || "Narration batch",
        items: selectedProjects.map((project_id) => ({ project_id, profile_id: profileId })),
      });
      setBatches((current) => [created, ...current.filter((item) => item.id !== created.id)]);
      setActiveBatchId(created.id);
      setSelectedProjects([]);
    } catch (reason) { setError(reason.message); }
    finally { setWorking(""); }
  };

  const runBatchAction = async (action) => {
    if (!activeBatch) return;
    setWorking(action);
    setError("");
    try {
      const updated = await api.batchAction(activeBatch.id, action);
      setBatches((current) => [updated, ...current.filter((item) => item.id !== updated.id)]);
    } catch (reason) { setError(reason.message); }
    finally { setWorking(""); }
  };

  const reorderItem = async (itemId, offset) => {
    if (!activeBatch) return;
    const ids = activeBatch.items.map((item) => item.id);
    const index = ids.indexOf(itemId);
    const destination = index + offset;
    if (index < 0 || destination < 0 || destination >= ids.length) return;
    [ids[index], ids[destination]] = [ids[destination], ids[index]];
    setWorking(itemId);
    try {
      const updated = await api.reorderBatch(activeBatch.id, ids);
      setBatches((current) => [updated, ...current.filter((item) => item.id !== updated.id)]);
    } catch (reason) { setError(reason.message); }
    finally { setWorking(""); }
  };

  const removeItem = async (itemId) => {
    if (!activeBatch) return;
    setWorking(itemId);
    try {
      const updated = await api.removeBatchItem(activeBatch.id, itemId);
      setBatches((current) => [updated, ...current.filter((item) => item.id !== updated.id)]);
    } catch (reason) { setError(reason.message); }
    finally { setWorking(""); }
  };

  return (
    <main className="library-workspace">
      <header className="workspace-header">
        <div><p className="eyebrow">Create · Library</p><h1>Your documents, takes, and imported history.</h1></div>
        <button className="secondary-button" onClick={refresh} disabled={loading}><RefreshCw size={16} />Refresh</button>
      </header>
      {error && <div className="inline-error" role="alert">{error}</div>}
      <section className="library-toolbar">
        <label><Search size={17} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search projects…" /></label>
        <span>{selectedProjects.length ? `${selectedProjects.length} selected · ` : ""}{visible.length} of {projects.length} projects</span>
      </section>
      <section className="batch-composer" aria-labelledby="batch-composer-title">
        <div>
          <p className="eyebrow">Batch render</p>
          <h2 id="batch-composer-title">Queue several documents with one frozen profile.</h2>
          <p>Each item keeps its own document revision, profile settings, provider revision, and render plan—even if you edit the originals later.</p>
        </div>
        <label><span>Queue name</span><input value={batchName} onChange={(event) => setBatchName(event.target.value)} /></label>
        <label><span>Render profile</span><select value={profileId} onChange={(event) => setProfileId(event.target.value)}><option value="">Choose a saved profile</option>{profiles.map((profile) => <option key={profile.id} value={profile.id}>{profile.name}</option>)}</select></label>
        <button className="primary-button" disabled={!selectedProjects.length || !profileId || working === "create"} onClick={createBatch}><Play size={15} />Queue {selectedProjects.length || "selected"}</button>
      </section>
      {!profiles.length && !loading && <div className="inline-note">Save a render profile in Narrate before creating a batch. Profiles freeze the engine, voice, delivery controls, and advanced parameters for reproducible work.</div>}
      {batches.length > 0 && (
        <section className="batch-monitor" aria-live="polite">
          <div className="batch-monitor-heading">
            <div><p className="eyebrow">Durable queue</p><h2>{activeBatch?.name}</h2></div>
            <label><span>History</span><select value={activeBatch?.id || ""} onChange={(event) => setActiveBatchId(event.target.value)}>{batches.map((batch) => <option key={batch.id} value={batch.id}>{batch.name} · {statusLabel(batch.status)}</option>)}</select></label>
          </div>
          {activeBatch && <>
            <div className="batch-progress"><div style={{ width: `${Math.round(activeBatch.progress * 100)}%` }} /><span>{Math.round(activeBatch.progress * 100)}%</span></div>
            <div className="batch-summary">
              <strong className={`status-${activeBatch.status}`}>{statusLabel(activeBatch.status)}</strong>
              <span>{activeBatch.counts.completed} completed</span><span>{activeBatch.counts.failed} failed</span><span>{activeBatch.counts.skipped} skipped</span><span>{activeBatch.counts.cancelled} cancelled</span>
            </div>
            <div className="batch-actions">
              {activeBatch.status === "paused" ? <button className="secondary-button" disabled={Boolean(working)} onClick={() => runBatchAction("resume")}><Play size={14} />Resume queue</button> : <>
                <button className="secondary-button" disabled={Boolean(working) || !["queued", "running"].includes(activeBatch.status)} onClick={() => runBatchAction("pause-current")}><Pause size={14} />Pause current + queue</button>
                <button className="secondary-button" disabled={Boolean(working) || !["queued", "running"].includes(activeBatch.status)} onClick={() => runBatchAction("pause-remaining")}><Pause size={14} />Pause after current</button>
              </>}
              <button className="secondary-button danger" disabled={Boolean(working) || activeBatch.status !== "running"} onClick={() => runBatchAction("cancel-current")}><Square size={13} />Cancel current</button>
              <button className="secondary-button danger" disabled={Boolean(working) || !["queued", "running", "paused"].includes(activeBatch.status)} onClick={() => runBatchAction("cancel-remaining")}><X size={14} />Cancel remaining</button>
            </div>
            <ol className="batch-items">
              {activeBatch.items.map((item, index) => {
                const editable = ["pending", "ready"].includes(item.status);
                const previousEditable = index > 0 && ["pending", "ready"].includes(activeBatch.items[index - 1].status);
                const nextEditable = index < activeBatch.items.length - 1 && ["pending", "ready"].includes(activeBatch.items[index + 1].status);
                return <li key={item.id}>
                  <span className={`job-dot status-${item.status}`} />
                  <div><strong>{item.project_name}</strong><small>{item.profile_name} · {item.provider_name || "unresolved"}{item.error_detail ? ` · ${item.error_detail}` : ""}</small></div>
                  <i>{statusLabel(item.status)}</i>
                  <div className="batch-item-actions">
                    {item.status === "completed" && item.job_id && <a className="icon-button" href={`/v1/speech/jobs/${encodeURIComponent(item.job_id)}/audio`} download aria-label={`Download ${item.project_name}`}><Download size={14} /></a>}
                    {editable && <><button className="icon-button" disabled={Boolean(working) || !previousEditable} onClick={() => reorderItem(item.id, -1)} aria-label={`Move ${item.project_name} earlier`}>↑</button><button className="icon-button" disabled={Boolean(working) || !nextEditable} onClick={() => reorderItem(item.id, 1)} aria-label={`Move ${item.project_name} later`}>↓</button><button className="icon-button" disabled={Boolean(working)} onClick={() => removeItem(item.id)} aria-label={`Remove ${item.project_name}`}><X size={14} /></button></>}
                  </div>
                </li>;
              })}
            </ol>
          </>}
        </section>
      )}
      {loading && <section className="library-empty"><RefreshCw className="spin" size={24} /><p>Loading Studio projects…</p></section>}
      {!loading && projects.length === 0 && (
        <section className="library-empty">
          <BookOpen size={28} />
          <h2>Your Studio library is ready.</h2>
          <p>Import existing SPLICR jobs and Narrator metadata once, then they will appear here without moving the original files.</p>
          <code>uv run splicr migrate-studio --narrator-data &lt;path&gt;</code>
        </section>
      )}
      {!loading && visible.length > 0 && (
        <section className="project-grid">
          {visible.map((project) => {
            const origin = project.metadata.legacy_source_system || "studio";
            const status = project.metadata.legacy_status || project.metadata.legacy_job_status || "ready";
            return (
              <article className="project-card" key={project.id}>
                <div className="project-card-heading">
                  <button className={`project-select ${selectedProjects.includes(project.id) ? "selected" : ""}`} disabled={!project.source_chars} onClick={() => toggleProject(project.id)} aria-pressed={selectedProjects.includes(project.id)} aria-label={`${selectedProjects.includes(project.id) ? "Remove" : "Add"} ${project.name} ${selectedProjects.includes(project.id) ? "from" : "to"} batch`}><FileText size={20} /></button>
                  <div><p>{origin.replaceAll("-", " ")}</p><h2>{project.name}</h2></div>
                  <i>{statusLabel(status)}</i>
                </div>
                <p className="project-preview">{project.source_preview || "This imported project keeps its original document linked externally."}</p>
                <dl>
                  <div><dt>Source</dt><dd>{project.source_name || "Linked document"}</dd></div>
                  <div><dt>Plans</dt><dd>{project.render_plan_count}</dd></div>
                  <div><dt>Takes</dt><dd>{project.take_count}</dd></div>
                  <div><dt>Characters</dt><dd>{formatCount(project.source_chars)}</dd></div>
                </dl>
                <button className="secondary-button" disabled={!project.source_chars} onClick={() => open(project)}>
                  {project.source_chars ? "Open in Narrate" : "Source remains external"}<ChevronRight size={15} />
                </button>
              </article>
            );
          })}
        </section>
      )}
    </main>
  );
}

function NarrateWorkspace({ active, projectToLoad }) {
  const inputRef = useRef(null);
  const [providers, setProviders] = useState([]);
  const [voiceProfiles, setVoiceProfiles] = useState([]);
  const [jobs, setJobs] = useState([]);
  const [job, setJob] = useState(null);
  const [preview, setPreview] = useState(null);
  const [activeChunk, setActiveChunk] = useState(0);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [sourceName, setSourceName] = useState("");
  const [projectName, setProjectName] = useState("");
  const [profilesOpen, setProfilesOpen] = useState(false);
  const [resourcesOpen, setResourcesOpen] = useState(false);
  const [advancedControlsValid, setAdvancedControlsValid] = useState(true);
  const [form, setForm] = useState({
    text: "",
    provider: "",
    model: "",
    voice: "",
    voice_profile_id: "",
    instructions: "",
    split_strategy: "semantic",
    chunk_target_mode: "automatic",
    chunk_target_value: null,
    remove_numeric_citations: false,
    export_name: "",
    controls: { tone: "neutral", pace: "normal", vocal_style: "natural", nonverbal_frequency: "never" },
    variables: {},
    resource_revision: null,
  });

  const provider = providers.find((item) => item.name === form.provider) || providers[0];
  const stats = useMemo(() => textStats(form.text), [form.text]);
  const capabilities = provider?.capabilities || {};
  const controlDefinitions = capabilities.control_definitions || [];
  const voiceEngine = provider?.name === "qwen3-local"
    ? "qwen3"
    : provider?.name === "audio8-local"
      ? "audio8"
      : null;
  const profileVoices = voiceEngine
    ? voiceProfiles.filter((item) => {
        const engine = item.engine_id.toLowerCase();
        return engine === voiceEngine || engine === `${voiceEngine}-local`;
      })
    : [];
  const requiresVoiceProfile = Boolean(voiceEngine);
  const selectedVoiceProfile = profileVoices.find((item) => item.id === form.voice_profile_id);
  const directorNotesSupported = Boolean(capabilities.supports_custom_instructions)
    && !(provider?.name === "qwen3-local" && selectedVoiceProfile?.kind !== "preset");

  const patchForm = (values) => {
    setForm((current) => ({ ...current, ...values }));
    if (
      "text" in values
      || "provider" in values
      || "split_strategy" in values
      || "chunk_target_mode" in values
      || "chunk_target_value" in values
      || "remove_numeric_citations" in values
    ) setPreview(null);
  };
  const patchControls = (values) => setForm((current) => ({ ...current, controls: { ...current.controls, ...values } }));

  const selectVoiceProfile = (voiceProfileId) => {
    patchForm({ voice_profile_id: voiceProfileId });
  };

  const loadJobs = async () => {
    const next = await api.jobs();
    setJobs(next);
    if (job) {
      const fresh = next.find((item) => item.id === job.id);
      if (fresh) setJob(fresh);
    }
  };

  const refreshProviders = async (preferredId = null) => {
    const providerRows = await api.providers();
    setProviders(providerRows);
    if (providerRows.length) {
      setForm((current) => {
        const selected = providerRows.find((item) => item.name === (preferredId || current.provider)) || providerRows[0];
        return {
          ...current,
          provider: selected.name,
          resource_revision: preferredId ? null : current.resource_revision,
          model: selected.name === current.provider ? current.model : selected.default_model,
          voice: selected.name === current.provider ? current.voice : selected.default_voice,
          voice_profile_id: selected.name === current.provider ? current.voice_profile_id : "",
        };
      });
    }
    return providerRows;
  };

  useEffect(() => {
    Promise.all([api.providers(), api.jobs()])
      .then(([providerRows, jobRows]) => {
        setProviders(providerRows);
        setJobs(jobRows);
        if (providerRows.length) {
          const first = providerRows[0];
          setForm((current) => ({ ...current, provider: first.name, model: first.default_model, voice: first.default_voice }));
        }
      })
      .catch((reason) => setError(reason.message));
  }, []);

  useEffect(() => {
    if (!active) return;
    api.voices().then(setVoiceProfiles).catch((reason) => setError(reason.message));
  }, [active]);

  useEffect(() => {
    if (provider?.name !== "qwen3-local" || !selectedVoiceProfile) return;
    const customVoiceModel = (capabilities.models || []).find((item) => item.endsWith("CustomVoice"));
    setForm((current) => {
      const nextModel = selectedVoiceProfile.kind === "preset"
        ? customVoiceModel || current.model
        : current.model.endsWith("CustomVoice")
          ? provider.default_model
          : current.model;
      return nextModel === current.model ? current : { ...current, model: nextModel };
    });
  }, [provider?.name, selectedVoiceProfile?.id, selectedVoiceProfile?.kind]);

  useEffect(() => {
    if (provider?.name !== "qwen3-local") return;
    const voiceTake = designedVoiceTake(selectedVoiceProfile);
    setForm((current) => {
      const variables = { ...current.variables };
      if (voiceTake === null) delete variables.voice_take;
      else variables.voice_take = voiceTake;
      return JSON.stringify(variables) === JSON.stringify(current.variables)
        ? current
        : { ...current, variables };
    });
  }, [provider?.name, selectedVoiceProfile?.id, selectedVoiceProfile?.kind]);

  useEffect(() => {
    if (!projectToLoad) return;
    setForm((current) => ({
      ...current,
      text: projectToLoad.source_text || "",
      export_name: projectToLoad.name || "",
    }));
    setSourceName(projectToLoad.source_name || projectToLoad.name);
    setProjectName(projectToLoad.name);
    setPreview(null);
    setActiveChunk(0);
  }, [projectToLoad?.id]);

  useEffect(() => {
    if (!provider) return;
    const models = capabilities.models || [];
    const voices = capabilities.voices || [];
    const tones = capabilities.tone_presets?.length ? capabilities.tone_presets : ["neutral"];
    const paces = capabilities.speech_paces?.length ? capabilities.speech_paces : ["normal"];
    const styles = capabilities.vocal_styles?.length ? capabilities.vocal_styles : ["natural"];
    const nonverbals = capabilities.nonverbal_frequencies?.length ? capabilities.nonverbal_frequencies : ["never"];
    setForm((current) => ({
      ...current,
      provider: provider.name,
      model: models.includes(current.model) ? current.model : provider.default_model,
      voice: voices.some((item) => item.id === current.voice) ? current.voice : provider.default_voice,
      voice_profile_id: voiceEngine && profileVoices.some((item) => item.id === current.voice_profile_id)
        ? current.voice_profile_id
        : "",
      controls: {
        tone: tones.includes(current.controls.tone) ? current.controls.tone : tones[0],
        pace: paces.includes(current.controls.pace) ? current.controls.pace : paces[0],
        vocal_style: styles.includes(current.controls.vocal_style) ? current.controls.vocal_style : styles[0],
        nonverbal_frequency: nonverbals.includes(current.controls.nonverbal_frequency)
          ? current.controls.nonverbal_frequency
          : nonverbals[0],
      },
    }));
  }, [provider?.name, voiceProfiles.length]);

  useEffect(() => {
    if (!provider) return;
    setForm((current) => {
      const variables = reconcileControlValues(
        controlDefinitions,
        current.variables,
        Boolean(capabilities.allows_undeclared_variables),
      );
      return JSON.stringify(variables) === JSON.stringify(current.variables)
        ? current
        : { ...current, variables };
    });
  }, [provider?.name, provider?.revision, controlDefinitions, capabilities.allows_undeclared_variables]);

  useEffect(() => {
    if (!job || TERMINAL.has(job.status) || job.status === "paused") return undefined;
    const timer = window.setInterval(async () => {
      try {
        const fresh = await api.job(job.id);
        setJob(fresh);
        if (fresh.completed_chunks !== job.completed_chunks || TERMINAL.has(fresh.status)) {
          const next = await api.jobs();
          setJobs(next);
        }
      } catch (reason) {
        setError(reason.message);
      }
    }, 750);
    return () => window.clearInterval(timer);
  }, [job?.id, job?.status, job?.completed_chunks]);

  const payload = () => ({
    ...form,
    model: form.model || null,
    voice: form.voice || null,
    voice_profile_id: form.voice_profile_id || null,
    instructions: directorNotesSupported ? form.instructions.trim() || null : null,
    export_name: form.export_name.trim() || null,
    project_name: projectName.trim() || null,
    source_name: sourceName.trim() || null,
  });

  const buildProfilePayload = (name, includeJob) => ({
    name,
    resource_id: form.provider,
    resource_revision: form.resource_revision,
    text: form.text,
    model: form.model || null,
    voice: form.voice || null,
    voice_profile_id: form.voice_profile_id || null,
    instructions: form.instructions.trim() || null,
    controls: form.controls,
    split_strategy: form.split_strategy,
    chunk_target_mode: form.chunk_target_mode,
    chunk_target_value: form.chunk_target_mode === "automatic" ? null : form.chunk_target_value,
    remove_numeric_citations: form.remove_numeric_citations,
    variables: form.variables,
    job_id: includeJob ? job?.id || null : null,
  });

  const loadProfile = (profile) => {
    setForm((current) => ({
      ...current,
      text: profile.text,
      provider: profile.resource_id,
      resource_revision: profile.resource_revision,
      model: profile.model || "",
      voice: profile.voice || "",
      voice_profile_id: profile.voice_profile_id || "",
      instructions: profile.instructions || "",
      controls: profile.controls,
      split_strategy: profile.split_strategy,
      chunk_target_mode: profile.chunk_target_mode || "automatic",
      chunk_target_value: profile.chunk_target_value ?? null,
      remove_numeric_citations: profile.remove_numeric_citations,
      variables: profile.variables || {},
      export_name: profile.name,
    }));
    setSourceName(`${profile.name} profile`);
    setProjectName(profile.name);
    setPreview(null);
    if (profile.job) {
      setJob(profile.job);
      setJobs((current) => [profile.job, ...current.filter((item) => item.id !== profile.job.id)]);
    }
  };

  const run = async (label, operation) => {
    setBusy(label);
    setError("");
    try { return await operation(); }
    catch (reason) { setError(reason.message); return null; }
    finally { setBusy(""); }
  };

  const importFile = async (file) => {
    if (!file) return;
    const imported = await run("import", () => api.importDocument(file));
    if (imported) {
      const documentName = imported.metadata.title || imported.filename.replace(/\.[^.]+$/, "");
      patchForm({ text: imported.text, export_name: documentName });
      setSourceName(imported.filename);
      setProjectName(documentName);
    }
  };

  const previewChunks = async () => {
    const result = await run("preview", () => api.preview(payload()));
    if (result) { setPreview(result); setActiveChunk(0); }
  };

  const startJob = async () => {
    const created = await run("start", () => api.createJob(payload()));
    if (created) {
      setJob(created);
      setJobs((current) => [created, ...current.filter((item) => item.id !== created.id)]);
    }
  };

  const actOnJob = async (action) => {
    if (!job) return;
    const changed = await run(action, () => api.jobAction(job.id, action));
    if (changed) { setJob(changed); await loadJobs(); }
  };

  return (
    <>
    <main className="narrate-workspace">
      <header className="workspace-header">
        <div><p className="eyebrow">Create · Narrate</p><h1>Turn a document into a finished voice performance.</h1></div>
        <div className="header-tools">
          <span className="local-pill"><i />Local workspace</span>
          <button className="secondary-button small" onClick={() => setProfilesOpen(true)}>Profiles</button>
          <button className="secondary-button small" onClick={() => setResourcesOpen(true)}><Plus size={15} />Connections</button>
          <a className="icon-button" href="/docs" aria-label="API documentation"><Settings2 size={18} /></a>
        </div>
      </header>

      {error && <div className="error-toast" role="alert"><span><strong>Something needs attention</strong>{error}</span><button onClick={() => setError("")}><X size={16} /></button></div>}

      <div className="workspace-grid">
        <div className="composition-stack">
          <section className="surface source-card">
            <div className="section-heading">
              <div><p className="eyebrow">01 · Source</p><h2>Document</h2></div>
              <span>{sourceName || "Paste or import"}</span>
            </div>
            <input ref={inputRef} className="visually-hidden" type="file" accept=".md,.markdown,.doc,.docx,.txt,.odt,.json" onChange={(event) => importFile(event.target.files?.[0])} />
            <button className="import-zone" onClick={() => inputRef.current?.click()} disabled={busy === "import"}>
              <span><Upload size={20} /></span>
              <span><strong>{busy === "import" ? "Reading document…" : "Import a document"}</strong><small>Markdown, Word, OpenDocument, text, or JSON</small></span>
              <ChevronRight size={18} />
            </button>
            <textarea
              className="source-editor"
              value={form.text}
              onChange={(event) => patchForm({ text: event.target.value })}
              placeholder="Paste the document you want to hear…"
              spellCheck="true"
            />
            <div className="editor-meta">
              <span>{formatCount(stats.words)} words</span><span>{formatCount(stats.characters)} characters</span><span>{formatCount(stats.bytes)} UTF-8 bytes</span>
            </div>
            <div className="planner-row">
              <Control label="Preferred boundary">
                <select value={form.split_strategy} onChange={(event) => patchForm({ split_strategy: event.target.value })}>
                  <option value="semantic">Semantic</option><option value="h1">Heading 1</option><option value="h2">Heading 2</option><option value="h3">Heading 3</option><option value="h4">Heading 4</option><option value="h5">Heading 5</option><option value="h6">Heading 6</option>
                  <option value="double_newline">Double newline</option><option value="newline">Every newline</option>
                </select>
              </Control>
              <label className="check-control"><input type="checkbox" checked={form.remove_numeric_citations} onChange={(event) => patchForm({ remove_numeric_citations: event.target.checked })} /><span><strong>Remove numeric citations</strong><small>[123] and \[123\]</small></span></label>
              <button className="secondary-button" disabled={!form.text.trim() || (requiresVoiceProfile && !form.voice_profile_id) || !advancedControlsValid || !!busy} onClick={previewChunks}><WandSparkles size={16} />{busy === "preview" ? "Planning…" : "Preview chunks"}</button>
            </div>
            <details className="chunk-advanced">
              <summary>Advanced chunk planning</summary>
              <div className="control-grid two">
                <Control label="Target mode" help="Provider safety limits always win.">
                  <select
                    value={form.chunk_target_mode}
                    onChange={(event) => patchForm({
                      chunk_target_mode: event.target.value,
                      chunk_target_value: event.target.value === "automatic" ? null : form.chunk_target_value || 1,
                    })}
                  >
                    <option value="automatic">Automatic</option>
                    <option value="parts">Approximate number of parts</option>
                    <option value="characters">Characters per chunk</option>
                    <option value="tokens">Tokens per chunk</option>
                  </select>
                </Control>
                {form.chunk_target_mode !== "automatic" && (
                  <Control label={form.chunk_target_mode === "parts" ? "Requested parts" : `Target ${form.chunk_target_mode}`}>
                    <input
                      type="number"
                      min="1"
                      max={form.chunk_target_mode === "parts" ? 10000 : 10000000}
                      step="1"
                      value={form.chunk_target_value || 1}
                      onChange={(event) => patchForm({ chunk_target_value: Number(event.target.value) })}
                    />
                  </Control>
                )}
              </div>
            </details>
          </section>

          <ChunkPreview preview={preview} activeChunk={activeChunk} setActiveChunk={setActiveChunk} />

          <section className="surface direction-card">
            <div className="section-heading"><div><p className="eyebrow">02 · Performance</p><h2>Engine & direction</h2></div><SlidersHorizontal size={20} /></div>
            <div className="control-grid three">
              <Control label="Engine">
              <select value={form.provider} onChange={(event) => patchForm({ provider: event.target.value, resource_revision: null })}>{providers.map((item) => <option key={item.name} value={item.name}>{item.name}</option>)}</select>
              </Control>
              <Control label="Model"><input value={form.model} onChange={(event) => patchForm({ model: event.target.value })} list="studio-models" /><datalist id="studio-models">{(capabilities.models || []).map((item) => <option key={item} value={item} />)}</datalist></Control>
              {requiresVoiceProfile ? (
                <Control label="Voice Profile">
                  <select value={form.voice_profile_id} onChange={(event) => selectVoiceProfile(event.target.value)}>
                    <option value="">Select a Voice Profile…</option>
                    {profileVoices.map((item) => <option key={item.id} value={item.id}>{item.label} · {item.kind}</option>)}
                  </select>
                  {!profileVoices.length && <small className="control-help">Create a compatible voice in Voice studio first.</small>}
                </Control>
              ) : (
                <Control label="Voice">
                  <select value={form.voice} onChange={(event) => patchForm({ voice: event.target.value })}>{(capabilities.voices || []).map((item) => <option key={item.id} value={item.id}>{item.id}{item.traits?.length ? ` · ${item.traits.join(", ")}` : ""}</option>)}</select>
                </Control>
              )}
            </div>
            <div className="control-grid two">
              <Control label="Emotion & tone"><select value={form.controls.tone} onChange={(event) => patchControls({ tone: event.target.value })}>{(capabilities.tone_presets || ["neutral"]).map((item) => <option key={item}>{item}</option>)}</select></Control>
              <Control label="Vocal style"><select value={form.controls.vocal_style} onChange={(event) => patchControls({ vocal_style: event.target.value })}>{(capabilities.vocal_styles || ["natural"]).map((item) => <option key={item}>{item}</option>)}</select></Control>
              <RangeControl label="Speaking pace" values={capabilities.speech_paces?.length ? capabilities.speech_paces : PACE} value={form.controls.pace} onChange={(value) => patchControls({ pace: value })} />
              <RangeControl label="Non-verbal sounds" values={capabilities.nonverbal_frequencies?.length ? capabilities.nonverbal_frequencies : NONVERBAL} value={form.controls.nonverbal_frequency} onChange={(value) => patchControls({ nonverbal_frequency: value })} />
              <Control
                label="Director's notes"
                wide
                help={directorNotesSupported ? "Optional instructions are stored with the take." : "This engine and voice mode does not accept per-take directions."}
              >
                <textarea
                  rows="3"
                  value={form.instructions}
                  maxLength="2000"
                  disabled={!directorNotesSupported}
                  onChange={(event) => patchForm({ instructions: event.target.value })}
                  placeholder={directorNotesSupported ? "Emphasize quotations and pause before each new section." : "Unavailable for this voice mode"}
                />
              </Control>
            </div>
            <AdvancedControls
              definitions={controlDefinitions}
              values={form.variables}
              context={{
                model: form.model,
                voice: form.voice,
                voice_profile_id: form.voice_profile_id,
                voice_profile_kind: selectedVoiceProfile?.kind || null,
              }}
              onChange={(variables) => patchForm({ variables })}
              onValidityChange={setAdvancedControlsValid}
            />
            <div className="control-grid two output-controls">
              <Control label="Export filename" help="The app sanitizes reserved characters and keeps the internal take ID unchanged.">
                <input
                  value={form.export_name}
                  maxLength="240"
                  onChange={(event) => patchForm({ export_name: event.target.value })}
                  placeholder={projectName || "My narration"}
                />
              </Control>
            </div>
            <div className="render-row">
              <span><Sparkles size={16} />Chunks are checkpointed locally and resume safely.</span>
              <button className="primary-button" disabled={!form.text.trim() || !form.provider || (requiresVoiceProfile && !form.voice_profile_id) || !advancedControlsValid || !!busy} onClick={startJob}>{busy === "start" ? "Starting…" : "Start new take"}<ChevronRight size={17} /></button>
            </div>
          </section>
        </div>

        <aside className="activity-stack">
          <JobCard job={job} onAction={actOnJob} onRefresh={async () => job && setJob(await api.job(job.id))} />
          <RecentJobs jobs={jobs} currentId={job?.id} onSelect={setJob} />
          <section className="format-card"><FileText size={18} /><div><strong>Output format</strong><span>Mono PCM · 24 kHz · 16-bit WAV</span></div></section>
        </aside>
      </div>
    </main>
    <ProfileManager open={profilesOpen} onClose={() => setProfilesOpen(false)} buildPayload={buildProfilePayload} onLoad={loadProfile} />
    <ResourceManager open={resourcesOpen} onClose={() => setResourcesOpen(false)} onChanged={refreshProviders} />
    </>
  );
}

export default function App() {
  const [active, setActive] = useState("narrate");
  const [collapsed, setCollapsed] = useState(false);
  const [projectToLoad, setProjectToLoad] = useState(null);
  const [errorsOpen, setErrorsOpen] = useState(false);
  const [unreadErrors, setUnreadErrors] = useState(0);
  const openProject = (project) => {
    setProjectToLoad(project);
    setActive("narrate");
  };
  return (
    <Shell active={active} onChange={setActive} collapsed={collapsed} setCollapsed={setCollapsed} onOpenErrors={() => setErrorsOpen(true)} unreadErrors={unreadErrors}>
      <div hidden={active !== "narrate"}>
        <NarrateWorkspace active={active === "narrate"} projectToLoad={projectToLoad} />
      </div>
      {active === "library" && <LibraryWorkspace onOpen={openProject} />}
      {active === "dialogue" && <DialogueWorkspace active={active === "dialogue"} />}
      {active === "timeline" && <TimelineWorkspace onNavigate={setActive} />}
      {active === "audiogram" && <AudiogramWorkspace onNavigate={setActive} />}
      {active === "publish" && <PublishingWorkspace />}
      {active === "convert" && <ConversionWorkspace />}
      {active === "components" && <ComponentsWorkspace />}
      {active === "pronunciation" && <LanguageWorkspace />}
      {active === "voices" && <VoiceStudio />}
      {active !== "narrate" && active !== "library" && active !== "dialogue" && active !== "timeline" && active !== "audiogram" && active !== "publish" && active !== "convert" && active !== "components" && active !== "pronunciation" && active !== "voices" && <WorkspacePlaceholder workspace={active} />}
      <ErrorCenter open={errorsOpen} onClose={() => setErrorsOpen(false)} onOpen={() => setErrorsOpen(true)} onUnreadChange={setUnreadErrors} />
    </Shell>
  );
}
