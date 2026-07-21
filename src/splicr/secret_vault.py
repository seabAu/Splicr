"""Secure, replaceable storage for API-resource credentials.

Resource specifications store only an opaque credential reference.  The secret itself
is kept behind :class:`SecretVault`, normally in the operating system credential store.
"""

from __future__ import annotations

import importlib
import json
import os
import tempfile
import threading
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from cryptography.fernet import Fernet, InvalidToken


SECURE_STORAGE_UNAVAILABLE = (
    "Secure credential storage is unavailable or could not be decrypted. Check the "
    "configured vault backend and key, then try again."
)


class SecretVaultError(RuntimeError):
    """Base class for stable credential-vault failures."""


class SecretVaultUnavailableError(SecretVaultError):
    """Raised when a secure keyring cannot be loaded or used."""


@runtime_checkable
class SecretVault(Protocol):
    """Minimal credential-store contract used by the API-resource catalog."""

    def set_secret(self, reference: str, secret: str) -> None:
        """Create or replace ``reference`` without returning the secret."""

    def get_secret(self, reference: str) -> str | None:
        """Resolve a secret for internal request execution only."""

    def delete_secret(self, reference: str) -> None:
        """Delete ``reference``; deleting a missing secret is idempotent."""


def _validate_reference(reference: str) -> str:
    if not isinstance(reference, str) or not reference.strip():
        raise ValueError("secret reference must be a non-empty string")
    if len(reference) > 255:
        raise ValueError("secret reference cannot exceed 255 characters")
    if any(character in reference for character in ("\x00", "\r", "\n")):
        raise ValueError("secret reference contains an invalid control character")
    return reference


def _validate_secret(secret: str) -> str:
    if not isinstance(secret, str) or not secret.strip():
        raise ValueError("API key must be a non-empty string")
    if any(character in secret for character in ("\x00", "\r", "\n")):
        raise ValueError("API key contains an invalid control character")
    return secret


class KeyringSecretVault:
    """Store credentials through Python keyring and the host OS credential backend.

    ``keyring`` is imported lazily so catalog reads and environment-only deployments do
    not require it.  There is intentionally no file or plaintext fallback.
    """

    def __init__(
        self,
        service_name: str = "splicr.api-resources",
        *,
        keyring_module: Any | None = None,
    ) -> None:
        if not service_name.strip():
            raise ValueError("service_name must be non-empty")
        self._service_name = service_name
        self._keyring_module = keyring_module
        self._lock = threading.RLock()

    def set_secret(self, reference: str, secret: str) -> None:
        reference = _validate_reference(reference)
        secret = _validate_secret(secret)
        keyring = self._keyring()
        try:
            with self._lock:
                keyring.set_password(self._service_name, reference, secret)
        except Exception as error:
            raise SecretVaultUnavailableError(SECURE_STORAGE_UNAVAILABLE) from error

    def get_secret(self, reference: str) -> str | None:
        reference = _validate_reference(reference)
        keyring = self._keyring()
        try:
            with self._lock:
                value = keyring.get_password(self._service_name, reference)
        except Exception as error:
            raise SecretVaultUnavailableError(SECURE_STORAGE_UNAVAILABLE) from error
        if value is None:
            return None
        if not isinstance(value, str):
            raise SecretVaultUnavailableError(SECURE_STORAGE_UNAVAILABLE)
        return value

    def delete_secret(self, reference: str) -> None:
        reference = _validate_reference(reference)
        keyring = self._keyring()
        try:
            with self._lock:
                # Most keyring backends raise when deleting an absent password.  Checking
                # first gives the protocol idempotent deletion semantics.
                if keyring.get_password(self._service_name, reference) is not None:
                    keyring.delete_password(self._service_name, reference)
        except Exception as error:
            raise SecretVaultUnavailableError(SECURE_STORAGE_UNAVAILABLE) from error

    def _keyring(self) -> Any:
        if self._keyring_module is not None:
            return self._keyring_module
        try:
            self._keyring_module = importlib.import_module("keyring")
        except Exception as error:
            raise SecretVaultUnavailableError(SECURE_STORAGE_UNAVAILABLE) from error
        return self._keyring_module


