"""Long-running work, tracked so an HTTP request doesn't have to wait for
it.

A render takes minutes to hours. That cannot live inside a request, so
every operation becomes a *job*: start it, get an id back immediately,
then poll status or subscribe to its log stream. The same shape works for
the desktop app, so this is not web-specific -- it is just the first time
the app has needed to name the thing it was already doing with threads.

`log` is the seam that makes this possible: every module in Narrator
already reports progress by calling a `log(message)` callable, so a job
simply supplies one that appends to its own buffer. Nothing underneath
had to change to become observable.
"""

import itertools
import json
import os
import threading
import time
import traceback

# Finished jobs are written here so "what did I run yesterday, and what
# came out of it" survives a restart. Only the tail of each log is kept:
# the point is to recognise a past job, not to re-read every line of it.
HISTORY_LIMIT = 200
HISTORY_LOG_LINES = 300


class Job:
    """One unit of background work and everything an interface needs to
    show about it."""

    _ids = itertools.count(1)

    def __init__(self, kind, label="", detail=None):
        self.id = f"{kind}-{next(Job._ids)}"
        self.kind = kind
        self.label = label
        # Whatever an interface needs to tell this job apart from a dozen
        # similar ones -- the document, engine and voice for a render.
        self.detail = dict(detail or {})
        # A one-line result in plain language, set by the work itself
        # since only it knows what "went well" means for its kind.
        self.outcome = ""
        self.status = "pending"      # pending|running|done|failed|cancelled
        self.lines = []
        self.result = None
        self.error = None
        self.started = time.time()
        self.finished = None
        self._cancel = threading.Event()
        self._lock = threading.Lock()
        # Bumped on every change so a client can tell "nothing new" from
        # "I missed something" without diffing the whole log.
        self.version = 0

    # --- what the work calls ---

    def log(self, message):
        with self._lock:
            self.lines.append(str(message))
            self.version += 1

    def cancelled(self):
        return self._cancel.is_set()

    # --- what an interface calls ---

    def cancel(self):
        self._cancel.set()
        self.log("Cancellation requested.")

    def duration(self):
        return (self.finished or time.time()) - self.started

    def search_text(self):
        """Everything worth matching a search box against, lowercased."""
        bits = [self.id, self.kind, self.label, self.outcome,
               self.error or ""]
        bits += [str(v) for v in self.detail.values()]
        return " ".join(bits).lower()

    def snapshot(self, since=0, with_lines=True):
        """Status plus only the log lines after `since`, so polling stays
        cheap on a job that has produced thousands of them. `with_lines`
        false gives just the summary, for a list view."""
        with self._lock:
            snap = {
                "id": self.id, "kind": self.kind, "label": self.label,
                "detail": dict(self.detail), "outcome": self.outcome,
                "status": self.status, "version": self.version,
                "total_lines": len(self.lines),
                "result": self.result, "error": self.error,
                "started": self.started, "finished": self.finished,
                "duration": self.duration(),
                "cancel_requested": self._cancel.is_set(),
            }
            snap["lines"] = self.lines[since:] if with_lines else []
            return snap


