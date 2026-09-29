from __future__ import annotations

import inspect
import re
import threading
from collections.abc import Mapping
from typing import Any, Protocol, cast

from .api_resources import (
    AdapterType,
    ApiResourceSpec,
    AuthMode,
    ResponseMode,
    RetryPolicy,
    SqliteApiResourceStore,
)
from .config import Settings
from .domain import (
    ControlCondition,
    ControlDefinition,
    ControlMode,
    ControlValueType,
    NonverbalFrequency,
    ProviderCapabilities,
    ProviderInfo,
    SpeechPace,
    TonePreset,
    TtsProvider,
    UnknownProviderError,
    VocalStyle,
    VoiceOption,
)
from .providers.deepgram import DeepgramTtsProvider
from .providers.gemini import GeminiTtsProvider
from .providers.generic_rest import (
    GenericRestResponseMode,
    GenericRestSpec,
    GenericRestTtsProvider,
)
from .providers.inworld import InworldTtsProvider

_RESOURCE_PLACEHOLDER_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_.-]*)\}")
_RESERVED_VARIABLES = frozenset(
    {
        "api_key",
        "instructions",
        "model",
        "nonverbal_frequency",
        "pace",
        "text",
        "tone",
        "vocal_style",
        "voice",
    }
)
_BUILTIN_ORDER = {"gemini": 0, "deepgram": 1, "inworld": 2}


class ResourceProviderFactory(Protocol):
    def __call__(
        self,
        spec: ApiResourceSpec,
        *,
        api_key: str | None,
        settings: Settings | None,
    ) -> TtsProvider: ...


def _effective_interval(spec: ApiResourceSpec) -> float:
    interval = spec.pacing.minimum_interval_seconds
    if spec.pacing.requests_per_minute is not None:
        interval = max(interval, 60.0 / spec.pacing.requests_per_minute)
    return interval


def _configured_native_values(
    spec: ApiResourceSpec, settings: Settings | None
) -> tuple[str, str, str, float, float]:
    """Return native-adapter values, retaining revision-one env compatibility.

    Once a built-in resource has been edited, its immutable resource revision is the
    source of truth. The revision-one compatibility branch keeps the pre-catalog
    ``SPLICR_*`` provider settings useful during migration.
    """

    model = spec.defaults.default_model
    voice = spec.defaults.default_voice
    url = spec.base_url
    timeout = spec.retry.request_timeout_seconds
    interval = _effective_interval(spec)
    is_seeded_builtin = spec.revision == 1 and spec.resource_id == spec.adapter_type.value
    if settings is None or not is_seeded_builtin:
        return model, voice, url, timeout, interval

    timeout = settings.provider_timeout_seconds
    if spec.adapter_type is AdapterType.GEMINI:
        model = settings.gemini_model
        voice = settings.gemini_voice
        interval = settings.pacing_seconds
    elif spec.adapter_type is AdapterType.DEEPGRAM:
        model = settings.deepgram_model
        voice = settings.deepgram_voice
        url = settings.deepgram_api_url
        interval = settings.deepgram_pacing_seconds
    elif spec.adapter_type is AdapterType.INWORLD:
        model = settings.inworld_model
        voice = settings.inworld_voice
        url = settings.inworld_api_url
        interval = settings.inworld_pacing_seconds
    return model, voice, url, timeout, interval


