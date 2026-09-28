import React, { useEffect, useState } from "react";
import {
  getVoicesFull,
  renameVoice,
  deleteVoice,
  auditionVoice,
  cloneVoiceUpload,
  fetchVoiceReference,
  getCustomSpeakers,
  fetchCustomSpeakers,
  saveCustomPreset,
  deleteCustomPreset,
  getEngines,
} from "./api";
import JobLog from "./JobLog";
import { Button } from "@/components/ui/button";
import { Play, Trash } from "@/components/ui/icons";
import { ConfirmDialog } from "@/components/ui/alert-dialog";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

const KIND_LABEL = { cloned: "clone", custom: "preset", designed: "design" };

function VoiceRow({ v, onRename, onDelete, onPlay }) {
  const [editing, setEditing] = useState(false);
  const [label, setLabel] = useState(v.label || "");
  // The label input's local state should track the saved label whenever
  // it's not actively being edited -- otherwise a second edit after a
  // successful rename would reopen showing the PREVIOUS typed value
  // (useState's initial value only applies once, on first mount), not
  // what was actually just saved.
  useEffect(() => {
    if (!editing) setLabel(v.label || "");
  }, [v.label, editing]);
  const when = v.created
    ? new Date(v.created * 1000).toISOString().slice(0, 10)
    : "";
  return (
    <li className="voice-row">
      <div className="voice-row-main">
        <span className="voice-kind">{KIND_LABEL[v.kind] || v.kind}</span>
        <span className="voice-engine">[{v.engine}]</span>
        {v.take ? <span className="voice-take">t{v.take}</span> : null}
        <span className="voice-when">{when}</span>
        {editing ? (
          <Input
            autoFocus
            value={label}
            onChange={(e) => setLabel(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                onRename(v, label);
                setEditing(false);
              } else if (e.key === "Escape") {
                setEditing(false);
              }
            }}
            onBlur={() => setEditing(false)}
          />
        ) : (
          <span className="voice-desc">
            {v.label ? `[${v.label}] ` : ""}
            {v.description}
          </span>
        )}
      </div>
      <div className="voice-row-actions">
        {v.has_reference && (
          <Button
            variant="ghost"
            size="icon"
            className="h-7 w-7"
            onClick={() => onPlay(v)}
            title="Play reference clip"
            aria-label="Play reference clip"
          >
            <Play className="h-3.5 w-3.5" />
          </Button>
        )}
        <Button variant="ghost" size="sm" onClick={() => setEditing(true)}>
          label
        </Button>
        <Button
          variant="ghost"
          size="icon"
          className="h-7 w-7 hover:text-destructive"
          onClick={() => onDelete(v)}
          title="Delete"
          aria-label="Delete this voice"
        >
          <Trash className="h-3.5 w-3.5" />
        </Button>
      </div>
    </li>
  );
}

