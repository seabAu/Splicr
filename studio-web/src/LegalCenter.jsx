import React, { useEffect, useState } from "react";
import {
  ExternalLink,
  FileText,
  Info,
  LoaderCircle,
  Scale,
  ShieldCheck,
  TriangleAlert,
  X,
} from "lucide-react";

import { api } from "./api.js";


export function LegalCenter({ open, onClose }) {
  const [info, setInfo] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!open) return undefined;
    let active = true;
    setLoading(true);
    setError("");
    api.legalInfo()
      .then((value) => active && setInfo(value))
      .catch((reason) => active && setError(reason.message))
      .finally(() => active && setLoading(false));
    const closeOnEscape = (event) => event.key === "Escape" && onClose();
    window.addEventListener("keydown", closeOnEscape);
    return () => {
      active = false;
      window.removeEventListener("keydown", closeOnEscape);
    };
  }, [open, onClose]);

  if (!open) return null;
  const source = info?.ffmpeg?.corresponding_source;
  return (
    <div
      className="studio-modal-backdrop"
      role="presentation"
      onMouseDown={(event) => event.target === event.currentTarget && onClose()}
    >
      <section className="studio-modal legal-center" role="dialog" aria-modal="true" aria-labelledby="legal-center-title">
        <header>
          <div>
            <p className="eyebrow">About this build</p>
            <h2 id="legal-center-title">SPLICR Studio &amp; legal</h2>
          </div>
          <button className="icon-button" type="button" onClick={onClose} aria-label="Close about and legal information">
            <X size={18} />
          </button>
        </header>

        {loading && !info ? (
          <div className="legal-loading"><LoaderCircle className="spin" size={24} /> Loading build information…</div>
        ) : error ? (
          <p className="inline-error">Could not load legal information: {error}</p>
        ) : info ? (
          <div className="legal-content">
            <section className="legal-summary">
              <span className="legal-icon"><Info size={19} /></span>
              <div>
                <strong>{info.application.name}</strong>
                <span>Version {info.application.version} · {info.application.license.id}</span>
              </div>
            </section>

            <section className="legal-section">
              <div className="legal-section-heading"><Scale size={18} /><h3>FFmpeg attribution</h3></div>
              <p>{info.ffmpeg.attribution}</p>
              <dl className="legal-facts">
                <dt>Effective package status</dt><dd>{info.ffmpeg.effective_license}</dd>
              </dl>
              <div className="legal-links">
                <a className="secondary-button" href={info.ffmpeg.project_url} target="_blank" rel="noreferrer">FFmpeg project <ExternalLink size={13} /></a>
                <a className="secondary-button" href={info.ffmpeg.legal_url} target="_blank" rel="noreferrer">FFmpeg legal information <ExternalLink size={13} /></a>
              </div>
            </section>

            <section className={`legal-source-status ${source?.available ? "is-ready" : "is-internal"}`}>
              {source?.available ? <ShieldCheck size={20} /> : <TriangleAlert size={20} />}
              <div>
                <strong>{source?.available ? "Corresponding source is published" : "Internal build: source archive not published"}</strong>
                {source?.available ? (
                  <>
                    <a href={source.url} target="_blank" rel="noreferrer">Download exact corresponding source <ExternalLink size={13} /></a>
                    <span>SHA-256 <code>{source.sha256}</code></span>
                  </>
                ) : (
                  <span>A public release must embed a direct HTTPS source link and its SHA-256 before distribution.</span>
                )}
              </div>
            </section>

            {info.documents.length > 0 && (
              <section className="legal-section">
                <div className="legal-section-heading"><FileText size={18} /><h3>Notices and provenance</h3></div>
                <div className="legal-document-list">
                  {info.documents.map((document) => (
                    <a key={document.id} href={document.url} target="_blank" rel="noreferrer">
                      <FileText size={15} /><span>{document.label}</span><ExternalLink size={13} />
                    </a>
                  ))}
                </div>
              </section>
            )}
          </div>
        ) : null}
      </section>
    </div>
  );
}
