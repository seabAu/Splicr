import React, { useEffect, useRef, useState } from "react";
import {
  getTakes,
  getTimeline,
  fetchTimelineSpan,
  respliceSegment,
  getTimelineWords,
} from "./api";
import JobLog from "./JobLog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";

// An SVG canvas, not <canvas> -- there's no existing canvas precedent in
// this app, and SVG gives ordinary React elements with per-shape event
// handlers, which fits the rest of the codebase's declarative style
// better than an imperative draw loop. Mirrors the desktop's Tk Canvas
// draw()/on_press/on_move/on_release/select_index logic exactly: click
// jumps the playhead and selects the sentence under it, drag selects a
// range, both the waveform and the sentence list are views of the same
// data so selecting either picks the same sentence.

const W = 940;
const H = 130;

function fmt(t) {
  const s = Math.max(0, t);
  return `${Math.floor(s / 60)}:${(s % 60).toFixed(2).padStart(5, "0")}`;
}

function sentenceAt(sentences, t) {
  for (const item of sentences) {
    if (item.start <= t && t <= item.end) return item.index;
  }
  const next = sentences.find((item) => item.start > t);
  if (next) return next.index;
  return sentences.length ? sentences[sentences.length - 1].index : 0;
}

export default function TimelineEditor() {
  const [takes, setTakes] = useState([]);
  const [manifest, setManifest] = useState("");
  const [data, setData] = useState(null); // {out_path, engine, duration, waveform, sentences}
  const [loadError, setLoadError] = useState("");
  const [selected, setSelected] = useState(0);
  const [range, setRange] = useState(null); // [start, end] or null
  const [playhead, setPlayhead] = useState(0);
  const [editText, setEditText] = useState("");
  const [playUrl, setPlayUrl] = useState(null);
  const [words, setWords] = useState([]);
  const [wordsNote, setWordsNote] = useState("");
  const [status, setStatus] = useState("");
  const [statusOk, setStatusOk] = useState(true);
  const [jobId, setJobId] = useState(null);
  const [busy, setBusy] = useState(false);
  const dragStart = useRef(null);

  const note = (text, ok = true) => {
    setStatus(text);
    setStatusOk(ok);
  };

  useEffect(() => {
    getTakes()
      .then((r) => {
        setTakes(r.takes);
        setManifest((prev) =>
          prev || (r.takes.length ? r.takes[r.takes.length - 1].manifest : "")
        );
      })
      .catch((e) => setLoadError(String(e.message || e)));
  }, []);

  const openManifest = (m) => {
    if (!m) return;
    setLoadError("");
    setData(null);
    getTimeline(m)
      .then((d) => {
        setData(d);
        setSelected(0);
        setRange(null);
        setPlayhead(d.sentences[0]?.start || 0);
        setEditText(d.sentences[0]?.text || "");
      })
      .catch((e) => setLoadError(String(e.message || e)));
  };

  useEffect(() => {
    if (manifest) openManifest(manifest);
  }, [manifest]);

  const selectIndex = (i) => {
    if (!data) return;
    const idx = Math.max(0, Math.min(data.sentences.length - 1, i));
    setSelected(idx);
    setEditText(data.sentences[idx].text);
    setWords([]);
    setWordsNote("");
  };

  const cur = data?.sentences[selected];
  const total = data?.duration || 1;
  const xFor = (t) => (t / total) * W;
  const tFor = (x) => Math.max(0, Math.min(total, (x / W) * total));

  const svgPointFromEvent = (e) => {
    const rect = e.currentTarget.getBoundingClientRect();
    return tFor(((e.clientX - rect.left) / rect.width) * W);
  };

  const onPointerDown = (e) => {
    const t = svgPointFromEvent(e);
    dragStart.current = t;
    setRange(null);
    setPlayhead(t);
  };

  const onPointerMove = (e) => {
    if (dragStart.current === null) return;
    const a = dragStart.current;
    const b = svgPointFromEvent(e);
    if (Math.abs(b - a) > 0.05) {
      setRange([Math.min(a, b), Math.max(a, b)]);
    }
  };

  const onPointerUp = (e) => {
    if (dragStart.current === null) return;
    const a = dragStart.current;
    const b = svgPointFromEvent(e);
    dragStart.current = null;
    if (Math.abs(b - a) <= 0.05) {
      setRange(null);
      setPlayhead(a);
      selectIndex(sentenceAt(data.sentences, a));
    } else {
      const lo = Math.min(a, b);
      setRange([lo, Math.max(a, b)]);
      selectIndex(sentenceAt(data.sentences, lo));
    }
  };

  const playSelection = async () => {
    if (!cur) return;
    const [start, end] = range || [cur.start, cur.end];
    try {
      const url = await fetchTimelineSpan(manifest, start, end);
      setPlayUrl(url);
    } catch (e) {
      note(String(e.message || e), false);
    }
  };

  const loadWords = async () => {
    if (!cur) return;
    try {
      const r = await getTimelineWords(manifest, editText);
      setWords(r.words);
      setWordsNote(r.note || "");
    } catch (e) {
      note(String(e.message || e), false);
    }
  };

  const runFix = async (retry) => {
    if (!cur) return;
    if (!editText.trim()) {
      note("The sentence can't be empty.", false);
      return;
    }
    setBusy(true);
    note("Re-recording that sentence…");
    try {
      const job = await respliceSegment(
        manifest, cur.chunk, cur.seg, editText, retry
      );
      setJobId(job.id);
    } catch (e) {
      note(String(e.message || e), false);
      setBusy(false);
    }
  };

  return (
    <div className="timeline-editor">
      <div className="row">
<Label>Take</Label>
        <Select
          value={manifest || undefined}
          onValueChange={setManifest}
          disabled={takes.length === 0}
        >
          <SelectTrigger className="w-auto min-w-[16rem]">
            <SelectValue
              placeholder={takes.length === 0 ? "no takes yet" : "Choose a take…"}
            />
          </SelectTrigger>
          <SelectContent>
            {takes.map((t) => (
              <SelectItem key={t.manifest} value={t.manifest}>
                {t.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {loadError && <p className="error">{loadError}</p>}
      {!data && !loadError && takes.length > 0 && (
        <p className="hint">Loading…</p>
      )}

      {data && cur && (
        <>
          <svg
            className="timeline-canvas"
            viewBox={`0 0 ${W} ${H}`}
            width="100%"
            height={H}
            onPointerDown={onPointerDown}
            onPointerMove={onPointerMove}
            onPointerUp={onPointerUp}
          >
            <rect x={0} y={0} width={W} height={H} fill="#1b1b1b" />
            {data.waveform.length > 0 ? (
              data.waveform.map((v, i) => {
                const step = W / data.waveform.length;
                const x = i * step;
                const mid = H / 2;
                const h = v * (H / 2 - 6);
                return (
                  <line
                    key={i}
                    x1={x} x2={x} y1={mid - h} y2={mid + h}
                    stroke="#3d6d8f"
                  />
                );
              })
            ) : (
              <text x={W / 2} y={H / 2} fill="#888" textAnchor="middle">
                reading waveform…
              </text>
            )}
            {data.sentences.map((s) => (
              <line
                key={s.index}
                x1={xFor(s.start)} x2={xFor(s.start)} y1={0} y2={H}
                stroke="#2f2f2f"
              />
            ))}
            {range && (
              <rect
                x={xFor(range[0])} y={0}
                width={xFor(range[1]) - xFor(range[0])} height={H}
                fill="#4ea3ff" opacity={0.25}
              />
            )}
            <rect
              x={xFor(cur.start)} y={1}
              width={Math.max(1, xFor(cur.end) - xFor(cur.start))}
              height={H - 2}
              fill="none" stroke="#ffd24d" strokeWidth={2}
            />
            <line
              x1={xFor(playhead)} x2={xFor(playhead)} y1={0} y2={H}
              stroke="#ff7b4d"
            />
          </svg>
          <p className="hint timeline-pos">
            sentence {selected + 1} of {data.sentences.length} &nbsp;
            {fmt(cur.start)} - {fmt(cur.end)} &nbsp;(chunk {cur.chunk + 1})
            {range && ` \u00a0 selection ${fmt(range[0])} - ${fmt(range[1])}`}
          </p>

          <div className="timeline-body">
            <ul className="timeline-sentence-list">
              {data.sentences.map((s) => {
                let preview = s.text.trim().replace(/\n/g, " ");
                if (preview.length > 92) preview = preview.slice(0, 89) + "...";
                return (
                  <li
                    key={s.index}
                    className={s.index === selected ? "sel" : ""}
                    onClick={() => selectIndex(s.index)}
                  >
                    [{fmt(s.start)}] {preview}
                  </li>
                );
              })}
            </ul>

            <div className="timeline-side">
              <Label>Selected sentence</Label>
              <Textarea
                rows={6}
                value={editText}
                onChange={(e) => setEditText(e.target.value)}
              />
              {status && (
                <p className={statusOk ? "ok" : "error"}>{status}</p>
              )}

              <Label>Words in this sentence</Label>
              <ul className="timeline-words">
                {data.engine !== "kokoro" ? (
                  <li className="hint">per-word detail is Kokoro-only</li>
                ) : words.length === 0 ? (
                  <li className="hint">
                    {wordsNote || "click \u201cCheck pronunciation\u201d"}
                  </li>
                ) : (
                  words.map((w, i) => {
                    const mark = {
                      override: "*", dictionary: " ",
                      guessed: "~", unknown: "!",
                    }[w.source] || " ";
                    return (
                      <li key={i}>
                        {mark} {w.word} — {w.phonemes || "(cannot say)"}
                      </li>
                    );
                  })
                )}
              </ul>
              {data.engine === "kokoro" && (
                <Button onClick={loadWords}>Check pronunciation</Button>
              )}
              <p className="hint">
                To change how a word sounds, use the Pronunciation tab,
                then re-record this sentence.
              </p>

              <Button onClick={playSelection}>Play selection</Button>
              <Button disabled={busy} onClick={() => runFix(0)}>
                Re-record with edits
              </Button>
              <Button
                disabled={busy}
                onClick={() => runFix(Math.floor(Math.random() * 1000) + 1)}
              >
                Try again (same text)
              </Button>
              <p className="hint">
                Click the waveform to jump to a sentence, or drag to select
                a range. Re-recording replaces just that sentence in the
                finished file.
              </p>
            </div>
          </div>

          <JobLog
            jobId={jobId}
            onFinished={(snap) => {
              setBusy(false);
              if (snap.status === "done") {
                note("Done — reopening to show the updated waveform.");
                openManifest(manifest);
              } else if (snap.status === "failed") {
                note(snap.error || "Re-recording failed.", false);
              }
            }}
          />

          {playUrl && (
            <div className="row">
              <audio controls autoPlay src={playUrl} />
              <Button onClick={() => setPlayUrl(null)}>Close</Button>
            </div>
          )}
        </>
      )}
    </div>
  );
}
