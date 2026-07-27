from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_production_compose_forces_application_authentication() -> None:
    compose = (ROOT / "compose.deploy.yaml").read_text(encoding="utf-8")

    assert 'SPLICR_AUTH_ENABLED: "true"' in compose
    assert 'SPLICR_AUTH_COOKIE_SECURE: "true"' in compose


def test_tls_nginx_templates_delegate_authentication_to_the_application() -> None:
    for filename in (
        "nginx-splicr.conf.template",
        "nginx-splicr-external-http.conf.template",
    ):
        template = (ROOT / "deploy" / filename).read_text(encoding="utf-8")
        assert 'auth_basic "SPLICR"' not in template
        assert "auth_basic_user_file" not in template
        assert "proxy_pass http://127.0.0.1:__SPLICR_HTTP_PORT__;" in template
