from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import re
import shutil
import sqlite3
import subprocess
import threading
import wave
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from email.utils import format_datetime
from pathlib import Path
from typing import Iterable
from urllib.parse import quote

from splicr.domain import JobNotFoundError, utc_now
from splicr.storage import LocalJobStorage
from splicr.store import SqliteJobStore

from .domain import Artifact, ArtifactKind, Project, RenderPlan, Take, TakeStatus
from .store import SqliteStudioStore
from .timeline import JobTimeline, build_job_timeline

ITUNES_NS = "http://www.itunes.com/dtds/podcast-1.0.dtd"
ATOM_NS = "http://www.w3.org/2005/Atom"
_HEADING_RE = re.compile(r"^(#{1,6})[ \t]+(.+?)[ \t]*#*[ \t]*$", re.MULTILINE)
_SAFE_ID_RE = re.compile(r"[^a-zA-Z0-9_.-]+")

ET.register_namespace("itunes", ITUNES_NS)
ET.register_namespace("atom", ATOM_NS)


class PublishingError(RuntimeError):
    """A local publishing operation could not be completed safely."""


@dataclass(frozen=True, slots=True)
class PodcastChannel:
    title: str = "SPLICR Podcast"
    author: str = ""
    owner_email: str = ""
    description: str = "Speech produced with SPLICR Studio."
    website_url: str = ""
    media_base_url: str = ""
    artwork_url: str = ""
    category: str = "Technology"
    language: str = "en-us"
    explicit: bool = False
    updated_at: str = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if not self.title.strip():
            raise ValueError("channel title must not be blank")
        if not self.description.strip():
            raise ValueError("channel description must not be blank")
        if self.media_base_url and not self.media_base_url.startswith(("http://", "https://")):
            raise ValueError("media base URL must begin with http:// or https://")


@dataclass(frozen=True, slots=True)
class ChapterCue:
    title: str
    seconds: float
    level: int


@dataclass(frozen=True, slots=True)
class PublishedEpisode:
    id: str
    take_id: str
    project_id: str
    audio_artifact_id: str
    title: str
    description: str
    publication_date: str
    episode_number: int
    media_path: str
    media_type: str
    media_size_bytes: int
    duration_seconds: float
    transcript_artifact_id: str | None = None
    chapters_artifact_id: str | None = None
    chapters: tuple[ChapterCue, ...] = ()
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)


