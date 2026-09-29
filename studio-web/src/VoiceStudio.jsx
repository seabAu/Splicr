import React, { useEffect, useMemo, useRef, useState } from "react";
import {
  AudioLines,
  ChevronRight,
  FileAudio,
  Library,
  Mic2,
  Pencil,
  Play,
  Plus,
  RefreshCw,
  Search,
  SlidersHorizontal,
  Trash2,
  Upload,
  Waves,
} from "lucide-react";

import { api } from "./api.js";
import { statusLabel } from "./format.js";

const EMPTY_CLONE = {
  label: "",
  engineId: "qwen3",
  referenceText: "",
  description: "",
  file: null,
};

const EMPTY_DESIGN = {
  label: "",
  description: "",
  take: 1,
};

const EMPTY_PRESET = {
  label: "",
  engine_id: "qwen3",
  voice_id: "",
  instructions: "",
  description: "",
};

function Notice({ message }) {
  if (!message?.text) return null;
  return <div className={`voice-notice ${message.error ? "error" : "success"}`}>{message.text}</div>;
}

function VoiceList({ voices, activeId, onSelect, query, setQuery }) {
  const visible = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return voices;
    return voices.filter((voice) =>
      `${voice.label} ${voice.description} ${voice.engine_id} ${voice.kind}`
        .toLowerCase()
        .includes(needle),
    );
  }, [voices, query]);

  return (
    <section className="voice-library surface">
      <div className="section-heading compact">
        <div><p className="eyebrow">Saved locally</p><h2>Voice library</h2></div>
        <span>{visible.length}</span>
      </div>
      <label className="voice-search">
        <Search size={16} />
        <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search voices…" />
      </label>
      <div className="voice-profile-list">
        {visible.map((voice) => (
          <button key={voice.id} className={activeId === voice.id ? "active" : ""} onClick={() => onSelect(voice.id)}>
            <span className={`voice-kind-mark kind-${voice.kind}`}><Mic2 size={16} /></span>
            <span>
              <strong>{voice.label}</strong>
              <small>{voice.engine_id} · {statusLabel(voice.kind)}</small>
            </span>
            <ChevronRight size={15} />
          </button>
        ))}
        {visible.length === 0 && (
          <div className="voice-empty"><Waves size={24} /><span>No matching voices.</span></div>
        )}
      </div>
    </section>
  );
}

