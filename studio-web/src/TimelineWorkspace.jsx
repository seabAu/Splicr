import React, { useEffect, useMemo, useRef, useState } from "react";
import {
  AudioLines,
  CheckCircle2,
  Clock3,
  LoaderCircle,
  Play,
  RefreshCw,
  Scissors,
  Sparkles,
} from "lucide-react";

import { api } from "./api.js";

const TERMINAL = new Set(["completed", "failed", "paused", "cancelled"]);

function formatTime(value) {
  if (!Number.isFinite(value)) return "0:00.000";
  const minutes = Math.floor(value / 60);
  const seconds = value - minutes * 60;
  return `${minutes}:${seconds.toFixed(3).padStart(6, "0")}`;
}

function takeLabel(take) {
  const date = new Date(take.updated_at);
  const stamp = Number.isNaN(date.getTime()) ? take.id.slice(0, 8) : date.toLocaleString();
  return `${take.provider} · ${take.voice} · ${stamp} · ${take.id.slice(0, 6)}`;
}

function TimelineEmpty({ loading, onNavigate }) {
  return (
    <section className="timeline-empty surface">
      {loading ? <LoaderCircle className="spin" size={28} /> : <AudioLines size={30} />}
      <div>
        <h2>{loading ? "Finding completed takes…" : "No editable takes yet"}</h2>
        <p>
          Completed narration and dialogue jobs appear here with their exact synthesis checkpoint
          timing. Render a take first, then return to shape it without starting over.
        </p>
      </div>
      {!loading && (
        <button className="primary-button" type="button" onClick={() => onNavigate("narrate")}>
          Create a take
        </button>
      )}
    </section>
  );
}

function Waveform({ timeline, selectedIndex, selection, onSelect, onSelectionChange }) {
  const svgRef = useRef(null);
  const dragStart = useRef(null);
  const [hoveredIndex, setHoveredIndex] = useState(null);
  const width = 1000;
  const height = 190;
  const center = height / 2;
  const waveform = timeline.waveform.length ? timeline.waveform : [0];
  const path = useMemo(() => {
    const upper = waveform.map((value, index) => {
      const x = waveform.length === 1 ? 0 : (index / (waveform.length - 1)) * width;
      const amplitude = Math.max(2, value * 78);
      return `${x.toFixed(2)},${(center - amplitude).toFixed(2)}`;
    });
    const lower = [...waveform].reverse().map((value, reverseIndex) => {
      const index = waveform.length - 1 - reverseIndex;
      const x = waveform.length === 1 ? width : (index / (waveform.length - 1)) * width;
      const amplitude = Math.max(2, value * 78);
      return `${x.toFixed(2)},${(center + amplitude).toFixed(2)}`;
    });
    return `M ${upper[0]} L ${upper.slice(1).join(" L ")} L ${lower.join(" L ")} Z`;
  }, [waveform]);

  const timeAtPointer = (event) => {
    const bounds = svgRef.current.getBoundingClientRect();
    const ratio = Math.max(0, Math.min(1, (event.clientX - bounds.left) / bounds.width));
    return ratio * timeline.duration;
  };
  const segmentAt = (time) =>
    timeline.segments.find((item) => time >= item.start && time <= item.end)
      || timeline.segments.at(-1);

  const handlePointerDown = (event) => {
    const time = timeAtPointer(event);
    dragStart.current = time;
    event.currentTarget.setPointerCapture(event.pointerId);
    onSelectionChange({ start: time, end: time });
  };
  const handlePointerMove = (event) => {
    const time = timeAtPointer(event);
    setHoveredIndex(segmentAt(time)?.index ?? null);
    if (dragStart.current !== null) {
      onSelectionChange({
        start: Math.min(dragStart.current, time),
        end: Math.max(dragStart.current, time),
      });
    }
  };
  const handlePointerUp = (event) => {
    const time = timeAtPointer(event);
    const start = Math.min(dragStart.current ?? time, time);
    const end = Math.max(dragStart.current ?? time, time);
    dragStart.current = null;
    const segment = segmentAt((start + end) / 2);
    if (segment) onSelect(segment, end - start >= 0.02);
  };

  const selectionX = timeline.duration ? (selection.start / timeline.duration) * width : 0;
  const selectionWidth = timeline.duration
    ? ((selection.end - selection.start) / timeline.duration) * width
    : 0;

  return (
    <div className="timeline-waveform-shell">
      <svg
        ref={svgRef}
        className="timeline-waveform"
        viewBox={`0 0 ${width} ${height}`}
        preserveAspectRatio="none"
        role="img"
        aria-label="Audio waveform with synthesis segment boundaries"
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={handlePointerUp}
        onPointerLeave={() => setHoveredIndex(null)}
      >
        {timeline.segments.map((segment) => {
          const x = (segment.start / timeline.duration) * width;
          const segmentWidth = ((segment.end - segment.start) / timeline.duration) * width;
          const active = segment.index === selectedIndex || segment.index === hoveredIndex;
          return (
            <rect
              key={segment.index}
              className={active ? "timeline-segment-zone active" : "timeline-segment-zone"}
              x={x}
              y="0"
              width={Math.max(1, segmentWidth)}
              height={height}
            />
          );
        })}
        <path className="timeline-waveform-shape" d={path} />
        {selectionWidth > 0.5 && (
          <rect
            className="timeline-selection"
            x={selectionX}
            y="0"
            width={selectionWidth}
            height={height}
          />
        )}
        {timeline.segments.slice(1).map((segment) => (
          <line
            key={segment.index}
            className="timeline-boundary"
            x1={(segment.start / timeline.duration) * width}
            x2={(segment.start / timeline.duration) * width}
            y1="0"
            y2={height}
          />
        ))}
      </svg>
      <div className="timeline-ruler">
        <span>{formatTime(0)}</span>
        <span>{formatTime(timeline.duration / 2)}</span>
        <span>{formatTime(timeline.duration)}</span>
      </div>
    </div>
  );
}