class JobStore:
    """Every job this process has run. In-memory on purpose: it mirrors
    `Session`, and a local tool that has been restarted has no running
    work to reattach to."""

    def __init__(self, keep=50, history_path=None):
        self._jobs = {}
        self._order = []
        self._keep = keep
        self._lock = threading.Lock()
        if history_path is None:
            from .config import DATA_DIR
            history_path = os.path.join(DATA_DIR, "narrator_jobs.json")
        self._history_path = history_path
        # Jobs finish on their own threads, so two can try to rewrite the
        # history at once. Without this, one truncates the file while
        # another is reading it and the result is an empty or half-written
        # file -- which is exactly what happened the first time.
        self._history_lock = threading.Lock()

    # --- history that outlives the process ---

    def history(self):
        """Past jobs from earlier runs, newest first. Never raises: a
        corrupt or missing history is an empty one, not a crash on
        startup."""
        try:
            with open(self._history_path, encoding="utf-8") as fh:
                return json.load(fh)
        except (OSError, ValueError):
            return []

    def _remember(self, job):
        record = job.snapshot(since=0, with_lines=True)
        record["truncated"] = record["total_lines"] > HISTORY_LOG_LINES
        record["lines"] = record["lines"][-HISTORY_LOG_LINES:]
        record["from_history"] = True
        with self._history_lock:
            entries = [e for e in self.history() if e.get("id") != job.id]
            entries.insert(0, record)
            del entries[HISTORY_LIMIT:]
            try:
                folder = os.path.dirname(self._history_path)
                if folder:
                    os.makedirs(folder, exist_ok=True)
                # Write a temp file and rename over the target: a rename is
                # atomic, so a reader sees either the old history or the new
                # one, never a half-written file. Writing in place would
                # leave an empty file if serialising failed partway.
                temp = self._history_path + ".tmp"
                with open(temp, "w", encoding="utf-8") as fh:
                    json.dump(entries, fh, indent=1, default=str)
                os.replace(temp, self._history_path)
            except (OSError, TypeError, ValueError):
                # History is a convenience, never load-bearing -- but do
                # not leave a stray temp file behind.
                try:
                    os.remove(self._history_path + ".tmp")
                except OSError:
                    pass

    def clear_history(self):
        try:
            os.remove(self._history_path)
        except OSError:
            pass
        return []

    def start(self, kind, target, label="", detail=None, **kwargs):
        """Run `target(job, **kwargs)` on a thread. `target` gets the job
        so it can call `job.log(...)`, check `job.cancelled()`, and set
        `job.outcome` to a one-line result."""
        job = Job(kind, label, detail)
        with self._lock:
            self._jobs[job.id] = job
            self._order.append(job.id)
            # Finished jobs are dropped oldest-first; a running one is
            # never evicted, however old, or its client would lose it.
            while len(self._order) > self._keep:
                for i, old in enumerate(self._order):
                    if self._jobs[old].status in ("done", "failed",
                                                  "cancelled"):
                        del self._jobs[old]
                        self._order.pop(i)
                        break
                else:
                    break

        def run():
            job.status = "running"
            try:
                job.result = target(job, **kwargs)
                job.status = "cancelled" if job.cancelled() else "done"
            except Exception as exc:
                job.status = "failed"
                job.error = f"{type(exc).__name__}: {exc}"
                job.log("Failed: " + job.error)
                job.log(traceback.format_exc().strip().splitlines()[-1])
            finally:
                job.finished = time.time()
                job.version += 1
                self._remember(job)

        threading.Thread(target=run, daemon=True).start()
        return job

    def get(self, job_id):
        return self._jobs.get(job_id)

    def list(self, query="", status="", kind="", include_history=True):
        """Summaries only -- no log lines -- newest first, with the
        current process's jobs ahead of remembered ones. Filtering happens
        here rather than in the client so a long history doesn't have to
        be shipped over the wire to be searched."""
        with self._lock:
            live = [self._jobs[i].snapshot(since=0, with_lines=False)
                   for i in reversed(self._order) if i in self._jobs]
        live_ids = {j["id"] for j in live}
        entries = list(live)
        if include_history:
            for record in self.history():
                if record.get("id") in live_ids:
                    continue
                summary = dict(record)
                summary["lines"] = []
                entries.append(summary)

        q = (query or "").strip().lower()
        out = []
        for entry in entries:
            if status and entry.get("status") != status:
                continue
            if kind and entry.get("kind") != kind:
                continue
            if q:
                haystack = " ".join([
                    str(entry.get("id", "")), str(entry.get("kind", "")),
                    str(entry.get("label", "")), str(entry.get("outcome", "")),
                    str(entry.get("error") or ""),
                    " ".join(str(v) for v in (entry.get("detail") or {}).values()),
                ]).lower()
                if q not in haystack:
                    continue
            out.append(entry)
        return out

    def get_record(self, job_id):
        """A live job if it exists, otherwise the remembered one -- so a
        job from an earlier run can still be opened and read."""
        job = self.get(job_id)
        if job is not None:
            return job.snapshot(since=0)
        for record in self.history():
            if record.get("id") == job_id:
                return record
        return None
