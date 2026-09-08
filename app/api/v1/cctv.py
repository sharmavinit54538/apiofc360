from urllib.parse import urlsplit, urlunsplit

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import not_found, permission_denied
from app.db.dependencies import CurrentUser, get_current_user
from app.db.session import get_db
from app.models.misc import CCTVCamera
from app.schemas.misc import CameraCreate, CameraOut, CameraUpdate
from app.services.audit_service import log_action

router = APIRouter(prefix="/cctv", tags=["CCTV"])
WRITE_ROLES = {"admin"}


def _redact(url: str) -> str:
    """Strip userinfo (credentials) from an RTSP/HTTP stream URL before it ever leaves the server."""
    try:
        parts = urlsplit(url)
        netloc = parts.hostname or ""
        if parts.port:
            netloc += f":{parts.port}"
        return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))
    except Exception:
        return "***redacted***"


def _out(c: CCTVCamera) -> CameraOut:
    return CameraOut(id=c.id, camera_name=c.camera_name, location=c.location, status=c.status, created_at=c.created_at)


@router.get("/cameras", response_model=list[CameraOut])
async def list_cameras(current: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if current.role not in {"admin", "teacher"}:
        raise permission_denied()
    rows = (await db.execute(select(CCTVCamera).where(CCTVCamera.tenant_id == current.tenant_id))).scalars().all()
    return [_out(c) for c in rows]


@router.post("/cameras", response_model=CameraOut, status_code=201)
async def create_camera(payload: CameraCreate, request: Request, current: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if current.role not in WRITE_ROLES:
        raise permission_denied()
    c = CCTVCamera(tenant_id=current.tenant_id, school_id=current.school_id, camera_name=payload.camera_name, location=payload.location, stream_url=payload.stream_url, status="offline")
    db.add(c)
    await db.flush()
    await log_action(db, request, current.tenant_id, current.id, "create", "cctv_camera", c.id, {"location": c.location})
    await db.commit()
    await db.refresh(c)
    return _out(c)


@router.put("/cameras/{camera_id}", response_model=CameraOut)
async def update_camera(camera_id: str, payload: CameraUpdate, request: Request, current: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if current.role not in WRITE_ROLES:
        raise permission_denied()
    c = await db.get(CCTVCamera, camera_id)
    if not c or c.tenant_id != current.tenant_id:
        raise not_found("Camera")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(c, field, value)
    await log_action(db, request, current.tenant_id, current.id, "update", "cctv_camera", c.id)
    await db.commit()
    await db.refresh(c)
    return _out(c)


@router.delete("/cameras/{camera_id}", status_code=204)
async def delete_camera(camera_id: str, request: Request, current: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if current.role not in WRITE_ROLES:
        raise permission_denied()
    c = await db.get(CCTVCamera, camera_id)
    if not c or c.tenant_id != current.tenant_id:
        raise not_found("Camera")
    await db.delete(c)
    await log_action(db, request, current.tenant_id, current.id, "delete", "cctv_camera", camera_id)
    await db.commit()
    return None


@router.post("/cameras/{camera_id}/test")
async def test_camera(camera_id: str, current: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if current.role not in WRITE_ROLES:
        raise permission_denied()
    c = await db.get(CCTVCamera, camera_id)
    if not c or c.tenant_id != current.tenant_id:
        raise not_found("Camera")
    # Placeholder connectivity check — swap in a real RTSP/HTTP probe.
    # Never echo the raw stream_url (may contain credentials) back to the client.
    c.status = "online"
    await db.commit()
    return {"success": True, "status": c.status, "stream": _redact(c.stream_url)}