function VoiceDetail({ voice, onSave, onDelete, onAnotherTake, busy }) {
  const [editing, setEditing] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [label, setLabel] = useState(voice?.label || "");
  const [description, setDescription] = useState(voice?.description || "");

  useEffect(() => {
    setEditing(false);
    setConfirming(false);
    setLabel(voice?.label || "");
    setDescription(voice?.description || "");
  }, [voice?.id]);

  if (!voice) {
    return (
      <section className="voice-detail surface voice-empty-detail">
        <AudioLines size={30} />
        <h2>Select a saved voice</h2>
        <p>Inspect its engine identity, reference recording, transcript, and reproducible settings.</p>
      </section>
    );
  }

  const save = async () => {
    if (!label.trim()) return;
    await onSave(voice.id, { label: label.trim(), description: description.trim() });
    setEditing(false);
  };

  return (
    <section className="voice-detail surface">
      <div className="voice-detail-heading">
        <span className={`voice-kind-mark large kind-${voice.kind}`}><Mic2 size={21} /></span>
        <div><p className="eyebrow">{voice.engine_id} · {statusLabel(voice.kind)}</p><h2>{voice.label}</h2></div>
        <button className="icon-button" onClick={() => setEditing((value) => !value)} aria-label="Edit voice"><Pencil size={16} /></button>
      </div>

      {editing ? (
        <div className="voice-edit-fields">
          <label><span>Display name</span><input value={label} onChange={(event) => setLabel(event.target.value)} /></label>
          <label><span>Description</span><textarea rows="3" value={description} onChange={(event) => setDescription(event.target.value)} /></label>
          <div><button className="primary-button small" disabled={busy || !label.trim()} onClick={save}>Save changes</button><button className="ghost-button small" onClick={() => setEditing(false)}>Cancel</button></div>
        </div>
      ) : (
        <p className="voice-description">{voice.description || "No additional description."}</p>
      )}

      {voice.has_reference && (
        <div className="voice-player">
          <span><Play size={16} /></span>
          <div><strong>Reference recording</strong><small>{voice.metadata.seconds ? `${voice.metadata.seconds}s` : "Saved audio"}</small></div>
          <audio controls preload="metadata" src={voice.reference_url} />
        </div>
      )}

      {voice.reference_text && (
        <div className="voice-transcript"><span>Exact reference transcript</span><p>{voice.reference_text}</p></div>
      )}

      <dl className="voice-facts">
        <div><dt>Engine</dt><dd>{voice.engine_id}</dd></div>
        <div><dt>Type</dt><dd>{statusLabel(voice.kind)}</dd></div>
        <div><dt>Storage</dt><dd>{voice.metadata.managed ? "Studio managed" : "External link"}</dd></div>
      </dl>

      {voice.kind === "preset" && (
        <div className="voice-preset-summary">
          <SlidersHorizontal size={17} />
          <div><strong>{voice.settings.voice_id || voice.settings.speaker}</strong><span>{voice.settings.instructions || "No saved direction"}</span></div>
        </div>
      )}

      {voice.kind === "designed" && (
        <div className="voice-preset-summary">
          <Waves size={17} />
          <div>
            <strong>Designed take {voice.settings.design_take || 1}</strong>
            <span>The saved reference and exact transcript keep this identity stable.</span>
          </div>
          <button className="secondary-button small" onClick={() => onAnotherTake(voice)}>
            Generate another take
          </button>
        </div>
      )}

      <div className="voice-delete-row">
        {confirming ? (
          <><span>{voice.metadata.managed ? "Delete this profile and its managed reference recording?" : "Remove this imported link? The original Narrator file stays untouched."}</span><button className="ghost-button small danger" disabled={busy} onClick={() => onDelete(voice.id)}>Confirm delete</button><button className="ghost-button small" onClick={() => setConfirming(false)}>Keep it</button></>
        ) : (
          <button className="text-button danger" onClick={() => setConfirming(true)}><Trash2 size={14} />Delete voice profile</button>
        )}
      </div>
    </section>
  );
}

