import React, { useEffect, useState } from "react";
import {
  getProviders,
  saveProvider,
  deleteProvider,
  verifyProvider,
} from "./api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

// Keys are never sent back in full — the server returns them masked, and
// saving with a blank key keeps whatever is stored. So the field can show
// the mask harmlessly and only a deliberate retype replaces the key.

function Stages({ stages }) {
  if (!stages) return null;
  return (
    <ol className="stages">
      {stages.map((s) => (
        <li key={s.stage} className={s.ok ? "ok" : "error"}>
          <strong>
            {s.ok ? "✓" : "✗"} {s.stage}
          </strong>
          <span> — {s.detail}</span>
        </li>
      ))}
    </ol>
  );
}

export default function Providers({ onChange }) {
  const [providers, setProviders] = useState({});
  const [templates, setTemplates] = useState({});
  const [editing, setEditing] = useState(null); // {name, base_url, ...}
  const [result, setResult] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const load = () =>
    getProviders()
      .then((r) => {
        setProviders(r.providers);
        setTemplates(r.templates);
        onChange?.(Object.keys(r.providers));
      })
      .catch((e) => setError(String(e.message || e)));

  useEffect(() => {
    load();
  }, []);

  const startFrom = (key) => {
    const t = templates[key];
    setResult(null);
    setEditing({
      name: key,
      base_url: t.base_url,
      api_key: "",
      model: t.example_model || "",
      local: t.local,
      _note: t.note,
      _needsKey: t.needs_key,
    });
  };

  const save = async () => {
    setBusy(true);
    setError("");
    try {
      const { name, _note, _needsKey, ...config } = editing;
      await saveProvider(name, config);
      await load();
      setEditing(null);
    } catch (e) {
      setError(String(e.message || e));
    } finally {
      setBusy(false);
    }
  };

  const verify = async (name, model) => {
    setBusy(true);
    setResult(null);
    setError("");
    try {
      setResult({ name, ...(await verifyProvider(name, model || "")) });
    } catch (e) {
      setError(String(e.message || e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="providers">
      <p className="hint">
        Narrator ships no keys and no models. Point it at your own — a local
        Ollama, or an API key you hold. Keys are stored on this machine in
        plain text (readable only by you), never sent anywhere but the
        provider you name.
      </p>

      <ul className="provider-rows">
        {Object.entries(providers).map(([name, p]) => (
          <li key={name}>
            <div className="prow">
              <strong>{name}</strong>
              <code>{p.model || "no model set"}</code>
              <span className="hint">{p.base_url}</span>
              {p.has_key && <span className="hint">key {p.api_key}</span>}
            </div>
            <div className="prow-actions">
              <Button disabled={busy} onClick={() => verify(name, p.model)}>
                Verify
              </Button>
              <Button
                onClick={() =>
                  setEditing({ name, ...p, api_key: "", _existing: true })
                }
              >
                Edit
              </Button>
              <Button
                onClick={() =>
                  deleteProvider(name).then(load).catch(() => {})
                }
              >
                Remove
              </Button>
            </div>
            {result?.name === name && <Stages stages={result.stages} />}
          </li>
        ))}
      </ul>

      {!editing && (
        <div className="add-provider">
          <Label htmlFor="tmpl">Add one</Label>
          {/* Deliberately still a native <select>: this is an ACTION
             menu, not a value selector -- it always shows the
             placeholder, fires startFrom() on pick and resets
             immediately. Radix Select is built around holding a value,
             so forcing it here would mean fighting it to stay
             unselected; DropdownMenu is the right Radix primitive if
             this ever needs to match visually. */}
          <select
            id="tmpl"
            value=""
            onChange={(e) => e.target.value && startFrom(e.target.value)}
          >
            <option value="">Choose a starting point…</option>
            {Object.entries(templates).map(([k, t]) => (
              <option key={k} value={k}>
                {t.label}
              </option>
            ))}
          </select>
        </div>
      )}

      {editing && (
        <div className="edit-provider">
          {editing._note && <p className="hint">{editing._note}</p>}
          <div className="field">
            <Label>Name</Label>
            <Input
              type="text"
              value={editing.name}
              disabled={editing._existing}
              onChange={(e) =>
                setEditing({ ...editing, name: e.target.value })
              }
            />
          </div>
          <div className="field">
            <Label>Endpoint</Label>
            <Input
              type="text"
              value={editing.base_url || ""}
              onChange={(e) =>
                setEditing({ ...editing, base_url: e.target.value })
              }
            />
          </div>
          <div className="field">
            <Label>Model</Label>
            <Input
              type="text"
              value={editing.model || ""}
              onChange={(e) =>
                setEditing({ ...editing, model: e.target.value })
              }
            />
          </div>
          <div className="field">
            <Label>
              API key {editing.local && <span className="hint">(not needed locally)</span>}
            </Label>
            <Input
              type="password"
              placeholder={
                editing._existing ? "leave blank to keep the stored key" : ""
              }
              value={editing.api_key || ""}
              onChange={(e) =>
                setEditing({ ...editing, api_key: e.target.value })
              }
            />
          </div>
          <div className="row">
            <Button variant="primary" disabled={busy} onClick={save}>
              Save
            </Button>
            <Button onClick={() => setEditing(null)}>Cancel</Button>
          </div>
        </div>
      )}

      {error && <p className="error">{error}</p>}
      {result && result.ok && (
        <p className="ok">
          {result.name} is ready — it reached the model and followed the
          script format.
        </p>
      )}
    </div>
  );
}
