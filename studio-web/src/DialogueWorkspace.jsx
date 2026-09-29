import { useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowLeftRight,
  Bot,
  LoaderCircle,
  MessageSquareText,
  Plus,
  Settings2,
  Sparkles,
  Trash2,
  UsersRound,
  WandSparkles,
} from "lucide-react";

import { api } from "./api.js";
import { formatCount, percent } from "./format.js";
import { ChatResourceManager } from "./StudioTools.jsx";

const TERMINAL = new Set(["completed", "failed", "cancelled"]);
const DEFAULT_CONTROLS = {
  tone: "neutral",
  pace: "normal",
  vocal_style: "natural",
  nonverbal_frequency: "never",
};
const DEFAULT_WRITER_OPTIONS = {
  host1_name: "Alex",
  host2_name: "Sam",
  host1_role: "explains the material clearly and with enthusiasm",
  host2_role: "asks the questions a smart newcomer would ask",
  style: "warm, curious and unhurried; plain language over jargon",
  words_per_section: 320,
  section_chars: 6000,
  max_sections: 40,
  temperature: 0.8,
};

function freshSpeaker() {
  return {
    model: "",
    voice: "",
    voice_profile_id: "",
    instructions: "",
    controls: { ...DEFAULT_CONTROLS },
    variables: {},
  };
}

function Control({ label, hint, children }) {
  return (
    <label className="control">
      <span>{label}</span>
      {children}
      {hint && <small>{hint}</small>}
    </label>
  );
}

function SpeakerCard({
  name,
  label,
  color,
  value,
  onChange,
  provider,
  voiceProfiles,
}) {
  const capabilities = provider?.capabilities || {};
  const engine = provider?.name === "qwen3-local"
    ? "qwen3"
    : provider?.name === "audio8-local"
      ? "audio8"
      : null;
  const profiles = engine
    ? voiceProfiles.filter((profile) => {
        const candidate = profile.engine_id.toLowerCase();
        return candidate === engine || candidate === `${engine}-local`;
      })
    : [];
  const selectedProfile = profiles.find((profile) => profile.id === value.voice_profile_id);
  const supportsNotes = Boolean(capabilities.supports_custom_instructions)
    && !(provider?.name === "qwen3-local" && selectedProfile?.kind !== "preset");
  const patch = (values) => onChange({ ...value, ...values });
  const patchControls = (values) => patch({ controls: { ...value.controls, ...values } });
  const options = (key, fallback) => capabilities[key]?.length ? capabilities[key] : fallback;

  return (
    <section className={`surface dialogue-speaker ${color}`}>
      <div className="dialogue-speaker-heading">
        <span className="speaker-orb">{name.slice(-1)}</span>
        <div>
          <p className="eyebrow">{name}</p>
          <h2>{label}</h2>
        </div>
      </div>
      <div className="dialogue-speaker-grid">
        {engine ? (
          <Control label="Voice profile" hint={profiles.length ? "Managed local voice" : "Create a matching voice in Voice Lab"}>
            <select
              value={value.voice_profile_id}
              onChange={(event) => patch({ voice_profile_id: event.target.value })}
            >
              <option value="">Select a voice…</option>
              {profiles.map((profile) => (
                <option key={profile.id} value={profile.id}>{profile.label}</option>
              ))}
            </select>
          </Control>
        ) : (
          <Control label="Voice">
            <select value={value.voice} onChange={(event) => patch({ voice: event.target.value })}>
              {(capabilities.voices || []).map((voice) => (
                <option key={voice.id} value={voice.id}>{voice.id}</option>
              ))}
            </select>
          </Control>
        )}
        <Control label="Model">
          <select value={value.model} onChange={(event) => patch({ model: event.target.value })}>
            {(capabilities.models || []).map((model) => <option key={model} value={model}>{model}</option>)}
          </select>
        </Control>
        <Control label="Tone">
          <select value={value.controls.tone} onChange={(event) => patchControls({ tone: event.target.value })}>
            {options("tone_presets", ["neutral"]).map((option) => <option key={option}>{option}</option>)}
          </select>
        </Control>
        <Control label="Pace">
          <select value={value.controls.pace} onChange={(event) => patchControls({ pace: event.target.value })}>
            {options("speech_paces", ["normal"]).map((option) => <option key={option}>{option}</option>)}
          </select>
        </Control>
        <Control label="Vocal style">
          <select value={value.controls.vocal_style} onChange={(event) => patchControls({ vocal_style: event.target.value })}>
            {options("vocal_styles", ["natural"]).map((option) => <option key={option}>{option}</option>)}
          </select>
        </Control>
        <Control label="Non-verbal cues">
          <select value={value.controls.nonverbal_frequency} onChange={(event) => patchControls({ nonverbal_frequency: event.target.value })}>
            {options("nonverbal_frequencies", ["never"]).map((option) => <option key={option}>{option}</option>)}
          </select>
        </Control>
      </div>
      <Control
        label="Director notes"
        hint={supportsNotes ? "Applied to every turn by this speaker" : "This voice does not accept custom directions"}
      >
        <textarea
          rows="2"
          value={value.instructions}
          disabled={!supportsNotes}
          placeholder="Warm, engaged, lightly conversational…"
          onChange={(event) => patch({ instructions: event.target.value })}
        />
      </Control>
    </section>
  );
}

