import React, { useEffect, useRef, useState } from "react";
import { Download, LoaderCircle, RotateCcw, Square, X } from "lucide-react";
import { api } from "./api.js";

const ACTIVE = new Set(["queued", "running", "cancelling"]);
const gib = (bytes) => `${(bytes / 1024 ** 3).toFixed(1)} GiB`;

export function EngineSetupPanel({ engines, onInstalled }) {
  const [catalog, setCatalog] = useState(null);
  const [selected, setSelected] = useState(null);
  const [accelerator, setAccelerator] = useState("cpu");
  const [consent, setConsent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [pollError, setPollError] = useState("");
  const refreshed = useRef(new Set());

  useEffect(() => {
    let alive = true;
    let timer;
    const poll = async () => {
      try {
        const next = await api.engineSetup();
        if (alive) { setCatalog(next); setPollError(""); }
      } catch (reason) {
        if (alive) setPollError(reason.message);
      } finally {
        if (alive) timer = setTimeout(poll, 2500);
      }
    };
    poll();
    return () => { alive = false; clearTimeout(timer); };
  }, []);

  useEffect(() => {
    const completed = (catalog?.jobs || []).filter((job) => job.status === "completed" && !refreshed.current.has(job.id));
    if (completed.length) {
      completed.forEach((job) => refreshed.current.add(job.id));
      void onInstalled();
    }
  }, [catalog, onInstalled]);

  const action = async (operation) => {
    setBusy(true); setError("");
    try {
      await operation();
      setCatalog(await api.engineSetup());
      await onInstalled();
      setSelected(null); setConsent(false);
    } catch (reason) { setError(reason.message); }
    finally { setBusy(false); }
  };

  const jobs = catalog?.jobs || [];
  const active = jobs.some((job) => ACTIVE.has(job.status));
  const recipe = catalog?.recipes.find((item) => item.id === selected);
  const label = (id) => engines.find((engine) => engine.id === id)?.label || id;
  const required = recipe ? (recipe.space_gb + (accelerator === "cuda" ? 8 : 0)) * 1024 ** 3 : 0;
  const enoughSpace = catalog && catalog.free_bytes >= required;

  return <section className="components-section managed-setup surface">
    <div className="section-heading"><div><p className="eyebrow">Guided setup</p><h2>Install engines without the terminal</h2></div><Download size={22} /></div>
    <p>Let SPLICR download a private Python runtime, install an isolated engine, and verify its packages. Your system Python and connected environments stay untouched.</p>
    {error && <p className="inline-error" role="alert">{error}</p>}
    {pollError && <p className="inline-error" role="alert">{pollError}</p>}
    {!catalog && !pollError && <p><LoaderCircle className="spin" size={16} /> Checking setup options…</p>}
    {catalog && !catalog.supported && <p>Managed installation currently supports Windows x64. Use Configure below to connect an existing environment on this platform.</p>}
    {catalog?.supported && <>
      <div className="managed-setup-options">{catalog.recipes.map((item) => {
        const locked = engines.find((engine) => engine.id === item.id)?.locked;
        return <button className="secondary-button" key={item.id} disabled={active || busy || locked} onClick={() => { setSelected(item.id); setAccelerator("cpu"); setConsent(false); setError(""); }}>
          <Download size={15} /> {engines.find((engine) => engine.id === item.id)?.path ? "Install managed copy:" : "Install"} {label(item.id)}
        </button>;
      })}</div>
      <small>{gib(catalog.free_bytes)} free · No admin or existing Python required. One setup at a time.</small>
    </>}
    {jobs.length > 0 && <div className="managed-setup-jobs">{[...jobs].reverse().slice(0, 8).map((job) => <article className="managed-setup-job" key={job.id}>
      <div className="managed-setup-job-heading"><strong>{label(job.engine_id)} · {job.accelerator.toUpperCase()}</strong><span className="component-state">{job.status}</span></div>
      <p role={ACTIVE.has(job.status) ? "status" : undefined}>{ACTIVE.has(job.status) && <LoaderCircle className="spin" size={14} />} {job.stage}</p>
      {job.download_total > 0 && ACTIVE.has(job.status) && <><progress aria-label="Setup tool download" max={job.download_total} value={job.download_bytes} /><small>{(job.download_bytes / 1024 ** 2).toFixed(1)} / {(job.download_total / 1024 ** 2).toFixed(1)} MiB</small></>}
      {job.error && <p className="inline-error">{job.error}</p>}
      {job.status === "completed" && <p>Restart the desktop app, then render a short sample. Models download on first use; package verification is not an audio-quality test. <button className="secondary-button small" onClick={onInstalled}>Refresh component status</button></p>}
      <div className="component-actions">
        {ACTIVE.has(job.status) && <button className="secondary-button small" disabled={busy || job.status === "cancelling"} onClick={() => action(() => api.cancelEngineSetup(job.id))}><Square size={14} /> Cancel setup</button>}
        {["failed", "cancelled", "interrupted"].includes(job.status) && <button className="secondary-button small" disabled={busy || active} onClick={() => { setSelected(job.engine_id); setAccelerator(job.accelerator); setConsent(false); setError(""); }}><RotateCcw size={14} /> Review and retry</button>}
      </div>
      {job.logs.length > 0 && <details><summary>Setup log</summary><pre className="managed-setup-log">{job.logs.join("\n")}</pre></details>}
    </article>)}</div>}
    {selected && recipe && <div className="studio-modal-backdrop" role="presentation">
      <section className="studio-modal component-dialog" role="dialog" aria-modal="true" aria-label={`Install ${label(selected)}`}>
        <header><div><p className="eyebrow">App-managed environment</p><h2>Install {label(selected)}</h2></div><button className="icon-button" disabled={busy} onClick={() => setSelected(null)} aria-label="Close engine setup"><X size={18} /></button></header>
        <p>{recipe.note}</p>
        <label className="control"><span>Processing hardware</span><select value={accelerator} onChange={(event) => setAccelerator(event.target.value)} disabled={busy}>
          <option value="cpu">CPU — works without an NVIDIA GPU</option>
          {["kokoro", "qwen3", "audio8"].includes(selected) && <option value="cuda" disabled={!catalog.nvidia_gpu}>NVIDIA CUDA 12.8{catalog.nvidia_gpu ? ` — ${catalog.nvidia_gpu}` : " — no working NVIDIA driver detected"}</option>}
        </select></label>
        <dl className="component-facts"><dt>Plan for</dt><dd>At least {gib(required)} free (estimate including model headroom)</dd><dt>Available</dt><dd>{gib(catalog.free_bytes)}</dd><dt>Storage</dt><dd>{catalog.root}</dd><dt>Packages</dt><dd>{recipe.packages.join(", ")}</dd></dl>
        <p>Downloads come from Astral/GitHub, PyPI and, where applicable, PyTorch. Selected models download from their upstream hosts on first use. Third-party package and model terms apply. No drivers, system packages, or administrator changes are installed.</p>
        <p>Cancellation keeps cached downloads for retry. Successful installation is connected automatically for the next app restart; existing jobs keep their current engine.</p>
        <label className="managed-setup-consent"><input type="checkbox" checked={consent} onChange={(event) => setConsent(event.target.checked)} /> I agree to these downloads and execution of third-party engine code{selected === "audio8" ? ", including Audio8 remote model code on first render" : ""}.</label>
        {!enoughSpace && <p className="inline-error">Not enough free space for this setup plan.</p>}
        {error && <p className="inline-error" role="alert">{error}</p>}
        <div className="component-dialog-actions"><button className="secondary-button" disabled={busy} onClick={() => setSelected(null)}>Not now</button><button className="primary-button" disabled={!consent || busy || active || !enoughSpace} onClick={() => action(() => {
          const retry = [...jobs].reverse().find((job) => job.engine_id === selected && job.accelerator === accelerator && ["failed", "cancelled", "interrupted"].includes(job.status));
          return retry ? api.retryEngineSetup(retry.id) : api.installEngine(selected, accelerator, consent);
        })}>{busy ? <LoaderCircle className="spin" size={16} /> : <Download size={16} />}{busy ? "Starting…" : "Install engine"}</button></div>
      </section>
    </div>}
  </section>;
}
