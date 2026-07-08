"""
Domain and Group management endpoints.
"""
from fastapi import APIRouter, Request, Form, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.session import get_db
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from typing import Optional

from app.api.deps import CurrentUser, DbSession
from app.repositories.repositories import DomainRepository, GroupRepository, AuditLogRepository

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


# ── Domains ───────────────────────────────────────────────────────────────

@router.get("/domains", response_class=HTMLResponse)
async def domains_list(
    request: Request, user: CurrentUser, session: AsyncSession = Depends(get_db)
):
    repo = DomainRepository(session)
    # All domains flat; template builds tree
    domains = await repo.list()
    return templates.TemplateResponse(
        "domains/list.html", {"request": request, "user": user, "domains": domains}
    )


@router.post("/domains")
async def domain_create(
    request: Request,
    user: CurrentUser,
    name: str = Form(...),
    parent_id: Optional[str] = Form(None),
    description: Optional[str] = Form(None),
    session: AsyncSession = Depends(get_db),
):
    repo = DomainRepository(session)
    audit = AuditLogRepository(session)
    domain = await repo.create(
        name=name,
        parent_id=parent_id or None,
        description=description or None,
    )
    await audit.log(
        action="create", resource_type="domain",
        user_id=user.id, resource_id=domain.id,
        ip_address=request.client.host if request.client else None,
    )
    return RedirectResponse("/domains", status_code=302)


@router.post("/domains/{domain_id}/delete")
async def domain_delete(
    request: Request,
    domain_id: str,
    user: CurrentUser,
    session: AsyncSession = Depends(get_db),
):
    repo = DomainRepository(session)
    audit = AuditLogRepository(session)
    domain = await repo.get(domain_id)
    if domain:
        await repo.delete(domain)
        await audit.log(
            action="delete", resource_type="domain",
            user_id=user.id, resource_id=domain_id,
        )
    return RedirectResponse("/domains", status_code=302)


# ── Groups ─────────────────────────────────────────────────────────────────

@router.get("/groups", response_class=HTMLResponse)
async def groups_list(
    request: Request, user: CurrentUser, session: AsyncSession = Depends(get_db)
):
    group_repo = GroupRepository(session)
    domain_repo = DomainRepository(session)
    groups = await group_repo.list_with_domain()
    domains = await domain_repo.list()
    return templates.TemplateResponse(
        "groups/list.html",
        {"request": request, "user": user, "groups": groups, "domains": domains},
    )


@router.post("/groups")
async def group_create(
    request: Request,
    user: CurrentUser,
    name: str = Form(...),
    domain_id: Optional[str] = Form(None),
    description: Optional[str] = Form(None),
    session: AsyncSession = Depends(get_db),
):
    repo = GroupRepository(session)
    audit = AuditLogRepository(session)
    group = await repo.create(
        name=name,
        domain_id=domain_id or None,
        description=description or None,
    )
    await audit.log(
        action="create", resource_type="group",
        user_id=user.id, resource_id=group.id,
    )
    return RedirectResponse("/groups", status_code=302)


@router.post("/groups/{group_id}/delete")
async def group_delete(
    request: Request,
    group_id: str,
    user: CurrentUser,
    session: AsyncSession = Depends(get_db),
):
    repo = GroupRepository(session)
    audit = AuditLogRepository(session)
    group = await repo.get(group_id)
    if group:
        await repo.delete(group)
        await audit.log(
            action="delete", resource_type="group",
            user_id=user.id, resource_id=group_id,
        )
    return RedirectResponse("/groups", status_code=302)