function TurnEditor({ turn, index, onChange, onRemove, onRefine, canRemove, preview }) {
  const textArea = useRef(null);
  const refine = () => {
    const node = textArea.current;
    const start = node?.selectionStart ?? 0;
    const end = node?.selectionEnd ?? turn.text.length;
    onRefine({
      start: start === end ? 0 : start,
      end: start === end ? turn.text.length : end,
    });
  };
  return (
    <article className={`dialogue-turn ${turn.speaker === "Person1" ? "person-one" : "person-two"}`}>
      <div className="turn-rail">
        <span>{String(index + 1).padStart(2, "0")}</span>
        <i />
      </div>
      <div className="turn-body">
        <div className="turn-toolbar">
          <select
            aria-label={`Speaker for turn ${index + 1}`}
            value={turn.speaker}
            onChange={(event) => onChange({ ...turn, speaker: event.target.value })}
          >
            <option value="Person1">Person 1</option>
            <option value="Person2">Person 2</option>
          </select>
          <span className="turn-metrics">
            {formatCount(turn.text.length)} chars
            {preview ? ` · ${preview.chunks.length} chunk${preview.chunks.length === 1 ? "" : "s"}` : ""}
          </span>
          <div className="turn-actions">
            <button
              className="icon-button compact"
              type="button"
              disabled={!turn.text.trim()}
              onClick={refine}
              aria-label={`Refine turn ${index + 1}`}
              title="Refine selected text, or the whole turn"
            >
              <WandSparkles size={15} />
            </button>
            <button
              className="icon-button compact"
              type="button"
              disabled={!canRemove}
              onClick={onRemove}
              aria-label={`Remove turn ${index + 1}`}
            >
              <Trash2 size={15} />
            </button>
          </div>
        </div>
        <textarea
          ref={textArea}
          rows="3"
          value={turn.text}
          placeholder={turn.speaker === "Person1" ? "Opening, question, or response…" : "Reply…"}
          onChange={(event) => onChange({ ...turn, text: event.target.value })}
        />
      </div>
    </article>
  );
}

