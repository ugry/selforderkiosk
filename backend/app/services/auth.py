"""
Simple API-key auth for kiosk/monitor machines,
and session-based auth for admin web interface.
"""
import logging
from fastapi import Request, HTTPException, Header
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from datetime import datetime

from app.models.models import Machine
from app.config import settings

auth_log = logging.getLogger("app.auth")


async def verify_api_key(
    x_api_key: Optional[str] = Header(None),
    db: AsyncSession = None,
    client_ip: str = "unknown",
) -> Machine:
    if not x_api_key:
        auth_log.warning("AUTH FAIL  reason=missing_key  ip=%s", client_ip)
        raise HTTPException(403, "Missing X-Api-Key header")
    result = await db.execute(
        select(Machine).where(Machine.api_key == x_api_key, Machine.is_active == True)
    )
    machine = result.scalar_one_or_none()
    if not machine:
        auth_log.warning(
            "AUTH FAIL  reason=invalid_key  ip=%s  key_hint=%.8s…",
            client_ip, x_api_key,
        )
        raise HTTPException(403, "Invalid API key")
    # Update last seen
    await db.execute(
        update(Machine).where(Machine.id == machine.id)
        .values(last_seen=datetime.utcnow())
    )
    auth_log.info(
        "AUTH OK  machine=%s  type=%s  ip=%s",
        machine.name, machine.machine_type, client_ip,
    )
    return machine


def verify_admin_session(request: Request):
    if not request.session.get("admin_logged_in"):
        from fastapi.responses import RedirectResponse
        raise HTTPException(401, "Admin login required")
    return True
