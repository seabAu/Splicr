from __future__ import annotations

import json
import os
import re
import sqlite3
import threading
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .secret_vault import KeyringSecretVault, SecretVault
from .studio.chat import ChatResource


_RESOURCE_ID_RE = re.compile(r"[a-z][a-z0-9._-]{0,63}")
_ENV_NAME_RE = re.compile(r"[A-Z_][A-Z0-9_]{0,127}")
_SCHEMA_VERSION = 1


class ChatResourceError(RuntimeError):
    pass


class ChatResourceNotFoundError(ChatResourceError):
    pass


class ChatResourceConflictError(ChatResourceError):
    pass


@dataclass(frozen=True, slots=True)
class ChatResourceSpec:
    resource_id: str
    revision: int
    name: str
    base_url: str
    default_model: str
    models: tuple[str, ...] = ()
    description: str = ""
    local: bool = False
    allow_insecure_http: bool = False
    headers: Mapping[str, str] = field(default_factory=dict)
    timeout_seconds: float = 180.0
    api_key_envs: tuple[str, ...] = ()
    built_in: bool = False

    def __post_init__(self) -> None:
        if not _RESOURCE_ID_RE.fullmatch(self.resource_id):
            raise ValueError("invalid chat resource id")
        if isinstance(self.revision, bool) or not isinstance(self.revision, int) or self.revision < 1:
            raise ValueError("chat resource revision must be positive")
        if not isinstance(self.description, str) or len(self.description) > 10_000:
            raise ValueError("chat resource description cannot exceed 10000 characters")
        default_model = self.default_model.strip()
        models = tuple(model.strip() for model in self.models if model.strip())
        if len(models) != len(set(models)):
            raise ValueError("chat resource models must be unique")
        if default_model not in models:
            models = (default_model, *models)
        envs = tuple(self.api_key_envs)
        if any(not _ENV_NAME_RE.fullmatch(name) for name in envs):
            raise ValueError("chat API-key environment variable names are invalid")
        if len(envs) != len(set(envs)):
            raise ValueError("chat API-key environment variable names must be unique")
        runtime = ChatResource(
            resource_id=self.resource_id,
            name=self.name,
            base_url=self.base_url,
            model=default_model,
            local=self.local,
            allow_insecure_http=self.allow_insecure_http,
            headers=dict(self.headers or {}),
            timeout_seconds=self.timeout_seconds,
        )
        object.__setattr__(self, "name", runtime.name)
        object.__setattr__(self, "base_url", runtime.base_url)
        object.__setattr__(self, "default_model", runtime.model)
        object.__setattr__(self, "models", models)
        object.__setattr__(self, "headers", runtime.headers)
        object.__setattr__(self, "api_key_envs", envs)

    def runtime(self, *, model: str | None = None) -> ChatResource:
        selected = (model or self.default_model).strip()
        if self.models and selected not in self.models:
            raise ValueError(f"model {selected!r} is not configured for {self.name}")
        return ChatResource(
            resource_id=self.resource_id,
            name=self.name,
            base_url=self.base_url,
            model=selected,
            local=self.local,
            allow_insecure_http=self.allow_insecure_http,
            headers=self.headers,
            timeout_seconds=self.timeout_seconds,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": _SCHEMA_VERSION,
            "resource_id": self.resource_id,
            "revision": self.revision,
            "name": self.name,
            "description": self.description,
            "base_url": self.base_url,
            "default_model": self.default_model,
            "models": list(self.models),
            "local": self.local,
            "allow_insecure_http": self.allow_insecure_http,
            "headers": dict(self.headers),
            "timeout_seconds": self.timeout_seconds,
            "api_key_envs": list(self.api_key_envs),
            "built_in": self.built_in,
        }

    def to_json(self) -> str:
        return json.dumps(
            self.to_dict(),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )

    @classmethod
    def from_json(cls, payload: str) -> "ChatResourceSpec":
        try:
            value = json.loads(payload)
        except (TypeError, json.JSONDecodeError) as error:
            raise ValueError("invalid chat resource JSON") from error
        if not isinstance(value, dict) or value.get("schema_version") != _SCHEMA_VERSION:
            raise ValueError("unsupported chat resource schema")
        return cls(
            resource_id=value["resource_id"],
            revision=value["revision"],
            name=value["name"],
            description=value.get("description", ""),
            base_url=value["base_url"],
            default_model=value["default_model"],
            models=tuple(value.get("models", ())),
            local=value.get("local", False),
            allow_insecure_http=value.get("allow_insecure_http", False),
            headers=value.get("headers", {}),
            timeout_seconds=value.get("timeout_seconds", 180.0),
            api_key_envs=tuple(value.get("api_key_envs", ())),
            built_in=value.get("built_in", False),
        )


