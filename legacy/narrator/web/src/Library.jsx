import React, { useEffect, useState } from "react";
import { getLibrary } from "./api";
import { Button } from "@/components/ui/button";

// Documents worked on before, with the settings last used for each.
// Loading one puts its settings back into the form -- the same thing the
// desktop app's "Load selected" does, over the same saved cfg.

const STATUS_ORDER = ["not_started", "prepared", "rendered", "published"];

function ago(seconds) {
  if (!seconds) return "never";
  const delta = Date.now() / 1000 - seconds;
  if (delta < 60) return "just now";
  if (delta < 3600) return `${Math.floor(delta / 60)}m ago`;
  if (delta < 86400) return `${Math.floor(delta / 3600)}h ago`;
  const days = Math.floor(delta / 86400);
  return days < 30
    ? `${days}d ago`
    : new Date(seconds * 1000).toLocaleDateString();
}

export default function Library({ onLoad, refreshKey }) {
  const [projects, setProjects] = useState([]);
  const [error, setError] = useState("");

  useEffect(() => {
    getLibrary()
      .then((r) => setProjects(r.projects))
      .catch((e) => setError(String(e.message || e)));
  }, [refreshKey]);

  if (error) return <p className="error">{error}</p>;
  if (projects.length === 0)
    return <p className="hint">Nothing here yet. Render something.</p>;

  return (
    <ul className="library">
      {projects.map((p) => {
        const stage = STATUS_ORDER.indexOf(p.status);
        return (
          <li key={p.path}>
            <div className="lib-main">
              <strong>{p.label}</strong>
              <span className={`status s-${p.status}`}>
                {p.status.replace("_", " ")}
              </span>
              <span className="hint">{ago(p.updated)}</span>
            </div>
            <div className="lib-sub">
              <code title={p.path}>{p.path}</code>
              {p.cfg?.voice && <span className="hint"> · {p.cfg.voice}</span>}
            </div>
            <div className="lib-actions">
              <Button
                disabled={!p.cfg?.engine}
                title={
                  p.cfg?.engine
                    ? "Put these settings back in the form"
                    : "No settings saved yet — render it once first"
                }
                onClick={() => onLoad(p)}
              >
                Load settings
              </Button>
              {stage >= 2 && p.output && (
                <code className="hint">{p.output.split("/").pop()}</code>
              )}
            </div>
          </li>
        );
      })}
    </ul>
  );
}
