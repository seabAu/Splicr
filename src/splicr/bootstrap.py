from __future__ import annotations

from .api_resources import SqliteApiResourceStore
from .config import Settings
from .resource_registry import ResourceProviderRegistry
from .secret_vault import EncryptedFileSecretVault
from .service import SynthesisService


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
    providers = ResourceProviderRegistry(resource_store, settings=settings)
    return SynthesisService(settings=settings, providers=providers)
