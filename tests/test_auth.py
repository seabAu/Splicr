from __future__ import annotations

import json
import re
from argparse import Namespace
from io import StringIO

from fastapi.testclient import TestClient

from splicr.__main__ import _manage_auth
from splicr.api import create_app
from splicr.auth import AuthManager
from splicr.config import Settings
from splicr.providers import ProviderRegistry
from splicr.service import SynthesisService

from .fakes import RecordingProvider


PASSWORD = "correct horse battery staple"
NEW_PASSWORD = "an even better horse battery staple"


def _settings(tmp_path, *, configured: bool = True) -> Settings:
    settings = Settings(
        data_dir=tmp_path,
        auth_enabled=True,
        auth_cookie_secure=True,
        auth_session_seconds=3_600,
        pacing_seconds=0,
    )
    if configured:
        AuthManager(settings.auth_credentials_path).set_password("ember", PASSWORD)
    return settings


def _app(settings: Settings):
    service = SynthesisService(
        settings=settings,
        providers=ProviderRegistry([RecordingProvider()]),
    )
    return create_app(settings=settings, service=service)


def _login(client: TestClient, password: str = PASSWORD, *, next_path: str = "/"):
    return client.post(
        "/auth/login",
        data={"username": "ember", "password": password, "next": next_path},
        follow_redirects=False,
    )


def _csrf(document: str) -> str:
    match = re.search(r'name="csrf_token" value="([^"]+)"', document)
    assert match is not None
    return match.group(1)


def test_unconfigured_production_auth_fails_closed_but_health_remains_available(tmp_path) -> None:
    settings = _settings(tmp_path, configured=False)
    with TestClient(_app(settings), base_url="https://testserver") as client:
        health = client.get("/health")
        root = client.get("/", follow_redirects=False)
        api = client.get("/v1/providers")
        auth = client.get("/auth")
        stylesheet = client.get("/assets/auth.css")

    assert health.status_code == 200
    assert root.status_code == 303
    assert root.headers["location"] == "/auth?next=%2F"
    assert api.status_code == 401
    assert api.json()["error_code"] == "authentication_required"
    assert "www-authenticate" not in api.headers
    assert auth.status_code == 503
    assert "Authentication is not configured" in auth.text
    assert "splicr auth set-password" in auth.text
    assert auth.headers["cache-control"] == "no-store"
    assert stylesheet.status_code == 200


def test_login_form_supports_password_managers_and_issues_hardened_cookie(tmp_path) -> None:
    settings = _settings(tmp_path)
    with TestClient(_app(settings), base_url="https://testserver") as client:
        login_page = client.get("/auth")
        rejected = _login(client, "incorrect password")
        accepted = _login(client, next_path="/docs")
        root = client.get("/")
        providers = client.get("/v1/providers")
        account = client.get("/auth/settings")

    assert login_page.status_code == 200
    assert 'name="username" type="text"' in login_page.text
    assert 'autocomplete="username"' in login_page.text
    assert 'name="password" type="password"' in login_page.text
    assert 'autocomplete="current-password"' in login_page.text
    assert rejected.status_code == 401
    assert "set-cookie" not in rejected.headers
    assert accepted.status_code == 303
    assert accepted.headers["location"] == "/docs"
    cookie = accepted.headers["set-cookie"]
    assert "__Host-splicr_session=" in cookie
    assert "HttpOnly" in cookie
    assert "Secure" in cookie
    assert "SameSite=strict" in cookie
    assert "Path=/" in cookie
    assert root.status_code == 200
    assert providers.status_code == 200
    assert account.status_code == 200
    assert 'autocomplete="current-password"' in account.text
    assert account.text.count('autocomplete="new-password"') == 2


def test_login_rejects_external_redirect_targets(tmp_path) -> None:
    settings = _settings(tmp_path)
    with TestClient(_app(settings), base_url="https://testserver") as client:
        accepted = _login(client, next_path="https://example.com/stolen")

    assert accepted.status_code == 303
    assert accepted.headers["location"] == "/"


