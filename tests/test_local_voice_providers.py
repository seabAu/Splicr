from __future__ import annotations

import asyncio
import contextlib
import json
import struct
import sys
import wave
from pathlib import Path
from types import SimpleNamespace

import pytest

from splicr.domain import DeliveryControls, ProviderError, SynthesisOptions
from splicr.providers.audio8 import AUDIO8_MODEL, Audio8TtsProvider
from splicr.providers.qwen3 import QWEN3_MODELS, Qwen3TtsProvider
from splicr import engine_worker


class _FakeArray:
    def __init__(self, values) -> None:
        self.values = [float(value) for value in values]
        self.ndim = 1
        self.shape = (len(self.values),)

    def __len__(self) -> int:
        return len(self.values)

    def __mul__(self, scalar):
        return _FakeArray(value * scalar for value in self.values)

    def reshape(self, *_shape):
        return self

    def astype(self, dtype, copy=False):
        del copy
        if dtype == "<i2":
            integers = [max(-32768, min(32767, int(value))) for value in self.values]
            return SimpleNamespace(tobytes=lambda: struct.pack(f"<{len(integers)}h", *integers))
        return self


class _FakeNumpy:
    float32 = "float32"

    @staticmethod
    def asarray(values, dtype=None):
        del dtype
        return values if isinstance(values, _FakeArray) else _FakeArray(values)

    @staticmethod
    def zeros(length, dtype=None):
        del dtype
        return _FakeArray([0.0] * length)

    @staticmethod
    def clip(values, minimum, maximum):
        return _FakeArray(max(minimum, min(maximum, value)) for value in values.values)

    @staticmethod
    def concatenate(parts):
        return _FakeArray(value for part in parts for value in part.values)

    @staticmethod
    def linspace(start, stop, *, num, endpoint=False):
        del endpoint
        if num <= 1:
            return [start]
        step = (stop - start) / num
        return [start + step * index for index in range(num)]

    @staticmethod
    def interp(targets, sources, values):
        del sources
        if not values.values:
            return _FakeArray([])
        return _FakeArray(
            values.values[min(len(values.values) - 1, int(target * len(values.values)))]
            for target in targets
        )


class _FakeCuda:
    @staticmethod
    def is_available() -> bool:
        return False

    @staticmethod
    def empty_cache() -> None:
        return None


class _FakeTorch:
    cuda = _FakeCuda()
    bfloat16 = "bfloat16"
    float32 = "float32"
    seeds: list[int] = []

    @classmethod
    def manual_seed(cls, value: int) -> None:
        cls.seeds.append(value)

    @staticmethod
    def no_grad():
        return contextlib.nullcontext()


class _FakeQwenModel:
    loads: list[str] = []
    prompt_calls = 0
    design_calls: list[dict] = []

    @classmethod
    def from_pretrained(cls, repo, **kwargs):
        del kwargs
        cls.loads.append(repo)
        return cls()

    def create_voice_clone_prompt(self, **kwargs):
        self.__class__.prompt_calls += 1
        return kwargs

    def generate_voice_clone(self, **kwargs):
        del kwargs
        return [[0.25, -0.25]], 24_000

    def generate_custom_voice(self, **kwargs):
        del kwargs
        return [[0.5, -0.5]], 24_000

    def generate_voice_design(self, **kwargs):
        self.__class__.design_calls.append(kwargs)
        return [[0.25, -0.25]], 24_000


class _FakeInputs(dict):
    def to(self, device):
        del device
        return self


class _FakeAudio8Processor:
    @classmethod
    def from_pretrained(cls, *args, **kwargs):
        del args, kwargs
        return cls()

    def __call__(self, **kwargs):
        del kwargs
        return _FakeInputs(input_ids=[1])


class _FakeAudio8Model:
    load_count = 0

    @classmethod
    def from_pretrained(cls, *args, **kwargs):
        del args, kwargs
        cls.load_count += 1
        return cls()

    def to(self, device):
        del device
        return self

    def eval(self):
        return self

    def generate(self, **kwargs):
        del kwargs
        return [1]

    def decode_audio(self, generated):
        del generated
        return [0.1] * 60_000, 44_100


@pytest.mark.parametrize(
    ("provider_type", "provider_name", "recommended_characters"),
    [
        (Qwen3TtsProvider, "qwen3-local", 250),
        (Audio8TtsProvider, "audio8-local", 150),
    ],
)
def test_local_voice_provider_builds_job_scoped_adapter(
    provider_type,
    provider_name: str,
    recommended_characters: int,
) -> None:
    provider = provider_type(Path(sys.executable))

    adapter = provider.create_engine_adapter()

    assert provider.info.name == provider_name
    assert provider.info.recommended_chunk_characters == recommended_characters
    assert adapter.descriptor.id == provider_name
    assert adapter.spec.command[-2:] == ("--engine", provider_name)


def test_local_voice_provider_models_are_explicit() -> None:
    qwen = Qwen3TtsProvider(Path(sys.executable)).info.capabilities
    assert qwen.models == QWEN3_MODELS
    assert [definition.key for definition in qwen.control_definitions] == [
        "seed",
        "voice_take",
    ]
    assert qwen.control_definitions[0].randomizable is True
    assert qwen.control_definitions[1].read_only is True
    assert Audio8TtsProvider(Path(sys.executable)).info.capabilities.models == (AUDIO8_MODEL,)