export function DialogueWorkspace({ active }) {
  const [providers, setProviders] = useState([]);
  const [voiceProfiles, setVoiceProfiles] = useState([]);
  const [chatResources, setChatResources] = useState([]);
  const [chatResourceId, setChatResourceId] = useState("");
  const [writerModel, setWriterModel] = useState("");
  const [sourceText, setSourceText] = useState("");
  const [writerOptions, setWriterOptions] = useState(DEFAULT_WRITER_OPTIONS);
  const [writerResult, setWriterResult] = useState(null);
  const [scriptJob, setScriptJob] = useState(null);
  const [chatConnectionsOpen, setChatConnectionsOpen] = useState(false);
  const [refineTarget, setRefineTarget] = useState(null);
  const [refineInstruction, setRefineInstruction] = useState("");
  const [providerId, setProviderId] = useState("");
  const [projectName, setProjectName] = useState("Untitled dialogue");
  const [turns, setTurns] = useState([
    { speaker: "Person1", text: "" },
    { speaker: "Person2", text: "" },
  ]);
  const [person1, setPerson1] = useState(freshSpeaker);
  const [person2, setPerson2] = useState(freshSpeaker);
  const [splitStrategy, setSplitStrategy] = useState("semantic");
  const [removeCitations, setRemoveCitations] = useState(false);
  const [preview, setPreview] = useState(null);
  const [job, setJob] = useState(null);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const appliedScriptResult = useRef("");
  const provider = providers.find((candidate) => candidate.name === providerId) || providers[0];
  const writerResource = chatResources.find((candidate) => candidate.resource_id === chatResourceId)
    || chatResources[0];
  const writerActive = Boolean(scriptJob && !TERMINAL.has(scriptJob.status));
  const isLocalProfileEngine = provider?.name === "qwen3-local" || provider?.name === "audio8-local";
  const transcriptStats = useMemo(() => {
    const text = turns.map((turn) => turn.text).join(" ").trim();
    return {
      chars: text.length,
      words: text ? text.split(/\s+/u).length : 0,
    };
  }, [turns]);

  const normalizeSpeaker = (current, selectedProvider) => {
    const capabilities = selectedProvider.capabilities || {};
    const models = capabilities.models || [];
    const voices = capabilities.voices || [];
    const values = (key, fallback) => capabilities[key]?.length ? capabilities[key] : fallback;
    return {
      ...current,
      model: models.includes(current.model) ? current.model : selectedProvider.default_model,
      voice: voices.some((voice) => voice.id === current.voice)
        ? current.voice
        : selectedProvider.default_voice,
      voice_profile_id: selectedProvider.name.endsWith("-local")
        ? current.voice_profile_id
        : "",
      controls: {
        tone: values("tone_presets", ["neutral"]).includes(current.controls.tone)
          ? current.controls.tone
          : values("tone_presets", ["neutral"])[0],
        pace: values("speech_paces", ["normal"]).includes(current.controls.pace)
          ? current.controls.pace
          : values("speech_paces", ["normal"])[0],
        vocal_style: values("vocal_styles", ["natural"]).includes(current.controls.vocal_style)
          ? current.controls.vocal_style
          : values("vocal_styles", ["natural"])[0],
        nonverbal_frequency: values("nonverbal_frequencies", ["never"]).includes(current.controls.nonverbal_frequency)
          ? current.controls.nonverbal_frequency
          : values("nonverbal_frequencies", ["never"])[0],
      },
    };
  };

  const refreshChatResources = async (preferred = chatResourceId) => {
    const rows = await api.chatResources();
    setChatResources(rows);
    const selected = rows.find((item) => item.resource_id === preferred) || rows[0];
    if (selected) setChatResourceId(selected.resource_id);
    return rows;
  };

  useEffect(() => {
    Promise.all([api.providers(), api.voices(), api.chatResources(), api.dialogueScriptJobs()])
      .then(([providerRows, voiceRows, chatRows, scriptRows]) => {
        setProviders(providerRows);
        setVoiceProfiles(voiceRows);
        setChatResources(chatRows);
        setScriptJob(scriptRows[0]?.status !== "completed" ? scriptRows[0] : null);
        if (providerRows.length) setProviderId((current) => current || providerRows[0].name);
        if (chatRows.length) setChatResourceId((current) => current || chatRows[0].resource_id);
      })
      .catch((reason) => setError(reason.message));
  }, []);

  useEffect(() => {
    if (!active) return;
    Promise.all([api.voices(), api.chatResources(), api.dialogueScriptJobs()])
      .then(([voiceRows, chatRows, scriptRows]) => {
        setVoiceProfiles(voiceRows);
        setChatResources(chatRows);
        setScriptJob((current) => (
          scriptRows.find((row) => row.id === current?.id)
          || (scriptRows[0]?.status !== "completed" ? scriptRows[0] : null)
          || current
        ));
      })
      .catch((reason) => setError(reason.message));
  }, [active]);

  useEffect(() => {
    if (!writerResource) return;
    setWriterModel((current) => (
      writerResource.models.includes(current) ? current : writerResource.default_model
    ));
  }, [writerResource?.resource_id, writerResource?.revision]);

  useEffect(() => {
    if (!provider) return;
    setPerson1((current) => normalizeSpeaker(current, provider));
    setPerson2((current) => normalizeSpeaker(current, provider));
    setPreview(null);
  }, [provider?.name]);

  useEffect(() => {
    if (!job || TERMINAL.has(job.status) || job.status === "paused") return undefined;
    const timer = window.setInterval(() => {
      api.job(job.id)
        .then(setJob)
        .catch((reason) => setError(reason.message));
    }, 750);
    return () => window.clearInterval(timer);
  }, [job?.id, job?.status]);

  useEffect(() => {
    if (!scriptJob || TERMINAL.has(scriptJob.status)) return undefined;
    const timer = window.setInterval(() => {
      api.dialogueScriptJob(scriptJob.id)
        .then(setScriptJob)
        .catch((reason) => setError(reason.message));
    }, 500);
    return () => window.clearInterval(timer);
  }, [scriptJob?.id, scriptJob?.status]);

  useEffect(() => {
    if (!scriptJob?.result || !TERMINAL.has(scriptJob.status)) return;
    const signature = `${scriptJob.id}:${scriptJob.status}:${scriptJob.updated_at}`;
    if (appliedScriptResult.current === signature) return;
    appliedScriptResult.current = signature;
    setTurns(scriptJob.result.turns);
    setPreview(null);
    setWriterResult(scriptJob.result);
    setRefineTarget(null);
  }, [scriptJob?.id, scriptJob?.status, scriptJob?.updated_at]);

  const changeTurns = (next) => {
    setTurns(next);
    setPreview(null);
  };
  const updateTurn = (index, value) => changeTurns(turns.map((turn, turnIndex) => (
    turnIndex === index ? value : turn
  )));
  const removeTurn = (index) => changeTurns(turns.filter((_, turnIndex) => turnIndex !== index));
  const addTurn = () => {
    const speaker = turns.at(-1)?.speaker === "Person1" ? "Person2" : "Person1";
    changeTurns([...turns, { speaker, text: "" }]);
  };
  const swapSpeakers = () => changeTurns(turns.map((turn) => ({
    ...turn,
    speaker: turn.speaker === "Person1" ? "Person2" : "Person1",
  })));

  const speakerPayload = (value) => ({
    model: value.model || null,
    voice: isLocalProfileEngine ? null : value.voice || null,
    voice_profile_id: isLocalProfileEngine ? value.voice_profile_id || null : null,
    instructions: value.instructions.trim() || null,
    controls: value.controls,
    variables: value.variables,
  });
  const payload = () => ({
    provider: provider?.name,
    project_name: projectName.trim() || "Untitled dialogue",
    export_name: projectName.trim() || "Untitled dialogue",
    turns: turns.map((turn) => ({ ...turn, text: turn.text.trim() })),
    person1: speakerPayload(person1),
    person2: speakerPayload(person2),
    split_strategy: splitStrategy,
    remove_numeric_citations: removeCitations,
  });
  const ready = Boolean(provider)
    && turns.length > 0
    && turns.every((turn) => turn.text.trim())
    && (!isLocalProfileEngine || (person1.voice_profile_id && person2.voice_profile_id));

  const run = async (label, operation) => {
    setBusy(label);
    setError("");
    try {
      return await operation();
    } catch (reason) {
      setError(reason.message);
      return null;
    } finally {
      setBusy("");
    }
  };
  const previewDialogue = async () => {
    const result = await run("preview", () => api.previewDialogue(payload()));
    if (result) setPreview(result);
  };
  const renderDialogue = async () => {
    const result = await run("render", () => api.createDialogueJob(payload()));
    if (result) setJob(result);
  };
  const actOnJob = async (action) => {
    if (!job) return;
    const result = await run(action, () => api.jobAction(job.id, action));
    if (result) setJob(result);
  };
  const exportSubtitles = async (format) => {
    if (!job) return;
    const result = await run(`subtitles-${format}`, () => api.exportJobSubtitles(job.id, format));
    if (result) window.location.assign(result.download_url);
  };
  const generateDialogue = async () => {
    if (!writerResource || !sourceText.trim()) return;
    const result = await run("generate", () => api.createDialogueScriptJob({
      text: sourceText,
      chat_resource_id: writerResource.resource_id,
      model: writerModel || null,
      options: writerOptions,
    }));
    if (!result) return;
    setScriptJob(result);
    setWriterResult(null);
    setRefineTarget(null);
  };
  const actOnScriptJob = async (action) => {
    if (!scriptJob) return;
    const result = await run(`script-${action}`, () => (
      api.dialogueScriptJobAction(scriptJob.id, action)
    ));
    if (result) setScriptJob(result);
  };
  const openRefinement = (index, range) => {
    setRefineTarget({ index, ...range });
    setRefineInstruction("");
  };
  const applyRefinement = async () => {
    if (!writerResource || !refineTarget || !refineInstruction.trim()) return;
    const turn = turns[refineTarget.index];
    if (!turn) return;
    const before = turn.text.slice(0, refineTarget.start);
    const selected = turn.text.slice(refineTarget.start, refineTarget.end);
    const after = turn.text.slice(refineTarget.end);
    const result = await run("refine", () => api.refineDialogueSelection({
      chat_resource_id: writerResource.resource_id,
      model: writerModel || null,
      before,
      selected,
      after,
      instruction: refineInstruction,
      speaker: turn.speaker,
      neighbor_before: turns[refineTarget.index - 1] || null,
      neighbor_after: turns[refineTarget.index + 1] || null,
    }));
    if (!result) return;
    updateTurn(refineTarget.index, {
      ...turn,
      text: `${before}${result.replacement}${after}`,
    });
    setRefineTarget(null);
    setRefineInstruction("");
  };

  return (
    <main className="dialogue-workspace">
      <header className="workspace-header dialogue-header">
        <div>
          <p className="eyebrow">Create · Dialogue</p>
          <h1>Shape a conversation, then render every voice as one continuous take.</h1>
        </div>
        <span className="local-pill"><i />Resumable render</span>
      </header>

      {error && <div className="inline-error" role="alert">{error}</div>}

      <section className="surface dialogue-setup">
        <div className="section-heading">
          <div><p className="eyebrow">01 · Cast</p><h2>Choose the engine and two voices</h2></div>
          <UsersRound size={20} />
        </div>
        <div className="dialogue-project-row">
          <Control label="Project name">
            <input value={projectName} onChange={(event) => setProjectName(event.target.value)} />
          </Control>
          <Control label="Engine">
            <select value={provider?.name || ""} onChange={(event) => setProviderId(event.target.value)}>
              {providers.map((item) => <option key={item.name} value={item.name}>{item.name}</option>)}
            </select>
          </Control>
          <Control label="Chunking">
            <select value={splitStrategy} onChange={(event) => { setSplitStrategy(event.target.value); setPreview(null); }}>
              <option value="semantic">Natural boundaries</option>
              <option value="double_newline">Double newline</option>
              <option value="newline">Every newline</option>
            </select>
          </Control>
          <label className="check-control dialogue-citation">
            <input type="checkbox" checked={removeCitations} onChange={(event) => { setRemoveCitations(event.target.checked); setPreview(null); }} />
            <span><strong>Remove citations</strong><small>[123] and \[123\]</small></span>
          </label>
        </div>
      </section>

      <div className="dialogue-cast-grid">
        <SpeakerCard name="Person1" label="Primary voice" color="person-one" value={person1} onChange={(value) => { setPerson1(value); setPreview(null); }} provider={provider} voiceProfiles={voiceProfiles} />
        <SpeakerCard name="Person2" label="Secondary voice" color="person-two" value={person2} onChange={(value) => { setPerson2(value); setPreview(null); }} provider={provider} voiceProfiles={voiceProfiles} />
      </div>

      <section className="surface dialogue-script">
        <div className="section-heading dialogue-script-heading">
          <div>
            <p className="eyebrow">02 · Script</p>
            <h2>Build the turn-by-turn performance</h2>
            <small>{formatCount(turns.length)} turns · {formatCount(transcriptStats.words)} words · {formatCount(transcriptStats.chars)} characters</small>
          </div>
          <div className="header-tools">
            <button className="secondary-button small" type="button" onClick={swapSpeakers}><ArrowLeftRight size={15} />Swap cast</button>
            <button className="secondary-button small" type="button" onClick={addTurn}><Plus size={15} />Add turn</button>
          </div>
        </div>
        <div className="dialogue-writer">
          <div className="dialogue-writer-heading">
            <div className="dialogue-writer-title">
              <span className="writer-icon"><Bot size={18} /></span>
              <div><strong>Draft from source material</strong><small>Outline-first writing with continuity and duplicate cleanup</small></div>
            </div>
            <button className="ghost-button small" type="button" onClick={() => setChatConnectionsOpen(true)}><Settings2 size={14} />Connections</button>
          </div>
          <div className="dialogue-writer-grid">
            <Control label="Writer connection" hint={writerResource?.local ? "Runs on this computer" : "Remote HTTPS provider"}>
              <select value={writerResource?.resource_id || ""} onChange={(event) => setChatResourceId(event.target.value)}>
                {chatResources.map((item) => <option key={item.resource_id} value={item.resource_id}>{item.name}</option>)}
              </select>
            </Control>
            <Control label="Writer model">
              <select value={writerModel} onChange={(event) => setWriterModel(event.target.value)}>
                {(writerResource?.models || []).map((model) => <option key={model} value={model}>{model}</option>)}
              </select>
            </Control>
            <Control label="Words per section">
              <input type="number" min="50" max="2000" value={writerOptions.words_per_section} onChange={(event) => setWriterOptions((current) => ({ ...current, words_per_section: Number(event.target.value) }))} />
            </Control>
          </div>
          <Control label="Source document" hint="Paste or import source text here; the generated turns remain fully editable.">
            <textarea rows="8" value={sourceText} onChange={(event) => setSourceText(event.target.value)} placeholder="Paste the document, article, notes, or chapter to adapt into dialogue..." />
          </Control>
          <details className="dialogue-writer-options">
            <summary>Hosts and writing direction</summary>
            <div className="dialogue-writer-options-grid">
              <Control label="Host 1 name"><input value={writerOptions.host1_name} onChange={(event) => setWriterOptions((current) => ({ ...current, host1_name: event.target.value }))} /></Control>
              <Control label="Host 2 name"><input value={writerOptions.host2_name} onChange={(event) => setWriterOptions((current) => ({ ...current, host2_name: event.target.value }))} /></Control>
              <Control label="Host 1 role"><textarea rows="2" value={writerOptions.host1_role} onChange={(event) => setWriterOptions((current) => ({ ...current, host1_role: event.target.value }))} /></Control>
              <Control label="Host 2 role"><textarea rows="2" value={writerOptions.host2_role} onChange={(event) => setWriterOptions((current) => ({ ...current, host2_role: event.target.value }))} /></Control>
              <Control label="Conversation style"><textarea rows="2" value={writerOptions.style} onChange={(event) => setWriterOptions((current) => ({ ...current, style: event.target.value }))} /></Control>
              <Control label="Creativity" hint={writerOptions.temperature.toFixed(1)}><input type="range" min="0" max="2" step="0.1" value={writerOptions.temperature} onChange={(event) => setWriterOptions((current) => ({ ...current, temperature: Number(event.target.value) }))} /></Control>
            </div>
          </details>
          {scriptJob && (
            <div className={`dialogue-writer-progress status-${scriptJob.status}`}>
              <div className="dialogue-writer-progress-heading">
                <div>
                  <strong>{scriptJob.status === "completed" ? "Script ready" : scriptJob.status.replaceAll("_", " ")}</strong>
                  <span>{formatCount(scriptJob.completed_sections)} of {formatCount(scriptJob.total_sections)} sections</span>
                </div>
                <span>{percent(scriptJob.progress)}</span>
              </div>
              <progress max="1" value={scriptJob.progress} aria-label="Dialogue writing progress" />
              <small>{scriptJob.error_detail || scriptJob.progress_message}</small>
              <div className="dialogue-writer-progress-actions">
                {writerActive && scriptJob.status !== "cancel_requested" && (
                  <button className="ghost-button small danger" type="button" disabled={!!busy} onClick={() => actOnScriptJob("cancel")}>Cancel writing</button>
                )}
                {["cancelled", "failed"].includes(scriptJob.status) && scriptJob.completed_sections < scriptJob.total_sections && (
                  <button className="secondary-button small" type="button" disabled={!!busy} onClick={() => actOnScriptJob("resume")}>Resume from checkpoint</button>
                )}
              </div>
            </div>
          )}
          <div className="dialogue-writer-actions">
            {writerResult && <span>{formatCount(writerResult.sections)} sections · {formatCount(writerResult.word_count)} words · {formatCount(writerResult.removed_duplicates)} duplicates removed</span>}
            <button className="primary-button" type="button" disabled={!writerResource || !sourceText.trim() || !!busy || writerActive} onClick={generateDialogue}>
              {busy === "generate" ? <LoaderCircle className="spin" size={16} /> : <WandSparkles size={16} />}
              {busy === "generate" ? "Queueing writer…" : writerActive ? "Writing dialogue…" : "Generate script"}
            </button>
          </div>
        </div>
        <div className="dialogue-turns">
          {turns.map((turn, index) => (
            <TurnEditor
              key={index}
              turn={turn}
              index={index}
              preview={preview?.turns[index]}
              canRemove={turns.length > 1}
              onChange={(value) => updateTurn(index, value)}
              onRemove={() => removeTurn(index)}
              onRefine={(range) => openRefinement(index, range)}
            />
          ))}
        </div>
        {refineTarget && turns[refineTarget.index] && (
          <div className="dialogue-refine">
            <div><p className="eyebrow">Refine turn {refineTarget.index + 1}</p><strong>“{turns[refineTarget.index].text.slice(refineTarget.start, refineTarget.end)}”</strong></div>
            <input autoFocus value={refineInstruction} onChange={(event) => setRefineInstruction(event.target.value)} onKeyDown={(event) => event.key === "Enter" && applyRefinement()} placeholder="Make it clearer, warmer, shorter..." />
            <button className="secondary-button small" type="button" onClick={() => setRefineTarget(null)}>Cancel</button>
            <button className="primary-button small" type="button" disabled={!refineInstruction.trim() || !!busy} onClick={applyRefinement}>{busy === "refine" ? <LoaderCircle className="spin" size={14} /> : <Sparkles size={14} />}{busy === "refine" ? "Refining…" : "Apply"}</button>
          </div>
        )}
        <button className="dialogue-add-turn" type="button" onClick={addTurn}><Plus size={16} />Add another turn</button>
      </section>

      <section className="surface dialogue-render">
        <div className="section-heading">
          <div><p className="eyebrow">03 · Render</p><h2>Preflight and create the take</h2></div>
          <MessageSquareText size={20} />
        </div>
        {preview ? (
          <div className="dialogue-preview-summary">
            <span><strong>{formatCount(preview.total_turns)}</strong> turns</span>
            <span><strong>{formatCount(preview.total_chunks)}</strong> audio chunks</span>
            <span><strong>{formatCount(preview.total_words)}</strong> words</span>
            <span><strong>{formatCount(preview.total_bytes)}</strong> UTF-8 bytes</span>
          </div>
        ) : (
          <p className="dialogue-preflight-empty">Preview validates both voices and shows the exact chunk count before any synthesis begins.</p>
        )}
        <div className="dialogue-render-actions">
          <button className="secondary-button" disabled={!ready || !!busy} onClick={previewDialogue}>
            {busy === "preview" ? <LoaderCircle className="spin" size={16} /> : <WandSparkles size={16} />}
            {busy === "preview" ? "Checking…" : "Preview render"}
          </button>
          <button className="primary-button" disabled={!ready || !!busy} onClick={renderDialogue}>
            {busy === "render" ? <LoaderCircle className="spin" size={16} /> : <Sparkles size={16} />}
            {busy === "render" ? "Starting…" : "Render dialogue"}
          </button>
        </div>

        {job && (
          <div className="dialogue-job">
            <div className="dialogue-job-heading">
              <div><strong>{job.status.replaceAll("_", " ")}</strong><small>{job.completed_chunks} of {job.total_chunks} chunks</small></div>
              <span>{percent(job.progress)}</span>
            </div>
            <div className="progress-track"><i style={{ width: percent(job.progress) }} /></div>
            {job.current_excerpt && <p className="dialogue-current-line">“{job.current_excerpt}”</p>}
            <div className="dialogue-job-actions">
              {job.status === "running" && <button className="secondary-button small" onClick={() => actOnJob("pause")}>Pause</button>}
              {job.status === "paused" && <button className="secondary-button small" onClick={() => actOnJob("resume")}>Resume</button>}
              {!TERMINAL.has(job.status) && <button className="secondary-button small danger" onClick={() => actOnJob("cancel")}>Cancel</button>}
            </div>
            {(job.audio_url || job.partial_audio_url) && (
              <div className="dialogue-player-stack">
                <audio className="dialogue-player" controls preload="metadata" src={job.audio_url || job.partial_audio_url} />
                {job.audio_url && <a href={job.audio_url} download={job.download_filename}>Download master WAV</a>}
                {job.checkpoint_export_url && (
                  <a href={job.checkpoint_export_url} download>
                    {job.status === "completed" ? "Export checkpoint WAVs + manifest" : "Export completed checkpoints (partial)"}
                  </a>
                )}
                {job.completed_chunks > 0 && (
                  <details className="job-caption-export">
                    <summary>Export captions</summary>
                    <button type="button" disabled={!!busy} onClick={() => exportSubtitles("srt")}>{busy === "subtitles-srt" ? "Exporting…" : "SRT"}</button>
                    <button type="button" disabled={!!busy} onClick={() => exportSubtitles("vtt")}>{busy === "subtitles-vtt" ? "Exporting…" : "WebVTT"}</button>
                  </details>
                )}
              </div>
            )}
          </div>
        )}
      </section>
      <ChatResourceManager
        open={chatConnectionsOpen}
        onClose={() => setChatConnectionsOpen(false)}
        onChanged={refreshChatResources}
      />
    </main>
  );
}
