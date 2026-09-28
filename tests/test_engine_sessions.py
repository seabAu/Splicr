import asyncio
from dataclasses import dataclass
from pathlib import Path

from splicr.domain import AudioChunk, ProviderInfo, SynthesisOptions
from splicr.providers.generic_rest import GenericRestSpec, GenericRestTtsProvider
from splicr.studio import (
    EngineSessionContext,
    EngineTransport,
    ProviderEngineAdapter,
    engine_adapter_for_provider,
)


@dataclass
class FakeProvider:
    texts: list[str]

    @property
    def info(self) -> ProviderInfo:
        return ProviderInfo(
            name="fake",
            default_model="model",
            default_voice="voice",
            max_input_bytes=100,
            max_input_tokens=50,
        )

    def estimate_input_tokens(self, text: str, options: SynthesisOptions) -> int:
        del options
        return len(text.split())

    def estimate_input_characters(self, text: str, options: SynthesisOptions) -> int:
        del options
        return len(text)

    async def synthesize(self, text: str, options: SynthesisOptions) -> AudioChunk:
        del options
        self.texts.append(text)
        return AudioChunk(pcm=b"\x00\x00")


def test_remote_provider_adapts_to_job_scoped_engine_session(tmp_path: Path) -> None:
    provider = FakeProvider(texts=[])
    adapter = ProviderEngineAdapter(provider, display_name="Remote fake")
    options = SynthesisOptions(model="model", voice="voice")
    context = EngineSessionContext(
        job_id="job-1",
        project_id="project-1",
        render_plan_id="plan-1",
        take_id="take-1",
        work_directory=tmp_path.resolve(),
    )

    async def render() -> AudioChunk:
        async with adapter.open_session(context) as session:
            return await session.synthesize("Hello session", options)

    chunk = asyncio.run(render())

    assert adapter.descriptor.transport is EngineTransport.REMOTE_HTTP
    assert adapter.descriptor.display_name == "Remote fake"
    assert adapter.estimate_input_tokens("Hello session", options) == 2
    assert adapter.estimate_input_characters("Hello session", options) == 13
    assert provider.texts == ["Hello session"]
    assert chunk.pcm == b"\x00\x00"


def test_loopback_generic_rest_provider_is_classified_as_local_http() -> None:
    provider = GenericRestTtsProvider(
        GenericRestSpec(
            name="local-server",
            url="http://127.0.0.1:8880/synthesize",
            default_model="local-model",
            default_voice="local-voice",
            body_template={"text": "{{text}}"},
        )
    )

    adapter = engine_adapter_for_provider(provider)

    assert adapter.descriptor.transport is EngineTransport.LOCAL_HTTP
