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
import { formatCount, percent, statusLabel, textStats } from "./format.js";
import { ErrorCenter, ProfileManager, ResourceManager } from "./StudioTools.jsx";
import { LanguageWorkspace } from "./LanguageWorkspace.jsx";
import { VoiceStudio } from "./VoiceStudio.jsx";

const NAVIGATION = [
  {
    label: "Create",
    items: [
      { id: "narrate", label: "Narrate", icon: AudioLines, ready: true },
      { id: "library", label: "Library", icon: Library, ready: true },
      { id: "dialogue", label: "Dialogue", icon: MessageSquareText },
    ],
  },
  {
    label: "Edit",
    items: [
      { id: "timeline", label: "Timeline", icon: Scissors },
      { id: "audiogram", label: "Audiogram", icon: Clapperboard },
      { id: "publish", label: "Publish", icon: Upload },
    ],
  },
  {
    label: "Studio",
    items: [
      { id: "voices", label: "Voice studio", icon: Mic2, ready: true },
      { id: "pronunciation", label: "Pronunciation", icon: FileAudio, ready: true },
      { id: "components", label: "Components", icon: Boxes },
      { id: "convert", label: "Convert", icon: RefreshCw },
    ],
  },
];

const PACE = ["very_slow", "slow", "normal", "fast", "very_fast"];
const NONVERBAL = ["never", "rare", "occasional", "frequent", "very_frequent"];
const TERMINAL = new Set(["completed", "failed", "cancelled"]);

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
        <div className="chunk-inspector">
          <span>Chunk {selected.index + 1} · {selected.boundary}</span>
          <p>{selected.text}</p>
          <small>Characters {formatCount(selected.start_char)}–{formatCount(selected.end_char)}</small>
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
          {job.audio_url && <a href={job.audio_url} download><Download size={16} />Download WAV</a>}
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
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const refresh = async () => {
    setLoading(true);
    setError("");
    try { setProjects(await api.projects()); }
    catch (reason) { setError(reason.message); }
    finally { setLoading(false); }
  };

  useEffect(() => { refresh(); }, []);
  const visible = projects.filter((project) => {
    const haystack = `${project.name} ${project.source_name || ""} ${project.source_preview}`.toLowerCase();
    return haystack.includes(query.trim().toLowerCase());
  });

  const open = async (project) => {
    setError("");
    try { onOpen(await api.project(project.id)); }
    catch (reason) { setError(reason.message); }
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
        <span>{visible.length} of {projects.length} projects</span>
      </section>
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
                  <span><FileText size={20} /></span>
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

function NarrateWorkspace({ projectToLoad }) {
  const inputRef = useRef(null);
  const [providers, setProviders] = useState([]);
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
  const [form, setForm] = useState({
    text: "",
    provider: "",
    model: "",
    voice: "",
    instructions: "",
    split_strategy: "semantic",
    remove_numeric_citations: false,
    controls: { tone: "neutral", pace: "normal", vocal_style: "natural", nonverbal_frequency: "never" },
    variables: {},
    resource_revision: null,
  });

  const provider = providers.find((item) => item.name === form.provider) || providers[0];
  const stats = useMemo(() => textStats(form.text), [form.text]);
  const capabilities = provider?.capabilities || {};

  const patchForm = (values) => {
    setForm((current) => ({ ...current, ...values }));
    if ("text" in values || "provider" in values || "split_strategy" in values || "remove_numeric_citations" in values) setPreview(null);
  };
  const patchControls = (values) => setForm((current) => ({ ...current, controls: { ...current.controls, ...values } }));

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
    if (!projectToLoad) return;
    setForm((current) => ({ ...current, text: projectToLoad.source_text || "" }));
    setSourceName(projectToLoad.source_name || projectToLoad.name);
    setProjectName(projectToLoad.name);
    setPreview(null);
    setActiveChunk(0);
  }, [projectToLoad?.id]);

  useEffect(() => {
    if (!provider) return;
    const models = capabilities.models || [];
    const voices = capabilities.voices || [];
    const tones = capabilities.tone_presets || ["neutral"];
    const paces = capabilities.speech_paces || ["normal"];
    const styles = capabilities.vocal_styles || ["natural"];
    const nonverbals = capabilities.nonverbal_frequencies || ["never"];
    setForm((current) => ({
      ...current,
      provider: provider.name,
      model: models.includes(current.model) ? current.model : provider.default_model,
      voice: voices.some((item) => item.id === current.voice) ? current.voice : provider.default_voice,
      controls: {
        tone: tones.includes(current.controls.tone) ? current.controls.tone : tones[0],
        pace: paces.includes(current.controls.pace) ? current.controls.pace : paces[0],
        vocal_style: styles.includes(current.controls.vocal_style) ? current.controls.vocal_style : styles[0],
        nonverbal_frequency: nonverbals.includes(current.controls.nonverbal_frequency)
          ? current.controls.nonverbal_frequency
          : nonverbals[0],
      },
    }));
  }, [provider?.name]);

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
    instructions: form.instructions.trim() || null,
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
    instructions: form.instructions.trim() || null,
    controls: form.controls,
    split_strategy: form.split_strategy,
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
      instructions: profile.instructions || "",
      controls: profile.controls,
      split_strategy: profile.split_strategy,
      remove_numeric_citations: profile.remove_numeric_citations,
      variables: profile.variables || {},
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
      patchForm({ text: imported.text });
      setSourceName(imported.filename);
      setProjectName(imported.metadata.title || imported.filename.replace(/\.[^.]+$/, ""));
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
                  <option value="semantic">Semantic</option><option value="h1">Heading 1</option><option value="h2">Heading 2</option><option value="h3">Heading 3</option>
                  <option value="double_newline">Double newline</option><option value="newline">Every newline</option>
                </select>
              </Control>
              <label className="check-control"><input type="checkbox" checked={form.remove_numeric_citations} onChange={(event) => patchForm({ remove_numeric_citations: event.target.checked })} /><span><strong>Remove numeric citations</strong><small>[123] and \[123\]</small></span></label>
              <button className="secondary-button" disabled={!form.text.trim() || !!busy} onClick={previewChunks}><WandSparkles size={16} />{busy === "preview" ? "Planning…" : "Preview chunks"}</button>
            </div>
          </section>

          <ChunkPreview preview={preview} activeChunk={activeChunk} setActiveChunk={setActiveChunk} />

          <section className="surface direction-card">
            <div className="section-heading"><div><p className="eyebrow">02 · Performance</p><h2>Engine & direction</h2></div><SlidersHorizontal size={20} /></div>
            <div className="control-grid three">
              <Control label="Engine">
              <select value={form.provider} onChange={(event) => patchForm({ provider: event.target.value, resource_revision: null })}>{providers.map((item) => <option key={item.name} value={item.name}>{item.name}</option>)}</select>
              </Control>
              <Control label="Model"><input value={form.model} onChange={(event) => patchForm({ model: event.target.value })} list="studio-models" /><datalist id="studio-models">{(capabilities.models || []).map((item) => <option key={item} value={item} />)}</datalist></Control>
              <Control label="Voice">
                <select value={form.voice} onChange={(event) => patchForm({ voice: event.target.value })}>{(capabilities.voices || []).map((item) => <option key={item.id} value={item.id}>{item.id}{item.traits?.length ? ` · ${item.traits.join(", ")}` : ""}</option>)}</select>
              </Control>
            </div>
            <div className="control-grid two">
              <Control label="Emotion & tone"><select value={form.controls.tone} onChange={(event) => patchControls({ tone: event.target.value })}>{(capabilities.tone_presets || ["neutral"]).map((item) => <option key={item}>{item}</option>)}</select></Control>
              <Control label="Vocal style"><select value={form.controls.vocal_style} onChange={(event) => patchControls({ vocal_style: event.target.value })}>{(capabilities.vocal_styles || ["natural"]).map((item) => <option key={item}>{item}</option>)}</select></Control>
              <RangeControl label="Speaking pace" values={capabilities.speech_paces?.length ? capabilities.speech_paces : PACE} value={form.controls.pace} onChange={(value) => patchControls({ pace: value })} />
              <RangeControl label="Non-verbal sounds" values={capabilities.nonverbal_frequencies?.length ? capabilities.nonverbal_frequencies : NONVERBAL} value={form.controls.nonverbal_frequency} onChange={(value) => patchControls({ nonverbal_frequency: value })} />
              <Control label="Director's notes" wide help="Optional instructions are stored with the take."><textarea rows="3" value={form.instructions} maxLength="2000" onChange={(event) => patchForm({ instructions: event.target.value })} placeholder="Emphasize quotations and pause before each new section." /></Control>
            </div>
            <div className="render-row">
              <span><Sparkles size={16} />Chunks are checkpointed locally and resume safely.</span>
              <button className="primary-button" disabled={!form.text.trim() || !form.provider || !!busy} onClick={startJob}>{busy === "start" ? "Starting…" : "Start new take"}<ChevronRight size={17} /></button>
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
        <NarrateWorkspace projectToLoad={projectToLoad} />
      </div>
      {active === "library" && <LibraryWorkspace onOpen={openProject} />}
      {active === "pronunciation" && <LanguageWorkspace />}
      {active === "voices" && <VoiceStudio />}
      {active !== "narrate" && active !== "library" && active !== "pronunciation" && active !== "voices" && <WorkspacePlaceholder workspace={active} />}
      <ErrorCenter open={errorsOpen} onClose={() => setErrorsOpen(false)} onOpen={() => setErrorsOpen(true)} onUnreadChange={setUnreadErrors} />
    </Shell>
  );
}
