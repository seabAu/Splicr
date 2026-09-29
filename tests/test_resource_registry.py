from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path

import pytest

from splicr.api_resources import (
    AdapterType,
    ApiAuthSpec,
    ApiResourceSpec,
    ApiResponseSpec,
    ApiVariableDefinition,
    AuthMode,
    CapabilityMode,
    HttpMethod,
    InputLimits,
    LimitBasis,
    PacingPolicy,
    ResponseMode,
    SqliteApiResourceStore,
    TtsCapabilities,
    TtsDefaults,
    TtsVoiceSpec,
)
from splicr.config import Settings
from splicr.domain import (
    ControlMode,
    ProviderInfo,
    TonePreset,
    UnknownProviderError,
)
from splicr.providers.deepgram import DeepgramTtsProvider
from splicr.providers.gemini import GeminiTtsProvider
from splicr.providers.generic_rest import (
    GenericRestResponseMode,
    GenericRestTtsProvider,
)
from splicr.providers.inworld import InworldTtsProvider
from splicr.resource_registry import ResourceProviderRegistry
from splicr.secret_vault import InMemorySecretVault


def _store(
    database_path: Path,
    *,
    environ: dict[str, str] | None = None,
    seed_builtins: bool = False,
) -> SqliteApiResourceStore:
    store = SqliteApiResourceStore(
        database_path,
        vault=InMemorySecretVault(),
        environ={} if environ is None else environ,
    )
    store.initialize(seed_builtins=seed_builtins)
    return store


def _resource(
    resource_id: str = "custom",
    *,
    name: str = "Custom REST",
    base_url: str = "https://speech.example.test/v1/synthesize",
) -> ApiResourceSpec:
    return ApiResourceSpec(
        resource_id=resource_id,
        revision=1,
        name=name,
        adapter_type=AdapterType.GENERIC_REST,
        method=HttpMethod.POST,
        base_url=base_url,
        auth=ApiAuthSpec(
            mode=AuthMode.HEADER,
            name="Authorization",
            prefix="Bearer ",
        ),
        headers={"X-Locale": "${locale}"},
        query={"voice": "${voice}"},
        request_template={
            "input": {"text": "${text}", "voice": "${voice}"},
            "tags": ("locale:${locale}", True),
        },
        variables=(
            ApiVariableDefinition("text", required=True),
            ApiVariableDefinition("voice", required=True),
            ApiVariableDefinition(
                "locale",
                label="Language locale",
                description="Locale sent to the custom endpoint.",
                group="Voice",
                default="en-US",
                choices=("en-US", "en-GB"),
                visible_when={"regional": True},
            ),
        ),
        response=ApiResponseSpec(ResponseMode.JSON_BASE64_PCM, json_pointer="/audio/data"),
        defaults=TtsDefaults(
            default_model="speech-v2",
            default_voice="narrator",
            models=("speech-v2",),
            voices=(TtsVoiceSpec("narrator", traits=("warm",)),),
        ),
        input_limits=InputLimits(
            max_bytes=8_000,
            max_tokens=2_000,
            max_characters=4_000,
            max_words=700,
            recommended_bytes=3_000,
            recommended_words=300,
            recommended_characters=2_500,
            limit_basis=LimitBasis.BODY,
        ),
        pacing=PacingPolicy(minimum_interval_seconds=0.5, requests_per_minute=30),
        capabilities=TtsCapabilities(
            tone_presets=("neutral", "warm"),
            tone_modes=(CapabilityMode.NATIVE_ENUM,),
            supports_custom_instructions=True,
        ),
    )