@dataclass(frozen=True, slots=True)
class StoredChatResource:
    spec: ChatResourceSpec
    created_at: str
    deleted: bool = False


class SqliteChatResourceStore:
    def __init__(
        self,
        database_path: Path,
        vault: SecretVault | None = None,
        *,
        environ: Mapping[str, str] | None = None,
    ) -> None:
        self.database_path = Path(database_path)
        self.vault = vault if vault is not None else KeyringSecretVault()
        self.environ = environ if environ is not None else os.environ
        self._lock = threading.RLock()

    def initialize(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS chat_resource_revisions (
                    resource_id TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    spec_json TEXT NOT NULL,
                    deleted INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (resource_id, revision)
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_chat_resource_latest
                ON chat_resource_revisions(resource_id, revision DESC)
                """
            )
            connection.commit()

    def seed_builtins(self) -> None:
        for spec in builtin_chat_resources():
            try:
                self.create(spec)
            except ChatResourceConflictError:
                continue

    def create(self, spec: ChatResourceSpec) -> StoredChatResource:
        if spec.revision != 1:
            raise ValueError("a new chat resource must start at revision 1")
        with self._lock, self._connect() as connection:
            current = self._current_row(connection, spec.resource_id)
            if current is not None:
                raise ChatResourceConflictError(
                    f"chat resource already exists: {spec.resource_id}"
                )
            created_at = _utc_now()
            self._insert(connection, spec, deleted=False, created_at=created_at)
            connection.commit()
        return StoredChatResource(spec, created_at)

    def update(
        self,
        resource_id: str,
        spec: ChatResourceSpec,
        *,
        expected_revision: int | None = None,
    ) -> StoredChatResource:
        if spec.resource_id != resource_id:
            raise ValueError("resource id cannot be changed")
        with self._lock, self._connect() as connection:
            row = self._current_row(connection, resource_id)
            if row is None or bool(row["deleted"]):
                raise ChatResourceNotFoundError(f"chat resource not found: {resource_id}")
            current = ChatResourceSpec.from_json(row["spec_json"])
            if expected_revision is not None and current.revision != expected_revision:
                raise ChatResourceConflictError(
                    f"chat resource {resource_id} changed; expected revision {expected_revision}, current revision is {current.revision}"
                )
            next_spec = replace(spec, revision=current.revision + 1, built_in=current.built_in)
            created_at = _utc_now()
            self._insert(connection, next_spec, deleted=False, created_at=created_at)
            connection.commit()
        return StoredChatResource(next_spec, created_at)

    def soft_delete(self, resource_id: str) -> StoredChatResource:
        with self._lock, self._connect() as connection:
            row = self._current_row(connection, resource_id)
            if row is None or bool(row["deleted"]):
                raise ChatResourceNotFoundError(f"chat resource not found: {resource_id}")
            current = ChatResourceSpec.from_json(row["spec_json"])
            if current.built_in:
                raise ChatResourceConflictError("built-in chat resources cannot be deleted")
            deleted = replace(current, revision=current.revision + 1)
            created_at = _utc_now()
            self._insert(connection, deleted, deleted=True, created_at=created_at)
            connection.commit()
        self.clear_api_key(resource_id)
        return StoredChatResource(deleted, created_at, deleted=True)

    def list(self) -> list[StoredChatResource]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                """
                SELECT revisions.* FROM chat_resource_revisions AS revisions
                JOIN (
                    SELECT resource_id, MAX(revision) AS revision
                    FROM chat_resource_revisions GROUP BY resource_id
                ) AS latest
                ON revisions.resource_id = latest.resource_id
                AND revisions.revision = latest.revision
                WHERE revisions.deleted = 0
                ORDER BY json_extract(revisions.spec_json, '$.name'), revisions.resource_id
                """
            ).fetchall()
        return [self._stored(row) for row in rows]

    def get_current(self, resource_id: str) -> StoredChatResource:
        with self._lock, self._connect() as connection:
            row = self._current_row(connection, resource_id)
        if row is None or bool(row["deleted"]):
            raise ChatResourceNotFoundError(f"chat resource not found: {resource_id}")
        return self._stored(row)

    def set_api_key(self, resource_id: str, api_key: str) -> None:
        self.get_current(resource_id)
        self.vault.set_secret(self._credential_reference(resource_id), api_key)

    def clear_api_key(self, resource_id: str) -> None:
        self.vault.delete_secret(self._credential_reference(resource_id))

    def resolve_api_key(self, resource_id: str) -> str | None:
        stored = self.get_current(resource_id)
        secret = self.vault.get_secret(self._credential_reference(resource_id))
        if secret:
            return secret
        for env_name in stored.spec.api_key_envs:
            candidate = self.environ.get(env_name)
            if candidate:
                return candidate
        return None

    def api_key_source(self, resource_id: str) -> str | None:
        stored = self.get_current(resource_id)
        if self.vault.get_secret(self._credential_reference(resource_id)):
            return "vault"
        return next(
            (f"environment:{name}" for name in stored.spec.api_key_envs if self.environ.get(name)),
            None,
        )

    @staticmethod
    def _credential_reference(resource_id: str) -> str:
        return f"splicr.chat.{resource_id}"

    @staticmethod
    def _insert(
        connection: sqlite3.Connection,
        spec: ChatResourceSpec,
        *,
        deleted: bool,
        created_at: str,
    ) -> None:
        connection.execute(
            """
            INSERT INTO chat_resource_revisions
                (resource_id, revision, spec_json, deleted, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (spec.resource_id, spec.revision, spec.to_json(), int(deleted), created_at),
        )

    @staticmethod
    def _stored(row: sqlite3.Row) -> StoredChatResource:
        return StoredChatResource(
            spec=ChatResourceSpec.from_json(row["spec_json"]),
            created_at=row["created_at"],
            deleted=bool(row["deleted"]),
        )

    @staticmethod
    def _current_row(
        connection: sqlite3.Connection,
        resource_id: str,
    ) -> sqlite3.Row | None:
        return connection.execute(
            """
            SELECT * FROM chat_resource_revisions
            WHERE resource_id = ? ORDER BY revision DESC LIMIT 1
            """,
            (resource_id,),
        ).fetchone()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        return connection


def builtin_chat_resources() -> tuple[ChatResourceSpec, ...]:
    return (
        ChatResourceSpec(
            "ollama",
            1,
            "Ollama (local)",
            "http://localhost:11434/v1",
            "qwen3:14b",
            description="OpenAI-compatible Ollama server on this computer.",
            local=True,
            built_in=True,
        ),
        ChatResourceSpec(
            "lmstudio",
            1,
            "LM Studio (local)",
            "http://localhost:1234/v1",
            "local-model",
            description="LM Studio's local OpenAI-compatible server.",
            local=True,
            built_in=True,
        ),
        ChatResourceSpec(
            "llamacpp",
            1,
            "llama.cpp server (local)",
            "http://localhost:8080/v1",
            "local-model",
            description="A local llama-server OpenAI-compatible endpoint.",
            local=True,
            built_in=True,
        ),
    )


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()