def test_opt_in_local_http_authentication_uses_a_non_host_prefixed_cookie(tmp_path) -> None:
    settings = Settings(
        data_dir=tmp_path,
        auth_enabled=True,
        auth_cookie_secure=False,
        pacing_seconds=0,
    )
    AuthManager(settings.auth_credentials_path).set_password("ember", PASSWORD)

    with TestClient(_app(settings), base_url="http://testserver") as client:
        accepted = _login(client)
        root = client.get("/")

    cookie = accepted.headers["set-cookie"]
    assert "splicr_session=" in cookie
    assert "__Host-" not in cookie
    assert "Secure" not in cookie
    assert root.status_code == 200


def test_password_change_rotates_sessions_and_requires_csrf(tmp_path) -> None:
    settings = _settings(tmp_path)
    with (
        TestClient(_app(settings), base_url="https://testserver") as primary,
        TestClient(_app(settings), base_url="https://testserver") as older_session,
    ):
        assert _login(primary).status_code == 303
        assert _login(older_session).status_code == 303
        account = primary.get("/auth/settings")
        rejected = primary.post(
            "/auth/password",
            data={
                "csrf_token": "wrong",
                "current_password": PASSWORD,
                "new_password": NEW_PASSWORD,
                "confirm_password": NEW_PASSWORD,
            },
            follow_redirects=False,
        )
        changed = primary.post(
            "/auth/password",
            data={
                "csrf_token": _csrf(account.text),
                "current_password": PASSWORD,
                "new_password": NEW_PASSWORD,
                "confirm_password": NEW_PASSWORD,
            },
            follow_redirects=False,
        )
        revoked = older_session.get("/v1/providers")
        old_password = _login(older_session, PASSWORD)
        new_password = _login(older_session, NEW_PASSWORD)

    assert rejected.status_code == 403
    assert changed.status_code == 303
    assert changed.headers["location"] == "/auth/settings?changed=1"
    assert revoked.status_code == 401
    assert old_password.status_code == 401
    assert new_password.status_code == 303


def test_logout_clears_the_session_cookie(tmp_path) -> None:
    settings = _settings(tmp_path)
    with TestClient(_app(settings), base_url="https://testserver") as client:
        assert _login(client).status_code == 303
        account = client.get("/auth/settings")
        response = client.post(
            "/auth/logout",
            data={"csrf_token": _csrf(account.text)},
            follow_redirects=False,
        )
        protected = client.get("/", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/auth"
    assert "Max-Age=0" in response.headers["set-cookie"]
    assert protected.status_code == 303


def test_auth_manager_never_persists_plaintext_and_rejects_tampered_sessions(tmp_path) -> None:
    path = tmp_path / "auth" / "credentials.json"
    manager = AuthManager(path)
    manager.set_password("ember", PASSWORD)
    token, session = manager.issue_session("ember")

    persisted = path.read_text(encoding="utf-8")
    record = json.loads(persisted)

    assert PASSWORD not in persisted
    assert record["password"]["algorithm"] == "pbkdf2-sha256"
    assert record["password"]["iterations"] == 600_000
    assert manager.verify_session(token) == session
    assert manager.verify_session(f"{token[:-1]}A") is None
    assert manager.authenticate("ember", PASSWORD) is True
    assert manager.authenticate("ember", "incorrect password") is False


def test_cli_password_reset_uses_the_configured_data_directory(
    monkeypatch,
    tmp_path,
    capsys,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SPLICR_DATA_DIR", str(tmp_path / "state"))
    monkeypatch.setattr("sys.stdin", StringIO(f"{PASSWORD}\n"))

    result = _manage_auth(
        Namespace(
            auth_command="set-password",
            username="ember",
            password_stdin=True,
        )
    )

    settings = Settings.from_env()
    manager = AuthManager(settings.auth_credentials_path)
    assert result == 0
    assert manager.authenticate("ember", PASSWORD) is True
    assert "All existing sessions have been invalidated" in capsys.readouterr().out
