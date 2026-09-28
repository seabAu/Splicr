import React, { useEffect, useState } from "react";
import {
  getProviders,
  startScript,
  renderDialogue,
  dialogueSignoff,
  getEngines,
  getVoices,
  pollJob,
} from "./api";
import FileBrowser from "./FileBrowser";
import JobLog from "./JobLog";
import Providers from "./Providers";
import TurnEditor, { withIds } from "./TurnEditor";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

// The script is plain data and round-trips through its tagged text form
// at the two boundaries (a generation job returns it, a render request
// wants it back) -- so it can still be inspected or hand-edited outside
// the app if needed. In between, it's held as a structured turn list
// (see TurnEditor.jsx), because a right-click "refine this selection"
// popup needs to know which turn and which span within it a selection
// belongs to -- something a single flat block of tagged text can't
// answer without re-parsing on every keystroke.

export default function Dialogue({ cfg, onJob }) {
  const [providers, setProviders] = useState([]);
  const [provider, setProvider] = useState("");
  const [document, setDocument] = useState(cfg?.path || "");
  const [picking, setPicking] = useState(false);
  const [turns, setTurns] = useState([]);
  const [jobId, setJobId] = useState(null);
  const [voices, setVoices] = useState([]);
  const [voice1, setVoice1] = useState("");
  const [voice2, setVoice2] = useState("");
  const [showProviders, setShowProviders] = useState(false);
  const [status, setStatus] = useState("");
  const [error, setError] = useState("");
  const [options, setOptions] = useState({
    host1_name: "Alex",
    host2_name: "Sam",
    words_per_section: 320,
  });

  const loadProviders = () =>
    getProviders()
      .then((r) => {
        const names = Object.keys(r.providers);
        setProviders(names);
        setProvider((p) => (p && names.includes(p) ? p : names[0] || ""));
      })
      .catch(() => {});

  useEffect(() => {
    loadProviders();
    getEngines()
      .then(async (r) => {
        const engine =
          r.engines.find((e) => e.name === cfg?.engine) ||
          r.engines.find((e) => e.installed) ||
          r.engines[0];
        const presets = (engine?.voices || []).map((v) => ({
          ...v,
          kind: "preset",
        }));
        // Cloned voices are engine-specific -- a voice cloned for Qwen3
        // will fail if handed to Audio8's renderer and vice versa, so
        // only THIS engine's own clones are offered here, not every
        // clone in the library the way Voice studio's management view
        // shows them.
        let cloned = [];
        if (engine?.key) {
          try {
            const cr = await getVoices(engine.key);
            cloned = cr.voices.map((v) => ({
              id: v.id,
              label: `${v.label} (${v.kind === "cloned" ? "cloned" : v.kind})`,
              kind: v.kind,
            }));
          } catch {
            // A voices lookup failing shouldn't block presets from
            // showing -- cloning may just not be set up for this engine.
          }
        }
        const list = [...presets, ...cloned];
        setVoices(list);
        setVoice1((v) => (list.some((x) => x.id === v) ? v : list[0]?.id || ""));
        setVoice2((v) =>
          list.some((x) => x.id === v)
            ? v
            : list[1]?.id || list[0]?.id || ""
        );
      })
      .catch(() => {});
  }, [cfg?.engine]);

  const generate = async () => {
    setError("");
    setStatus("");
    try {
      const job = await startScript(document, provider, "", options);
      setJobId(job.id);
    } catch (e) {
      setError(String(e.message || e));
    }
  };

  // When the script job finishes, pull the turns into the editor.
  const onFinished = async (snapshot) => {
    onJob?.();
    if (snapshot.status !== "done") return;
    try {
      const full = await pollJob(snapshot.id, 0);
      const result = full.result;
      if (result?.turns?.length) {
        setTurns(withIds(result.turns));
        setStatus(
          `${result.turns.length} turns, about ${result.word_count} words` +
            (result.removed_duplicates
              ? `, ${result.removed_duplicates} repeated point(s) removed`
              : "")
        );
      }
    } catch (e) {
      setError(String(e.message || e));
    }
  };

  // The editor's ids are a UI concern only -- the render/signoff API
  // wants plain {speaker, text} the way a generation job returns them.
  const plainTurns = (list) =>
    list.map(({ speaker, text }) => ({ speaker, text }));

  const render = async (sample) => {
    setError("");
    try {
      const body = { ...cfg, path: document || cfg?.path };
      const job = sample
        ? await dialogueSignoff(
            body, voice1, voice2, plainTurns(turns.slice(0, 4)))
        : await renderDialogue(body, plainTurns(turns), voice1, voice2);
      setJobId(job.id);
    } catch (e) {
      setError(String(e.message || e));
    }
  };

  return (
    <div className="dialogue">
      <div className="row">
        <code>{document || "no document chosen"}</code>
        <Button onClick={() => setPicking(true)}>Choose…</Button>
      </div>
      {picking && (
        <FileBrowser
          onPick={(p) => {
            setDocument(p);
            setPicking(false);
          }}
          onClose={() => setPicking(false)}
        />
      )}

      <div className="row">
        <Label htmlFor="prov">Written by</Label>
        <Select
          value={provider || undefined}
          onValueChange={setProvider}
          disabled={providers.length === 0}
        >
          <SelectTrigger id="prov" className="w-auto min-w-[12rem]">
            <SelectValue
              placeholder={
                providers.length === 0 ? "none set up yet" : "Choose a provider…"
              }
            />
          </SelectTrigger>
          <SelectContent>
            {providers.map((p) => (
              <SelectItem key={p} value={p}>
                {p}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Button onClick={() => setShowProviders((s) => !s)}>
          {showProviders ? "Hide" : "Providers…"}
        </Button>
      </div>

      {showProviders && <Providers onChange={loadProviders} />}

      <div className="settings">
        {[
          ["host1_name", "First host"],
          ["host2_name", "Second host"],
          ["words_per_section", "Words per section"],
        ].map(([key, label]) => (
          <div className="field" key={key}>
            <Label htmlFor={`o-${key}`}>{label}</Label>
            <Input
              id={`o-${key}`}
              type={key === "words_per_section" ? "number" : "text"}
              value={options[key]}
              onChange={(e) =>
                setOptions({
                  ...options,
                  [key]:
                    key === "words_per_section"
                      ? Number(e.target.value)
                      : e.target.value,
                })
              }
            />
          </div>
        ))}
      </div>

      <Button
        variant="primary"
        className="my-4"
        disabled={!document || !provider}
        onClick={generate}
      >
        Write the script
      </Button>
      {status && <p className="ok">{status}</p>}
      {error && <p className="error">{error}</p>}

      <JobLog jobId={jobId} onFinished={onFinished} />

      {turns.length > 0 && (
        <>
          <h3>
            The script <span className="hint">({turns.length} turns)</span>
          </h3>
          <TurnEditor
            turns={turns}
            onChange={setTurns}
            hosts={{ host1: options.host1_name, host2: options.host2_name }}
            provider={provider}
          />

          <div className="row">
            <Label>Voices</Label>
            <Select
              value={voice1 || undefined}
              onValueChange={setVoice1}
              disabled={voices.length === 0}
            >
              <SelectTrigger>
                <SelectValue placeholder="Choose a voice…" />
              </SelectTrigger>
              <SelectContent>
                {voices.map((v) => (
                  <SelectItem key={v.id} value={v.id}>
                    {v.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Select
              value={voice2 || undefined}
              onValueChange={setVoice2}
              disabled={voices.length === 0}
            >
              <SelectTrigger>
                <SelectValue placeholder="Choose a voice…" />
              </SelectTrigger>
              <SelectContent>
                {voices.map((v) => (
                  <SelectItem key={v.id} value={v.id}>
                    {v.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          {voice1 && voice1 === voice2 && (
            <p className="warn">
              Both hosts are set to the same voice — the conversation will
              sound like one person talking to themselves.
            </p>
          )}

          <div className="row">
            <Button disabled={!turns.length} onClick={() => render(true)}>
              Hear a sample
            </Button>
            <Button
              variant="primary"
              disabled={!turns.length}
              onClick={() => render(false)}
            >
              Render the whole thing
            </Button>
          </div>
        </>
      )}
    </div>
  );
}
