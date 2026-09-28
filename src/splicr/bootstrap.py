from __future__ import annotations

from .api_resources import SqliteApiResourceStore
from .config import Settings
from .resource_registry import ResourceProviderRegistry
from .secret_vault import EncryptedFileSecretVault
from .service import SynthesisService
from .providers import CompositeProviderRegistry
from .providers.kokoro import KokoroTtsProvider


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
    providers = resource_providers
    if settings.kokoro_python is not None:
        providers = CompositeProviderRegistry(
            resource_providers,
            (
                KokoroTtsProvider(
                    settings.kokoro_python,
                    startup_timeout_seconds=settings.local_engine_startup_timeout_seconds,
                    request_timeout_seconds=settings.local_engine_request_timeout_seconds,
                ),
            ),
        )
    return SynthesisService(settings=settings, providers=providers)
