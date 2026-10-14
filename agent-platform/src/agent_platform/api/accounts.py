"""中台管理端账号 API：登录 / 当前账号 / 账号与角色自管理。

`AP_ADMIN_AUTH_ENABLED=false`（默认）时免鉴权，接口可用但不受保护，行为与改造前一致。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from agent_platform.api.deps import get_current_admin, require_permission
from agent_platform.api.schemas import LoginRequest, RoleCreateRequest, UserCreateRequest, UserUpdateRequest
from agent_platform.core import accounts
from agent_platform.core.accounts import AdminPrincipal
from agent_platform.core.security import AuthError

router = APIRouter(prefix="/admin", tags=["admin-accounts"])


@router.post("/login")
def login(request: LoginRequest) -> dict[str, Any]:
    try:
        return {"data": accounts.login(request.username, request.password)}
    except AuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


@router.get("/me")
def me(principal: AdminPrincipal = Depends(get_current_admin)) -> dict[str, Any]:
    return {
        "data": {
            "uuid": principal.uuid,
            "username": principal.username,
            "role_code": principal.role_code,
            "tenant_code": principal.tenant_code,
            "permissions": principal.permissions,
            "authenticated": principal.authenticated,
        }
    }


@router.get("/users", dependencies=[Depends(require_permission("user:read"))])
def list_users(principal: AdminPrincipal = Depends(get_current_admin)) -> dict[str, Any]:
    return {"data": accounts.list_users(principal.scope_tenant())}


@router.post("/users", dependencies=[Depends(require_permission("user:write"))])
def create_user(request: UserCreateRequest, principal: AdminPrincipal = Depends(get_current_admin)) -> dict[str, Any]:
    try:
        row = accounts.create_user(
            request.username,
            request.password,
            role_code=request.role_code,
            tenant_code=principal.scope_tenant(request.tenant_code),
            display_name=request.display_name,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"data": row}


@router.put("/users/{user_uuid}", dependencies=[Depends(require_permission("user:write"))])
def update_user(user_uuid: str, request: UserUpdateRequest) -> dict[str, Any]:
    row = accounts.update_user(user_uuid, **request.model_dump(exclude_unset=True))
    if row is None:
        raise HTTPException(status_code=404, detail="账号不存在")
    return {"data": row}


@router.delete("/users/{user_uuid}", dependencies=[Depends(require_permission("user:write"))])
def delete_user(user_uuid: str) -> dict[str, Any]:
    if not accounts.delete_user(user_uuid):
        raise HTTPException(status_code=404, detail="账号不存在")
    return {"data": {"uuid": user_uuid}}


@router.get("/roles", dependencies=[Depends(require_permission("role:read"))])
def list_roles() -> dict[str, Any]:
    return {"data": accounts.list_roles()}


@router.post("/roles", dependencies=[Depends(require_permission("role:write"))])
def create_role(request: RoleCreateRequest) -> dict[str, Any]:
    try:
        row = accounts.create_role(request.code, request.name, request.permissions)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"data": row}


@router.delete("/roles/{code}", dependencies=[Depends(require_permission("role:write"))])
def delete_role(code: str) -> dict[str, Any]:
    try:
        if not accounts.delete_role(code):
            raise HTTPException(status_code=404, detail="角色不存在")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"data": {"code": code}}
