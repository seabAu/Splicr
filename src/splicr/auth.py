from __future__ import annotations

import base64
import hashlib
import hmac
import html
import json
import os
import re
import secrets
import tempfile
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TypedDict, cast
from urllib.parse import quote, urlsplit

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response

from .config import Settings


_STATIC_ROOT = Path(__file__).with_name("static")
_SECURE_COOKIE_NAME = "__Host-splicr_session"
_LOCAL_COOKIE_NAME = "splicr_session"
_PASSWORD_ALGORITHM = "pbkdf2-sha256"
_PASSWORD_ITERATIONS = 600_000
_PASSWORD_MIN_LENGTH = 12
_PASSWORD_MAX_LENGTH = 1_024
_USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
_AUTH_CSP = "; ".join(
    (
        "default-src 'self'",
        "script-src 'none'",
        "style-src 'self'",
        "img-src 'self' data:",
        "object-src 'none'",
        "base-uri 'none'",
        "frame-ancestors 'none'",
        "form-action 'self'",
    )
)


class AuthConfigurationError(RuntimeError):
    """Raised when persisted authentication state is missing or invalid."""


@dataclass(frozen=True, slots=True)
class AuthSession:
    username: str
    csrf_token: str
    expires_at: int


class PasswordRecord(TypedDict):
    algorithm: str
    iterations: int
    salt: str
    digest: str


class CredentialRecord(TypedDict):
    version: int
    username: str
    password: PasswordRecord
    session_secret: str
    session_version: int
    updated_at: str


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def _password_digest(password: str, salt: bytes, iterations: int) -> bytes:
    return hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        iterations,
        dklen=32,
    )


def _safe_next(value: str | None, default: str = "/") -> str:
    candidate = (value or "").strip()
    parsed = urlsplit(candidate)
    if (
        not candidate.startswith("/")
        or candidate.startswith("//")
        or "\\" in candidate
        or parsed.scheme
        or parsed.netloc
    ):
        return default
    return candidate


def _security_headers() -> dict[str, str]:
    return {
        "Cache-Control": "no-store",
        "Content-Security-Policy": _AUTH_CSP,
        "Referrer-Policy": "no-referrer",
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
    }


def _cookie_name(settings: Settings) -> str:
    return _SECURE_COOKIE_NAME if settings.auth_cookie_secure else _LOCAL_COOKIE_NAME