export default function VoiceStudio() {
  const [voices, setVoices] = useState([]);
  const [status, setStatus] = useState("");
  const [statusOk, setStatusOk] = useState(true);
  const [playingUrl, setPlayingUrl] = useState(null);
  const [tab, setTab] = useState("audition");
  const [engines, setEngines] = useState([]);

  const note = (text, ok = true) => {
    setStatus(text);
    setStatusOk(ok);
  };

  const refresh = () =>
    getVoicesFull()
      .then((r) => setVoices(r.voices))
      .catch((e) => note(String(e.message || e), false));

  useEffect(() => {
    refresh();
    getEngines()
      .then((r) => setEngines(r.engines))
      .catch(() => {});
  }, []);

  const doPlay = async (v) => {
    try {
      const url = await fetchVoiceReference(v.folder);
      setPlayingUrl(url);
    } catch (e) {
      note(String(e.message || e), false);
    }
  };

  const doRename = async (v, label) => {
    try {
      await renameVoice(v.folder, label);
      refresh();
    } catch (e) {
      note(String(e.message || e), false);
    }
  };

  // Deleting is two steps now: doDelete opens the confirmation, and
  // reallyDelete runs once it's confirmed. The wording is unchanged --
  // it was already the right warning, it just lived in window.confirm.
  const [pendingDelete, setPendingDelete] = useState(null);

  const describeDelete = (v) =>
    v.kind === "custom"
      ? `Remove the saved preset "${v.label}"? The speaker itself is ` +
          "part of the model, not this app -- this only forgets the " +
          "label and instruction you saved."
        : `Delete the saved voice for:\n\n${v.description}` +
          (v.take ? ` (take ${v.take})` : "") +
          "\n\nAudio already rendered with it is untouched. " +
          (v.kind === "cloned"
            ? "A CLONED voice cannot be rebuilt without the original " +
              "recording."
            : "Re-rendering the same description and take will design " +
              "it again.");

  const doDelete = (v) => setPendingDelete(v);

  const reallyDelete = async (v) => {
    setPendingDelete(null);
    try {
      if (v.kind === "custom") {
        await deleteCustomPreset(v.label);
      } else {
        await deleteVoice(v.folder);
      }
      note("Deleted.");
      refresh();
    } catch (e) {
      note(String(e.message || e), false);
    }
  };

  return (
    <div className="voice-studio">
      <ConfirmDialog
        pending={pendingDelete}
        title={
          pendingDelete?.kind === "custom" ? "Remove this preset?" : "Delete this voice?"
        }
        description={pendingDelete ? describeDelete(pendingDelete) : ""}
        confirmLabel={pendingDelete?.kind === "custom" ? "Remove" : "Delete"}
        onConfirm={reallyDelete}
        onCancel={() => setPendingDelete(null)}
      />
      <p className="hint">
        Voices are saved the first time they're used and reused after that,
        so the same description and take always give the same narrator.
      </p>

      <ul className="voice-list">
        {voices.map((v) => (
          <VoiceRow
            key={v.folder || v.label}
            v={v}
            onRename={doRename}
            onDelete={doDelete}
            onPlay={doPlay}
          />
        ))}
        {voices.length === 0 && (
          <li className="hint">
            No saved voices yet. Audition a description below, or clone one
            from a recording.
          </li>
        )}
      </ul>

      {playingUrl && (
        <div className="row">
          <audio controls autoPlay src={playingUrl} />
          <Button onClick={() => setPlayingUrl(null)}>Close</Button>
        </div>
      )}

      {status && (
        <p className={statusOk ? "ok" : "error"}>{status}</p>
      )}

      {/* Unlike the app's top-level tabs, these three genuinely SHOULD
         unmount when switched away (Radix's default): each is a
         short form whose half-filled state means nothing once you've
         moved to a different way of making a voice, and a fresh form on
         return is the friendlier behaviour. So no forceMount here. */}
      <Tabs value={tab} onValueChange={setTab} className="voice-tabs">
        <TabsList>
          {[
            ["audition", "Audition a description"],
            ["clone", "Clone from a recording"],
            ["custom", "CustomVoice (preset speakers)"],
          ].map(([key, label]) => (
            <TabsTrigger key={key} value={key}>
              {label}
            </TabsTrigger>
          ))}
        </TabsList>

        <TabsContent value="audition">
          <AuditionTab note={note} onDone={refresh} />
        </TabsContent>
        <TabsContent value="clone">
          <CloneTab note={note} onDone={refresh} engines={engines} />
        </TabsContent>
        <TabsContent value="custom">
          <CustomVoiceTab note={note} onDone={refresh} />
        </TabsContent>
      </Tabs>
    </div>
  );
}

function AuditionTab({ note, onDone }) {
  const [description, setDescription] = useState("");
  const [take, setTake] = useState(1);
  const [jobId, setJobId] = useState(null);
  const [busy, setBusy] = useState(false);

  const start = async () => {
    if (!description.trim()) {
      note("Describe the voice first.", false);
      return;
    }
    setBusy(true);
    note("Designing — progress is below.");
    try {
      const job = await auditionVoice(description, take);
      setJobId(job.id);
    } catch (e) {
      note(String(e.message || e), false);
      setBusy(false);
    }
  };

  return (
    <div className="voice-tab-body">
      <p className="hint">
        Designs the voice and saves its reference clip, without narrating a
        document. Takes a minute or so the first time.
      </p>
      <Input
        placeholder="Describe the voice — tone, pace, character…"
        value={description}
        onChange={(e) => setDescription(e.target.value)}
      />
      <div className="row">
        <Label>Take</Label>
        <Input
          type="number"
          min="1"
          max="99"
          style={{ width: 60 }}
          value={take}
          onChange={(e) => setTake(Number(e.target.value))}
        />
        <Button disabled={busy} onClick={start}>
          Audition
        </Button>
      </div>
      <JobLog
        jobId={jobId}
        onFinished={(snap) => {
          setBusy(false);
          if (snap.status === "done") {
            note("Done — it's in the list now.");
            onDone();
          } else if (snap.status === "failed") {
            note(snap.error || "Audition failed.", false);
          }
        }}
      />
    </div>
  );
}

