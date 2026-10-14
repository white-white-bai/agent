"""中台独立账号体系：种子管理员 + 角色/权限 + 租户维度隔离。

密码用 PBKDF2-HMAC-SHA256 加盐单向存储（SM4 可逆，不用于口令）；令牌复用兼容层 JWT 签名，
额外带 `typ=admin` 与角色/租户声明，与云智 client_credentials 令牌互不冒充。
`AP_ADMIN_AUTH_ENABLED=false`（默认）时全部免鉴权，行为与改造前一致。
"""
from __future__ import annotations

import hashlib
import hmac
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from agent_platform.core.config import get_settings
from agent_platform.core.db import session_scope
from agent_platform.core.security import AuthError, issue_token, verify_token
from agent_platform.domain.models import AdminRole, AdminUser

PBKDF2_ITERATIONS = 200_000
USERNAME_PATTERN = "admin"

WILDCARD = "*"

BUILTIN_ROLES: dict[str, dict[str, object]] = {
    "admin": {"name": "管理员", "permissions": [WILDCARD]},
    "editor": {
        "name": "编辑",
        "permissions": [
            "app:read", "app:write",
            "graph:read", "graph:write",
            "guard:read", "guard:write",
            "mcp:read", "mcp:write",
            "knowledge:read", "knowledge:write",
            "provider:read",
            "metrics:read",
        ],
    },
    "viewer": {
        "name": "只读",
        "permissions": [
            "app:read", "graph:read", "guard:read", "mcp:read", "knowledge:read", "user:read", "role:read",
            "provider:read",
            "metrics:read",
        ],
    },
}


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def hash_password(password: str, salt: str = "") -> tuple[str, str]:
    raw_salt = bytes.fromhex(salt) if salt else os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), raw_salt, PBKDF2_ITERATIONS)
    return digest.hex(), raw_salt.hex()


def verify_password(password: str, salt: str, expected: str) -> bool:
    try:
        digest, _ = hash_password(password, salt)
    except ValueError:
        return False
    return hmac.compare_digest(digest, expected)


@dataclass
class AdminPrincipal:
    uuid: str = ""
    username: str = ""
    role_code: str = ""
    tenant_code: str = ""
    permissions: list[str] = field(default_factory=list)
    authenticated: bool = False

    def allows(self, permission: str) -> bool:
        return WILDCARD in self.permissions or permission in self.permissions

    def scope_tenant(self, requested: str = "") -> str:
        """租户隔离：账号绑定租户时只可见本租户；未绑定（空）表示全局。"""
        return self.tenant_code or requested


ANONYMOUS = AdminPrincipal(permissions=[WILDCARD])


def _role_dict(row: AdminRole) -> dict[str, object]:
    return {
        "code": row.code,
        "name": row.name,
        "permissions": row.permissions or [],
        "is_builtin": row.is_builtin,
    }


def _user_dict(row: AdminUser) -> dict[str, object]:
    return {
        "uuid": row.uuid,
        "username": row.username,
        "display_name": row.display_name,
        "role_code": row.role_code,
        "tenant_code": row.tenant_code,
        "is_active": row.is_active,
    }


def list_roles() -> list[dict[str, object]]:
    with session_scope() as session:
        rows = session.query(AdminRole).order_by(AdminRole.id).all()
        return [_role_dict(row) for row in rows]


def list_users(tenant_code: str = "") -> list[dict[str, object]]:
    with session_scope() as session:
        query = session.query(AdminUser)
        if tenant_code:
            query = query.filter(AdminUser.tenant_code == tenant_code)
        return [_user_dict(row) for row in query.order_by(AdminUser.id).all()]


def get_user(username: str) -> AdminUser | None:
    with session_scope() as session:
        return session.query(AdminUser).filter(AdminUser.username == username).first()


def permissions_for(role_code: str) -> list[str]:
    with session_scope() as session:
        row = session.query(AdminRole).filter(AdminRole.code == role_code).first()
        return list(row.permissions or []) if row else []


def create_role(code: str, name: str = "", permissions: list[str] | None = None) -> dict[str, object]:
    with session_scope() as session:
        existing = session.query(AdminRole).filter(AdminRole.code == code).first()
        if existing is not None:
            raise ValueError("角色已存在")
        row = AdminRole(code=code, name=name, permissions=permissions or [], is_builtin=0)
        session.add(row)
        session.flush()
        return _role_dict(row)