function CreateVoice({
  onCreated,
  onDesignJob,
  onRetryDesign,
  onCancelDesign,
  designTemplate,
  activeDesignJob,
  busy,
  setBusy,
  setMessage,
}) {
  const fileRef = useRef(null);
  const [mode, setMode] = useState("clone");
  const [clone, setClone] = useState(EMPTY_CLONE);
  const [design, setDesign] = useState(EMPTY_DESIGN);
  const [preset, setPreset] = useState(EMPTY_PRESET);

  useEffect(() => {
    if (!designTemplate) return;
    setMode("design");
    setDesign(designTemplate);
  }, [designTemplate]);

  const submitDesign = async (event) => {
    event.preventDefault();
    setBusy("design");
    setMessage(null);
    try {
      const job = await api.createVoiceDesign({
        label: design.label.trim(),
        description: design.description.trim(),
        take: Number(design.take),
      });
      onDesignJob(job);
      setMessage({ text: "Voice design queued. You can leave this workspace while it runs." });
    } catch (error) {
      setMessage({ text: error.message, error: true });
    } finally {
      setBusy("");
    }
  };

  const submitClone = async (event) => {
    event.preventDefault();
    if (!clone.file) return setMessage({ text: "Choose a WAV recording first.", error: true });
    setBusy("clone");
    setMessage(null);
    try {
      const created = await api.createReferenceVoice(clone);
      setClone(EMPTY_CLONE);
      if (fileRef.current) fileRef.current.value = "";
      setMessage({ text: "Reference voice saved locally." });
      onCreated(created);
    } catch (error) {
      setMessage({ text: error.message, error: true });
    } finally {
      setBusy("");
    }
  };

  const submitPreset = async (event) => {
    event.preventDefault();
    setBusy("preset");
    setMessage(null);
    try {
      const created = await api.createVoicePreset(preset);
      setPreset(EMPTY_PRESET);
      setMessage({ text: "Voice preset saved." });
      onCreated(created);
    } catch (error) {
      setMessage({ text: error.message, error: true });
    } finally {
      setBusy("");
    }
  };

  return (
    <section className="voice-create surface">
      <div className="section-heading">
        <div><p className="eyebrow">New voice</p><h2>Build a reusable identity</h2></div>
        <Plus size={19} />
      </div>
      <div className="voice-mode-tabs">
        <button className={mode === "design" ? "active" : ""} onClick={() => setMode("design")}><Waves size={15} />Designed voice</button>
        <button className={mode === "clone" ? "active" : ""} onClick={() => setMode("clone")}><FileAudio size={15} />Reference clone</button>
        <button className={mode === "preset" ? "active" : ""} onClick={() => setMode("preset")}><SlidersHorizontal size={15} />Engine preset</button>
      </div>

      {mode === "design" ? (
        <form className="voice-create-form" onSubmit={submitDesign}>
          <p>Describe an identity once. Qwen VoiceDesign creates one managed reference recording, then narration clones that fixed voice across every chunk.</p>
          <div className="voice-fields two">
            <label><span>Name</span><input required value={design.label} onChange={(event) => setDesign({ ...design, label: event.target.value })} placeholder="Measured documentary narrator" /></label>
            <label><span>Take</span><input required type="number" min="1" max="99" step="1" value={design.take} onChange={(event) => setDesign({ ...design, take: Number(event.target.value) })} /></label>
          </div>
          <label><span>Voice description</span><textarea required rows="4" value={design.description} onChange={(event) => setDesign({ ...design, description: event.target.value })} placeholder="A warm, thoughtful alto voice with measured pacing and restrained emotion" /></label>
          <small className="control-help">The description and take define the identity. The resulting seed, reference WAV, and exact transcript are saved with the profile.</small>
          <button className="primary-button" disabled={!!busy || ["queued", "running", "cancel_requested"].includes(activeDesignJob?.status)}>{busy === "design" ? "Queueing design…" : "Design voice"}<ChevronRight size={16} /></button>
          {activeDesignJob && (
            <div className={`voice-design-status status-${activeDesignJob.status}`}>
              <div>
                <strong>{statusLabel(activeDesignJob.status)} · take {activeDesignJob.take}</strong>
                <span>{activeDesignJob.status === "running" ? "Qwen is creating the managed reference recording…" : activeDesignJob.status === "cancel_requested" ? "Stopping the isolated Qwen worker safely…" : activeDesignJob.status === "cancelled" ? "Cancelled without creating a voice profile. Any atomic result can be reused on retry." : activeDesignJob.error_detail || "The job is checkpointed locally."}</span>
              </div>
              <progress max="1" value={activeDesignJob.progress || 0} aria-label="Voice design progress" />
              {["queued", "running"].includes(activeDesignJob.status) && <button type="button" className="ghost-button small danger" onClick={() => onCancelDesign(activeDesignJob.id)}>Cancel design</button>}
              {activeDesignJob.status === "cancel_requested" && <button type="button" className="ghost-button small" disabled>Cancelling…</button>}
              {["failed", "cancelled"].includes(activeDesignJob.status) && <button type="button" className="secondary-button small" onClick={() => onRetryDesign(activeDesignJob.id)}>Retry</button>}
            </div>
          )}
        </form>
      ) : mode === "clone" ? (
        <form className="voice-create-form" onSubmit={submitClone}>
          <p>Store a clear recording and the exact words spoken. Qwen3 and Audio8 can use this pair for in-context voice cloning once their local runtimes are connected.</p>
          <div className="voice-fields two">
            <label><span>Name</span><input required value={clone.label} onChange={(event) => setClone({ ...clone, label: event.target.value })} placeholder="Warm essay narrator" /></label>
            <label><span>Engine</span><select value={clone.engineId} onChange={(event) => setClone({ ...clone, engineId: event.target.value })}><option value="qwen3">Qwen3-TTS</option><option value="audio8">Audio8</option></select></label>
          </div>
          <label className="voice-upload">
            <Upload size={20} />
            <span><strong>{clone.file?.name || "Choose a WAV recording"}</strong><small>{clone.engineId === "audio8" ? "At least 3 seconds" : "At least 2 seconds"} of clear speech</small></span>
            <input ref={fileRef} required type="file" accept="audio/wav,.wav" onChange={(event) => setClone({ ...clone, file: event.target.files?.[0] || null })} />
          </label>
          <label><span>Exact words spoken</span><textarea required rows="3" value={clone.referenceText} onChange={(event) => setClone({ ...clone, referenceText: event.target.value })} placeholder="Type the recording word for word…" /></label>
          <label><span>Voice description</span><input value={clone.description} onChange={(event) => setClone({ ...clone, description: event.target.value })} placeholder="Warm, thoughtful, measured" /></label>
          <button className="primary-button" disabled={!!busy}>{busy === "clone" ? "Saving recording…" : "Save reference voice"}<ChevronRight size={16} /></button>
        </form>
      ) : (
        <form className="voice-create-form" onSubmit={submitPreset}>
          <p>Save a built-in speaker plus its recurring direction as one reusable voice identity. This stores settings, not model weights.</p>
          <div className="voice-fields two">
            <label><span>Preset name</span><input required value={preset.label} onChange={(event) => setPreset({ ...preset, label: event.target.value })} placeholder="Bright announcer" /></label>
            <label><span>Engine ID</span><input required value={preset.engine_id} onChange={(event) => setPreset({ ...preset, engine_id: event.target.value })} /></label>
          </div>
          <label><span>Built-in speaker / voice ID</span><input required value={preset.voice_id} onChange={(event) => setPreset({ ...preset, voice_id: event.target.value })} placeholder="Ryan" /></label>
          <label><span>Recurring direction</span><textarea rows="3" value={preset.instructions} onChange={(event) => setPreset({ ...preset, instructions: event.target.value })} placeholder="Bright, concise, restrained enthusiasm" /></label>
          <label><span>Description</span><input value={preset.description} onChange={(event) => setPreset({ ...preset, description: event.target.value })} placeholder="Used for chapter intros" /></label>
          <button className="primary-button" disabled={!!busy}>{busy === "preset" ? "Saving preset…" : "Save engine preset"}<ChevronRight size={16} /></button>
        </form>
      )}
    </section>
  );
}

