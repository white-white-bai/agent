"""中台独立账号体系：口令哈希 / 角色权限 / 租户隔离 / 令牌 / 管理端鉴权门禁。"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from agent_platform.api.main import app
from agent_platform.core import accounts
from agent_platform.core.accounts import ANONYMOUS, AdminPrincipal, AdminRole, AdminUser
from agent_platform.core.config import get_settings
from agent_platform.core.db import session_scope
from agent_platform.core.security import AuthError, issue_token


@pytest.fixture()
def auth_on(monkeypatch):
    monkeypatch.setenv("AP_ADMIN_AUTH_ENABLED", "true")
    monkeypatch.setenv("AP_ADMIN_SEED_USERNAME", "admin")
    monkeypatch.setenv("AP_ADMIN_SEED_PASSWORD", "admin123")
    get_settings.cache_clear()
    accounts.seed()
    yield
    get_settings.cache_clear()


def _token(client: TestClient, username: str, password: str) -> str:
    resp = client.post("/admin/login", json={"username": username, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]["token"]


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# --------------------------------------------------------------------------- 口令

def test_hash_password_is_salted_and_verifiable():
    digest, salt = accounts.hash_password("s3cret")
    assert len(digest) == 64 and len(salt) == 32
    assert accounts.verify_password("s3cret", salt, digest)
    assert not accounts.verify_password("wrong", salt, digest)


def test_hash_password_same_salt_is_deterministic_and_salt_varies():
    first, salt = accounts.hash_password("s3cret")
    second, _ = accounts.hash_password("s3cret", salt)
    assert first == second
    other, other_salt = accounts.hash_password("s3cret")
    assert other_salt != salt
    assert other != first


def test_verify_password_rejects_malformed_salt():
    assert not accounts.verify_password("s3cret", "zz", "00")
    assert not accounts.verify_password("s3cret", "", "")


def test_password_is_not_reversible_via_storage():
    digest, salt = accounts.hash_password("s3cret")
    assert "s3cret" not in digest and "s3cret" not in salt


# --------------------------------------------------------------------------- 角色与权限

def test_seed_is_idempotent_and_fills_builtin_roles():
    assert accounts.seed() is True
    assert accounts.seed() is False
    roles = {row["code"]: row for row in accounts.list_roles()}
    assert set(roles) == {"admin", "editor", "viewer"}
    assert all(row["is_builtin"] == 1 for row in roles.values())
    users = accounts.list_users()
    assert [row["username"] for row in users] == ["admin"]
    assert users[0]["role_code"] == "admin"


def test_principal_allows_wildcard_and_explicit():
    assert ANONYMOUS.allows("anything:at:all")
    editor = AdminPrincipal(permissions=["app:read", "app:write"])
    assert editor.allows("app:read")
    assert not editor.allows("user:write")


def test_scope_tenant_binds_bound_account_and_passes_through_global():
    bound = AdminPrincipal(tenant_code="t1")
    assert bound.scope_tenant() == "t1"
    assert bound.scope_tenant("t2") == "t1"
    assert AdminPrincipal().scope_tenant("t2") == "t2"
    assert AdminPrincipal().scope_tenant() == ""


def test_create_and_delete_role():
    accounts.seed()
    row = accounts.create_role("ops", "运维", ["app:read"])
    assert row["code"] == "ops" and row["permissions"] == ["app:read"]
    with pytest.raises(ValueError):
        accounts.create_role("ops", "重复")
    assert accounts.delete_role("ops") is True
    assert accounts.delete_role("ops") is False


def test_builtin_role_cannot_be_deleted():
    accounts.seed()
    with pytest.raises(ValueError):
        accounts.delete_role("admin")


def test_permissions_for_unknown_role_is_empty():
    accounts.seed()
    assert accounts.permissions_for("nope") == []
    assert "app:read" in accounts.permissions_for("viewer")


# --------------------------------------------------------------------------- 账号

def test_create_user_rejects_duplicate():
    accounts.create_user("alice", "pw", display_name="A")
    with pytest.raises(ValueError):
        accounts.create_user("alice", "pw")


def test_update_user_changes_role_and_password():
    accounts.seed()
    row = accounts.create_user("bob", "old")
    assert row["display_name"] == "bob"
    updated = accounts.update_user(row["uuid"], role_code="editor", password="new")
    assert updated is not None and updated["role_code"] == "editor"
    with pytest.raises(AuthError):
        accounts.login("bob", "old")
    assert accounts.login("bob", "new")["role_code"] == "editor"
    assert accounts.update_user("missing") is None


def test_delete_user():
    row = accounts.create_user("carol", "pw")
    assert accounts.delete_user(row["uuid"]) is True
    assert accounts.delete_user(row["uuid"]) is False


def test_login_rejects_bad_password_and_inactive_account():
    accounts.seed()
    with pytest.raises(AuthError):
        accounts.login("admin", "wrong")
    with pytest.raises(AuthError):
        accounts.login("nobody", "admin123")
    row = accounts.create_user("dave", "pw")
    accounts.update_user(row["uuid"], is_active=0)
    with pytest.raises(AuthError):
        accounts.login("dave", "pw")


def test_login_issues_admin_typed_token_with_role_and_tenant():
    accounts.seed()
    result = accounts.login("admin", "admin123")
    assert result["role_code"] == "admin"
    assert result["expire"] == get_settings().admin_token_ttl_seconds
    principal = accounts.principal_from_token(result["token"])
    assert principal.authenticated is True
    assert principal.username == "admin"
    assert principal.allows("user:write")


def test_principal_from_token_rejects_non_admin_token():
    accounts.seed()
    cloud_token, _ = issue_token("xiaochang_chat", ttl_seconds=60)
    with pytest.raises(AuthError):
        accounts.principal_from_token(cloud_token)


def test_principal_from_token_rejects_deleted_user():
    accounts.seed()
    token = accounts.login("admin", "admin123")["token"]
    with session_scope() as session:
        session.query(AdminUser).filter(AdminUser.username == "admin").delete()
    with pytest.raises(AuthError):
        accounts.principal_from_token(token)


def test_admin_role_model_roundtrip():
    with session_scope() as session:
        session.add(AdminRole(code="tmp", name="临时", permissions=["app:read"], is_builtin=0))
        session.add(AdminUser(uuid="u1", username="tmp", password_hash="h", salt="s", display_name="T"))
    assert [row["code"] for row in accounts.list_roles()] == ["tmp"]
    assert accounts.get_user("tmp") is not None


# --------------------------------------------------------------------------- 默认关闭

def test_admin_routes_open_when_auth_disabled(api_client):
    assert api_client.get("/admin/apps").status_code == 200
    body = api_client.get("/admin/me").json()["data"]
    assert body["authenticated"] is False
    assert body["permissions"] == ["*"]
    assert api_client.get("/admin/roles").status_code == 200


# --------------------------------------------------------------------------- 管理端接口（开启后）

def test_login_and_me_via_api(auth_on, api_client):
    token = _token(api_client, "admin", "admin123")
    body = api_client.get("/admin/me", headers=_auth(token)).json()["data"]
    assert body["username"] == "admin"
    assert body["authenticated"] is True
    assert body["role_code"] == "admin"


def test_login_rejects_bad_credentials_via_api(auth_on, api_client):
    resp = api_client.post("/admin/login", json={"username": "admin", "password": "nope"})
    assert resp.status_code == 401


def test_admin_routes_require_token(auth_on, api_client):
    assert api_client.get("/admin/apps").status_code == 401
    assert api_client.get("/admin/me").status_code == 401
    assert api_client.get("/admin/apps", headers=_auth("garbage")).status_code == 401


def test_cloud_token_is_not_accepted_by_admin(auth_on, api_client):
    cloud_token, _ = issue_token("xiaochang_chat", ttl_seconds=60)
    assert api_client.get("/admin/me", headers=_auth(cloud_token)).status_code == 401


def test_missing_permission_is_forbidden(auth_on, api_client):
    accounts.create_user("lisa", "pw", role_code="viewer")
    token = _token(api_client, "lisa", "pw")
    assert api_client.get("/admin/apps", headers=_auth(token)).status_code == 200
    resp = api_client.post("/admin/apps", json={"app_name": "x"}, headers=_auth(token))
    assert resp.status_code == 403
    assert api_client.get("/admin/users", headers=_auth(token)).status_code == 200


def test_app_listing_is_scoped_to_account_tenant(auth_on, api_client, seed_app):
    seed_app(tenant_code="t1", app_id="a1", api_key="k1")
    seed_app(tenant_code="t2", app_id="a2", api_key="k2")
    accounts.create_user("tina", "pw", role_code="viewer", tenant_code="t1")
    token = _token(api_client, "tina", "pw")
    rows = api_client.get("/admin/apps", headers=_auth(token)).json()["data"]
    assert [row["app_id"] for row in rows] == ["a1"]
    admin_token = _token(api_client, "admin", "admin123")
    all_rows = api_client.get("/admin/apps", headers=_auth(admin_token)).json()["data"]
    assert {row["app_id"] for row in all_rows} == {"a1", "a2"}


def test_users_and_roles_crud_via_api(auth_on, api_client):
    token = _token(api_client, "admin", "admin123")
    headers = _auth(token)

    created = api_client.post(
        "/admin/users",
        json={"username": "zoe", "password": "pw", "role_code": "editor", "display_name": "Z"},
        headers=headers,
    )
    assert created.status_code == 200
    user_uuid = created.json()["data"]["uuid"]
    assert created.json()["data"]["tenant_code"] == ""

    listed = api_client.get("/admin/users", headers=headers).json()["data"]
    assert {row["username"] for row in listed} == {"admin", "zoe"}

    updated = api_client.put(f"/admin/users/{user_uuid}", json={"role_code": "viewer"}, headers=headers)
    assert updated.json()["data"]["role_code"] == "viewer"

    role = api_client.post("/admin/roles", json={"code": "audit", "name": "审计"}, headers=headers)
    assert role.status_code == 200
    assert "audit" in {row["code"] for row in api_client.get("/admin/roles", headers=headers).json()["data"]}

    assert api_client.delete("/admin/roles/admin", headers=headers).status_code == 400
    assert api_client.delete("/admin/roles/audit", headers=headers).status_code == 200
    assert api_client.delete(f"/admin/users/{user_uuid}", headers=headers).status_code == 200
    assert api_client.delete(f"/admin/users/{user_uuid}", headers=headers).status_code == 404


def test_lifespan_seeds_accounts_when_enabled(auth_on):
    with session_scope() as session:
        session.query(AdminUser).delete()
        session.query(AdminRole).delete()
    with TestClient(app):
        pass
    assert accounts.get_user("admin") is not None
