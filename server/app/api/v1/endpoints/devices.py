"""
Device Inventory web endpoints (HTML + HTMX partials).
"""
from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.api.deps import CurrentUser, DbSession
from app.services.device_service import DeviceService
from app.repositories.repositories import DeviceMetricRepository, DomainRepository, GroupRepository

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/devices", response_class=HTMLResponse)
async def device_list(
    request: Request,
    user: CurrentUser,
    page: int = 1,
    session: DbSession = None,
):
    svc = DeviceService(session)
    devices, total = await svc.list_devices(page=page, page_size=50)
    pages = max(1, (total + 49) // 50)
    return templates.TemplateResponse(
        "devices/list.html",
        {
            "request": request,
            "user": user,
            "devices": devices,
            "total": total,
            "page": page,
            "pages": pages,
        },
    )


@router.get("/devices/{device_id}", response_class=HTMLResponse)
async def device_detail(
    request: Request,
    device_id: str,
    user: CurrentUser,
    session: DbSession = None,
):
    svc = DeviceService(session)
    device = await svc.get_device(device_id)
    if not device:
        return HTMLResponse("Device not found", status_code=404)

    metrics = await svc.get_metrics(device.id, limit=60)
    domain_repo = DomainRepository(session)
    group_repo = GroupRepository(session)
    domains = await domain_repo.list()
    groups = await group_repo.list()

    return templates.TemplateResponse(
        "devices/detail.html",
        {
            "request": request,
            "user": user,
            "device": device,
            "metrics": metrics,
            "domains": domains,
            "groups": groups,
        },
    )


@router.get("/devices/{device_id}/metrics-chart", response_class=HTMLResponse)
async def metrics_chart_partial(
    request: Request,
    device_id: str,
    user: CurrentUser,
    session: DbSession = None,
):
    """HTMX partial — returns just the chart fragment."""
    svc = DeviceService(session)
    device = await svc.get_device(device_id)
    if not device:
        return HTMLResponse("")

    metrics = await svc.get_metrics(device.id, limit=30)
    metrics_reversed = list(reversed(metrics))

    return templates.TemplateResponse(
        "partials/metrics_chart.html",
        {"request": request, "metrics": metrics_reversed, "device": device},
    )