def _resource_template(value: Any) -> Any:
    """Translate catalog ``${name}`` placeholders to the REST adapter grammar."""

    if isinstance(value, str):
        return _RESOURCE_PLACEHOLDER_RE.sub(r"{{\1}}", value)
    if isinstance(value, Mapping):
        return {key: _resource_template(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_resource_template(item) for item in value]
    return value


def _resource_capabilities(spec: ApiResourceSpec) -> ProviderCapabilities:
    defaults = spec.defaults
    model_ids = tuple(dict.fromkeys((defaults.default_model, *defaults.models)))
    voices = [VoiceOption(voice.id, voice.traits) for voice in defaults.voices]
    if all(voice.id != defaults.default_voice for voice in voices):
        voices.insert(0, VoiceOption(defaults.default_voice))
    capabilities = spec.capabilities
    control_definitions = tuple(
        ControlDefinition(
            key=variable.name,
            value_type=ControlValueType(variable.kind.value),
            label=variable.label or variable.name.replace("_", " ").title(),
            description=variable.description,
            group=variable.group,
            required=variable.required,
            default=variable.default,
            choices=variable.choices,
            minimum=variable.minimum,
            maximum=variable.maximum,
            step=variable.step,
            unit=variable.unit,
            sensitive=variable.sensitive,
            visible_when=tuple(
                ControlCondition(key=key, equals=value)
                for key, value in sorted(variable.visible_when.items())
            ),
            enabled_when=tuple(
                ControlCondition(key=key, equals=value)
                for key, value in sorted(variable.enabled_when.items())
            ),
        )
        for variable in spec.variables
        if variable.name not in _RESERVED_VARIABLES
    )
    return ProviderCapabilities(
        models=model_ids,
        voices=tuple(voices),
        tone_presets=tuple(TonePreset(value) for value in capabilities.tone_presets),
        speech_paces=tuple(SpeechPace(value) for value in capabilities.speech_paces),
        vocal_styles=tuple(VocalStyle(value) for value in capabilities.vocal_styles),
        nonverbal_frequencies=tuple(
            NonverbalFrequency(value) for value in capabilities.nonverbal_frequencies
        ),
        tone_modes=tuple(ControlMode(value.value) for value in capabilities.tone_modes),
        pace_modes=tuple(ControlMode(value.value) for value in capabilities.pace_modes),
        vocal_style_modes=tuple(
            ControlMode(value.value) for value in capabilities.vocal_style_modes
        ),
        nonverbal_modes=tuple(ControlMode(value.value) for value in capabilities.nonverbal_modes),
        nonverbal_cues=capabilities.nonverbal_cues,
        supports_custom_instructions=capabilities.supports_custom_instructions,
        control_definitions=control_definitions,
        allows_undeclared_variables=False,
    )


def _generic_rest_spec(spec: ApiResourceSpec) -> GenericRestSpec:
    serialized = spec.to_dict()
    defaults = {
        variable["name"]: _resource_template(variable["default"])
        for variable in serialized["variables"]
        if variable["name"] not in _RESERVED_VARIABLES
    }
    required_variables = tuple(
        variable["name"]
        for variable in serialized["variables"]
        if variable["name"] not in _RESERVED_VARIABLES and variable["required"]
    )
    response_modes = {
        ResponseMode.RAW_PCM: GenericRestResponseMode.RAW_PCM16,
        ResponseMode.WAV: GenericRestResponseMode.WAV_PCM16,
        ResponseMode.JSON_BASE64_PCM: GenericRestResponseMode.JSON_BASE64_RAW_PCM16,
        ResponseMode.JSON_BASE64_WAV: GenericRestResponseMode.JSON_BASE64_WAV,
    }
    return GenericRestSpec(
        name=spec.resource_id,
        url=spec.base_url,
        method=spec.method.value,
        default_model=spec.defaults.default_model,
        default_voice=spec.defaults.default_voice,
        headers=_resource_template(serialized["headers"]),
        query=_resource_template(serialized["query"]),
        body_template=_resource_template(serialized["request_template"]),
        custom_variables=defaults,
        required_variables=required_variables,
        auth_location=("none" if spec.auth.mode is AuthMode.TEMPLATE else spec.auth.mode.value),
        auth_name=spec.auth.name or "",
        auth_prefix=spec.auth.prefix,
        response_mode=response_modes[spec.response.mode],
        response_json_pointer=spec.response.json_pointer or "",
        timeout_seconds=spec.retry.request_timeout_seconds,
        max_input_characters=spec.input_limits.max_characters,
        max_input_bytes=spec.input_limits.max_bytes,
        max_input_tokens=spec.input_limits.max_tokens,
        max_input_words=spec.input_limits.max_words,
        recommended_chunk_characters=spec.input_limits.recommended_characters,
        recommended_chunk_bytes=spec.input_limits.recommended_bytes,
        recommended_chunk_words=spec.input_limits.recommended_words,
        limit_basis=spec.input_limits.limit_basis.value,
        response_sample_rate=spec.response.sample_rate_hz,
        response_channels=spec.response.channels,
        response_sample_width=spec.response.sample_width_bytes,
        response_encoding={
            1: "pcm_u8",
            2: "pcm_s16le",
            3: "pcm_s24le",
            4: "pcm_s32le",
        }[spec.response.sample_width_bytes],
        minimum_request_interval_seconds=_effective_interval(spec),
        models=spec.defaults.models,
        voices=tuple(voice.id for voice in spec.defaults.voices),
        capabilities=_resource_capabilities(spec),
    )


def provider_from_resource(
    spec: ApiResourceSpec,
    *,
    api_key: str | None = None,
    settings: Settings | None = None,
) -> TtsProvider:
    """Build the TTS adapter represented by one immutable resource revision."""

    model, voice, url, timeout, interval = _configured_native_values(spec, settings)
    trust_env_proxies = settings.trust_env_proxies if settings is not None else False
    if spec.adapter_type is AdapterType.GEMINI:
        return GeminiTtsProvider(
            default_model=model,
            default_voice=voice,
            provider_name=spec.resource_id,
            request_timeout_seconds=timeout,
            trust_env_proxies=trust_env_proxies,
            api_key=api_key,
        )
    if spec.adapter_type is AdapterType.DEEPGRAM:
        return DeepgramTtsProvider(
            default_model=model,
            default_voice=voice,
            provider_name=spec.resource_id,
            api_url=url,
            request_timeout_seconds=timeout,
            minimum_request_interval_seconds=interval,
            trust_env_proxies=trust_env_proxies,
            api_key=api_key,
        )
    if spec.adapter_type is AdapterType.INWORLD:
        return InworldTtsProvider(
            default_model=model,
            default_voice=voice,
            provider_name=spec.resource_id,
            api_url=url,
            request_timeout_seconds=timeout,
            minimum_request_interval_seconds=interval,
            trust_env_proxies=trust_env_proxies,
            api_key=api_key,
        )
    if spec.adapter_type is AdapterType.GENERIC_REST:
        return GenericRestTtsProvider(
            cast(Any, _generic_rest_spec(spec)),
            api_key=api_key,
            trust_env_proxies=trust_env_proxies,
        )
    raise ValueError(f"unsupported API resource adapter: {spec.adapter_type}")


class ResourceProviderRegistry:
    """Resolve versioned API resources into cached TTS provider adapters."""

    def __init__(
        self,
        store: SqliteApiResourceStore,
        *,
        settings: Settings | None = None,
        provider_factory: ResourceProviderFactory = provider_from_resource,
    ) -> None:
        self.store = store
        self.settings = settings
        self._provider_factory = provider_factory
        self._providers: dict[tuple[str, int], TtsProvider] = {}
        self._lock = threading.RLock()
        self._closed = False

    def get(self, name: str) -> TtsProvider:
        resource_id = self._normalize_name(name)
        spec = self.store.get_current(resource_id)
        if spec is None:
            raise UnknownProviderError(f"unknown TTS provider: {name}")
        return self._get_spec(spec)

    def get_revision(self, name: str, revision: int) -> TtsProvider:
        resource_id = self._normalize_name(name)
        if isinstance(revision, bool) or revision < 1:
            raise UnknownProviderError(f"unknown TTS provider revision: {resource_id}@{revision}")
        spec = self.store.get(resource_id, revision)
        if spec is None:
            raise UnknownProviderError(f"unknown TTS provider revision: {resource_id}@{revision}")
        return self._get_spec(spec)

    def current_revision(self, name: str) -> int:
        resource_id = self._normalize_name(name)
        spec = self.store.get_current(resource_id)
        if spec is None:
            raise UnknownProviderError(f"unknown TTS provider: {name}")
        return spec.revision

    def retry_policy(self, name: str, revision: int | None = None) -> RetryPolicy:
        resource_id = self._normalize_name(name)
        spec = (
            self.store.get(resource_id, revision)
            if revision is not None
            else self.store.get_current(resource_id)
        )
        if spec is None:
            suffix = f"@{revision}" if revision is not None else ""
            raise UnknownProviderError(f"unknown TTS provider revision: {resource_id}{suffix}")
        return spec.retry

    def list(self) -> list[ProviderInfo]:
        """Describe enabled resource heads without reading their credentials."""

        infos: list[ProviderInfo] = []
        specs = sorted(
            self.store.list(),
            key=lambda spec: (
                _BUILTIN_ORDER.get(spec.resource_id, len(_BUILTIN_ORDER)),
                spec.name.casefold(),
                spec.resource_id,
            ),
        )
        for spec in specs:
            key = (spec.resource_id, spec.revision)
            with self._lock:
                cached = self._providers.get(key)
            if cached is not None:
                infos.append(cached.info)
                continue
            provider = self._provider_factory(spec, api_key=None, settings=self.settings)
            self._validate_provider_name(spec, provider)
            infos.append(provider.info)
        return infos

    async def invalidate(self, name: str | None = None, revision: int | None = None) -> None:
        """Evict and close cached adapters after resource or credential changes."""

        if revision is not None and name is None:
            raise ValueError("revision requires a resource name")
        resource_id = None if name is None else self._normalize_name(name)
        with self._lock:
            keys = [
                key
                for key in self._providers
                if (resource_id is None or key[0] == resource_id)
                and (revision is None or key[1] == revision)
            ]
            providers = [self._providers.pop(key) for key in keys]
        seen: set[int] = set()
        for provider in providers:
            identity = id(provider)
            if identity in seen:
                continue
            seen.add(identity)
            await self._close_provider(provider)

    async def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
        await self.invalidate()

    def _get_spec(self, spec: ApiResourceSpec) -> TtsProvider:
        key = (spec.resource_id, spec.revision)
        with self._lock:
            if self._closed:
                raise RuntimeError("provider registry is closed")
            provider = self._providers.get(key)
            if provider is not None:
                return provider
            api_key = self.store.resolve_api_key(spec)
            provider = self._provider_factory(spec, api_key=api_key, settings=self.settings)
            self._validate_provider_name(spec, provider)
            self._providers[key] = provider
            return provider

    @staticmethod
    def _normalize_name(name: str) -> str:
        return name.strip().lower()

    @staticmethod
    def _validate_provider_name(spec: ApiResourceSpec, provider: TtsProvider) -> None:
        if provider.info.name.strip().lower() != spec.resource_id:
            raise ValueError(
                "resource provider factory returned mismatched provider name: "
                f"expected {spec.resource_id!r}, got {provider.info.name!r}"
            )

    @staticmethod
    async def _close_provider(provider: TtsProvider) -> None:
        close = getattr(provider, "close", None)
        if close is None:
            return
        result = close()
        if inspect.isawaitable(result):
            await result
