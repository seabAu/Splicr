"""The project library: a persisted, per-document record of the settings
last used and how far that document has gotten, so returning to an
earlier chapter next week doesn't mean reconstructing everything from
memory. This is the piece the queue (batch rendering several documents
unattended) builds on top of.

Pure data layer -- no Tk here. ui.py captures the actual widget state into
a cfg dict (already built for rendering) and restores it back into the
widgets; this module only keeps narrator_data/narrator_projects.json in
sync and answers "what do we know about this document."
"""

import os
import time

from .config import load_projects, save_projects

# A document's status only ever moves forward. Rendering a document a
# second time (to fix something) doesn't demote it from "published" back
# to "rendered" -- publishing is a stronger signal of progress than a
# single render, not the other way round.
STATUS_ORDER = ["not_started", "prepared", "rendered", "published"]
STATUS_LABELS = {"not_started": "not started", "prepared": "prepared",
                 "rendered": "rendered", "published": "published"}


def _label(path):
    return os.path.splitext(os.path.basename(path))[0]


def touch(path, cfg=None, status=None, output=None):
    """Add or update the entry for `path`. `cfg`, if given, REPLACES the
    saved settings (the latest render's settings are what you'd want back
    next time, not a merge with older ones). `status`, if given, only
    moves the entry forward along STATUS_ORDER -- never backward. Returns
    the updated entry."""
    projects = load_projects()
    entry = next((p for p in projects if p["path"] == path), None)
    if entry is None:
        entry = {"path": path, "label": _label(path), "cfg": {},
                 "status": "not_started", "output": None, "updated": 0.0}
        projects.append(entry)
    entry["label"] = _label(path)
    if cfg is not None:
        entry["cfg"] = cfg
    if output is not None:
        entry["output"] = output
    if status is not None and (STATUS_ORDER.index(status) >
                               STATUS_ORDER.index(entry["status"])):
        entry["status"] = status
    entry["updated"] = time.time()
    save_projects(projects)
    return entry


def remove(path):
    projects = [p for p in load_projects() if p["path"] != path]
    save_projects(projects)
    return projects


def all_projects():
    """Every known project, most recently touched first."""
    return sorted(load_projects(), key=lambda p: -p.get("updated", 0.0))


def relative_time(ts):
    if not ts:
        return "never"
    delta = max(0, time.time() - ts)
    if delta < 60:
        return "just now"
    if delta < 3600:
        m = int(delta // 60)
        return f"{m} minute{'s' if m != 1 else ''} ago"
    if delta < 86400:
        h = int(delta // 3600)
        return f"{h} hour{'s' if h != 1 else ''} ago"
    d = int(delta // 86400)
    if d < 30:
        return f"{d} day{'s' if d != 1 else ''} ago"
    return time.strftime("%Y-%m-%d", time.localtime(ts))