def delete_role(code: str) -> bool:
    with session_scope() as session:
        row = session.query(AdminRole).filter(AdminRole.code == code).first()
        if row is None:
            return False
        if row.is_builtin:
            raise ValueError("内置角色不可删除")
        session.delete(row)
        return True


def create_user(
    username: str,
    password: str,
    *,
    role_code: str = "viewer",
    tenant_code: str = "",
    display_name: str = "",
) -> dict[str, object]:
    password_hash, salt = hash_password(password)
    with session_scope() as session:
        if session.query(AdminUser).filter(AdminUser.username == username).first() is not None:
            raise ValueError("账号已存在")
        row = AdminUser(
            uuid=uuid.uuid4().hex,
            username=username,
            password_hash=password_hash,
            salt=salt,
            display_name=display_name or username,
            role_code=role_code,
            tenant_code=tenant_code,
        )
        session.add(row)
        session.flush()
        return _user_dict(row)


def update_user(
    user_uuid: str,
    *,
    role_code: str | None = None,
    tenant_code: str | None = None,
    display_name: str | None = None,
    is_active: int | None = None,
    password: str = "",
) -> dict[str, object] | None:
    with session_scope() as session:
        row = session.query(AdminUser).filter(AdminUser.uuid == user_uuid).first()
        if row is None:
            return None
        if role_code is not None:
            row.role_code = role_code
        if tenant_code is not None:
            row.tenant_code = tenant_code
        if display_name is not None:
            row.display_name = display_name
        if is_active is not None:
            row.is_active = int(is_active)
        if password:
            row.password_hash, row.salt = hash_password(password)
        session.flush()
        return _user_dict(row)


def delete_user(user_uuid: str) -> bool:
    with session_scope() as session:
        row = session.query(AdminUser).filter(AdminUser.uuid == user_uuid).first()
        if row is None:
            return False
        session.delete(row)
        return True


def login(username: str, password: str) -> dict[str, object]:
    row = get_user(username)
    if row is None or not row.is_active or not verify_password(password, row.salt, row.password_hash):
        raise AuthError("账号或密码错误")
    ttl = get_settings().admin_token_ttl_seconds
    token, expire = issue_token(
        username,
        ttl_seconds=ttl,
        claims={"typ": USERNAME_PATTERN, "role": row.role_code, "tenant": row.tenant_code, "uid": row.uuid},
    )
    with session_scope() as session:
        current = session.query(AdminUser).filter(AdminUser.uuid == row.uuid).first()
        if current is not None:
            current.last_login_at = _now()
    return {"token": token, "expire": expire, "username": username, "role_code": row.role_code}


def principal_from_token(token: str) -> AdminPrincipal:
    payload = verify_token(token)
    if payload.get("typ") != USERNAME_PATTERN:
        raise AuthError("令牌类型非法")
    row = get_user(str(payload.get("sub", "")))
    if row is None or not row.is_active:
        raise AuthError("账号不存在或已停用")
    return AdminPrincipal(
        uuid=row.uuid,
        username=row.username,
        role_code=row.role_code,
        tenant_code=row.tenant_code,
        permissions=permissions_for(row.role_code),
        authenticated=True,
    )


def seed() -> bool:
    """幂等：补齐内置角色与种子管理员。仅 admin_auth_enabled 时调用。"""
    settings = get_settings()
    created = False
    with session_scope() as session:
        for code, spec in BUILTIN_ROLES.items():
            row = session.query(AdminRole).filter(AdminRole.code == code).first()
            if row is None:
                session.add(
                    AdminRole(code=code, name=str(spec["name"]), permissions=list(spec["permissions"]), is_builtin=1)
                )
                created = True
                continue
            current = list(row.permissions or [])
            merged = current + [item for item in spec["permissions"] if item not in current]
            if merged != current:
                row.permissions = merged
                created = True
        if session.query(AdminUser).filter(AdminUser.username == settings.admin_seed_username).first() is None:
            password_hash, salt = hash_password(settings.admin_seed_password)
            session.add(
                AdminUser(
                    uuid=uuid.uuid4().hex,
                    username=settings.admin_seed_username,
                    password_hash=password_hash,
                    salt=salt,
                    display_name="种子管理员",
                    role_code="admin",
                    tenant_code="",
                )
            )
            created = True
    return created
