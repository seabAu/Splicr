from __future__ import annotations

import json
from pathlib import Path

from splicr.pronunciation import TextCustomizationStore
from splicr.studio import (
    SqliteStudioStore,
    import_narrator_customizations,
    import_narrator_projects,
    import_narrator_voices,
    scan_narrator_data,
)


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def _narrator_data(tmp_path: Path) -> Path:
    root = tmp_path / "narrator_data"
    _write_json(
        root / "narrator_projects.json",
        [
            {
                "path": "C:/Documents/book.md",
                "label": "My Book",
                "cfg": {"engine": "kokoro", "voice": "af_heart"},
                "status": "rendered",
                "output": "C:/Narrator Output/book.wav",
                "updated": 1_700_000_000.0,
            }
        ],
    )
    _write_json(
        root / "narrator_settings.json",
        {
            "last_engine": "kokoro",
            "custom_voice_presets": [
                {
                    "label": "Announcer",
                    "speaker": "Ryan",
                    "instruct": "Bright and concise",
                    "created": 1_700_000_001.0,
                }
            ],
        },
    )
    _write_json(root / "narrator_podcast.json", {"title": "A Show"})
    _write_json(root / "narrator_episodes.json", [{"title": "Episode 1"}])
    _write_json(root / "narrator_pronunciations.json", {"SQL": "sequel"})
    _write_json(root / "narrator_substitutions.json", {"form": "expanded"})
    _write_json(root / "narrator_jobs.json", [{"id": "job-1", "status": "done"}])
    qwen = root / "voices" / "essayist"
    _write_json(qwen / "voice.json", {"description": "Thoughtful", "take": 2})
    (qwen / "reference.wav").write_bytes(b"RIFFreference")
    kokoro = root / "voices" / "kokoro"
    _write_json(
        kokoro / "my_narrator.json",
        {
            "label": "My Narrator",
            "lang_code": "a",
            "sources": [{"voice": "af_heart", "weight": 1.0}],
        },
    )
    (kokoro / "my_narrator.pt").write_bytes(b"tensor")
    return root


def test_scan_narrator_data_is_read_only_and_discovers_manifests(tmp_path) -> None:
    root = _narrator_data(tmp_path)
    before = {path: path.read_bytes() for path in root.rglob("*") if path.is_file()}

    snapshot = scan_narrator_data(root)

    after = {path: path.read_bytes() for path in root.rglob("*") if path.is_file()}
    assert after == before
    assert snapshot.projects[0].label == "My Book"
    assert snapshot.settings["last_engine"] == "kokoro"
    assert snapshot.podcast["title"] == "A Show"
    assert snapshot.episodes == ({"title": "Episode 1"},)
    assert snapshot.jobs == ({"id": "job-1", "status": "done"},)
    assert {voice.engine for voice in snapshot.voices} == {"kokoro", "qwen3"}
    assert all(voice.asset_path is not None for voice in snapshot.voices)
    assert snapshot.warnings == ()


def test_import_narrator_projects_is_idempotent_and_keeps_paths_external(tmp_path) -> None:
    root = _narrator_data(tmp_path)
    snapshot = scan_narrator_data(root)
    store = SqliteStudioStore(tmp_path / "splicr.sqlite3")
    store.initialize()

    first = import_narrator_projects(snapshot, store)
    second = import_narrator_projects(snapshot, store)

    assert first == second
    project = store.get_project(first[0].project_id)
    assert project.name == "My Book"
    assert project.source_text == ""
    assert project.source_name == "book.md"
    assert project.source_media_type == "text/markdown"
    assert project.metadata["legacy_source_path"] == "C:/Documents/book.md"
    assert project.metadata["legacy_render_config"] == {
        "engine": "kokoro",
        "voice": "af_heart",
    }
    assert len(store.list_projects()) == 1


def test_import_narrator_language_customizations_is_additive_and_idempotent(tmp_path) -> None:
    snapshot = scan_narrator_data(_narrator_data(tmp_path))
    customizations = TextCustomizationStore(tmp_path / "studio" / "language")
    customizations.save_substitution(source="existing", replacement="keep me")

    first = import_narrator_customizations(snapshot, customizations)
    second = import_narrator_customizations(snapshot, customizations)

    assert first.pronunciations == 1
    assert first.substitutions == 1
    assert second.pronunciations == 0
    assert second.substitutions == 0
    assert customizations.pronunciation_entries()[0].word == "sql"
    assert customizations.substitutions() == {
        "existing": "keep me",
        "form": "expanded",
    }


def test_import_narrator_voices_is_idempotent_and_keeps_assets_external(tmp_path) -> None:
    root = _narrator_data(tmp_path)
    snapshot = scan_narrator_data(root)
    store = SqliteStudioStore(tmp_path / "splicr.sqlite3")
    store.initialize()

    first = import_narrator_voices(snapshot, store)
    second = import_narrator_voices(snapshot, store)

    assert first == second
    assert len(first) == 3
    profiles = store.list_voice_profiles()
    assert {profile.kind.value for profile in profiles} == {"designed", "blend", "preset"}
    assert {profile.engine_id for profile in profiles} == {"kokoro", "qwen3"}
    assert all(profile.metadata["managed"] is False for profile in profiles)
    qwen = next(profile for profile in profiles if profile.kind.value == "designed")
    assert qwen.reference_audio_path == str(
        (root / "voices" / "essayist" / "reference.wav").resolve()
    )
    preset = next(profile for profile in profiles if profile.kind.value == "preset")
    assert preset.settings == {
        "speaker": "Ryan",
        "instructions": "Bright and concise",
    }


def test_scan_reports_bad_records_without_stopping_other_imports(tmp_path) -> None:
    root = tmp_path / "narrator_data"
    _write_json(
        root / "narrator_projects.json",
        [None, {"label": "missing path"}, {"path": "C:/Documents/good.txt"}],
    )
    (root / "narrator_settings.json").write_text("{broken", encoding="utf-8")

    snapshot = scan_narrator_data(root)

    assert [item.source_path for item in snapshot.projects] == ["C:/Documents/good.txt"]
    assert snapshot.settings == {}
    assert len(snapshot.warnings) == 3
