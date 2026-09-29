import React, { useEffect, useState } from "react";
import {
  Boxes,
  CheckCircle2,
  CircleAlert,
  ExternalLink,
  HardDriveDownload,
  LoaderCircle,
  Pencil,
  Power,
  RefreshCw,
  RotateCcw,
  Trash2,
  X,
} from "lucide-react";

import { api } from "./api.js";

function StateBadge({ state }) {
  const label = state === "restart_required" ? "Restart needed" : state;
  return <span className={`component-state state-${state}`}>{label.replaceAll("_", " ")}</span>;
}

function ComponentCard({ item, onConfigure, onClear, onRefreshVoices, busy }) {
  return (
    <article className={`component-card surface component-${item.state}`}>
      <div className="component-card-heading">
        <span className="component-card-icon">
          {["ready", "configured"].includes(item.state) ? <CheckCircle2 size={20} /> : item.state === "planned" ? <Boxes size={20} /> : <CircleAlert size={20} />}
        </span>
        <div><h3>{item.label}</h3><StateBadge state={item.state} /></div>
      </div>
      <p>{item.description}</p>
      <ul>{item.unlocks.map((feature) => <li key={feature}>{feature}</li>)}</ul>
      {(item.path || item.version || item.detail) && (
        <dl className="component-facts">
          {item.path && <><dt>Path</dt><dd title={item.path}>{item.path}</dd></>}
          {item.version && <><dt>Version</dt><dd>{item.version}</dd></>}
          {item.detail && <><dt>Note</dt><dd>{item.detail}</dd></>}
          {item.voice_catalog?.count > 0 && <><dt>Voice catalog</dt><dd>{item.voice_catalog.count} cached voices</dd></>}
        </dl>
      )}
      <div className="component-actions">
        {item.kind === "engine" && !item.locked && (
          <button className="secondary-button" type="button" onClick={() => onConfigure(item)}>
            <Pencil size={14} /> {item.path ? "Change" : "Configure"}
          </button>
        )}
        {item.kind === "engine" && item.path && !item.locked && (
          <button className="icon-button danger" type="button" onClick={() => onClear(item)} aria-label={`Clear ${item.label} configuration`} title="Clear saved path">
            <Trash2 size={15} />
          </button>
        )}
        {item.id === "edge" && item.available && !item.restart_required && (
          <button className="secondary-button" type="button" disabled={busy} onClick={onRefreshVoices}>
            <RefreshCw className={busy ? "spin" : ""} size={14} />
            {busy ? "Refreshing…" : "Refresh voices"}
          </button>
        )}
        {item.locked && <span className="component-lock"><Power size={13} /> {item.environment_variable}</span>}
        {item.install_url && (
          <a className="secondary-button" href={item.install_url} target="_blank" rel="noreferrer">
            Official downloads <ExternalLink size={13} />
          </a>
        )}
      </div>
    </article>
  );
}

function EngineDialog({ engine, busy, error, onClose, onSave }) {
  const [path, setPath] = useState(engine?.path || "");
  useEffect(() => setPath(engine?.path || ""), [engine]);
  if (!engine) return null;
  return (
    <div className="studio-modal-backdrop" role="presentation" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
      <section className="studio-modal component-dialog" role="dialog" aria-modal="true" aria-label={`Configure ${engine.label}`}>
        <header><div><p className="eyebrow">Local engine environment</p><h2>Configure {engine.label}</h2></div><button className="icon-button" type="button" onClick={onClose} aria-label="Close"><X size={18} /></button></header>
        <p className="modal-intro">Point SPLICR at the Python executable inside an existing {engine.label} environment. The environment, model cache, and weights stay where they are; SPLICR only stores this path.</p>
        {error && <p className="inline-error">{error}</p>}
        <label className="control component-path-field"><span>Python executable</span><input value={path} autoFocus spellCheck="false" onChange={(event) => setPath(event.target.value)} placeholder="C:\path\to\environment\Scripts\python.exe" /><small>SPLICR runs <code>--version</code> before saving. No packages or models are downloaded.</small></label>
        <div className="component-dialog-actions"><button className="secondary-button" type="button" onClick={onClose}>Cancel</button><button className="primary-button" type="button" disabled={!path.trim() || busy} onClick={() => onSave(path)}>{busy ? <LoaderCircle className="spin" size={15} /> : <HardDriveDownload size={15} />}{busy ? "Checking…" : "Save for next restart"}</button></div>
      </section>
    </div>
  );
}

