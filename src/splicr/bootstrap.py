from __future__ import annotations

from .api_resources import SqliteApiResourceStore
from .config import Settings
from .resource_registry import ResourceProviderRegistry
from .secret_vault import EncryptedFileSecretVault
from .service import SynthesisService
from .providers import CompositeProviderRegistry
from .providers.audio8 import Audio8TtsProvider
from .providers.edge import EdgeTtsProvider
from .providers.kokoro import KokoroTtsProvider
from .providers.qwen3 import Qwen3TtsProvider


def create_service(settings: Settings) -> SynthesisService:
    vault = None
    if settings.secret_vault_backend == "encrypted-file":
        if settings.secret_vault_key_file is None:
            raise ValueError(
                "SPLICR_SECRET_VAULT_KEY_FILE is required for the encrypted-file vault"
            )
        vault = EncryptedFileSecretVault(
            settings.encrypted_vault_path,
            key_file=settings.secret_vault_key_file,
        )
    elif settings.secret_vault_backend != "keyring":
        raise ValueError(f"unknown secret vault backend: {settings.secret_vault_backend}")
    resource_store = SqliteApiResourceStore(settings.database_path, vault=vault)
    resource_store.initialize(seed_builtins=True)
    resource_providers = ResourceProviderRegistry(resource_store, settings=settings)
    local_providers = []
    for provider_type, executable in (
        (KokoroTtsProvider, settings.kokoro_python),
        (Qwen3TtsProvider, settings.qwen3_python),
        (Audio8TtsProvider, settings.audio8_python),
    ):
        if executable is not None:
            local_providers.append(
                provider_type(
                    executable,
                    startup_timeout_seconds=settings.local_engine_startup_timeout_seconds,
                    request_timeout_seconds=settings.local_engine_request_timeout_seconds,
                )
            )
    if settings.edge_python is not None:
        local_providers.append(
            EdgeTtsProvider(
                settings.edge_python,
                voice_cache_path=settings.data_dir / "studio" / "edge-voices.json",
                startup_timeout_seconds=settings.local_engine_startup_timeout_seconds,
                request_timeout_seconds=settings.local_engine_request_timeout_seconds,
            )
        )
    providers = resource_providers
    if local_providers:
        providers = CompositeProviderRegistry(
            resource_providers,
            tuple(local_providers),
        )
    return SynthesisService(settings=settings, providers=providers)
