import React, { useEffect, useState } from "react";
import {
  getTakes,
  getPodcast,
  savePodcast,
  publishTake,
  getChapters,
  embedChapters,
} from "./api";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

// Channel settings are true for every episode, so they live apart from
// the per-episode title and notes -- the same split the desktop app makes.
function ChannelSettings({ podcast, onSave }) {
  const [values, setValues] = useState(podcast.settings || {});
  const [saved, setSaved] = useState(false);

  const set = (key, value) => {
    setValues((prev) => ({ ...prev, [key]: value }));
    setSaved(false);
  };

  return (
    <details className="channel">
      <summary>
        Channel settings
        {podcast.missing?.length > 0 && (
          <span className="warn"> — {podcast.missing.length} still needed</span>
        )}
      </summary>
      <div className="settings">
        {Object.entries(podcast.fields || {}).map(([key, label]) => (
          <div className="field" key={key}>
            <Label htmlFor={`pod-${key}`}>{key}</Label>
            <Input
              id={`pod-${key}`}
              type="text"
              value={values[key] || ""}
              onChange={(e) => set(key, e.target.value)}
            />
            <p className="hint">{label}</p>
          </div>
        ))}
      </div>
      <Button
        onClick={async () => {
          await savePodcast(values);
          setSaved(true);
          onSave();
        }}
      >
        Save channel settings
      </Button>
      {saved && <span className="ok"> saved</span>}
    </details>
  );
}

export default function Publish({ refreshKey }) {
  const [takes, setTakes] = useState([]);
  const [take, setTake] = useState("");
  const [podcast, setPodcast] = useState({});
  const [title, setTitle] = useState("");
  const [notes, setNotes] = useState("");
  const [chapters, setChapters] = useState(null);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const load = () => {
    getTakes()
      .then((r) => {
        setTakes(r.takes);
        // Default to the most recent take, but never silently switch away
        // from one the person has deliberately chosen.
        setTake((prev) =>
          prev && r.takes.some((t) => t.name === prev)
            ? prev
            : r.takes.length
            ? r.takes[r.takes.length - 1].name
            : ""
        );
      })
      .catch((e) => setError(String(e.message || e)));
    getPodcast().then(setPodcast).catch(() => {});
  };

  useEffect(() => {
    load();
  }, [refreshKey]);

  const run = async (fn, describe) => {
    setBusy(true);
    setError("");
    setMessage("");
    try {
      const result = await fn();
      setMessage(describe(result));
      load();
    } catch (e) {
      setError(String(e.message || e));
    } finally {
      setBusy(false);
    }
  };

  if (takes.length === 0)
    return (
      <p className="hint">
        Nothing to publish yet — render something first.
      </p>
    );

  return (
    <div className="publish">
      <div className="row">
        <Label htmlFor="take">Take</Label>
        <Select
          value={take || undefined}
          onValueChange={(v) => {
            setTake(v);
            setChapters(null);
          }}
          disabled={takes.length === 0}
        >
          <SelectTrigger id="take" className="w-auto min-w-[16rem]">
            <SelectValue
              placeholder={takes.length === 0 ? "no takes yet" : "Choose a take…"}
            />
          </SelectTrigger>
          <SelectContent>
            {takes.map((t) => (
              <SelectItem key={t.out_path} value={t.name}>
                {t.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <div className="field">
        <Label htmlFor="ep-title">Episode title</Label>
        <Input
          id="ep-title"
          type="text"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
        />
      </div>
      <div className="field">
        <Label htmlFor="ep-notes">Episode notes</Label>
        <Textarea
          id="ep-notes"
          rows={3}
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
        />
      </div>

      <div className="row">
        <Button
          disabled={busy || !take}
          onClick={() =>
            run(
              () => publishTake(take, title, notes),
              (r) =>
                `Published episode ${r.episode.episode_number}. Feed rebuilt.` +
                (r.missing?.length
                  ? ` Still missing: ${r.missing.join(", ")}.`
                  : "") +
                (r.format_warning ? ` ${r.format_warning}` : "")
            )
          }
        >
          Publish to feed
        </Button>
        <Button
          disabled={busy || !take}
          onClick={() =>
            run(
              () => getChapters(take).then((r) => (setChapters(r), r)),
              (r) =>
                r.chapters.length
                  ? `Found ${r.chapters.length} chapter(s).`
                  : "No headings could be matched against this take."
            )
          }
        >
          Find chapters
        </Button>
        <Button
          disabled={busy || !take || !chapters?.chapters?.length}
          onClick={() =>
            run(
              () => embedChapters(take),
              (r) => `Embedded ${r.embedded} chapter marker(s) into the file.`
            )
          }
        >
          Embed into audio
        </Button>
      </div>

      {message && <p className="ok">{message}</p>}
      {error && <p className="error">{error}</p>}

      {chapters?.text && (
        <>
          <p className="hint">
            Paste into a YouTube description. Guessed from this document's
            headings.
          </p>
          <pre className="chapters">{chapters.text}</pre>
        </>
      )}

      <ChannelSettings podcast={podcast} onSave={load} />

      {podcast.episodes?.length > 0 && (
        <>
          <h3>In the feed</h3>
          <ul className="episodes">
            {podcast.episodes.map((e) => (
              <li key={e.guid}>
                <strong>{e.episode_number}.</strong> {e.title}{" "}
                <span className="hint">{e.pub_date}</span>
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}