export function TimelineWorkspace({ onNavigate }) {
  const [takes, setTakes] = useState([]);
  const [takeId, setTakeId] = useState("");
  const [timeline, setTimeline] = useState(null);
  const [selectedIndex, setSelectedIndex] = useState(null);
  const [selection, setSelection] = useState({ start: 0, end: 0 });
  const [editText, setEditText] = useState("");
  const [selectionAudio, setSelectionAudio] = useState("");
  const [revisionJob, setRevisionJob] = useState(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");

  const loadTakes = async (preferredId = "") => {
    const loaded = await api.timelineTakes();
    setTakes(loaded);
    const next = preferredId && loaded.some((item) => item.id === preferredId)
      ? preferredId
      : loaded[0]?.id || "";
    setTakeId(next);
    return next;
  };

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    loadTakes()
      .catch((reason) => {
        if (!cancelled) setError(reason.message);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    if (!takeId) {
      setTimeline(null);
      return undefined;
    }
    let cancelled = false;
    setBusy("timeline");
    setError("");
    api.timeline(takeId)
      .then((loaded) => {
        if (cancelled) return;
        setTimeline(loaded);
        const first = loaded.segments[0] || null;
        setSelectedIndex(first?.index ?? null);
        setEditText(first?.text || "");
        setSelection(first ? { start: first.start, end: first.end } : { start: 0, end: 0 });
        setSelectionAudio("");
      })
      .catch((reason) => {
        if (!cancelled) setError(reason.message);
      })
      .finally(() => {
        if (!cancelled) setBusy("");
      });
    return () => { cancelled = true; };
  }, [takeId]);

  useEffect(() => {
    if (!revisionJob || TERMINAL.has(revisionJob.status)) return undefined;
    const timer = window.setInterval(async () => {
      try {
        const updated = await api.job(revisionJob.id);
        setRevisionJob(updated);
        if (updated.status === "completed") {
          window.clearInterval(timer);
          await loadTakes(updated.id);
        }
      } catch (reason) {
        setError(reason.message);
        window.clearInterval(timer);
      }
    }, 650);
    return () => window.clearInterval(timer);
  }, [revisionJob?.id, revisionJob?.status]);

  const selected = timeline?.segments.find((item) => item.index === selectedIndex) || null;
  const selectSegment = (segment, preserveSelection = false) => {
    setSelectedIndex(segment.index);
    setEditText(segment.text);
    if (!preserveSelection) {
      setSelection({ start: segment.start, end: segment.end });
    }
    setSelectionAudio("");
  };
  const playSelection = () => {
    if (!timeline || selection.end <= selection.start) return;
    setSelectionAudio(
      `${api.timelineSpanUrl(timeline.job_id, selection.start, selection.end)}&v=${Date.now()}`,
    );
  };
  const revise = async () => {
    if (!timeline || selectedIndex === null || !editText.trim()) return;
    setBusy("revise");
    setError("");
    try {
      setRevisionJob(
        await api.reviseTimelineSegment(timeline.job_id, selectedIndex, editText),
      );
    } catch (reason) {
      setError(reason.message);
    } finally {
      setBusy("");
    }
  };

  if (!takes.length && !timeline) {
    return (
      <main className="timeline-workspace">
        <header className="workspace-header">
          <div><p className="eyebrow">Non-destructive editor</p><h1>Timeline</h1></div>
        </header>
        {error && <p className="inline-error">{error}</p>}
        <TimelineEmpty loading={loading} onNavigate={onNavigate} />
      </main>
    );
  }

  return (
    <main className="timeline-workspace">
      <header className="workspace-header timeline-header">
        <div>
          <p className="eyebrow">Non-destructive editor</p>
          <h1>Shape the take, keep the checkpoints.</h1>
        </div>
        <label className="control timeline-take-picker">
          <span>Completed take</span>
          <select value={takeId} onChange={(event) => setTakeId(event.target.value)}>
            {takes.map((take) => <option key={take.id} value={take.id}>{takeLabel(take)}</option>)}
          </select>
        </label>
      </header>

      {error && <p className="inline-error">{error}</p>}
      {busy === "timeline" || !timeline ? (
        <section className="timeline-loading surface"><LoaderCircle className="spin" />Loading timeline…</section>
      ) : (
        <div className="timeline-layout">
          <section className="timeline-main-stack">
            <div className="surface timeline-canvas-card">
              <div className="section-heading">
                <div><p className="eyebrow">Exact synthesis checkpoints</p><h2>Waveform</h2></div>
                <span>{timeline.segments.length} segments · {formatTime(timeline.duration)}</span>
              </div>
              <Waveform
                timeline={timeline}
                selectedIndex={selectedIndex}
                selection={selection}
                onSelectionChange={(next) => { setSelection(next); setSelectionAudio(""); }}
                onSelect={selectSegment}
              />
              <div className="timeline-transport">
                <button className="secondary-button" type="button" onClick={playSelection} disabled={selection.end <= selection.start}>
                  <Play size={15} /> Play selection
                </button>
                <span><Clock3 size={14} />{formatTime(selection.start)} — {formatTime(selection.end)}</span>
              </div>
              {selectionAudio && <audio className="timeline-player" controls autoPlay src={selectionAudio} />}
              <audio className="timeline-player" controls src={timeline.audio_url || undefined} />
            </div>

            <div className="surface timeline-editor-card">
              <div className="section-heading compact">
                <div>
                  <p className="eyebrow">Selected checkpoint</p>
                  <h2>{selected ? `Segment ${selected.index + 1}` : "Select a segment"}</h2>
                </div>
                {selected && <span>{selected.speaker || selected.voice_id} · {selected.engine_id}</span>}
              </div>
              <textarea
                className="timeline-text-editor"
                value={editText}
                onChange={(event) => setEditText(event.target.value)}
                disabled={!selected}
                aria-label="Selected segment transcript"
              />
              <div className="timeline-edit-footer">
                <p>
                  A revision creates a new take. Every unchanged audio checkpoint is reused; only
                  this segment is synthesized again.
                </p>
                <button
                  className="primary-button"
                  type="button"
                  onClick={revise}
                  disabled={!selected || !editText.trim() || editText === selected.text || !!busy}
                >
                  {busy === "revise" ? <LoaderCircle className="spin" size={16} /> : <Scissors size={16} />}
                  Create revised take
                </button>
              </div>
              {revisionJob && (
                <div className={`timeline-revision-status ${revisionJob.status}`}>
                  {revisionJob.status === "completed" ? <CheckCircle2 size={17} /> : <LoaderCircle className={TERMINAL.has(revisionJob.status) ? "" : "spin"} size={17} />}
                  <div>
                    <strong>Revision {revisionJob.status}</strong>
                    <span>{revisionJob.completed_chunks} of {revisionJob.total_chunks} checkpoints ready</span>
                  </div>
                  <i>{Math.round(revisionJob.progress * 100)}%</i>
                </div>
              )}
            </div>
          </section>

          <aside className="surface timeline-segment-panel">
            <div className="section-heading compact">
              <div><p className="eyebrow">Transcript map</p><h2>Segments</h2></div>
              <Sparkles size={17} />
            </div>
            <p className="timeline-fidelity-note">
              Timing is exact at checkpoint boundaries. Sentence and word timing will appear when
              an engine supplies alignment data.
            </p>
            <div className="timeline-segment-list">
              {timeline.segments.map((segment) => (
                <button
                  key={segment.index}
                  className={segment.index === selectedIndex ? "active" : ""}
                  type="button"
                  onClick={() => selectSegment(segment)}
                >
                  <span>{String(segment.index + 1).padStart(2, "0")}</span>
                  <div><strong>{segment.speaker || segment.voice_id}</strong><p>{segment.text}</p></div>
                  <time>{formatTime(segment.start)}</time>
                </button>
              ))}
            </div>
          </aside>
        </div>
      )}
    </main>
  );
}
