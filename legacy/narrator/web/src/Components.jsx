import React, { useEffect, useState } from "react";
import {
  getComponents,
  installComponent,
  installEngine,
  getSettings,
  setEnvRoot,
} from "./api";
import JobLog from "./JobLog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

// Narrator runs with none of these present. This exists so a missing
// piece says so and offers to fix itself, rather than a feature failing
// partway through with no explanation.

function EnvRootControl() {
  const [path, setPath] = useState("");
  const [saved, setSaved] = useState("");
  const [status, setStatus] = useState("");
  const [statusOk, setStatusOk] = useState(true);

  useEffect(() => {
    getSettings()
      .then((r) => {
        const v = r.settings.env_root || "";
        setPath(v);
        setSaved(v);
      })
      .catch(() => {});
  }, []);

  const apply = async (value) => {
    try {
      const r = await setEnvRoot(value);
      setSaved(r.env_root);
      setPath(r.env_root);
      setStatus(
        r.env_root
          ? "Saved — engines will be looked for there too."
          : "Cleared — back to this app's own folder."
      );
      setStatusOk(true);
    } catch (e) {
      setStatus(String(e.message || e));
      setStatusOk(false);
    }
  };

  return (
    <div className="env-root">
      <Label htmlFor="env-root-input">Environments folder</Label>
      <p className="hint">
        Each engine needs its own environment, several GB. Point this at
        an older Narrator folder to reuse the environments built there
        instead of downloading everything again — already-downloaded
        model weights are shared automatically either way. Leave empty
        to use this app's own folder.
      </p>
      <div className="row">
        <Input
          id="env-root-input"
          value={path}
          onChange={(e) => setPath(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && apply(path)}
          placeholder="(this app's own folder)"
        />
        <Button onClick={() => apply(path)}>Save</Button>
        {saved && <Button onClick={() => apply("")}>Use app folder</Button>}
      </div>
      {status && <p className={statusOk ? "ok" : "error"}>{status}</p>}
    </div>
  );
}

export default function Components({ onJob }) {
  const [items, setItems] = useState([]);
  // The list takes a moment (it probes for installed tools); without a
  // "loaded" flag the tab just looked empty until it arrived.
  const [loaded, setLoaded] = useState(false);
  const [jobId, setJobId] = useState(null);
  const [error, setError] = useState("");

  const load = () =>
    getComponents()
      .then((r) => setItems(r.components))
      .catch((e) => setError(String(e.message || e)))
      .finally(() => setLoaded(true));

  useEffect(() => {
    load();
  }, []);

  const install = async (item) => {
    setError("");
    try {
      const job =
        item.kind === "engine"
          ? await installEngine(item.label)
          : await installComponent(item.key);
      setJobId(job.id);
    } catch (e) {
      setError(String(e.message || e));
    }
  };

  return (
    <div className="components">
      <p className="hint">
        Narrator runs with none of these. Each unlocks what's listed beside
        it. Licences are shown because some carry conditions if you pass the
        program on — that's information, not legal advice.
      </p>
      {error && <p className="error">{error}</p>}
      <EnvRootControl />
      {!loaded && <p className="hint">Checking what's installed…</p>}
      <ul className="component-rows">
        {items.map((item) => (
          <li key={item.key}>
            <div className="crow">
              <span className={`mark ${item.installed ? "done" : "missing"}`}>
                {item.installed ? "✓" : item.essential ? "!" : "–"}
              </span>
              <strong>{item.label}</strong>
              <span className="hint">
                {item.size} · {item.licence}
              </span>
            </div>
            <div className="crow-sub hint">
              {item.installed ? item.detail : item.enables.join(", ")}
            </div>
            {!item.installed && (
              <div className="crow-actions">
                {item.kind === "python" || item.kind === "engine" ? (
                  <Button onClick={() => install(item)}>
                    {item.kind === "engine"
                      ? `Download and set up (${item.size})`
                      : "Install"}
                  </Button>
                ) : (
                  <a href={item.url} target="_blank" rel="noreferrer">
                    Download page
                  </a>
                )}
                {item.hint && <span className="hint"> — {item.hint}</span>}
              </div>
            )}
          </li>
        ))}
      </ul>
      <JobLog
        jobId={jobId}
        onFinished={() => {
          load();
          onJob?.();
        }}
      />
    </div>
  );
}
