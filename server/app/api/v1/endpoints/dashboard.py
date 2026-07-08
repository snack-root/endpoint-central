from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, DbSession
from app.db.session import get_db
from app.services.device_service import DeviceService
from app.repositories.repositories import AlertRepository, AuditLogRepository

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    user: CurrentUser,
    session: AsyncSession = Depends(get_db),
):
    device_svc = DeviceService(session)
    stats = await device_svc.get_dashboard_stats()

    alert_repo = AlertRepository(session)
    open_alerts = await alert_repo.get_open()

    audit_repo = AuditLogRepository(session)
    recent_audits = await audit_repo.recent(limit=10)

    return templates.TemplateResponse(
        "dashboard/index.html",
        {
            "request": request,
            "user": user,
            "stats": stats,
            "open_alerts": open_alerts,
            "recent_audits": recent_audits,
        },
    )