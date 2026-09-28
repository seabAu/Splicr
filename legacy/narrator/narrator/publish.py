"""Podcast RSS feed and transcript export.

The feed is regenerated from scratch every time from two small files in
narrator_data/ -- podcast-level settings and the list of published
episodes -- plus the builder below. The XML in narrator_output/ is a pure
derived artifact: never hand-edited, never parsed back in. A malformed
feed is always fixable by rebuilding rather than patched, and the episode
list (the thing worth keeping) stays in a format that's easy to read,
diff, and hand-fix if it ever needs it.
"""

import os
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import format_datetime

from .config import (load_podcast_settings, save_podcast_settings,
                     load_episodes, save_episodes, slugify, unique_path)
from .audio import duration_of

ITUNES_NS = "http://www.itunes.com/dtds/podcast-1.0.dtd"
ET.register_namespace("itunes", ITUNES_NS)

MIME_TYPES = {".mp3": "audio/mpeg", ".m4a": "audio/mp4",
             ".wav": "audio/wav", ".flac": "audio/flac"}
# Podcast directories overwhelmingly expect one of these two; the others
# are accepted by few if any, so publishing one is flagged, not silent.
WIDELY_SUPPORTED = {".mp3", ".m4a"}

# What Apple/Spotify actually require to accept a feed. Checked before
# writing, surfaced as a plain warning -- never blocks writing the file,
# since seeing the draft feed is often how you notice what's missing.
REQUIRED_CHANNEL_FIELDS = {
    "title": "podcast title", "author": "author name",
    "email": "owner email", "description": "podcast description",
    "artwork_url": "artwork URL (square, 1400-3000px, already hosted "
                   "somewhere)", "audio_base_url": "hosting URL for the "
                   "audio files",
}


def _itag(tag):
    return f"{{{ITUNES_NS}}}{tag}"


def mime_type_for(path):
    return MIME_TYPES.get(os.path.splitext(path)[1].lower(), "audio/mpeg")


def missing_channel_fields(settings):
    return [label for key, label in REQUIRED_CHANNEL_FIELDS.items()
           if not (settings.get(key) or "").strip()]


def _duration_str(seconds):
    seconds = int(round(seconds or 0))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def episode_from_render(last_render, title, description):
    """Build an episode record from a just-finished real render (a
    `state["last_render"]` dict -- never a sample or a voice comparison,
    neither of which set that key). Raises ValueError if the rendered file
    is no longer where it was saved, rather than publishing a dead link."""
    out_path = last_render["out_path"]
    if not os.path.isfile(out_path):
        raise ValueError("The rendered file is no longer where it was "
                         f"saved:\n{out_path}\n\nRe-run Generate, then "
                         "publish again.")
    root = last_render["cfg"]["root"]
    rel = os.path.relpath(out_path, root).replace(os.sep, "/")
    return {
        "title": title.strip() or os.path.splitext(os.path.basename(out_path))[0],
        "description": description.strip(),
        "pub_date": format_datetime(datetime.now(timezone.utc), usegmt=True),
        "audio_relpath": rel,
        "audio_bytes": os.path.getsize(out_path),
        "audio_type": mime_type_for(out_path),
        "duration_seconds": duration_of(out_path) or 0.0,
        "source_document": os.path.basename(last_render.get("source_path") or ""),
        "guid": rel,  # stable as long as the published file isn't moved
    }


def add_episode(episode):
    """Insert or replace (by guid -- the same output file republished
    updates its existing entry rather than duplicating it), number it, and
    save. Returns the updated episode list; does NOT write the XML --
    call write_feed() with the actual output root after this."""
    episodes = [e for e in load_episodes() if e.get("guid") != episode["guid"]]
    used = [e["episode_number"] for e in episodes if e.get("episode_number")]
    episode["episode_number"] = (max(used) + 1) if used else 1
    episodes.append(episode)
    episodes.sort(key=lambda e: e["pub_date"])
    save_episodes(episodes)
    return episodes


def remove_episode(guid):
    episodes = [e for e in load_episodes() if e.get("guid") != guid]
    save_episodes(episodes)
    return episodes