class AuthManager:
    def __init__(self, path: Path, *, session_seconds: int = 43_200) -> None:
        self.path = path
        self.session_seconds = session_seconds
        self._lock = threading.RLock()

    @property
    def is_configured(self) -> bool:
        try:
            self._read_credentials()
        except AuthConfigurationError:
            return False
        return True

    @property
    def configured_username(self) -> str | None:
        try:
            return str(self._read_credentials()["username"])
        except AuthConfigurationError:
            return None

    def set_password(self, username: str, password: str) -> None:
        username = username.strip()
        self._validate_username(username)
        self._validate_new_password(password)
        with self._lock:
            previous_version = 0
            if self.path.exists():
                try:
                    previous_version = int(self._read_credentials()["session_version"])
                except AuthConfigurationError:
                    previous_version = 0
            salt = secrets.token_bytes(16)
            record: CredentialRecord = {
                "version": 1,
                "username": username,
                "password": {
                    "algorithm": _PASSWORD_ALGORITHM,
                    "iterations": _PASSWORD_ITERATIONS,
                    "salt": _b64encode(salt),
                    "digest": _b64encode(
                        _password_digest(password, salt, _PASSWORD_ITERATIONS)
                    ),
                },
                "session_secret": _b64encode(secrets.token_bytes(32)),
                "session_version": previous_version + 1,
                "updated_at": datetime.now(UTC).isoformat(),
            }
            self._atomic_write(record)

    def authenticate(self, username: str, password: str) -> bool:
        if len(password) > _PASSWORD_MAX_LENGTH:
            return False
        try:
            record = self._read_credentials()
            password_record = record["password"]
            expected = _b64decode(str(password_record["digest"]))
            actual = _password_digest(
                password,
                _b64decode(str(password_record["salt"])),
                int(password_record["iterations"]),
            )
        except (AuthConfigurationError, KeyError, TypeError, ValueError):
            return False
        return hmac.compare_digest(
            str(record["username"]).encode("utf-8"),
            username.encode("utf-8"),
        ) and hmac.compare_digest(expected, actual)

    def change_password(self, username: str, current_password: str, new_password: str) -> None:
        if not self.authenticate(username, current_password):
            raise ValueError("The current password is incorrect.")
        self.set_password(username, new_password)

    def issue_session(self, username: str) -> tuple[str, AuthSession]:
        record = self._read_credentials()
        if not hmac.compare_digest(
            str(record["username"]).encode("utf-8"),
            username.encode("utf-8"),
        ):
            raise AuthConfigurationError("authentication credentials do not match")
        now = int(time.time())
        session = AuthSession(
            username=username,
            csrf_token=_b64encode(secrets.token_bytes(24)),
            expires_at=now + self.session_seconds,
        )
        payload = {
            "u": session.username,
            "v": int(record["session_version"]),
            "iat": now,
            "exp": session.expires_at,
            "csrf": session.csrf_token,
            "jti": _b64encode(secrets.token_bytes(16)),
        }
        encoded = _b64encode(
            json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
        )
        signature = hmac.new(
            _b64decode(str(record["session_secret"])),
            encoded.encode("ascii"),
            hashlib.sha256,
        ).digest()
        return f"{encoded}.{_b64encode(signature)}", session

    def verify_session(self, token: str | None) -> AuthSession | None:
        if not token:
            return None
        try:
            encoded, provided_signature = token.split(".", 1)
            record = self._read_credentials()
            expected_signature = hmac.new(
                _b64decode(str(record["session_secret"])),
                encoded.encode("ascii"),
                hashlib.sha256,
            ).digest()
            if not hmac.compare_digest(expected_signature, _b64decode(provided_signature)):
                return None
            payload = json.loads(_b64decode(encoded))
            now = int(time.time())
            if int(payload["exp"]) <= now or int(payload["iat"]) > now + 60:
                return None
            if int(payload["v"]) != int(record["session_version"]):
                return None
            username = str(payload["u"])
            if not hmac.compare_digest(username, str(record["username"])):
                return None
            return AuthSession(
                username=username,
                csrf_token=str(payload["csrf"]),
                expires_at=int(payload["exp"]),
            )
        except (AuthConfigurationError, KeyError, TypeError, ValueError, json.JSONDecodeError):
            return None

    @staticmethod
    def _validate_username(username: str) -> None:
        if not _USERNAME_PATTERN.fullmatch(username):
            raise ValueError(
                "Username must be 1–64 letters, numbers, dots, underscores, or hyphens."
            )

    @staticmethod
    def _validate_new_password(password: str) -> None:
        if len(password) < _PASSWORD_MIN_LENGTH:
            raise ValueError(f"Password must be at least {_PASSWORD_MIN_LENGTH} characters.")
        if len(password) > _PASSWORD_MAX_LENGTH:
            raise ValueError(f"Password must be at most {_PASSWORD_MAX_LENGTH:,} characters.")

    def _read_credentials(self) -> CredentialRecord:
        with self._lock:
            try:
                payload = json.loads(self.path.read_text(encoding="utf-8"))
                if not isinstance(payload, dict) or not isinstance(payload.get("password"), dict):
                    raise ValueError("invalid authentication record")
                password = payload["password"]
                if (
                    int(payload["version"]) != 1
                    or not _USERNAME_PATTERN.fullmatch(str(payload["username"]))
                    or str(password["algorithm"]) != _PASSWORD_ALGORITHM
                    or int(password["iterations"]) < _PASSWORD_ITERATIONS
                    or int(payload["session_version"]) < 1
                    or len(_b64decode(str(payload["session_secret"]))) != 32
                ):
                    raise ValueError("invalid authentication record")
                _b64decode(str(password["salt"]))
                _b64decode(str(password["digest"]))
            except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
                raise AuthConfigurationError(
                    f"authentication is not configured at {self.path}"
                ) from error
            return cast(CredentialRecord, payload)

    def _atomic_write(self, record: CredentialRecord) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            dir=self.path.parent,
            prefix=f".{self.path.name}.",
            suffix=".tmp",
        )
        temporary_path = Path(temporary_name)
        try:
            os.chmod(temporary_path, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as temporary_file:
                json.dump(record, temporary_file, indent=2, sort_keys=True)
                temporary_file.write("\n")
                temporary_file.flush()
                os.fsync(temporary_file.fileno())
            os.replace(temporary_path, self.path)
            try:
                os.chmod(self.path, 0o600)
            except OSError:
                pass
        finally:
            temporary_path.unlink(missing_ok=True)


class LoginAttemptLimiter:
    def __init__(self, *, max_failures: int = 5, window_seconds: int = 300) -> None:
        self.max_failures = max_failures
        self.window_seconds = window_seconds
        self._failures: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def retry_after(self, key: str) -> int:
        now = time.monotonic()
        with self._lock:
            failures = [
                occurred
                for occurred in self._failures.get(key, [])
                if now - occurred < self.window_seconds
            ]
            self._failures[key] = failures
            if len(failures) < self.max_failures:
                return 0
            return max(1, int(self.window_seconds - (now - failures[0])))

    def record_failure(self, key: str) -> None:
        with self._lock:
            self._failures.setdefault(key, []).append(time.monotonic())

    def clear(self, key: str) -> None:
        with self._lock:
            self._failures.pop(key, None)


class AuthMiddleware:
    def __init__(
        self,
        app,
        *,
        manager: AuthManager,
        cookie_secure: bool,
    ) -> None:
        self.app = app
        self.manager = manager
        self.cookie_name = _SECURE_COOKIE_NAME if cookie_secure else _LOCAL_COOKIE_NAME

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request = Request(scope, receive=receive)
        path = request.url.path
        if (
            request.method == "OPTIONS"
            or path == "/health"
            or path in {"/auth", "/auth/login", "/assets/auth.css"}
        ):
            await self.app(scope, receive, send)
            return
        session = self.manager.verify_session(request.cookies.get(self.cookie_name))
        if session is not None:
            scope.setdefault("state", {})["auth_session"] = session
            await self.app(scope, receive, send)
            return
        if path.startswith("/v1/"):
            response = JSONResponse(
                {
                    "detail": "Authentication required.",
                    "error_code": "authentication_required",
                },
                status_code=401,
                headers={"Cache-Control": "no-store"},
            )
        else:
            destination = path
            if request.url.query:
                destination = f"{destination}?{request.url.query}"
            response = RedirectResponse(
                f"/auth?next={quote(destination, safe='')}",
                status_code=303,
                headers={"Cache-Control": "no-store"},
            )
        await response(scope, receive, send)


def _page(
    *,
    eyebrow: str,
    heading: str,
    body: str,
    status_code: int = 200,
) -> HTMLResponse:
    document = f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{html.escape(heading)} · SPLICR</title>
    <link rel="stylesheet" href="/assets/auth.css">
  </head>
  <body>
    <div class="ambient ambient-one" aria-hidden="true"></div>
    <div class="ambient ambient-two" aria-hidden="true"></div>
    <main class="auth-shell">
      <a class="brand" href="/" aria-label="SPLICR home">
        <span class="brand-mark" aria-hidden="true"><i></i><i></i><i></i><i></i><i></i></span>
        <span>SPLICR</span>
      </a>
      <section class="auth-card">
        <p class="eyebrow">{html.escape(eyebrow)}</p>
        <h1>{html.escape(heading)}</h1>
        {body}
      </section>
      <p class="auth-footnote">Private speech synthesis workspace</p>
    </main>
  </body>
</html>
"""
    return HTMLResponse(document, status_code=status_code, headers=_security_headers())


def _client_key(request: Request, username: str) -> str:
    address = request.headers.get("x-real-ip")
    if not address and request.client is not None:
        address = request.client.host
    return f"{address or 'unknown'}:{username.casefold()}"


def _same_origin(request: Request) -> bool:
    origin = request.headers.get("origin")
    if not origin:
        return True
    parsed = urlsplit(origin)
    return parsed.scheme in {"http", "https"} and parsed.netloc == request.headers.get("host")


def _set_session_cookie(response: Response, settings: Settings, token: str) -> None:
    response.set_cookie(
        _cookie_name(settings),
        token,
        max_age=settings.auth_session_seconds,
        path="/",
        secure=settings.auth_cookie_secure,
        httponly=True,
        samesite="strict",
    )


def register_auth(
    application: FastAPI,
    *,
    settings: Settings,
    manager: AuthManager,
) -> None:
    limiter = LoginAttemptLimiter()

    @application.get("/assets/auth.css", include_in_schema=False)
    async def auth_stylesheet() -> FileResponse:
        return FileResponse(
            _STATIC_ROOT / "auth.css",
            media_type="text/css",
            headers={
                "Cache-Control": "public, max-age=3600",
                "X-Content-Type-Options": "nosniff",
            },
        )

    @application.get("/auth", include_in_schema=False)
    async def login_page(request: Request, next: str = "/") -> Response:
        if not settings.auth_enabled:
            return RedirectResponse("/", status_code=303)
        if manager.verify_session(request.cookies.get(_cookie_name(settings))) is not None:
            return RedirectResponse(_safe_next(next), status_code=303)
        if not manager.is_configured:
            return _page(
                eyebrow="Setup required",
                heading="Authentication is not configured",
                status_code=503,
                body=(
                    "<p class=\"lede\">SPLICR is locked until an administrator creates its "
                    "first password on the server.</p>"
                    "<div class=\"command\"><code>splicr auth set-password</code></div>"
                    "<p class=\"muted\">No application data or API routes are accessible "
                    "while this lock is active.</p>"
                ),
            )
        safe_next = html.escape(_safe_next(next), quote=True)
        username = html.escape(manager.configured_username or "", quote=True)
        return _page(
            eyebrow="Private workspace",
            heading="Welcome back",
            body=f"""
              <p class="lede">Sign in to continue to the speech studio.</p>
              <form class="auth-form" method="post" action="/auth/login">
                <input type="hidden" name="next" value="{safe_next}">
                <label for="username">Username</label>
                <input id="username" name="username" type="text" value="{username}"
                       autocomplete="username" autocapitalize="none" spellcheck="false" required autofocus>
                <label for="password">Password</label>
                <input id="password" name="password" type="password"
                       autocomplete="current-password" required>
                <button type="submit">Sign in</button>
              </form>
              <p class="muted">Your password is verified locally and is never sent to a speech provider.</p>
            """,
        )

    @application.post("/auth/login", include_in_schema=False)
    async def login(request: Request) -> Response:
        if not settings.auth_enabled:
            return RedirectResponse("/", status_code=303)
        form = await request.form()
        username = str(form.get("username", "")).strip()
        password = str(form.get("password", ""))
        destination = _safe_next(str(form.get("next", "/")))
        key = _client_key(request, username)
        retry_after = limiter.retry_after(key)
        if retry_after:
            response = _page(
                eyebrow="Please wait",
                heading="Too many sign-in attempts",
                status_code=429,
                body=(
                    f"<p class=\"lede error\">Try again in {retry_after} seconds.</p>"
                    "<a class=\"button-link\" href=\"/auth\">Return to sign in</a>"
                ),
            )
            response.headers["Retry-After"] = str(retry_after)
            return response
        if not manager.authenticate(username, password):
            limiter.record_failure(key)
            response = _page(
                eyebrow="Sign-in failed",
                heading="Check your credentials",
                status_code=401,
                body=(
                    "<p class=\"lede error\">The username or password was not accepted.</p>"
                    "<a class=\"button-link\" href=\"/auth\">Try again</a>"
                ),
            )
            return response
        limiter.clear(key)
        token, _session = manager.issue_session(username)
        response = RedirectResponse(destination, status_code=303)
        response.headers.update(_security_headers())
        _set_session_cookie(response, settings, token)
        return response

    @application.get("/auth/settings", include_in_schema=False)
    async def auth_settings(request: Request, changed: int = 0) -> Response:
        if not settings.auth_enabled:
            return RedirectResponse("/", status_code=303)
        session: AuthSession = request.state.auth_session
        notice = (
            "<p class=\"notice\" role=\"status\">Password updated. Other sessions were signed out.</p>"
            if changed
            else ""
        )
        csrf = html.escape(session.csrf_token, quote=True)
        username = html.escape(session.username)
        return _page(
            eyebrow="Account",
            heading="Security settings",
            body=f"""
              {notice}
              <p class="lede">Signed in as <strong>{username}</strong>.</p>
              <form class="auth-form" method="post" action="/auth/password">
                <input type="hidden" name="csrf_token" value="{csrf}">
                <label for="current-password">Current password</label>
                <input id="current-password" name="current_password" type="password"
                       autocomplete="current-password" required>
                <label for="new-password">New password</label>
                <input id="new-password" name="new_password" type="password"
                       autocomplete="new-password" minlength="{_PASSWORD_MIN_LENGTH}" required>
                <label for="confirm-password">Confirm new password</label>
                <input id="confirm-password" name="confirm_password" type="password"
                       autocomplete="new-password" minlength="{_PASSWORD_MIN_LENGTH}" required>
                <button type="submit">Update password</button>
              </form>
              <div class="auth-actions">
                <a class="text-link" href="/">Back to studio</a>
                <form method="post" action="/auth/logout">
                  <input type="hidden" name="csrf_token" value="{csrf}">
                  <button class="quiet-danger" type="submit">Sign out</button>
                </form>
              </div>
            """,
        )

    @application.post("/auth/password", include_in_schema=False)
    async def change_password(request: Request) -> Response:
        if not _same_origin(request):
            return Response(status_code=403, headers=_security_headers())
        session: AuthSession = request.state.auth_session
        form = await request.form()
        csrf_token = str(form.get("csrf_token", ""))
        if not hmac.compare_digest(session.csrf_token, csrf_token):
            return Response(status_code=403, headers=_security_headers())
        current_password = str(form.get("current_password", ""))
        new_password = str(form.get("new_password", ""))
        confirm_password = str(form.get("confirm_password", ""))
        try:
            if new_password != confirm_password:
                raise ValueError("The new passwords do not match.")
            manager.change_password(session.username, current_password, new_password)
        except ValueError as error:
            response = _page(
                eyebrow="Password unchanged",
                heading="Review the password",
                status_code=400,
                body=(
                    f"<p class=\"lede error\">{html.escape(str(error))}</p>"
                    "<a class=\"button-link\" href=\"/auth/settings\">Return to security settings</a>"
                ),
            )
            return response
        token, _new_session = manager.issue_session(session.username)
        response = RedirectResponse("/auth/settings?changed=1", status_code=303)
        response.headers.update(_security_headers())
        _set_session_cookie(response, settings, token)
        return response

    @application.post("/auth/logout", include_in_schema=False)
    async def logout(request: Request) -> Response:
        if not _same_origin(request):
            return Response(status_code=403, headers=_security_headers())
        session: AuthSession = request.state.auth_session
        form = await request.form()
        if not hmac.compare_digest(session.csrf_token, str(form.get("csrf_token", ""))):
            return Response(status_code=403, headers=_security_headers())
        response = RedirectResponse("/auth", status_code=303)
        response.headers.update(_security_headers())
        response.delete_cookie(
            _cookie_name(settings),
            path="/",
            secure=settings.auth_cookie_secure,
            httponly=True,
            samesite="strict",
        )
        return response
