from __future__ import annotations

import asyncio
import json
import sys
from dataclasses import replace
from pathlib import Path

from fastapi.testclient import TestClient

from splicr.api import create_app
from splicr.config import Settings
from splicr.pronunciation import (
    PRONUNCIATION_REVISION_VARIABLE,
    PRONUNCIATION_VARIABLE,
    KokoroToolClient,
    TextCustomizationStore,
    apply_substitutions,
)
from splicr.providers import ProviderRegistry
from splicr.service import SynthesisService

from .fakes import RecordingProvider


def test_customization_store_round_trips_pronunciations_and_substitutions(
    tmp_path: Path,
) -> None:
    store = TextCustomizationStore(tmp_path / "language")

    entry = store.save_pronunciation(
        word="SPLICR",
        ipa="splɪkɚ",
        respelling="*split cur",
    )
    before_revision = store.pronunciation_revision()
    substitutions = store.save_substitution(source="Dr.", replacement="Doctor")

    assert entry.word == "splicr"
    assert store.pronunciation_entries() == (entry,)
    assert store.real_pronunciations(store.pronunciation_snapshot()) == {
        "splicr": "splɪkɚ"
    }
    assert substitutions == {"Dr.": "Doctor"}
    assert json.loads(store.pronunciations_path.read_text(encoding="utf-8")) == {
        "splicr": "splɪkɚ",
        "splicr__respelling": "*split cur",
    }

    store.save_pronunciation(word="SPLICR", ipa="new", respelling="new")
    assert store.pronunciation_revision() != before_revision
    assert store.delete_pronunciation("splicr") is True
    assert store.delete_substitution("Dr.") is True
    assert store.pronunciation_entries() == ()
    assert store.substitutions() == {}


def test_substitutions_are_case_insensitive_whole_words_and_longest_first() -> None:
    result, applied = apply_substitutions(
        "The State of Nature differs by state, not statement.",
        {
            "state": "province",
            "state of nature": "natural condition",
        },
    )

    assert result == "The natural condition differs by province, not statement."
    assert applied == {"state of nature": 1, "state": 1}


def test_substitution_replacement_is_literal_text() -> None:
    result, applied = apply_substitutions("token", {"token": r"\1 literal"})

    assert result == r"\1 literal"
    assert applied == {"token": 1}


def test_kokoro_job_freezes_pronunciation_snapshot(tmp_path: Path) -> None:
    async def scenario() -> None:
        settings = Settings(data_dir=tmp_path, pacing_seconds=0)
        provider = RecordingProvider()
        provider._info = replace(provider.info, name="kokoro-local")
        customizations = TextCustomizationStore(tmp_path / "language")
        customizations.save_pronunciation(
            word="splicr",
            ipa="splɪkɚ",
            respelling="*split cur",
        )
        service = SynthesisService(
            settings=settings,
            providers=ProviderRegistry([provider]),
            customizations=customizations,
        )
        service.store.initialize()
        service.storage.initialize()

        job = await service.submit(text="SPLICR", provider_name="kokoro-local")
        assert job.variables[PRONUNCIATION_VARIABLE] == {"splicr": "splɪkɚ"}
        assert job.variables[PRONUNCIATION_REVISION_VARIABLE] == (
            customizations.pronunciation_revision()
        )

        customizations.save_pronunciation(word="splicr", ipa="changed", respelling="changed")
        persisted = service.store.get_job(job.id)
        assert persisted.variables[PRONUNCIATION_VARIABLE] == {"splicr": "splɪkɚ"}

    asyncio.run(scenario())


def test_preview_and_job_apply_shared_substitutions(tmp_path: Path) -> None:
    async def scenario() -> None:
        settings = Settings(data_dir=tmp_path, pacing_seconds=0)
        provider = RecordingProvider()
        service = SynthesisService(
            settings=settings,
            providers=ProviderRegistry([provider]),
        )
        service.store.initialize()
        service.storage.initialize()
        service.customizations.save_substitution(source="SPLICR", replacement="split cur")

        preview = service.preview(text="Use SPLICR.", provider_name="fake")
        job = await service.submit(text="Use SPLICR.", provider_name="fake")

        assert [chunk.text for chunk in preview.chunks] == ["Use split cur."]
        assert [chunk.text for chunk in service.store.chunks_for_job(job.id)] == [
            "Use split cur."
        ]
        assert service.storage.source_path(job.id).read_text(encoding="utf-8") == "Use SPLICR."

    asyncio.run(scenario())


def test_pronunciation_and_substitution_api(tmp_path: Path, monkeypatch) -> None:
    settings = Settings(
        data_dir=tmp_path,
        kokoro_python=Path(sys.executable),
        pacing_seconds=0,
    )
    service = SynthesisService(
        settings=settings,
        providers=ProviderRegistry([RecordingProvider()]),
    )

    def fake_execute(self, operation, payload):
        del self
        if operation == "respell_to_ipa":
            return {"ipa": "splɪkɚ", "failed": None}
        if operation == "current_phonemes":
            return {
                "word": payload["word"],
                "phonemes": "splɪkɚ",
                "source": "override",
                "error": None,
            }
        return {
            "matches": [
                {"word": "splicr", "phonemes": "splɪkɚ", "source": "override"}
            ],
            "total": 1,
            "error": None,
        }

    monkeypatch.setattr(KokoroToolClient, "execute", fake_execute)
    with TestClient(create_app(settings=settings, service=service)) as client:
        assert client.get("/v1/studio/pronunciation/status").json()["available"] is True
        saved = client.put(
            "/v1/studio/pronunciations/splicr",
            json={"word": "splicr", "respelling": "*split cur"},
        )
        assert saved.status_code == 200
        assert saved.json() == {
            "word": "splicr",
            "ipa": "splɪkɚ",
            "respelling": "*split cur",
        }
        assert client.get("/v1/studio/pronunciations").json() == [saved.json()]
        assert client.get(
            "/v1/studio/pronunciation/search", params={"query": "spl"}
        ).json()["total"] == 1
        assert client.get(
            "/v1/studio/pronunciation/word", params={"word": "splicr"}
        ).json()["source"] == "override"

        assert client.post(
            "/v1/studio/substitutions",
            json={"source": "SPLICR", "replacement": "split cur"},
        ).json() == {"SPLICR": "split cur"}
        assert client.get("/v1/studio/substitutions").json() == {
            "SPLICR": "split cur"
        }
        assert client.delete(
            "/v1/studio/substitutions", params={"source": "SPLICR"}
        ).status_code == 204
        assert client.delete("/v1/studio/pronunciations/splicr").status_code == 204