@pytest.mark.parametrize("provider_type", [Qwen3TtsProvider, Audio8TtsProvider])
def test_local_voice_provider_refuses_stateless_synthesis(provider_type) -> None:
    provider = provider_type(Path(sys.executable))

    async def scenario() -> None:
        with pytest.raises(ProviderError, match="job-scoped local engine session"):
            await provider.synthesize(
                "Hello",
                SynthesisOptions(
                    model=provider.info.default_model,
                    voice=provider.info.default_voice,
                    controls=DeliveryControls(),
                ),
            )

    asyncio.run(scenario())


def test_qwen_runtime_reuses_model_and_clone_prompt(monkeypatch, tmp_path) -> None:
    _FakeQwenModel.loads.clear()
    _FakeQwenModel.prompt_calls = 0
    _FakeTorch.seeds.clear()
    modules = {
        "numpy": _FakeNumpy,
        "torch": _FakeTorch,
        "qwen_tts": SimpleNamespace(Qwen3TTSModel=_FakeQwenModel),
    }
    monkeypatch.setattr(engine_worker.importlib, "import_module", modules.__getitem__)
    reference = tmp_path / "reference.wav"
    reference.write_bytes(b"RIFF-reference")
    options = {
        "model": QWEN3_MODELS[0],
        "variables": {
            "seed": 31_415,
            engine_worker.VOICE_PROFILE_VARIABLE: {
                "id": "voice-one",
                "kind": "cloned",
                "reference_audio_path": str(reference),
                "reference_text": "Exact spoken words.",
                "settings": {"language": "English"},
                "updated_at": "2026-09-28T00:00:00Z",
            }
        },
    }
    runtime = engine_worker.Qwen3Runtime()

    first = tmp_path / "first.pcm"
    second = tmp_path / "second.pcm"
    retry = tmp_path / "retry.pcm"
    runtime.synthesize("First sentence.", options, first)
    runtime.synthesize("Second sentence.", options, second)
    runtime.synthesize("First sentence.", options, retry)

    assert _FakeQwenModel.loads == [QWEN3_MODELS[0]]
    assert _FakeQwenModel.prompt_calls == 1
    assert len(_FakeTorch.seeds) == 3
    assert _FakeTorch.seeds[0] == _FakeTorch.seeds[2]
    assert _FakeTorch.seeds[0] != _FakeTorch.seeds[1]
    assert first.read_bytes() == struct.pack("<2h", 8191, -8191)
    assert second.read_bytes() == first.read_bytes()
    assert retry.read_bytes() == first.read_bytes()


def test_qwen_voice_design_tool_writes_exact_managed_reference(monkeypatch, tmp_path) -> None:
    _FakeQwenModel.loads.clear()
    _FakeQwenModel.design_calls.clear()
    _FakeTorch.seeds.clear()
    modules = {
        "numpy": _FakeNumpy,
        "torch": _FakeTorch,
        "qwen_tts": SimpleNamespace(Qwen3TTSModel=_FakeQwenModel),
    }
    monkeypatch.setattr(engine_worker.importlib, "import_module", modules.__getitem__)
    output = tmp_path / "reference.wav"
    result_path = tmp_path / "design-result.json"

    result = engine_worker._tool_qwen_voice_design(
        {
            "description": "A calm, precise narrator",
            "take": 7,
            "output_path": str(output.resolve()),
            "result_path": str(result_path.resolve()),
        }
    )

    assert _FakeQwenModel.loads == [engine_worker.QWEN_DESIGN_REPO]
    assert _FakeTorch.seeds == [1007]
    assert _FakeQwenModel.design_calls == [
        {
            "text": engine_worker.QWEN_REFERENCE_TEXT,
            "instruct": "A calm, precise narrator",
            "language": "English",
        }
    ]
    with wave.open(str(output), "rb") as recording:
        assert recording.getnchannels() == 1
        assert recording.getsampwidth() == 2
        assert recording.getframerate() == 24_000
        assert recording.getnframes() == 2
    assert json.loads(result_path.read_text(encoding="utf-8")) == result


def test_audio8_runtime_reuses_model_and_normalizes_to_24khz(monkeypatch, tmp_path) -> None:
    _FakeAudio8Model.load_count = 0
    modules = {
        "numpy": _FakeNumpy,
        "torch": _FakeTorch,
        "transformers": SimpleNamespace(
            AutoModel=_FakeAudio8Model,
            AutoProcessor=_FakeAudio8Processor,
        ),
    }
    monkeypatch.setattr(engine_worker.importlib, "import_module", modules.__getitem__)
    reference = tmp_path / "reference.wav"
    reference.write_bytes(b"RIFF-reference")
    options = {
        "variables": {
            engine_worker.VOICE_PROFILE_VARIABLE: {
                "id": "voice-one",
                "kind": "cloned",
                "reference_audio_path": str(reference),
                "reference_text": "Exact spoken words.",
                "settings": {},
            }
        }
    }
    runtime = engine_worker.Audio8Runtime()

    first = tmp_path / "first.pcm"
    second = tmp_path / "second.pcm"
    runtime.synthesize("A sufficiently long sentence for the duration check.", options, first)
    runtime.synthesize("Another sufficiently long sentence for rendering.", options, second)

    assert _FakeAudio8Model.load_count == 1
    expected_samples = round(60_000 * 24_000 / 44_100)
    assert len(first.read_bytes()) == expected_samples * 2
    assert len(second.read_bytes()) == expected_samples * 2