class PublishingStore:
    """SQLite-backed channel and episode metadata for deterministic local feeds."""

    def __init__(self, database_path: Path) -> None:
        self.database_path = Path(database_path)
        self._lock = threading.RLock()

    def initialize(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock, self._connect() as connection:
            connection.executescript(
                """
                PRAGMA journal_mode = WAL;

                CREATE TABLE IF NOT EXISTS studio_podcast_channel (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    payload_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS studio_podcast_episodes (
                    id TEXT PRIMARY KEY,
                    take_id TEXT NOT NULL UNIQUE,
                    project_id TEXT NOT NULL,
                    audio_artifact_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL,
                    publication_date TEXT NOT NULL,
                    episode_number INTEGER NOT NULL CHECK (episode_number >= 1),
                    media_path TEXT NOT NULL,
                    media_type TEXT NOT NULL,
                    media_size_bytes INTEGER NOT NULL CHECK (media_size_bytes >= 0),
                    duration_seconds REAL NOT NULL CHECK (duration_seconds >= 0),
                    transcript_artifact_id TEXT,
                    chapters_artifact_id TEXT,
                    chapters_json TEXT NOT NULL DEFAULT '[]',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS studio_podcast_episodes_number_idx
                    ON studio_podcast_episodes(episode_number, publication_date, id);
                """
            )

    def get_channel(self) -> PodcastChannel:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT payload_json, updated_at FROM studio_podcast_channel WHERE id = 1"
            ).fetchone()
        if row is None:
            return PodcastChannel()
        payload = json.loads(row["payload_json"])
        payload["updated_at"] = row["updated_at"]
        return PodcastChannel(**payload)

    def save_channel(self, channel: PodcastChannel) -> PodcastChannel:
        updated = PodcastChannel(
            **{key: value for key, value in asdict(channel).items() if key != "updated_at"},
            updated_at=utc_now(),
        )
        payload = asdict(updated)
        payload.pop("updated_at")
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO studio_podcast_channel (id, payload_json, updated_at)
                VALUES (1, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    payload_json = excluded.payload_json,
                    updated_at = excluded.updated_at
                """,
                (json.dumps(payload, ensure_ascii=False, sort_keys=True), updated.updated_at),
            )
        return updated

    def get_episode(self, episode_id: str) -> PublishedEpisode:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM studio_podcast_episodes WHERE id = ?", (episode_id,)
            ).fetchone()
        if row is None:
            raise KeyError(f"published episode not found: {episode_id}")
        return self._episode_from_row(row)

    def get_episode_for_take(self, take_id: str) -> PublishedEpisode | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM studio_podcast_episodes WHERE take_id = ?", (take_id,)
            ).fetchone()
        return self._episode_from_row(row) if row is not None else None

    def list_episodes(self) -> list[PublishedEpisode]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM studio_podcast_episodes
                ORDER BY episode_number, publication_date, id
                """
            ).fetchall()
        return [self._episode_from_row(row) for row in rows]

    def save_episode(self, episode: PublishedEpisode) -> PublishedEpisode:
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO studio_podcast_episodes (
                    id, take_id, project_id, audio_artifact_id, title, description,
                    publication_date, episode_number, media_path, media_type,
                    media_size_bytes, duration_seconds, transcript_artifact_id,
                    chapters_artifact_id, chapters_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(take_id) DO UPDATE SET
                    audio_artifact_id = excluded.audio_artifact_id,
                    title = excluded.title,
                    description = excluded.description,
                    publication_date = excluded.publication_date,
                    episode_number = excluded.episode_number,
                    media_path = excluded.media_path,
                    media_type = excluded.media_type,
                    media_size_bytes = excluded.media_size_bytes,
                    duration_seconds = excluded.duration_seconds,
                    transcript_artifact_id = excluded.transcript_artifact_id,
                    chapters_artifact_id = excluded.chapters_artifact_id,
                    chapters_json = excluded.chapters_json,
                    updated_at = excluded.updated_at
                """,
                (
                    episode.id,
                    episode.take_id,
                    episode.project_id,
                    episode.audio_artifact_id,
                    episode.title,
                    episode.description,
                    episode.publication_date,
                    episode.episode_number,
                    episode.media_path,
                    episode.media_type,
                    episode.media_size_bytes,
                    episode.duration_seconds,
                    episode.transcript_artifact_id,
                    episode.chapters_artifact_id,
                    json.dumps([asdict(cue) for cue in episode.chapters], ensure_ascii=False),
                    episode.created_at,
                    episode.updated_at,
                ),
            )
        return self.get_episode_for_take(episode.take_id) or episode

    def next_episode_number(self) -> int:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT COALESCE(MAX(episode_number), 0) + 1 AS number FROM studio_podcast_episodes"
            ).fetchone()
        return int(row["number"])

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=30.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    @staticmethod
    def _episode_from_row(row: sqlite3.Row) -> PublishedEpisode:
        chapters = tuple(ChapterCue(**item) for item in json.loads(row["chapters_json"]))
        return PublishedEpisode(
            id=row["id"],
            take_id=row["take_id"],
            project_id=row["project_id"],
            audio_artifact_id=row["audio_artifact_id"],
            title=row["title"],
            description=row["description"],
            publication_date=row["publication_date"],
            episode_number=row["episode_number"],
            media_path=row["media_path"],
            media_type=row["media_type"],
            media_size_bytes=row["media_size_bytes"],
            duration_seconds=row["duration_seconds"],
            transcript_artifact_id=row["transcript_artifact_id"],
            chapters_artifact_id=row["chapters_artifact_id"],
            chapters=chapters,
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


class PublishingService:
    """Build local transcript, chapter, media, and RSS artifacts from Studio takes."""

    def __init__(
        self,
        *,
        store: PublishingStore,
        studio_store: SqliteStudioStore,
        job_store: SqliteJobStore,
        job_storage: LocalJobStorage,
        output_root: Path,
    ) -> None:
        self.store = store
        self.studio_store = studio_store
        self.job_store = job_store
        self.job_storage = job_storage
        self.output_root = Path(output_root)

    def initialize(self) -> None:
        self.store.initialize()
        for directory in ("media", "transcripts", "chapters"):
            (self.output_root / directory).mkdir(parents=True, exist_ok=True)

    @property
    def feed_path(self) -> Path:
        return self.output_root / "podcast.xml"

    def list_sources(self) -> list[dict[str, object]]:
        sources: list[dict[str, object]] = []
        for project in self.studio_store.list_projects():
            for take in self.studio_store.list_takes(project.id):
                if take.status is not TakeStatus.COMPLETED:
                    continue
                audio = [
                    artifact
                    for artifact in self.studio_store.list_artifacts(take.id)
                    if artifact.kind is ArtifactKind.AUDIO and Path(artifact.path).is_file()
                ]
                if not audio:
                    continue
                sources.append(
                    {
                        "take_id": take.id,
                        "take_label": take.label,
                        "project_id": project.id,
                        "project_name": project.name,
                        "audio_artifacts": [self._artifact_mapping(item) for item in audio],
                    }
                )
        return sources

    def preview_chapters(self, take_id: str) -> tuple[ChapterCue, ...]:
        take, project, plan = self._source(take_id)
        timeline = self._timeline(plan)
        duration = timeline.duration if timeline is not None else self._take_duration(take)
        return chapter_cues(project.source_text, plan, timeline, duration)

    def export_transcript(self, take_id: str) -> Artifact:
        take, project, _ = self._source(take_id)
        text = project.source_text.strip() + "\n"
        return self._write_artifact(
            take,
            ArtifactKind.TRANSCRIPT,
            "transcripts",
            ".md",
            text.encode("utf-8"),
            "text/markdown; charset=utf-8",
        )

    def export_chapters(self, take_id: str) -> tuple[Artifact, tuple[ChapterCue, ...]]:
        take, _, _ = self._source(take_id)
        cues = self.preview_chapters(take_id)
        payload = youtube_chapters(cues).encode("utf-8")
        artifact = self._write_artifact(
            take,
            ArtifactKind.CHAPTERS,
            "chapters",
            ".txt",
            payload,
            "text/plain; charset=utf-8",
        )
        return artifact, cues

    def publish_episode(
        self,
        *,
        take_id: str,
        audio_artifact_id: str,
        title: str,
        description: str = "",
        publication_date: str | None = None,
        episode_number: int | None = None,
    ) -> PublishedEpisode:
        take, project, _ = self._source(take_id)
        if not title.strip():
            raise ValueError("episode title must not be blank")
        channel = self.store.get_channel()
        if not channel.media_base_url:
            raise ValueError("set the channel media base URL before publishing an episode")
        source = self.studio_store.get_artifact(audio_artifact_id)
        if source.take_id != take.id or source.kind is not ArtifactKind.AUDIO:
            raise ValueError("the selected audio artifact does not belong to this take")
        source_path = Path(source.path)
        if not source_path.is_file():
            raise FileNotFoundError(f"audio artifact is missing: {source_path}")

        existing = self.store.get_episode_for_take(take.id)
        number = episode_number or (
            existing.episode_number if existing is not None else self.store.next_episode_number()
        )
        if number < 1:
            raise ValueError("episode number must be at least 1")
        published_at = _validated_publication_date(publication_date)
        transcript = self.export_transcript(take.id)
        chapters_artifact, cues = self.export_chapters(take.id)
        digest = _sha256_file(source_path)
        suffix = source_path.suffix.casefold() or mimetypes.guess_extension(source.media_type) or ".audio"
        media_name = f"{_safe_id(take.id)}-{digest[:12]}{suffix}"
        media_path = self.output_root / "media" / media_name
        _atomic_copy(source_path, media_path)
        duration = _audio_duration(media_path)
        now = utc_now()
        episode = PublishedEpisode(
            id=existing.id if existing is not None else f"episode-{_safe_id(take.id)}",
            take_id=take.id,
            project_id=project.id,
            audio_artifact_id=source.id,
            title=title.strip(),
            description=description.strip(),
            publication_date=published_at,
            episode_number=number,
            media_path=str(media_path.resolve()),
            media_type=source.media_type,
            media_size_bytes=media_path.stat().st_size,
            duration_seconds=duration,
            transcript_artifact_id=transcript.id,
            chapters_artifact_id=chapters_artifact.id,
            chapters=cues,
            created_at=existing.created_at if existing is not None else now,
            updated_at=now,
        )
        saved = self.store.save_episode(episode)
        self.rebuild_feed()
        return saved

    def rebuild_feed(self) -> Path:
        payload = build_feed_xml(self.store.get_channel(), self.store.list_episodes())
        _atomic_write(self.feed_path, payload)
        return self.feed_path

    def episode_media_path(self, episode_id: str) -> Path:
        path = Path(self.store.get_episode(episode_id).media_path)
        if not path.is_file():
            raise FileNotFoundError(f"published media is missing: {path}")
        return path

    def artifact_path(self, artifact_id: str) -> Path:
        artifact = self.studio_store.get_artifact(artifact_id)
        if artifact.kind not in {ArtifactKind.TRANSCRIPT, ArtifactKind.CHAPTERS}:
            raise ValueError("artifact is not a publishing export")
        path = Path(artifact.path)
        try:
            path.resolve().relative_to(self.output_root.resolve())
        except ValueError as error:
            raise ValueError("artifact is outside the publishing workspace") from error
        if not path.is_file():
            raise FileNotFoundError(f"publishing artifact is missing: {path}")
        return path

    def _source(self, take_id: str) -> tuple[Take, Project, RenderPlan]:
        take = self.studio_store.get_take(take_id)
        if take.status is not TakeStatus.COMPLETED:
            raise ValueError("only completed takes can be published")
        return (
            take,
            self.studio_store.get_project(take.project_id),
            self.studio_store.get_render_plan(take.render_plan_id),
        )

    def _timeline(self, plan: RenderPlan) -> JobTimeline | None:
        job_id = plan.metadata.get("legacy_job_id")
        if not isinstance(job_id, str) or not job_id:
            return None
        try:
            return build_job_timeline(self.job_store, self.job_storage, job_id, waveform_buckets=1)
        except (JobNotFoundError, KeyError, ValueError, FileNotFoundError, wave.Error):
            return None

    def _take_duration(self, take: Take) -> float:
        for artifact in self.studio_store.list_artifacts(take.id):
            if artifact.kind is ArtifactKind.AUDIO and Path(artifact.path).is_file():
                return _audio_duration(Path(artifact.path))
        return 0.0

    def _write_artifact(
        self,
        take: Take,
        kind: ArtifactKind,
        directory: str,
        suffix: str,
        payload: bytes,
        media_type: str,
    ) -> Artifact:
        digest = hashlib.sha256(payload).hexdigest()
        artifact_id = f"publish-{kind.value}-{_safe_id(take.id)}-{digest[:12]}"
        for existing in self.studio_store.list_artifacts(take.id):
            if existing.id == artifact_id and Path(existing.path).is_file():
                return existing
        path = self.output_root / directory / f"{_safe_id(take.id)}-{digest[:12]}{suffix}"
        _atomic_write(path, payload)
        artifact = Artifact(
            id=artifact_id,
            project_id=take.project_id,
            take_id=take.id,
            kind=kind,
            path=str(path.resolve()),
            media_type=media_type,
            size_bytes=len(payload),
            sha256=digest,
        )
        try:
            return self.studio_store.add_artifact(artifact)
        except sqlite3.IntegrityError:
            return self.studio_store.get_artifact(artifact_id)

    @staticmethod
    def _artifact_mapping(artifact: Artifact) -> dict[str, object]:
        return {
            "id": artifact.id,
            "name": Path(artifact.path).name,
            "media_type": artifact.media_type,
            "size_bytes": artifact.size_bytes,
        }


def chapter_cues(
    source_text: str,
    plan: RenderPlan,
    timeline: JobTimeline | None,
    duration_seconds: float,
) -> tuple[ChapterCue, ...]:
    headings = list(_HEADING_RE.finditer(source_text))
    if not headings:
        return ()
    cues: list[ChapterCue] = []
    for match in headings:
        position = match.start()
        seconds = _position_seconds(position, len(source_text), plan, timeline, duration_seconds)
        title = re.sub(r"[*_`~]", "", match.group(2)).strip()
        if title:
            cues.append(ChapterCue(title=title, seconds=max(0.0, seconds), level=len(match.group(1))))
    if cues and cues[0].seconds > 1.5:
        cues.insert(0, ChapterCue(title="Introduction", seconds=0.0, level=1))
    return tuple(cues)


def youtube_chapters(cues: Iterable[ChapterCue]) -> str:
    lines = [f"{_format_duration(cue.seconds)} {cue.title}" for cue in cues]
    if not lines:
        return "No Markdown headings were found in this document.\n"
    if len(lines) < 3:
        lines.append("# YouTube chapter navigation requires at least three timestamps.")
    return "\n".join(lines) + "\n"


def build_feed_xml(channel: PodcastChannel, episodes: Iterable[PublishedEpisode]) -> bytes:
    root = ET.Element("rss", {"version": "2.0"})
    channel_node = ET.SubElement(root, "channel")
    _text(channel_node, "title", channel.title)
    _text(channel_node, "link", channel.website_url or channel.media_base_url)
    _text(channel_node, "language", channel.language)
    _text(channel_node, "description", channel.description)
    _text(channel_node, f"{{{ITUNES_NS}}}summary", channel.description)
    _text(channel_node, f"{{{ITUNES_NS}}}author", channel.author)
    _text(channel_node, f"{{{ITUNES_NS}}}explicit", "yes" if channel.explicit else "no")
    if channel.category:
        ET.SubElement(channel_node, f"{{{ITUNES_NS}}}category", {"text": channel.category})
    if channel.artwork_url:
        ET.SubElement(channel_node, f"{{{ITUNES_NS}}}image", {"href": channel.artwork_url})
        image = ET.SubElement(channel_node, "image")
        _text(image, "url", channel.artwork_url)
        _text(image, "title", channel.title)
        _text(image, "link", channel.website_url or channel.media_base_url)
    if channel.author or channel.owner_email:
        owner = ET.SubElement(channel_node, f"{{{ITUNES_NS}}}owner")
        _text(owner, f"{{{ITUNES_NS}}}name", channel.author)
        _text(owner, f"{{{ITUNES_NS}}}email", channel.owner_email)
    feed_url = _public_url(channel.media_base_url, "podcast.xml")
    ET.SubElement(
        channel_node,
        f"{{{ATOM_NS}}}link",
        {"href": feed_url, "rel": "self", "type": "application/rss+xml"},
    )
    ordered = sorted(episodes, key=lambda item: item.episode_number, reverse=True)
    latest = _as_datetime(ordered[0].publication_date) if ordered else datetime.now(timezone.utc)
    _text(channel_node, "lastBuildDate", format_datetime(latest))
    for episode in ordered:
        item = ET.SubElement(channel_node, "item")
        _text(item, "title", episode.title)
        _text(item, "description", episode.description)
        _text(item, "guid", episode.id)
        _text(item, "pubDate", format_datetime(_as_datetime(episode.publication_date)))
        _text(item, f"{{{ITUNES_NS}}}episode", str(episode.episode_number))
        _text(item, f"{{{ITUNES_NS}}}duration", _format_duration(episode.duration_seconds))
        ET.SubElement(
            item,
            "enclosure",
            {
                "url": _public_url(channel.media_base_url, f"media/{Path(episode.media_path).name}"),
                "length": str(episode.media_size_bytes),
                "type": episode.media_type,
            },
        )
    ET.indent(root, space="  ")
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def _position_seconds(
    position: int,
    source_length: int,
    plan: RenderPlan,
    timeline: JobTimeline | None,
    duration_seconds: float,
) -> float:
    if timeline is not None:
        by_index = {segment.index: segment for segment in timeline.segments}
        for segment in plan.segments:
            if segment.source_start <= position < segment.source_end:
                timing = by_index.get(segment.ordinal)
                if timing is not None:
                    fraction = (position - segment.source_start) / max(
                        1, segment.source_end - segment.source_start
                    )
                    return timing.start + timing.duration * min(1.0, max(0.0, fraction))
        if position <= plan.segments[0].source_start:
            return 0.0
        return timeline.duration
    if source_length <= 0 or duration_seconds <= 0:
        return 0.0
    return duration_seconds * min(1.0, max(0.0, position / source_length))


def _validated_publication_date(value: str | None) -> str:
    if value is None or not value.strip():
        return datetime.now(timezone.utc).isoformat()
    parsed = _as_datetime(value)
    return parsed.isoformat()


def _as_datetime(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("publication date must be an ISO 8601 date or date-time") from error
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _audio_duration(path: Path) -> float:
    if path.suffix.casefold() in {".wav", ".wave"}:
        try:
            with wave.open(str(path), "rb") as stream:
                return stream.getnframes() / max(1, stream.getframerate())
        except wave.Error:
            pass
    ffprobe = shutil.which("ffprobe")
    if ffprobe is None:
        return 0.0
    completed = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    try:
        return max(0.0, float(completed.stdout.strip())) if completed.returncode == 0 else 0.0
    except ValueError:
        return 0.0


def _format_duration(seconds: float) -> str:
    total = max(0, int(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes}:{seconds:02d}"


def _public_url(base: str, relative: str) -> str:
    return f"{base.rstrip('/')}/{quote(relative, safe='/')}"


def _text(parent: ET.Element, name: str, value: str) -> None:
    node = ET.SubElement(parent, name)
    node.text = value


def _safe_id(value: str) -> str:
    return _SAFE_ID_RE.sub("-", value).strip("-.") or "item"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.part")
    try:
        temporary.write_bytes(payload)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _atomic_copy(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.is_file() and destination.stat().st_size == source.stat().st_size:
        return
    temporary = destination.with_name(f".{destination.name}.{os.getpid()}.part")
    try:
        shutil.copy2(source, temporary)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