def test_generic_resource_maps_endpoint_secret_templates_limits_and_capabilities(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path / "resources.sqlite3")
    store.create(_resource(), api_key="vault-secret")
    registry = ResourceProviderRegistry(store, settings=Settings(trust_env_proxies=True))

    provider = registry.get("  CUSTOM ")

    assert isinstance(provider, GenericRestTtsProvider)
    assert provider.info.name == "custom"
    assert provider.info.max_input_bytes == 8_000
    assert provider.info.max_input_tokens == 2_000
    assert provider.info.max_input_characters == 4_000
    assert provider.info.recommended_chunk_words == 300
    assert provider.info.minimum_request_interval_seconds == 2.0
    assert provider.info.capabilities.tone_presets == (TonePreset.NEUTRAL, TonePreset.WARM)
    assert provider.info.capabilities.tone_modes == (ControlMode.NATIVE_ENUM,)
    assert provider.info.capabilities.voices[0].traits == ("warm",)
    control = provider.info.capabilities.control_definitions[0]
    assert control.key == "locale"
    assert control.label == "Language locale"
    assert control.group == "Voice"
    assert control.choices == ("en-US", "en-GB")
    assert control.visible_when[0].key == "regional"
    assert control.visible_when[0].equals is True
    assert provider.info.capabilities.allows_undeclared_variables is False
    assert provider._api_key == "vault-secret"
    assert provider._trust_env_proxies is True
    assert provider._spec.url == "https://speech.example.test/v1/synthesize"
    assert provider._spec.response_mode == GenericRestResponseMode.JSON_BASE64_RAW_PCM16
    assert provider._spec.response_json_pointer == "/audio/data"
    assert provider._spec.limit_basis == "body"
    assert provider._spec.headers["X-Locale"] == "{{locale}}"
    assert provider._spec.query["voice"] == "{{voice}}"
    assert provider._spec.body_template["input"]["text"] == "{{text}}"
    assert provider._spec.body_template["tags"][0] == "locale:{{locale}}"
    assert provider._spec.custom_variables == {"locale": "en-US"}

    asyncio.run(registry.close())


def test_current_and_historical_revisions_use_distinct_cached_providers(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path / "resources.sqlite3")
    first = store.create(_resource(), api_key="secret")
    registry = ResourceProviderRegistry(store)

    first_provider = registry.get("custom")
    second = store.update(
        "custom",
        replace(
            first,
            base_url="https://speech.example.test/v2/synthesize",
            defaults=replace(first.defaults, default_model="speech-v3", models=("speech-v3",)),
        ),
    )
    second_provider = registry.get("custom")

    assert second.revision == 2
    assert registry.current_revision("custom") == 2
    assert first_provider is registry.get_revision("custom", 1)
    assert second_provider is registry.get_revision("custom", 2)
    assert first_provider is not second_provider
    assert first_provider._spec.url.endswith("/v1/synthesize")
    assert second_provider._spec.url.endswith("/v2/synthesize")
    assert first_provider.info.default_model == "speech-v2"
    assert second_provider.info.default_model == "speech-v3"

    asyncio.run(registry.close())


def test_soft_deleted_resource_is_hidden_but_pinned_revision_still_resolves(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path / "resources.sqlite3")
    store.create(_resource(), api_key="secret")
    registry = ResourceProviderRegistry(store)
    pinned = registry.get_revision("custom", 1)

    assert store.soft_delete("custom") is True

    with pytest.raises(UnknownProviderError, match="unknown TTS provider: custom"):
        registry.get("custom")
    with pytest.raises(UnknownProviderError, match="unknown TTS provider: custom"):
        registry.current_revision("custom")
    assert registry.list() == []
    assert registry.get_revision("custom", 1) is pinned

    asyncio.run(registry.close())


