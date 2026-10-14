"""兼容层鉴权：云智 JWT 签发/校验 + api_key 解析。"""
from __future__ import annotations

import pytest

from agent_platform.core import security
from agent_platform.core.config import Settings
from agent_platform.core.security import AuthError, check_client, issue_token, resolve_api_key, verify_token


@pytest.fixture()
def use_settings(monkeypatch):
    def _apply(**overrides) -> Settings:
        settings = Settings(**overrides)
        monkeypatch.setattr(security, "get_settings", lambda: settings)
        return settings

    return _apply


@pytest.fixture(autouse=True)
def _default_settings(use_settings):
    return use_settings()


def test_issue_token_roundtrip():
    token, ttl = issue_token("cloud", ttl_seconds=120)
    assert ttl == 120 and token.count(".") == 1
    payload = verify_token(token)
    assert payload["sub"] == "cloud"
    assert payload["exp"] > 0


def test_verify_token_rejects_malformed():
    with pytest.raises(AuthError, match="token 格式非法"):
        verify_token("no-dot-here")


def test_verify_token_rejects_tampered_signature():
    token, _ = issue_token("cloud")
    tampered = f"{token[:-1]}{'0' if token[-1] != '0' else '1'}"
    with pytest.raises(AuthError, match="token 签名校验失败"):
        verify_token(tampered)


def test_verify_token_rejects_tampered_body():
    token, _ = issue_token("cloud")
    encoded, _, signature = token.partition(".")
    body = b'{"sub": "root", "exp": 9999999999}'
    forged = f"{security._b64encode(body)}.{signature}"
    with pytest.raises(AuthError, match="token 签名校验失败"):
        verify_token(forged)
    assert encoded != forged.split(".")[0]


def test_verify_token_rejects_expired():
    token, _ = issue_token("cloud", ttl_seconds=-5)
    with pytest.raises(AuthError, match="token 已过期"):
        verify_token(token)


def test_verify_token_is_secret_specific(use_settings):
    token, _ = issue_token("cloud")
    use_settings(jwt_secret="another-secret")
    with pytest.raises(AuthError, match="token 签名校验失败"):
        verify_token(token)


def test_check_client_without_registry_accepts_any_id(use_settings):
    use_settings(oauth_clients={})
    assert check_client("anything", "") is True
    assert check_client("", "") is False


def test_check_client_validates_secret(use_settings):
    use_settings(oauth_clients={"cloud": "s3cret"})
    assert check_client("cloud", "s3cret") is True
    assert check_client("cloud", "wrong") is False
    assert check_client("ghost", "s3cret") is False


def test_resolve_api_key_prefers_api_key_header():
    assert resolve_api_key("key-1", None) == "key-1"
    assert resolve_api_key("key-1", "Bearer other") == "key-1"


def test_resolve_api_key_uses_bearer_for_raw_dify():
    assert resolve_api_key(None, "Bearer key-1") == "key-1"
    assert resolve_api_key(None, "JWT key-1") == "key-1"


def test_resolve_api_key_requires_valid_token_when_requested():
    token, _ = issue_token("cloud")
    assert resolve_api_key(None, f"Bearer {token}", require_token=True) == token
    with pytest.raises(AuthError):
        resolve_api_key(None, "Bearer broken.token", require_token=True)


def test_resolve_api_key_without_headers_is_empty():
    assert resolve_api_key(None, None) == ""
    assert resolve_api_key("", "") == ""
    assert resolve_api_key(None, "Basic abc") == ""