export function VoiceStudio() {
  const [voices, setVoices] = useState([]);
  const [selectedId, setSelectedId] = useState(null);
  const [query, setQuery] = useState("");
  const [busy, setBusy] = useState("");
  const [loading, setLoading] = useState(true);
  const [message, setMessage] = useState(null);
  const [activeDesignJob, setActiveDesignJob] = useState(null);
  const [designTemplate, setDesignTemplate] = useState(null);

  const selected = voices.find((voice) => voice.id === selectedId) || null;
  const refresh = async (preferredId = selectedId) => {
    setLoading(true);
    try {
      const [next, designJobs] = await Promise.all([api.voices(), api.voiceDesignJobs()]);
      setVoices(next);
      setSelectedId(next.some((voice) => voice.id === preferredId) ? preferredId : next[0]?.id || null);
      setActiveDesignJob(designJobs.find((job) => ["queued", "running", "cancel_requested", "failed", "cancelled"].includes(job.status)) || designJobs[0] || null);
    } catch (error) {
      setMessage({ text: error.message, error: true });
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { refresh(null); }, []);

  useEffect(() => {
    if (!activeDesignJob || !["queued", "running", "cancel_requested"].includes(activeDesignJob.status)) return undefined;
    const timer = window.setInterval(async () => {
      try {
        const current = await api.voiceDesignJob(activeDesignJob.id);
        setActiveDesignJob(current);
        if (current.status === "completed" && current.profile) {
          created(current.profile);
          setMessage({ text: `Designed ${current.profile.label} and saved its managed reference.` });
        } else if (current.status === "failed") {
          setMessage({ text: current.error_detail || "Voice design failed.", error: true });
        } else if (current.status === "cancelled") {
          setMessage({ text: "Voice design cancelled. No voice profile was created." });
        }
      } catch (error) {
        setMessage({ text: error.message, error: true });
      }
    }, 750);
    return () => window.clearInterval(timer);
  }, [activeDesignJob?.id, activeDesignJob?.status]);

  const save = async (id, payload) => {
    setBusy("save");
    setMessage(null);
    try {
      const changed = await api.updateVoice(id, payload);
      setVoices((current) => current.map((voice) => voice.id === id ? changed : voice));
      setMessage({ text: "Voice details updated." });
    } catch (error) {
      setMessage({ text: error.message, error: true });
    } finally {
      setBusy("");
    }
  };

  const remove = async (id) => {
    setBusy("delete");
    setMessage(null);
    try {
      await api.deleteVoice(id);
      const next = voices.filter((voice) => voice.id !== id);
      setVoices(next);
      setSelectedId(next[0]?.id || null);
      setMessage({ text: "Voice profile removed." });
    } catch (error) {
      setMessage({ text: error.message, error: true });
    } finally {
      setBusy("");
    }
  };

  const created = (profile) => {
    setVoices((current) => [profile, ...current.filter((voice) => voice.id !== profile.id)]);
    setSelectedId(profile.id);
  };

  const anotherTake = (voice) => {
    const related = voices.filter((candidate) =>
      candidate.kind === "designed" && candidate.description.trim() === voice.description.trim()
    );
    const take = Math.min(
      99,
      Math.max(...related.map((candidate) => Number(candidate.settings.design_take || 1)), 0) + 1,
    );
    setDesignTemplate({
      label: `${voice.label.replace(/ · take \d+$/i, "")} · take ${take}`,
      description: voice.description,
      take,
    });
    setMessage({ text: `Ready to generate take ${take} from the same description.` });
  };

  const retryDesign = async (jobId) => {
    setBusy("design-retry");
    setMessage(null);
    try {
      setActiveDesignJob(await api.retryVoiceDesign(jobId));
    } catch (error) {
      setMessage({ text: error.message, error: true });
    } finally {
      setBusy("");
    }
  };

  const cancelDesign = async (jobId) => {
    setBusy("design-cancel");
    setMessage(null);
    try {
      const job = await api.cancelVoiceDesign(jobId);
      setActiveDesignJob(job);
      setMessage({ text: job.status === "cancelled" ? "Voice design cancelled." : "Cancellation requested. The isolated Qwen worker is stopping safely." });
    } catch (error) {
      setMessage({ text: error.message, error: true });
    } finally {
      setBusy("");
    }
  };

  return (
    <main className="voice-workspace">
      <header className="workspace-header">
        <div><p className="eyebrow">Studio · Voices</p><h1>Keep every narrator reproducible and close at hand.</h1></div>
        <button className="secondary-button" onClick={() => refresh()} disabled={loading}><RefreshCw className={loading ? "spin" : ""} size={16} />Refresh</button>
      </header>
      <Notice message={message} />
      <div className="voice-workspace-grid">
        <VoiceList voices={voices} activeId={selectedId} onSelect={setSelectedId} query={query} setQuery={setQuery} />
        <div className="voice-main-stack">
          <VoiceDetail voice={selected} onSave={save} onDelete={remove} onAnotherTake={anotherTake} busy={busy} />
          <CreateVoice onCreated={created} onDesignJob={setActiveDesignJob} onRetryDesign={retryDesign} onCancelDesign={cancelDesign} designTemplate={designTemplate} activeDesignJob={activeDesignJob} busy={busy} setBusy={setBusy} setMessage={setMessage} />
          <div className="voice-runtime-note"><Library size={18} /><div><strong>Local engine boundary</strong><span>VoiceDesign runs as a durable job inside the configured Qwen environment; FastAPI never loads the model. Cloning and narration reuse the managed reference through isolated engine sessions.</span></div></div>
        </div>
      </div>
    </main>
  );
}