export function ComponentsWorkspace() {
  const [catalog, setCatalog] = useState(null);
  const [editing, setEditing] = useState(null);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [dialogError, setDialogError] = useState("");

  const load = async () => {
    setError("");
    try {
      setCatalog(await api.components());
    } catch (reason) {
      setError(reason.message);
    }
  };

  useEffect(() => { load(); }, []);

  const save = async (path) => {
    setBusy(editing.id);
    setDialogError("");
    try {
      setCatalog(await api.configureEngineComponent(editing.id, path));
      setEditing(null);
    } catch (reason) {
      setDialogError(reason.message);
    } finally {
      setBusy("");
    }
  };

  const clear = async (item) => {
    setBusy(item.id);
    setError("");
    try {
      setCatalog(await api.clearEngineComponent(item.id));
    } catch (reason) {
      setError(reason.message);
    } finally {
      setBusy("");
    }
  };

  const refreshVoices = async () => {
    setBusy("edge-voices");
    setError("");
    try {
      await api.refreshEdgeVoices();
      await load();
    } catch (reason) {
      setError(reason.message);
    } finally {
      setBusy("");
    }
  };

  return (
    <main className="components-workspace">
      <header className="workspace-header components-header">
        <div><p className="eyebrow">Local capabilities</p><h1>Components</h1><p>See what is ready, what each piece unlocks, and connect isolated engine environments.</p></div>
        <button className="secondary-button" type="button" onClick={load}><RefreshCw size={15} /> Refresh detection</button>
      </header>
      {error && <p className="inline-error">{error}</p>}
      {!catalog ? (
        <section className="surface components-loading"><LoaderCircle className="spin" size={28} /><span>Inspecting local tools…</span></section>
      ) : (
        <>
          {catalog.restart_required && (
            <section className="component-restart-banner"><RotateCcw size={19} /><div><strong>Restart SPLICR to activate the saved engine change.</strong><span>Active jobs keep their current provider registry until then.</span></div></section>
          )}
          <section className="components-section">
            <div className="section-heading"><div><p className="eyebrow">Runtime</p><h2>System tools</h2></div><span>{catalog.system.filter((item) => item.available).length}/{catalog.system.length} ready</span></div>
            <div className="component-grid">{catalog.system.map((item) => <ComponentCard key={item.id} item={item} onConfigure={setEditing} onClear={clear} onRefreshVoices={refreshVoices} busy={busy === "edge-voices"} />)}</div>
          </section>
          <section className="components-section">
            <div className="section-heading"><div><p className="eyebrow">Speech engines</p><h2>Isolated Python environments</h2></div><span>{catalog.engines.filter((item) => item.available && !item.restart_required).length}/{catalog.engines.length} active</span></div>
            <p className="components-intro">Each engine keeps its own dependencies and model cache. SPLICR launches the configured interpreter through the same supervised, job-scoped protocol used by local narration.</p>
            <div className="component-grid">{catalog.engines.map((item) => <ComponentCard key={item.id} item={item} onConfigure={setEditing} onClear={clear} onRefreshVoices={refreshVoices} busy={busy === "edge-voices"} />)}</div>
          </section>
          <section className="components-section components-planned">
            <div className="section-heading"><div><p className="eyebrow">Migration queue</p><h2>Preserved, not active yet</h2></div></div>
            <div className="component-grid">{catalog.planned.map((item) => <ComponentCard key={item.id} item={item} onConfigure={setEditing} onClear={clear} onRefreshVoices={refreshVoices} busy={busy === "edge-voices"} />)}</div>
          </section>
        </>
      )}
      <EngineDialog engine={editing} busy={!!busy} error={dialogError} onClose={() => { setEditing(null); setDialogError(""); }} onSave={save} />
    </main>
  );
}