def test_builtin_resources_map_to_native_adapters_and_accept_settings(
    tmp_path: Path,
) -> None:
    store = _store(
        tmp_path / "resources.sqlite3",
        environ={
            "GEMINI_API_KEY": "gemini-key",
            "DEEPGRAM_API_KEY": "deepgram-key",
            "INWORLD_API_KEY": "inworld-key",
        },
        seed_builtins=True,
    )
    settings = Settings(
        gemini_model="configured-gemini",
        gemini_voice="ConfiguredGeminiVoice",
        deepgram_model="configured-deepgram",
        deepgram_voice="configured-deepgram-voice",
        deepgram_api_url="https://configured.deepgram.test/speak",
        deepgram_pacing_seconds=1.25,
        inworld_model="configured-inworld",
        inworld_voice="ConfiguredInworldVoice",
        inworld_api_url="https://configured.inworld.test/voice",
        inworld_pacing_seconds=2.5,
        provider_timeout_seconds=42,
        trust_env_proxies=True,
    )
    registry = ResourceProviderRegistry(store, settings=settings)

    gemini = registry.get("gemini")
    deepgram = registry.get("deepgram")
    inworld = registry.get("inworld")

    assert isinstance(gemini, GeminiTtsProvider)
    assert isinstance(deepgram, DeepgramTtsProvider)
    assert isinstance(inworld, InworldTtsProvider)
    assert gemini.info.name == "gemini"
    assert deepgram.info.name == "deepgram"
    assert inworld.info.name == "inworld"
    assert gemini.info.default_model == "configured-gemini"
    assert deepgram.info.default_model == "configured-deepgram"
    assert deepgram.info.minimum_request_interval_seconds == 1.25
    assert deepgram._api_url == "https://configured.deepgram.test/speak"
    assert inworld.info.default_model == "configured-inworld"
    assert inworld.info.minimum_request_interval_seconds == 2.5
    assert inworld._api_url == "https://configured.inworld.test/voice"
    assert gemini._api_key == "gemini-key"
    assert deepgram._api_key == "deepgram-key"
    assert inworld._api_key == "inworld-key"
    assert gemini._trust_env_proxies is True
    assert deepgram._trust_env_proxies is True
    assert inworld._trust_env_proxies is True

    asyncio.run(registry.close())


class _ClosingProvider:
    def __init__(self, name: str) -> None:
        self.info = ProviderInfo(name, "model", "voice", None, None)
        self.close_calls = 0

    async def close(self) -> None:
        self.close_calls += 1


class _RecordingFactory:
    def __init__(self) -> None:
        self.created: list[tuple[ApiResourceSpec, str | None, _ClosingProvider]] = []

    def __call__(
        self,
        spec: ApiResourceSpec,
        *,
        api_key: str | None,
        settings: Settings | None,
    ) -> _ClosingProvider:
        provider = _ClosingProvider(spec.resource_id)
        self.created.append((spec, api_key, provider))
        return provider


def test_invalidation_closes_selected_cached_revisions_and_close_is_idempotent(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path / "resources.sqlite3")
    first = store.create(_resource(), api_key="secret")
    factory = _RecordingFactory()
    registry = ResourceProviderRegistry(store, provider_factory=factory)
    first_provider = registry.get("custom")
    store.update(
        "custom",
        replace(first, base_url="https://speech.example.test/v2/synthesize"),
    )
    second_provider = registry.get("custom")

    asyncio.run(registry.invalidate("custom", revision=2))

    assert first_provider.close_calls == 0
    assert second_provider.close_calls == 1
    replacement_second = registry.get_revision("custom", 2)
    assert replacement_second is not second_provider
    asyncio.run(registry.invalidate("custom"))
    assert first_provider.close_calls == 1
    assert replacement_second.close_calls == 1

    asyncio.run(registry.close())
    asyncio.run(registry.close())
    with pytest.raises(RuntimeError, match="registry is closed"):
        registry.get("custom")


def test_missing_or_invalid_revision_raises_unknown_provider(tmp_path: Path) -> None:
    store = _store(tmp_path / "resources.sqlite3")
    store.create(_resource(), api_key="secret")
    registry = ResourceProviderRegistry(store)

    with pytest.raises(UnknownProviderError, match="unknown TTS provider: missing"):
        registry.get("missing")
    with pytest.raises(UnknownProviderError, match="custom@2"):
        registry.get_revision("custom", 2)
    with pytest.raises(UnknownProviderError, match="custom@0"):
        registry.get_revision("custom", 0)
    with pytest.raises(ValueError, match="revision requires"):
        asyncio.run(registry.invalidate(revision=1))

    asyncio.run(registry.close())
