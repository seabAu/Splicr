import React, { useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  CheckCheck,
  Eye,
  EyeOff,
  KeyRound,
  Plus,
  RefreshCw,
  Save,
  Trash2,
  X,
} from "lucide-react";

import { api } from "./api.js";
import { statusLabel } from "./format.js";

function Modal({ open, onClose, eyebrow, title, wide = false, children }) {
  useEffect(() => {
    if (!open) return undefined;
    const closeOnEscape = (event) => event.key === "Escape" && onClose();
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="studio-modal-backdrop" role="presentation" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
      <section className={`studio-modal${wide ? " studio-modal-wide" : ""}`} role="dialog" aria-modal="true" aria-label={title}>
        <header>
          <div><p className="eyebrow">{eyebrow}</p><h2>{title}</h2></div>
          <button className="icon-button" onClick={onClose} aria-label="Close"><X size={18} /></button>
        </header>
        {children}
      </section>
    </div>
  );
}

function InlineNotice({ error, message }) {
  if (!error && !message) return null;
  return <div className={error ? "tool-notice error" : "tool-notice"} role={error ? "alert" : "status"}>{error || message}</div>;
}

export function ProfileManager({ open, onClose, buildPayload, onLoad }) {
  const [profiles, setProfiles] = useState([]);
  const [name, setName] = useState("");
  const [includeJob, setIncludeJob] = useState(true);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  const refresh = async () => {
    setBusy("refresh");
    setError("");
    try { setProfiles(await api.profiles()); }
    catch (reason) { setError(reason.message); }
    finally { setBusy(""); }
  };

  useEffect(() => { if (open) refresh(); }, [open]);

  const save = async (event) => {
    event.preventDefault();
    setBusy("save");
    setError("");
    setMessage("");
    try {
      const saved = await api.createProfile(buildPayload(name.trim(), includeJob));
      setProfiles((current) => [saved, ...current]);
      setName("");
      setMessage(`Saved ${saved.name}.`);
    } catch (reason) { setError(reason.message); }
    finally { setBusy(""); }
  };

  const load = (profile) => {
    onLoad(profile);
    setMessage(`Loaded ${profile.name}.`);
    onClose();
  };

  const remove = async (profile) => {
    setBusy(profile.id);
    setError("");
    try {
      await api.deleteProfile(profile.id);
      setProfiles((current) => current.filter((item) => item.id !== profile.id));
    } catch (reason) { setError(reason.message); }
    finally { setBusy(""); }
  };

  return (
    <Modal open={open} onClose={onClose} eyebrow="Workspace presets" title="Profiles">
      <p className="modal-intro">Save the document, engine revision, delivery controls, custom variables, and optionally the current resumable take.</p>
      <InlineNotice error={error} message={message} />
      <form className="profile-create-row" onSubmit={save}>
        <label><span>Profile name</span><input required maxLength="100" value={name} onChange={(event) => setName(event.target.value)} placeholder="Warm documentary read" /></label>
        <label className="check-row"><input type="checkbox" checked={includeJob} onChange={(event) => setIncludeJob(event.target.checked)} />Include current take</label>
        <button className="primary-button small" disabled={busy === "save" || !name.trim()}><Save size={15} />Save profile</button>
      </form>
      <div className="tool-list-heading"><strong>Saved profiles</strong><button className="text-button" onClick={refresh} disabled={!!busy}><RefreshCw size={14} />Refresh</button></div>
      <div className="profile-tool-list">
        {!profiles.length && !busy && <p className="muted">No profiles saved yet.</p>}
        {profiles.map((profile) => (
          <article key={profile.id}>
            <div><strong>{profile.name}</strong><span>{profile.resource_id} · {profile.voice || "default voice"}</span><small>{profile.job_id ? "Includes a resumable take" : "Settings and source only"}</small></div>
            <div><button className="secondary-button small" onClick={() => load(profile)}>Load</button><button className="icon-button danger" onClick={() => remove(profile)} disabled={busy === profile.id} aria-label={`Delete ${profile.name}`}><Trash2 size={15} /></button></div>
          </article>
        ))}
      </div>
    </Modal>
  );
}

const EMPTY_RESOURCE = {
  id: "",
  name: "",
  adapter: "generic_rest",
  base_url: "",
  method: "POST",
  default_model: "",
  default_voice: "",
  auth_placement: "header",
  auth_name: "Authorization",
  auth_prefix: "Bearer ",
  api_key: "",
  clear_api_key: false,
  allow_insecure_http: false,
  auth_env_keys: "[]",
  headers: "{}",
  query: "{}",
  default_variables: "{}",
  variable_definitions: "[]",
  request_template: "{\n  \"text\": \"{{text}}\"\n}",
  models: "[]",
  voices: "[]",
  capabilities: "{}",
  max_input_bytes: "",
  max_input_characters: "",
  max_input_tokens: "",
  max_input_words: "",
  recommended_chunk_bytes: "",
  recommended_chunk_characters: "",
  recommended_chunk_words: "",
  limit_basis: "text",
  minimum_request_interval_seconds: "0",
  requests_per_minute: "",
  max_concurrency: "1",
  request_timeout_seconds: "300",
  retry_max_attempts: "3",
  retry_backoff_initial_seconds: "1",
  retry_backoff_max_seconds: "30",
  retry_jitter_seconds: "0.25",
  retry_status_codes: "[408, 409, 425, 429, 500, 502, 503, 504]",
  honor_retry_after: true,
  response_mode: "raw_pcm",
  audio_json_pointer: "",
  response_sample_rate_hz: "24000",
  response_channels: "1",
  response_sample_width_bytes: "2",
};

const pretty = (value, fallback) => JSON.stringify(value ?? fallback, null, 2);
const optionalNumber = (value) => value === "" ? null : Number(value);

function resourceForm(resource) {
  if (!resource) return { ...EMPTY_RESOURCE };
  return {
    ...EMPTY_RESOURCE,
    id: resource.id || resource.resource_id || "",
    name: resource.name || "",
    adapter: resource.adapter || resource.adapter_type || "generic_rest",
    base_url: resource.base_url || "",
    method: resource.method || "POST",
    default_model: resource.default_model || "",
    default_voice: resource.default_voice || "",
    auth_placement: resource.auth_placement || "header",
    auth_name: resource.auth_name || "Authorization",
    auth_prefix: resource.auth_prefix ?? "Bearer ",
    api_key: "",
    clear_api_key: false,
    allow_insecure_http: resource.allow_insecure_http || false,
    auth_env_keys: pretty(resource.auth_env_keys, []),
    headers: pretty(resource.headers, {}),
    query: pretty(resource.query, {}),
    default_variables: pretty(resource.default_variables ?? resource.variables, {}),
    variable_definitions: pretty(resource.variable_definitions, []),
    request_template: pretty(resource.request_template, {}),
    models: pretty(resource.models, []),
    voices: pretty(resource.voices, []),
    capabilities: pretty(resource.capabilities, {}),
    max_input_bytes: resource.max_input_bytes ?? "",
    max_input_characters: resource.max_input_characters ?? "",
    max_input_tokens: resource.max_input_tokens ?? "",
    max_input_words: resource.max_input_words ?? "",
    recommended_chunk_bytes: resource.recommended_chunk_bytes ?? "",
    recommended_chunk_characters: resource.recommended_chunk_characters ?? "",
    recommended_chunk_words: resource.recommended_chunk_words ?? "",
    limit_basis: resource.limit_basis || "text",
    minimum_request_interval_seconds: resource.minimum_request_interval_seconds ?? "0",
    requests_per_minute: resource.requests_per_minute ?? "",
    max_concurrency: resource.max_concurrency ?? "1",
    request_timeout_seconds: resource.request_timeout_seconds ?? "300",
    retry_max_attempts: resource.retry_max_attempts ?? "3",
    retry_backoff_initial_seconds: resource.retry_backoff_initial_seconds ?? "1",
    retry_backoff_max_seconds: resource.retry_backoff_max_seconds ?? "30",
    retry_jitter_seconds: resource.retry_jitter_seconds ?? "0.25",
    retry_status_codes: pretty(resource.retry_status_codes, [408, 409, 425, 429, 500, 502, 503, 504]),
    honor_retry_after: resource.honor_retry_after ?? true,
    response_mode: resource.response_mode || "raw_pcm",
    audio_json_pointer: resource.audio_json_pointer || "",
    response_sample_rate_hz: resource.response_sample_rate_hz ?? "24000",
    response_channels: resource.response_channels ?? "1",
    response_sample_width_bytes: resource.response_sample_width_bytes ?? "2",
    revision: resource.revision,
    has_api_key: resource.has_api_key,
    api_key_source: resource.api_key_source,
  };
}

function parseJson(value, label, expected) {
  let parsed;
  try { parsed = JSON.parse(value || (expected === "array" ? "[]" : "{}")); }
  catch (error) { throw new Error(`${label} is not valid JSON: ${error.message}`); }
  if (expected === "array" ? !Array.isArray(parsed) : !parsed || Array.isArray(parsed) || typeof parsed !== "object") {
    throw new Error(`${label} must be a JSON ${expected}.`);
  }
  return parsed;
}

export function ResourceManager({ open, onClose, onChanged }) {
  const [resources, setResources] = useState([]);
  const [editingId, setEditingId] = useState(null);
  const [form, setForm] = useState({ ...EMPTY_RESOURCE });
  const [showKey, setShowKey] = useState(false);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [confirmDelete, setConfirmDelete] = useState(false);

  const patch = (values) => setForm((current) => ({ ...current, ...values }));
  const refresh = async (preferred = editingId) => {
    setBusy("refresh");
    setError("");
    try {
      const rows = await api.resources();
      setResources(rows);
      const chosen = rows.find((item) => (item.id || item.resource_id) === preferred);
      if (chosen) {
        const detail = await api.resource(chosen.id || chosen.resource_id);
        setEditingId(chosen.id || chosen.resource_id);
        setForm(resourceForm(detail));
      } else if (!editingId) {
        setForm({ ...EMPTY_RESOURCE });
      }
    } catch (reason) { setError(reason.message); }
    finally { setBusy(""); }
  };

  useEffect(() => { if (open) refresh(null); }, [open]);
  useEffect(() => {
    if (!showKey) return undefined;
    const timer = window.setTimeout(() => setShowKey(false), 15000);
    return () => window.clearTimeout(timer);
  }, [showKey]);
  useEffect(() => { if (!open) setShowKey(false); }, [open]);

  const choose = async (id) => {
    setBusy("detail");
    setError("");
    try {
      const detail = await api.resource(id);
      setEditingId(id);
      setForm(resourceForm(detail));
      setShowKey(false);
      setConfirmDelete(false);
    } catch (reason) { setError(reason.message); }
    finally { setBusy(""); }
  };

  const beginNew = () => {
    setEditingId(null);
    setForm({ ...EMPTY_RESOURCE });
    setError("");
    setMessage("");
    setConfirmDelete(false);
  };

  const payload = () => {
    const value = {
      id: form.id.trim(),
      name: form.name.trim(),
      adapter: form.adapter,
      base_url: form.base_url.trim() || null,
      method: form.method,
      default_model: form.default_model.trim() || null,
      default_voice: form.default_voice.trim() || null,
      auth_placement: form.auth_placement,
      auth_name: form.auth_name.trim() || null,
      auth_prefix: form.auth_prefix,
      auth_env_keys: parseJson(form.auth_env_keys, "Environment key names", "array"),
      allow_insecure_http: form.allow_insecure_http,
      headers: parseJson(form.headers, "Headers", "object"),
      query: parseJson(form.query, "Query parameters", "object"),
      default_variables: parseJson(form.default_variables, "Default variables", "object"),
      variable_definitions: parseJson(form.variable_definitions, "Variable definitions", "array"),
      request_template: parseJson(form.request_template, "Request template", "object"),
      models: parseJson(form.models, "Models", "array"),
      voices: parseJson(form.voices, "Voices", "array"),
      capabilities: parseJson(form.capabilities, "Capabilities", "object"),
      max_input_bytes: optionalNumber(form.max_input_bytes),
      max_input_characters: optionalNumber(form.max_input_characters),
      max_input_tokens: optionalNumber(form.max_input_tokens),
      max_input_words: optionalNumber(form.max_input_words),
      recommended_chunk_bytes: optionalNumber(form.recommended_chunk_bytes),
      recommended_chunk_characters: optionalNumber(form.recommended_chunk_characters),
      recommended_chunk_words: optionalNumber(form.recommended_chunk_words),
      limit_basis: form.limit_basis,
      minimum_request_interval_seconds: optionalNumber(form.minimum_request_interval_seconds),
      requests_per_minute: optionalNumber(form.requests_per_minute),
      max_concurrency: optionalNumber(form.max_concurrency),
      request_timeout_seconds: optionalNumber(form.request_timeout_seconds),
      retry_max_attempts: optionalNumber(form.retry_max_attempts),
      retry_backoff_initial_seconds: optionalNumber(form.retry_backoff_initial_seconds),
      retry_backoff_max_seconds: optionalNumber(form.retry_backoff_max_seconds),
      retry_jitter_seconds: optionalNumber(form.retry_jitter_seconds),
      retry_status_codes: parseJson(form.retry_status_codes, "Retry status codes", "array"),
      honor_retry_after: form.honor_retry_after,
      response_mode: form.response_mode,
      audio_json_pointer: form.audio_json_pointer.trim() || null,
      response_sample_rate_hz: optionalNumber(form.response_sample_rate_hz),
      response_channels: optionalNumber(form.response_channels),
      response_sample_width_bytes: optionalNumber(form.response_sample_width_bytes),
    };
    if (editingId) value.revision = form.revision;
    if (form.clear_api_key) value.clear_api_key = true;
    else if (form.api_key) value.api_key = form.api_key;
    return value;
  };

  const save = async (event) => {
    event.preventDefault();
    setBusy("save");
    setError("");
    setMessage("");
    try {
      const value = payload();
      const saved = editingId
        ? await api.updateResource(editingId, value)
        : await api.createResource(value);
      const id = saved.id || saved.resource_id;
      setEditingId(id);
      setForm(resourceForm(saved));
      setMessage(`${saved.name} is ready.`);
      await refresh(id);
      await onChanged(id);
    } catch (reason) { setError(reason.message); }
    finally { setBusy(""); }
  };

  const remove = async () => {
    if (!editingId) return;
    if (!confirmDelete) {
      setConfirmDelete(true);
      setMessage("Click confirm delete to remove this resource from new jobs. Existing jobs keep their saved revision.");
      return;
    }
    setBusy("delete");
    setError("");
    try {
      await api.deleteResource(editingId);
      beginNew();
      await refresh(null);
      await onChanged(null);
    } catch (reason) { setError(reason.message); }
    finally { setBusy(""); }
  };

  const jsonField = (key, label, rows = 5) => (
    <label className="resource-json-field"><span>{label}</span><textarea rows={rows} spellCheck="false" value={form[key]} onChange={(event) => patch({ [key]: event.target.value })} /></label>
  );

  return (
    <Modal open={open} onClose={onClose} eyebrow="Engine connections" title="API resources" wide>
      <p className="modal-intro">Versioned endpoint definitions keep remote engines modular. Secrets are write-only, encrypted locally, and hidden again after 15 seconds.</p>
      <InlineNotice error={error} message={message} />
      <div className="resource-editor-layout">
        <aside className="resource-list">
          <button className={!editingId ? "active" : ""} onClick={beginNew}><Plus size={15} /><span><strong>New resource</strong><small>Custom endpoint</small></span></button>
          {resources.map((resource) => {
            const id = resource.id || resource.resource_id;
            return <button className={editingId === id ? "active" : ""} key={id} onClick={() => choose(id)}><span><strong>{resource.name}</strong><small>{id} · r{resource.revision}</small></span></button>;
          })}
        </aside>
        <form className="resource-form" onSubmit={save}>
          <div className="resource-section-heading"><div><strong>{editingId ? "Edit connection" : "Add connection"}</strong><span>Every save creates an immutable revision.</span></div>{editingId && <button type="button" className="ghost-button small danger" onClick={remove} disabled={busy === "delete"}><Trash2 size={14} />{confirmDelete ? "Confirm delete" : "Delete"}</button>}</div>
          <div className="resource-fields three">
            <label><span>ID</span><input required pattern="[a-z][a-z0-9._-]*" disabled={!!editingId} value={form.id} onChange={(event) => patch({ id: event.target.value })} /></label>
            <label><span>Name</span><input required value={form.name} onChange={(event) => patch({ name: event.target.value })} /></label>
            <label><span>Adapter</span><select value={form.adapter} onChange={(event) => patch({ adapter: event.target.value })}><option value="generic_rest">Generic JSON</option><option value="gemini">Gemini</option><option value="deepgram">Deepgram</option><option value="inworld">Inworld</option></select></label>
            <label className="span-two"><span>Base URL</span><input value={form.base_url} onChange={(event) => patch({ base_url: event.target.value })} placeholder="https://api.example.com/v1/tts" /></label>
            <label><span>Method</span><select value={form.method} onChange={(event) => patch({ method: event.target.value })}><option>GET</option><option>POST</option><option>PUT</option><option>PATCH</option></select></label>
            <label className="check-row"><input type="checkbox" checked={form.allow_insecure_http} onChange={(event) => patch({ allow_insecure_http: event.target.checked })} />Allow HTTP for loopback/local endpoints</label>
            <label><span>Default model</span><input value={form.default_model} onChange={(event) => patch({ default_model: event.target.value })} /></label>
            <label><span>Default voice</span><input value={form.default_voice} onChange={(event) => patch({ default_voice: event.target.value })} /></label>
          </div>

          <details open><summary>Authentication</summary><div className="resource-fields three">
            <label><span>Placement</span><select value={form.auth_placement} onChange={(event) => patch({ auth_placement: event.target.value })}><option value="header">Header</option><option value="query">Query parameter</option><option value="template">Request template</option><option value="none">None</option></select></label>
            <label><span>Name</span><input value={form.auth_name} onChange={(event) => patch({ auth_name: event.target.value })} /></label>
            <label><span>Prefix</span><input value={form.auth_prefix} onChange={(event) => patch({ auth_prefix: event.target.value })} /></label>
            <label className="span-two"><span>API key {form.has_api_key && <small>Stored via {form.api_key_source}</small>}</span><div className="secret-input"><KeyRound size={15} /><input type={showKey ? "text" : "password"} value={form.api_key} onChange={(event) => patch({ api_key: event.target.value, clear_api_key: false })} placeholder={form.has_api_key ? "Leave blank to keep stored key" : "Enter API key"} autoComplete="new-password" /><button type="button" onClick={() => setShowKey((value) => !value)} aria-label={showKey ? "Hide API key" : "Show API key"}>{showKey ? <EyeOff size={16} /> : <Eye size={16} />}</button></div></label>
            <label className="check-row"><input type="checkbox" checked={form.clear_api_key} onChange={(event) => patch({ clear_api_key: event.target.checked, api_key: "" })} />Remove stored key</label>
          </div></details>

          <details><summary>Request construction</summary><p className="details-help">These JSON documents accept arbitrary nesting. Template values can reference variables such as <code>{"{{text}}"}</code>, <code>{"{{voice}}"}</code>, and <code>{"{{api_key}}"}</code>.</p><div className="resource-json-grid">{jsonField("request_template", "JSON body", 9)}{jsonField("default_variables", "Default variables")}{jsonField("variable_definitions", "Variable definitions", 6)}{jsonField("headers", "Headers")}{jsonField("query", "Query parameters")}{jsonField("auth_env_keys", "API key environment names", 4)}{jsonField("models", "Models", 4)}{jsonField("voices", "Voices", 4)}{jsonField("capabilities", "Delivery capabilities", 7)}</div></details>

          <details><summary>Limits, pacing, and retries</summary><div className="resource-fields four">
            {[['max_input_bytes','Maximum bytes'],['max_input_characters','Maximum characters'],['max_input_tokens','Maximum tokens'],['max_input_words','Maximum words'],['recommended_chunk_bytes','Chunk bytes'],['recommended_chunk_characters','Chunk characters'],['recommended_chunk_words','Chunk words'],['minimum_request_interval_seconds','Seconds between requests'],['requests_per_minute','Requests / minute'],['max_concurrency','Concurrency'],['request_timeout_seconds','Timeout seconds'],['retry_max_attempts','Retry attempts'],['retry_backoff_initial_seconds','Initial backoff'],['retry_backoff_max_seconds','Maximum backoff'],['retry_jitter_seconds','Retry jitter']].map(([key,label]) => <label key={key}><span>{label}</span><input type="number" min="0" step="any" value={form[key]} onChange={(event) => patch({ [key]: event.target.value })} /></label>)}
            <label><span>Limit basis</span><select value={form.limit_basis} onChange={(event) => patch({ limit_basis: event.target.value })}><option value="text">Source text</option><option value="body">Rendered body</option></select></label>
            <label className="check-row"><input type="checkbox" checked={form.honor_retry_after} onChange={(event) => patch({ honor_retry_after: event.target.checked })} />Honor Retry-After</label>
          </div></details>

          <details><summary>Retry status codes</summary><div className="resource-json-grid single">{jsonField("retry_status_codes", "HTTP status codes", 4)}</div></details>

          <details><summary>Audio response</summary><div className="resource-fields four">
            <label><span>Mode</span><select value={form.response_mode} onChange={(event) => patch({ response_mode: event.target.value })}><option value="raw_pcm">Raw PCM body</option><option value="wav">WAV body</option><option value="json_base64_pcm">Base64 PCM in JSON</option><option value="json_base64_wav">Base64 WAV in JSON</option></select></label>
            <label><span>JSON pointer</span><input value={form.audio_json_pointer} onChange={(event) => patch({ audio_json_pointer: event.target.value })} placeholder="/audio/content" /></label>
            <label><span>Sample rate</span><input type="number" min="1" value={form.response_sample_rate_hz} onChange={(event) => patch({ response_sample_rate_hz: event.target.value })} /></label>
            <label><span>Channels</span><input type="number" min="1" value={form.response_channels} onChange={(event) => patch({ response_channels: event.target.value })} /></label>
            <label><span>Sample width bytes</span><input type="number" min="1" max="4" value={form.response_sample_width_bytes} onChange={(event) => patch({ response_sample_width_bytes: event.target.value })} /></label>
          </div></details>
          <footer><span>{editingId ? `Editing revision ${form.revision}` : "Unsaved custom resource"}</span><button className="primary-button" disabled={busy === "save" || !form.id.trim() || !form.name.trim()}><Save size={16} />{busy === "save" ? "Saving…" : "Save resource"}</button></footer>
        </form>
      </div>
    </Modal>
  );
}

const dateLabel = (value) => value ? new Date(value).toLocaleString() : "Unknown time";
const detailJson = (value) => JSON.stringify(value, null, 2);

export function ErrorCenter({ open, onClose, onOpen, onUnreadChange }) {
  const [events, setEvents] = useState([]);
  const [selected, setSelected] = useState(null);
  const [counts, setCounts] = useState({ unread_count: 0, total_count: 0 });
  const [initialized, setInitialized] = useState(false);
  const [toast, setToast] = useState(null);
  const [error, setError] = useState("");

  const refresh = async () => {
    try {
      const result = await api.errors();
      const previousMax = events.reduce((max, item) => Math.max(max, item.sequence), 0);
      const incoming = result.events.filter((item) => item.sequence > previousMax);
      setEvents(result.events);
      setCounts(result);
      onUnreadChange(result.unread_count);
      if (initialized && incoming.length) setToast(incoming.at(-1));
      setInitialized(true);
      setError("");
    } catch (reason) { setError(reason.message); }
  };

  useEffect(() => {
    refresh();
    const timer = window.setInterval(refresh, 4000);
    const immediate = (event) => setToast({ code: event.detail?.code || "request_error", message: event.detail?.message || "A request failed." });
    window.addEventListener("splicr:api-error", immediate);
    return () => { window.clearInterval(timer); window.removeEventListener("splicr:api-error", immediate); };
  }, [initialized, events.length]);
  useEffect(() => {
    if (!toast) return undefined;
    const timer = window.setTimeout(() => setToast(null), 9000);
    return () => window.clearTimeout(timer);
  }, [toast]);

  const inspect = async (event) => {
    try {
      const detail = await api.error(event.id);
      setSelected(detail);
      if (!detail.read_at) {
        const read = await api.markErrorRead(event.id);
        setSelected(read);
        await refresh();
      }
    } catch (reason) { setError(reason.message); }
  };

  const markAll = async () => { await api.markAllErrorsRead(); await refresh(); };
  const clearRead = async () => { await api.clearErrors("read"); setSelected(null); await refresh(); };
  const ordered = useMemo(() => [...events].sort((a, b) => b.sequence - a.sequence), [events]);

  return (
    <>
      {toast && <aside className="studio-error-toast" role="alert"><AlertTriangle size={18} /><span><strong>{toast.code || "Error"}</strong>{toast.message}</span><button onClick={() => { setToast(null); onOpen(); if (toast.id) inspect(toast); }} aria-label="View error details"><Eye size={17} /></button><button onClick={() => setToast(null)} aria-label="Dismiss"><X size={16} /></button></aside>}
      <Modal open={open} onClose={onClose} eyebrow="Diagnostics" title="Error center" wide>
        <div className="error-center-toolbar"><span>{counts.unread_count} unread · {counts.total_count} retained</span><div><button className="text-button" onClick={refresh}><RefreshCw size={14} />Refresh</button><button className="text-button" onClick={markAll}><CheckCheck size={14} />Mark all read</button><button className="text-button danger" onClick={clearRead}><Trash2 size={14} />Clear read</button></div></div>
        <InlineNotice error={error} />
        <div className="error-center-layout">
          <div className="error-event-list">
            {!ordered.length && <p className="muted">No errors have been recorded.</p>}
            {ordered.map((event) => <button key={event.id} className={`${selected?.id === event.id ? "active" : ""}${event.read_at ? " read" : ""}`} onClick={() => inspect(event)}><i className={`severity-${event.severity}`} /><span><strong>{event.code}</strong><small>{event.message}</small><time>{dateLabel(event.last_occurred_at)}{event.count > 1 ? ` · ×${event.count}` : ""}</time></span></button>)}
          </div>
          <article className="error-detail">
            {!selected && <div className="error-detail-empty"><Eye size={24} /><p>Select an event to inspect its request, response, exception, and runtime context.</p></div>}
            {selected && <>
              <div className="error-detail-heading"><span className={`severity-pill severity-${selected.severity}`}>{selected.severity}</span><h3>{selected.code}</h3><p>{selected.message}</p></div>
              <dl className="error-facts">
                <div><dt>Status</dt><dd>{selected.status_code || "n/a"}</dd></div><div><dt>Source</dt><dd>{selected.source}</dd></div><div><dt>Provider</dt><dd>{selected.provider || "n/a"}</dd></div><div><dt>Retryable</dt><dd>{selected.retryable ? "Yes" : "No"}</dd></div><div><dt>Job</dt><dd>{selected.job_id || "n/a"}</dd></div><div><dt>Chunk</dt><dd>{selected.chunk_index ?? "n/a"}</dd></div>
              </dl>
              {selected.endpoint && <section><strong>Endpoint</strong><code>{selected.method || ""} {selected.endpoint}</code></section>}
              {[['request','Request'],['response','Response'],['exception','Exception'],['context','Context']].map(([key,label]) => selected[key] && <details key={key} open={key === 'response'}><summary>{label}</summary><pre>{detailJson(selected[key])}</pre></details>)}
              <small>First: {dateLabel(selected.first_occurred_at)} · Last: {dateLabel(selected.last_occurred_at)} · {statusLabel(selected.category || "uncategorized")}</small>
            </>}
          </article>
        </div>
      </Modal>
    </>
  );
}
