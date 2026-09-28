import React, { useEffect, useState } from "react";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

// Radix Select reserves "" internally, so "no filter" needs its own
// sentinel; mapped back to "" at the component boundary.
const ANY = "__any__";
import { listJobs, pollJob, clearJobHistory } from "./api";
import { Button } from "@/components/ui/button";

// Filtering happens on the server, so a long history isn't shipped over
// the wire just to be searched here.

const STATUS_MARK = {
  running: "•",
  done: "✓",
  failed: "✗",
  cancelled: "–",
  pending: "…",
};

function when(seconds) {
  if (!seconds) return "";
  const date = new Date(seconds * 1000);
  const today = new Date().toDateString() === date.toDateString();
  return today
    ? date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
    : date.toLocaleDateString([], { month: "short", day: "numeric" });
}

function howLong(seconds) {
  if (!seconds || seconds < 1) return "";
  if (seconds < 60) return `${Math.round(seconds)}s`;
  const m = Math.floor(seconds / 60);
  return m < 60 ? `${m}m ${Math.round(seconds % 60)}s` : `${Math.floor(m / 60)}h ${m % 60}m`;
}

function Details({ job }) {
  const [lines, setLines] = useState(job.lines || []);
  const [loading, setLoading] = useState(true);

  // A list entry carries no log lines, so the full record is fetched only
  // when a row is actually opened.
  useEffect(() => {
    let cancelled = false;
    pollJob(job.id, 0)
      .then((full) => !cancelled && setLines(full.lines || []))
      .catch(() => {})
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [job.id]);

  const detail = job.detail || {};
  return (
    <div className="job-details">
      {Object.keys(detail).length > 0 && (
        <dl className="job-meta">
          {Object.entries(detail).map(([k, v]) => (
            <React.Fragment key={k}>
              <dt>{k}</dt>
              <dd title={String(v)}>{String(v)}</dd>
            </React.Fragment>
          ))}
        </dl>
      )}
      {job.error && <p className="error">{job.error}</p>}
      {job.truncated && (
        <p className="hint">
          Showing the last {lines.length} of {job.total_lines} lines.
        </p>
      )}
      <pre>{loading ? "Loading…" : lines.join("\n") || "(no output)"}</pre>
    </div>
  );
}

export default function JobList({ refreshKey }) {
  const [jobs, setJobs] = useState([]);
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("");
  const [kind, setKind] = useState("");
  const [open, setOpen] = useState(null);
  const [error, setError] = useState("");

  const load = () =>
    listJobs({ query, status, kind })
      .then((r) => {
        setJobs(r.jobs);
        setError("");
      })
      .catch((e) => setError(String(e.message || e)));

  // Debounced so typing in the search box doesn't fire a request per
  // keystroke; also re-runs whenever a job finishes elsewhere.
  useEffect(() => {
    const timer = setTimeout(load, 200);
    return () => clearTimeout(timer);
  }, [query, status, kind, refreshKey]);

  // Keep running jobs current without hammering the server.
  useEffect(() => {
    if (!jobs.some((j) => j.status === "running")) return undefined;
    const timer = setInterval(load, 2000);
    return () => clearInterval(timer);
  }, [jobs, query, status, kind]);

  return (
    <section className="jobs">
      <h2>History</h2>
      <div className="job-filters">
        <Input
          type="search"
          placeholder="Search document, engine, voice, result…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        {/* "any" is a real sentinel rather than "" -- Radix reserves the
           empty string and rejects it as an Item value -- mapped back to
           "" here so the API call and the rest of the component are
           unchanged. */}
        <Select
          value={kind || ANY}
          onValueChange={(v) => setKind(v === ANY ? "" : v)}
        >
          <SelectTrigger className="w-36">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ANY}>any kind</SelectItem>
            <SelectItem value="render">render</SelectItem>
            <SelectItem value="queue">queue</SelectItem>
            <SelectItem value="transcribe">transcribe</SelectItem>
          </SelectContent>
        </Select>
        <Select
          value={status || ANY}
          onValueChange={(v) => setStatus(v === ANY ? "" : v)}
        >
          <SelectTrigger className="w-36">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ANY}>any status</SelectItem>
            <SelectItem value="running">running</SelectItem>
            <SelectItem value="done">done</SelectItem>
            <SelectItem value="failed">failed</SelectItem>
            <SelectItem value="cancelled">cancelled</SelectItem>
          </SelectContent>
        </Select>
      </div>
      {error && <p className="error">{error}</p>}
      {jobs.length === 0 && <p className="hint">Nothing matches.</p>}
      <ul className="job-rows">
        {jobs.map((job) => (
          <li key={job.id} className={`job ${job.status}`}>
            {/* Stays a native button: it's a full-width expandable row
               (like the file browser's), not an action button. */}
            <button
              type="button"
              className="job-row"
              onClick={() => setOpen(open === job.id ? null : job.id)}
            >
              <span className={`mark ${job.status}`}>
                {STATUS_MARK[job.status] || "?"}
              </span>
              <span className="job-label">{job.label || job.id}</span>
              <span className="job-kind">{job.kind}</span>
              <span className="job-outcome">
                {job.outcome || job.error || job.status}
              </span>
              <span className="job-when">
                {when(job.started)} {howLong(job.duration)}
              </span>
            </button>
            {open === job.id && <Details job={job} />}
          </li>
        ))}
      </ul>
      {jobs.length > 0 && (
        <Button
          variant="ghost"
          size="sm"
          className="mt-1"
          onClick={() =>
            clearJobHistory()
              .then(load)
              .catch((e) => setError(String(e.message || e)))
          }
        >
          Clear remembered history
        </Button>
      )}
    </section>
  );
}
