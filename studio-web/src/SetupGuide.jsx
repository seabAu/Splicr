import React, { useEffect, useRef, useState } from "react";
import { ArrowRight, Boxes, Cloud, Cpu, LoaderCircle, X } from "lucide-react";

export function LocalSetupSummary({ status, onManage }) {
  if (!status?.enabled) return null;
  const engines = status.engines || [];
  const configured = engines.filter((item) => item.available && !item.restart_required).length;
  return <section className="surface setup-overview" aria-label="Local engine setup">
    <div className="setup-overview-heading"><div><strong>Local models start here</strong><p>{configured}/{engines.length} engine interpreters configured. Engine packages and model weights are separate downloads.</p></div>
      <button className="secondary-button small" onClick={() => onManage()}><Boxes size={15} /> Models &amp; setup</button></div>
    {status.restart_required && <p className="setup-restart-note">A saved engine change needs a full desktop-app restart. Current jobs keep their existing engine.</p>}
    <details><summary>Show local engines and setup actions</summary><div className="setup-engine-list">
      {engines.map((engine) => <article key={engine.id}>
        <div><strong>{engine.label}</strong><span className={`component-state state-${engine.state}`}>{engine.restart_required ? "Restart needed" : engine.available ? "Interpreter configured" : "Not configured"}</span><p>{engine.detail}</p></div>
        <button className="secondary-button small" onClick={() => onManage(engine.id)}>{engine.path || engine.locked ? "Review" : "Set up"} {engine.label}</button>
      </article>)}
    </div></details>
  </section>;
}

export function SetupGuideDialog({ open, status, error, busy, onChoose, onClose, onRetry }) {
  const [engineId, setEngineId] = useState("kokoro");
  const dialog = useRef(null);
  useEffect(() => {
    if (!open) return undefined;
    const previous = document.activeElement;
    dialog.current?.querySelector("button")?.focus();
    return () => { if (previous?.isConnected) previous.focus(); };
  }, [open]);
  useEffect(() => {
    if (status?.engines?.length && !status.engines.some((item) => item.id === engineId)) {
      setEngineId(status.engines[0].id);
    }
  }, [status, engineId]);
  if (!open) return null;
  const enabled = status?.enabled && !busy;
  const keyDown = (event) => {
    if (event.key === "Escape" && !busy) { event.preventDefault(); onClose(); }
    if (event.key !== "Tab") return;
    const fields = [...dialog.current.querySelectorAll("button:not(:disabled), select:not(:disabled), a[href]")];
    const first = fields[0]; const last = fields[fields.length - 1];
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
    if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
  };
  return <div className="studio-modal-backdrop" role="presentation">
    <section ref={dialog} className="studio-modal setup-guide-dialog" role="dialog" aria-modal="true" aria-labelledby="setup-guide-title" onKeyDown={keyDown}>
      <header><div><p className="eyebrow">Models &amp; setup</p><h2 id="setup-guide-title">Set up your studio</h2></div><button className="icon-button" disabled={busy} onClick={onClose} aria-label="Close setup guide"><X size={18} /></button></header>
      <p className="modal-intro">Choose how you want to work. Nothing downloads until you review an engine install and explicitly agree. Your documents, connections and existing jobs stay unchanged.</p>
      {busy && <p role="status"><LoaderCircle className="spin" size={15} /> Saving your choice…</p>}
      {error && <p className="inline-error" role="alert">{error} <button className="secondary-button small" onClick={onRetry} disabled={busy}>Try setup detection again</button></p>}
      {status?.preference_warning && <p className="inline-error" role="alert">{status.preference_warning}</p>}
      {!status && !error && <p role="status"><LoaderCircle className="spin" size={16} /> Checking your local setup…</p>}
      {status?.enabled === false && <p>Engine setup is available through the local desktop connection, not a hosted or cross-origin connection.</p>}
      <div className="setup-mode-grid">
        <section className="setup-mode-card"><Cpu size={23} /><h3>Use an app-managed engine</h3><p>Kokoro, Qwen3 and Audio8 can render on this computer. Edge TTS uses an online service; faster-whisper transcribes audio.</p>
          <label className="control"><span>Engine to review</span><select value={engineId} onChange={(event) => setEngineId(event.target.value)} disabled={!enabled}>
            {(status?.engines || []).map((engine) => <option value={engine.id} key={engine.id}>{engine.label}</option>)}
          </select></label>
          <p className="setup-fine-print">Private Python and engine packages are managed separately from model weights. Build tools such as Node, npm and Inno Setup are not needed to use the installed app.</p>
          {status && !status.managed_setup_supported && <p className="setup-fine-print">Guided installs currently need Windows x64. You can still connect an environment you already manage.</p>}
          <button className="primary-button" disabled={!enabled || !engineId} onClick={() => onChoose("local", engineId)}>Review local setup <ArrowRight size={15} /></button>
        </section>
        <section className="setup-mode-card"><Cloud size={23} /><h3>Connect a speech API</h3><p>Use Gemini, Deepgram, Inworld or a custom API connection. Text is sent to the chosen provider; its availability, terms and usage charges apply.</p>
          <p className="setup-fine-print">Keys are entered in Connections and kept in SPLICR’s credential vault. Choosing this route does not submit a document or start a paid job.</p>
          <button className="secondary-button" disabled={!enabled} onClick={() => onChoose("remote")}>Set up API connection <ArrowRight size={15} /></button>
        </section>
      </div>
      <footer className="setup-guide-footer"><span>You can reopen this guide from Narrate at any time.</span><button className="ghost-button" disabled={!enabled} onClick={() => onChoose("later")}>Decide later</button></footer>
    </section>
  </div>;
}