function CloneTab({ note, onDone, engines }) {
  const [file, setFile] = useState(null);
  const [transcript, setTranscript] = useState("");
  const [description, setDescription] = useState("");
  const [engine, setEngine] = useState("qwen3");
  const [busy, setBusy] = useState(false);

  // Only engines that actually clone are worth offering here -- Kokoro
  // and edge-tts have no cloning path at all, so listing them would just
  // be a choice that always fails.
  const cloneCapable = engines.filter((e) =>
    ["qwen3", "audio8"].includes(e.key)
  );

  const start = async () => {
    if (!file) {
      note("Choose a recording first.", false);
      return;
    }
    if (!transcript.trim()) {
      note("Type exactly what you said in the recording.", false);
      return;
    }
    setBusy(true);
    note("Uploading and cloning…");
    try {
      await cloneVoiceUpload(
        file,
        transcript,
        description.trim() || "my own voice",
        engine
      );
      note("Saved. It's in the list now, and works like any other voice.");
      setFile(null);
      onDone();
    } catch (e) {
      note(String(e.message || e), false);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="voice-tab-body">
      <p className="hint">
        Record a few seconds of clear speech, then type exactly what you
        said — the engine matches the words against the audio to learn the
        voice. The recording is uploaded to this app and not sent anywhere
        else.
      </p>
      <div className="row">
        <Label>Engine</Label>
        <Select value={engine} onValueChange={setEngine}>
          <SelectTrigger className="w-auto min-w-[14rem]">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {(cloneCapable.length
              ? cloneCapable
              : [{ key: "qwen3", name: "Qwen3-TTS" }]
            ).map((e) => (
              <SelectItem key={e.key} value={e.key}>
                {e.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
      <div className="row">
        <Input
          type="file"
          accept="audio/*"
          onChange={(e) => setFile(e.target.files?.[0] || null)}
        />
        {file && <span className="hint">{file.name}</span>}
      </div>
      <Label>Exactly what you said:</Label>
      <Input
        value={transcript}
        onChange={(e) => setTranscript(e.target.value)}
      />
      <Label>A name for this voice:</Label>
      <Input
        value={description}
        onChange={(e) => setDescription(e.target.value)}
      />
      <Button disabled={busy} onClick={start}>
        {busy ? "Saving…" : "Save this voice"}
      </Button>
    </div>
  );
}

function CustomVoiceTab({ note, onDone }) {
  const [speakers, setSpeakers] = useState([]);
  const [speaker, setSpeaker] = useState("");
  const [instruct, setInstruct] = useState("");
  const [label, setLabel] = useState("");
  const [jobId, setJobId] = useState(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    getCustomSpeakers()
      .then((r) => {
        setSpeakers(r.speakers);
        if (r.speakers.length) setSpeaker((s) => s || r.speakers[0]);
      })
      .catch(() => {});
  }, []);

  const doFetch = async () => {
    setBusy(true);
    note("Fetching the speaker list — progress is below.");
    try {
      const job = await fetchCustomSpeakers();
      setJobId(job.id);
    } catch (e) {
      note(String(e.message || e), false);
      setBusy(false);
    }
  };

  const doSave = async () => {
    if (!speaker) {
      note("Fetch the speaker list and pick one first.", false);
      return;
    }
    if (!label.trim()) {
      note("Give it a name to save it under.", false);
      return;
    }
    try {
      await saveCustomPreset(label.trim(), speaker, instruct);
      note(`Saved "${label.trim()}".`);
      onDone();
    } catch (e) {
      note(String(e.message || e), false);
    }
  };

  return (
    <div className="voice-tab-body">
      <p className="hint">
        Qwen3's fixed studio speakers, plus an optional instruction for how
        to read it (e.g. "speak slowly and warmly"). The speaker list isn't
        bundled — fetching it downloads the CustomVoice model itself
        (several GB, one time).
      </p>
      <div className="row">
        <Label>Speaker</Label>
        <Select
          value={speaker || undefined}
          onValueChange={setSpeaker}
          disabled={speakers.length === 0}
        >
          <SelectTrigger className="w-auto min-w-[10rem]">
            <SelectValue
              placeholder={
                speakers.length === 0 ? "fetch the list first" : "Choose…"
              }
            />
          </SelectTrigger>
          <SelectContent>
            {speakers.map((sp) => (
              <SelectItem key={sp} value={sp}>
                {sp}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Button disabled={busy} onClick={doFetch}>
          Fetch speaker list…
        </Button>
      </div>
      <JobLog
        jobId={jobId}
        onFinished={(snap) => {
          setBusy(false);
          if (snap.status === "done") {
            const found = snap.result?.speakers || [];
            setSpeakers(found);
            if (found.length) setSpeaker(found[0]);
            note(`Found ${found.length} speaker(s).`);
          } else if (snap.status === "failed") {
            note(snap.error || "Fetching speakers failed.", false);
          }
        }}
      />
      <Label>Instruction (optional)</Label>
      <Input value={instruct} onChange={(e) => setInstruct(e.target.value)} />
      <Label>A name to save this as:</Label>
      <Input value={label} onChange={(e) => setLabel(e.target.value)} />
      <Button onClick={doSave}>Save as preset</Button>
    </div>
  );
}
