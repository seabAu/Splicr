from __future__ import annotations

import struct
import time
from collections import Counter

from splicr.domain import (
    AudioChunk,
    ControlDefinition,
    ControlMode,
    NonverbalFrequency,
    ProviderCapabilities,
    ProviderError,
    ProviderInfo,
    SpeechPace,
    SynthesisOptions,
    TonePreset,
    VocalStyle,
    VoiceOption,
)


class RecordingProvider:
    def __init__(
        self,
        *,
        fail_text: str | None = None,
        transient_failures: int = 0,
        minimum_request_interval_seconds: float | None = None,
        control_definitions: tuple[ControlDefinition, ...] = (),
        allows_undeclared_variables: bool = True,
        provider_name: str = "fake",
    ) -> None:
        self._info = ProviderInfo(
            name=provider_name,
            default_model="fake-model",
            default_voice="fake-voice",
            max_input_bytes=10_000,
            max_input_tokens=10_000,
            recommended_chunk_bytes=10_000,
            recommended_chunk_words=10_000,
            minimum_request_interval_seconds=minimum_request_interval_seconds,
            capabilities=ProviderCapabilities(
                models=("fake-model",),
                voices=(VoiceOption("fake-voice", ("test",)),),
                tone_presets=tuple(TonePreset),
                speech_paces=tuple(SpeechPace),
                vocal_styles=tuple(VocalStyle),
                nonverbal_frequencies=tuple(NonverbalFrequency),
                tone_modes=(ControlMode.NATIVE_ENUM,),
                pace_modes=(ControlMode.NATIVE_ENUM,),
                vocal_style_modes=(ControlMode.NATIVE_ENUM,),
                nonverbal_modes=(ControlMode.INLINE_MARKUP,),
                nonverbal_cues=("sighs", "laughs"),
                control_definitions=control_definitions,
                allows_undeclared_variables=allows_undeclared_variables,
            ),
        )
        self.calls: list[str] = []
        self.options: list[SynthesisOptions] = []
        self.call_times: list[float] = []
        self.call_counts: Counter[str] = Counter()
        self.fail_text = fail_text
        self.transient_failures = transient_failures

    @property
    def info(self) -> ProviderInfo:
        return self._info

    def estimate_input_tokens(self, text: str, options: SynthesisOptions) -> int:
        return len(text.split())

    def estimate_input_characters(self, text: str, options: SynthesisOptions) -> int:
        return len(text)

    async def synthesize(self, text: str, options: SynthesisOptions) -> AudioChunk:
        self.call_times.append(time.monotonic())
        self.calls.append(text)
        self.options.append(options)
        self.call_counts[text] += 1
        if self.transient_failures:
            self.transient_failures -= 1
            raise ProviderError("temporary outage", retryable=True, status_code=503)
        if self.fail_text and self.fail_text in text:
            raise ProviderError("bad request", retryable=False, status_code=400)
        sample = len(self.calls)
        return AudioChunk(pcm=struct.pack("<h", sample) * 4)