def build_feed_xml(settings, episodes):
    """The full RSS document as a string, from channel settings + episode
    records. Pure function of its inputs, so it's easy to test without
    touching disk."""
    rss = ET.Element("rss", version="2.0")
    ch = ET.SubElement(rss, "channel")
    ET.SubElement(ch, "title").text = settings.get("title") or "Untitled podcast"
    ET.SubElement(ch, "link").text = (settings.get("website")
                                      or settings.get("audio_base_url") or "")
    ET.SubElement(ch, "language").text = settings.get("language") or "en-us"
    ET.SubElement(ch, "description").text = settings.get("description") or ""
    ET.SubElement(ch, _itag("summary")).text = settings.get("description") or ""
    ET.SubElement(ch, _itag("author")).text = settings.get("author") or ""
    owner = ET.SubElement(ch, _itag("owner"))
    ET.SubElement(owner, _itag("name")).text = settings.get("author") or ""
    ET.SubElement(owner, _itag("email")).text = settings.get("email") or ""
    if settings.get("artwork_url"):
        ET.SubElement(ch, _itag("image"), href=settings["artwork_url"])
    ET.SubElement(ch, _itag("category"), text=settings.get("category")
                 or "Education")
    explicit = "true" if settings.get("explicit") else "false"
    ET.SubElement(ch, _itag("explicit")).text = explicit
    ET.SubElement(ch, "lastBuildDate").text = format_datetime(
        datetime.now(timezone.utc), usegmt=True)
    if episodes:
        ET.SubElement(ch, "pubDate").text = episodes[-1]["pub_date"]

    base = (settings.get("audio_base_url") or "").rstrip("/")
    for ep in episodes:
        item = ET.SubElement(ch, "item")
        ET.SubElement(item, "title").text = ep["title"]
        ET.SubElement(item, "description").text = ep["description"]
        ET.SubElement(item, _itag("summary")).text = ep["description"]
        url = f"{base}/{ep['audio_relpath']}" if base else ep["audio_relpath"]
        ET.SubElement(item, "enclosure", url=url,
                     length=str(ep["audio_bytes"]), type=ep["audio_type"])
        guid = ET.SubElement(item, "guid", isPermaLink="true" if base else "false")
        guid.text = url
        ET.SubElement(item, "pubDate").text = ep["pub_date"]
        ET.SubElement(item, _itag("duration")).text = _duration_str(
            ep["duration_seconds"])
        ET.SubElement(item, _itag("explicit")).text = explicit
        if ep.get("episode_number"):
            ET.SubElement(item, _itag("episode")).text = str(ep["episode_number"])

    ET.indent(rss, space="  ")
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(
        rss, encoding="unicode")


def feed_path(audio_root):
    return os.path.join(audio_root, "podcast.xml")


def write_feed(audio_root):
    """Rebuild podcast.xml in the output root from current settings +
    episodes. Call after add_episode/remove_episode, or whenever channel
    settings change. Returns (path, missing_field_labels)."""
    settings = load_podcast_settings()
    episodes = load_episodes()
    xml_text = build_feed_xml(settings, episodes)
    os.makedirs(audio_root, exist_ok=True)
    path = feed_path(audio_root)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(xml_text)
    return path, missing_channel_fields(settings)


# ---------------------------------------------------------------------------
# Transcript export


def export_transcript(source_path, out_dir):
    """Clean `source_path` exactly the way narration does, except headings
    come back as real Markdown headings instead of being spoken or
    dropped, and tables come back verbatim instead of narrated prose --
    a written companion of the same text that gets narrated, not a
    separate re-edit of the source. Returns (path, log, orig_words)."""
    from .documents import clean_document
    text, log, orig_words = clean_document(source_path, tables="keep",
                                           keep_headings="markup")
    stem = slugify(os.path.splitext(os.path.basename(source_path))[0], 60)
    os.makedirs(out_dir, exist_ok=True)
    out_path = unique_path(os.path.join(out_dir, stem + "_transcript.md"))
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(text.strip() + "\n")
    return out_path, log, orig_words
