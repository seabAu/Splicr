from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from cryptography.fernet import Fernet

from splicr.secret_vault import (
    SECURE_STORAGE_UNAVAILABLE,
    EncryptedFileSecretVault,
    InMemorySecretVault,
    KeyringSecretVault,
    SecretVault,
    SecretVaultUnavailableError,
)


def _write_fernet_key(path: Path) -> bytes:
    key = Fernet.generate_key()
    path.write_bytes(key)
    return key


def test_in_memory_vault_fulfills_protocol_and_never_returns_on_write() -> None:
    vault = InMemorySecretVault()

    assert isinstance(vault, SecretVault)
    assert vault.set_secret("resource:custom", "very-secret") is None
    assert vault.get_secret("resource:custom") == "very-secret"

    vault.delete_secret("resource:custom")
    vault.delete_secret("resource:custom")
    assert vault.get_secret("resource:custom") is None


def test_keyring_adapter_uses_service_and_reference() -> None:
    values: dict[tuple[str, str], str] = {}
    fake = SimpleNamespace(
        set_password=lambda service, reference, secret: values.__setitem__(
            (service, reference), secret
        ),
        get_password=lambda service, reference: values.get((service, reference)),
        delete_password=lambda service, reference: values.pop((service, reference)),
    )
    vault = KeyringSecretVault("test.splicr", keyring_module=fake)

    vault.set_secret("resource:demo", "key-value")
    assert values == {("test.splicr", "resource:demo"): "key-value"}
    assert vault.get_secret("resource:demo") == "key-value"
    vault.delete_secret("resource:demo")
    vault.delete_secret("resource:demo")


def test_encrypted_file_vault_persists_without_plaintext(tmp_path: Path) -> None:
    key_file = tmp_path / "vault.key"
    _write_fernet_key(key_file)
    vault_path = tmp_path / "data" / "api-resources.vault"

    vault = EncryptedFileSecretVault(vault_path, key_file=key_file)
    vault.set_secret("resource:demo", "very-secret-value")

    ciphertext = vault_path.read_bytes()
    assert b"resource:demo" not in ciphertext
    assert b"very-secret-value" not in ciphertext
    assert EncryptedFileSecretVault(vault_path, key_file=key_file).get_secret(
        "resource:demo"
    ) == "very-secret-value"

    vault.delete_secret("resource:demo")
    vault.delete_secret("resource:demo")
    assert vault.get_secret("resource:demo") is None


def test_encrypted_file_vault_rejects_wrong_key_without_leaking_data(tmp_path: Path) -> None:
    key_file = tmp_path / "vault.key"
    _write_fernet_key(key_file)
    vault_path = tmp_path / "api-resources.vault"
    EncryptedFileSecretVault(vault_path, key_file=key_file).set_secret(
        "resource:demo", "very-secret-value"
    )
    wrong_key_file = tmp_path / "wrong.key"
    _write_fernet_key(wrong_key_file)

    with pytest.raises(SecretVaultUnavailableError) as raised:
        EncryptedFileSecretVault(vault_path, key_file=wrong_key_file).get_secret(
            "resource:demo"
        )

    assert str(raised.value) == SECURE_STORAGE_UNAVAILABLE
    assert "very-secret-value" not in str(raised.value)


def test_encrypted_file_vault_requires_valid_key_file(tmp_path: Path) -> None:
    missing_key = tmp_path / "missing.key"
    with pytest.raises(SecretVaultUnavailableError, match="Secure credential storage"):
        EncryptedFileSecretVault(tmp_path / "vault", key_file=missing_key)


@pytest.mark.parametrize("operation", ["set", "get", "delete"])
def test_keyring_backend_failures_have_one_stable_error(operation: str) -> None:
    def fail(*_args: str) -> None:
        raise RuntimeError("backend leaked detail")

    fake = SimpleNamespace(set_password=fail, get_password=fail, delete_password=fail)
    vault = KeyringSecretVault(keyring_module=fake)

    with pytest.raises(SecretVaultUnavailableError) as raised:
        if operation == "set":
            vault.set_secret("resource:demo", "key-value")
        elif operation == "get":
            vault.get_secret("resource:demo")
        else:
            vault.delete_secret("resource:demo")

    assert str(raised.value) == SECURE_STORAGE_UNAVAILABLE
    assert "backend leaked detail" not in str(raised.value)


@pytest.mark.parametrize(
    ("reference", "secret", "message"),
    [
        ("", "secret", "reference"),
        ("resource:demo", "", "API key"),
        ("resource:demo", "line\nbreak", "control character"),
    ],
)
def test_vault_rejects_ambiguous_or_header_injection_values(
    reference: str, secret: str, message: str
) -> None:
    vault = InMemorySecretVault()
    with pytest.raises(ValueError, match=message):
        vault.set_secret(reference, secret)