class EncryptedFileSecretVault:
    """Persist credentials in one Fernet-encrypted, atomically replaced file.

    This backend is intended for headless/container deployments where an operating-system
    keyring is unavailable. The encryption key is kept in a separate mounted secret file;
    neither the key nor plaintext credentials are written to the data directory.

    Updates are serialized within this process. SPLICR intentionally deploys one process and
    one container; a multi-process deployment would require an inter-process locking backend.
    """

    _VERSION = 1

    def __init__(self, path: Path, *, key_file: Path) -> None:
        self._path = Path(path)
        self._key_file = Path(key_file)
        self._lock = threading.RLock()
        self._fernet = self._load_fernet()

    def set_secret(self, reference: str, secret: str) -> None:
        reference = _validate_reference(reference)
        secret = _validate_secret(secret)
        with self._lock:
            secrets = self._read_secrets()
            secrets[reference] = secret
            self._write_secrets(secrets)

    def get_secret(self, reference: str) -> str | None:
        reference = _validate_reference(reference)
        with self._lock:
            return self._read_secrets().get(reference)

    def delete_secret(self, reference: str) -> None:
        reference = _validate_reference(reference)
        with self._lock:
            secrets = self._read_secrets()
            if reference not in secrets:
                return
            del secrets[reference]
            self._write_secrets(secrets)

    def _load_fernet(self) -> Fernet:
        try:
            key = self._key_file.read_bytes().strip()
            return Fernet(key)
        except (OSError, ValueError) as error:
            raise SecretVaultUnavailableError(SECURE_STORAGE_UNAVAILABLE) from error

    def _read_secrets(self) -> dict[str, str]:
        if not self._path.exists():
            return {}
        try:
            plaintext = self._fernet.decrypt(self._path.read_bytes())
            payload = json.loads(plaintext.decode("utf-8"))
            if not isinstance(payload, dict) or payload.get("version") != self._VERSION:
                raise ValueError("unsupported vault payload")
            raw_secrets = payload.get("secrets")
            if not isinstance(raw_secrets, dict):
                raise ValueError("invalid vault payload")
            secrets: dict[str, str] = {}
            for reference, secret in raw_secrets.items():
                secrets[_validate_reference(reference)] = _validate_secret(secret)
            return secrets
        except (
            InvalidToken,
            OSError,
            UnicodeDecodeError,
            json.JSONDecodeError,
            TypeError,
            ValueError,
        ) as error:
            raise SecretVaultUnavailableError(SECURE_STORAGE_UNAVAILABLE) from error

    def _write_secrets(self, secrets: dict[str, str]) -> None:
        payload = json.dumps(
            {"version": self._VERSION, "secrets": secrets},
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        token = self._fernet.encrypt(payload)
        temporary_path: Path | None = None
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            descriptor, temporary_name = tempfile.mkstemp(
                dir=self._path.parent,
                prefix=f".{self._path.name}.",
                suffix=".tmp",
            )
            temporary_path = Path(temporary_name)
            try:
                os.chmod(temporary_path, 0o600)
                with os.fdopen(descriptor, "wb") as temporary_file:
                    temporary_file.write(token)
                    temporary_file.flush()
                    os.fsync(temporary_file.fileno())
            except Exception:
                try:
                    os.close(descriptor)
                except OSError:
                    pass
                raise
            os.replace(temporary_path, self._path)
            self._sync_parent_directory()
        except OSError as error:
            raise SecretVaultUnavailableError(SECURE_STORAGE_UNAVAILABLE) from error
        finally:
            if temporary_path is not None:
                try:
                    temporary_path.unlink(missing_ok=True)
                except OSError:
                    pass

    def _sync_parent_directory(self) -> None:
        if os.name != "posix":
            return
        try:
            descriptor = os.open(
                self._path.parent,
                os.O_RDONLY | getattr(os, "O_DIRECTORY", 0),
            )
        except OSError:
            return
        try:
            os.fsync(descriptor)
        except OSError:
            pass
        finally:
            os.close(descriptor)


class InMemorySecretVault:
    """Thread-safe ephemeral vault for tests and explicitly temporary sessions."""

    def __init__(self) -> None:
        self._secrets: dict[str, str] = {}
        self._lock = threading.RLock()

    def set_secret(self, reference: str, secret: str) -> None:
        reference = _validate_reference(reference)
        secret = _validate_secret(secret)
        with self._lock:
            self._secrets[reference] = secret

    def get_secret(self, reference: str) -> str | None:
        reference = _validate_reference(reference)
        with self._lock:
            return self._secrets.get(reference)

    def delete_secret(self, reference: str) -> None:
        reference = _validate_reference(reference)
        with self._lock:
            self._secrets.pop(reference, None)
