import React, { useEffect, useRef, useState } from "react";
import { subscribe, pollJob, cancelJob } from "./api";
import { Button } from "@/components/ui/button";

// Live progress for one job. Streams by default and falls back to polling
// if the stream drops -- a dropped connection must not look like a hung
// render, which is the failure mode that would waste the most time.
export default function JobLog({ jobId, onFinished }) {
  const [lines, setLines] = useState([]);
  const [status, setStatus] = useState("running");
  const [polling, setPolling] = useState(false);
  const seen = useRef(0);
  const bottom = useRef(null);

  useEffect(() => {
    if (!jobId) return undefined;
    let stopped = false;

    // `stopped` was set on cleanup but never checked. It now guards
    // against an event for a job this log has already moved away from.
    const apply = (snapshot) => {
      if (stopped) return;
      if (snapshot.streamFailed) {
        setPolling(true);
        return;
      }
      if (snapshot.lines?.length) {
        seen.current += snapshot.lines.length;
        setLines((prev) => [...prev, ...snapshot.lines]);
      }
      setStatus(snapshot.status);
      if (["done", "failed", "cancelled"].includes(snapshot.status)) {
        onFinished?.(snapshot);
      }
    };

    const close = subscribe(jobId, apply);
    return () => {
      stopped = true;
      close();
    };
  }, [jobId]);

  useEffect(() => {
    if (!polling || !jobId) return undefined;
    // A poll can still be in flight when the job changes or the log
    // unmounts; without this its late answer appended the OLD job's lines
    // and fired onFinished for a job no longer on screen.
    let cancelled = false;
    const timer = setInterval(async () => {
      try {
        const snapshot = await pollJob(jobId, seen.current);
        if (cancelled) return;
        if (snapshot.lines?.length) {
          seen.current += snapshot.lines.length;
          setLines((prev) => [...prev, ...snapshot.lines]);
        }
        setStatus(snapshot.status);
        if (["done", "failed", "cancelled"].includes(snapshot.status)) {
          clearInterval(timer);
          onFinished?.(snapshot);
        }
      } catch {
        /* keep trying; the server may just be busy */
      }
    }, 1000);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [polling, jobId]);

  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: "smooth" });
  }, [lines.length]);

  if (!jobId) return null;
  return (
    <div className="joblog">
      <div className="joblog-head">
        <strong>{status}</strong>
        {polling && <em> (stream dropped; polling instead)</em>}
        {status === "running" && (
          <Button onClick={() => cancelJob(jobId)}>Cancel</Button>
        )}
      </div>
      <pre>
        {lines.join("\n")}
        <span ref={bottom} />
      </pre>
    </div>
  );
}
