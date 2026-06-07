"""Admin API for Telegram remote control."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Request

from core.middleware import require_admin
from src.auth_helpers import get_current_user


def setup_telegram_control_routes(telegram_control_manager, auth_manager=None) -> APIRouter:
    # Public route prefix kept as /api/remote-control for backward compatibility
    # with the existing Settings UI and stored config — only the code identity
    # is renamed to reflect that this is Telegram-specific.
    router = APIRouter(prefix="/api/remote-control", tags=["remote_control"])

    @router.get("")
    async def get_remote_control(request: Request):
        require_admin(request)
        return telegram_control_manager.safe_config()

    @router.put("/{provider}")
    async def update_remote_control(provider: str, request: Request, body: dict):
        require_admin(request)
        try:
            actor = get_current_user(request)
            return await telegram_control_manager.update_provider(provider, body or {}, actor=actor)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    @router.post("/{provider}/test")
    async def test_remote_control(provider: str, request: Request, body: Optional[dict] = None):
        require_admin(request)
        try:
            result = await telegram_control_manager.test_provider(provider, body or {})
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        if not result.get("ok"):
            return result
        return result

    @router.post("/{provider}/reload")
    async def reload_remote_control(provider: str, request: Request):
        require_admin(request)
        try:
            return await telegram_control_manager.reload(provider)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    return router
