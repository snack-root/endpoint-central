"""
All remaining management endpoints:
- Policies
- Scripts + Script Deployment
- Software Inventory + Software Deployment
- Alerts
- Audit Logs
- AI Reports
"""
import json
from typing import Optional

from fastapi import APIRouter, Request, Form, Depends, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse
from fastapi.templating import Jinja2Templates

from app.api.deps import CurrentUser, DbSession
from app.core.config import settings
from app.repositories.repositories import (
    PolicyRepository, ScriptRepository, ScriptDeploymentRepository,
    SoftwareInventoryRepository, SoftwarePackageRepository, SoftwareDeploymentRepository,
    AlertRuleRepository, AlertRepository, AuditLogRepository,
    ReportRepository, DeviceRepository, GroupRepository, DomainRepository,
)
from app.db.redis_client import get_redis

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


# ── Policies ──────────────────────────────────────────────────────────────

@router.get("/policies", response_class=HTMLResponse)
async def policies_list(
    request: Request, user: CurrentUser, session: DbSession = None
):
    repo = PolicyRepository(session)
    policies = await repo.list_with_assignments()
    device_repo = DeviceRepository(session)
    group_repo = GroupRepository(session)
    domain_repo = DomainRepository(session)
    devices = await device_repo.list()
    groups = await group_repo.list()
    domains = await domain_repo.list()
    return templates.TemplateResponse(
        "policies/list.html",
        {
            "request": request, "user": user, "policies": policies,
            "devices": devices, "groups": groups, "domains": domains,
        },
    )


@router.post("/policies")
async def policy_create(
    request: Request,
    user: CurrentUser,
    name: str = Form(...),
    policy_type: str = Form(...),
    config_json: str = Form("{}"),
    session: DbSession = None,
):
    repo = PolicyRepository(session)
    audit = AuditLogRepository(session)
    try:
        config = json.loads(config_json)
    except json.JSONDecodeError:
        config = {}
    policy = await repo.create(
        name=name, policy_type=policy_type, config=config, created_by=user.id
    )
    await audit.log(
        action="create", resource_type="policy",
        user_id=user.id, resource_id=policy.id,
    )
    return RedirectResponse("/policies", status_code=302)


@router.post("/policies/{policy_id}/delete")
async def policy_delete(
    request: Request, policy_id: str, user: CurrentUser,
    session: DbSession = None,
):
    repo = PolicyRepository(session)
    policy = await repo.get(policy_id)
    if policy:
        await repo.delete(policy)
    return RedirectResponse("/policies", status_code=302)


@router.post("/policies/{policy_id}/assign")
async def policy_assign(
    request: Request, policy_id: str, user: CurrentUser,
    target_type: str = Form(...),
    target_id: str = Form(...),
    session: DbSession = None,
):
    from app.models.models import PolicyAssignment
    assignment = PolicyAssignment(
        policy_id=policy_id,
        target_type=target_type,
        target_id=target_id,
        assigned_by=user.id,
    )
    session.add(assignment)
    await session.flush()

    redis = get_redis()
    await redis.rpush(
        "cmd:dispatch",
        json.dumps({
            "type": "policy_dispatch",
            "assignment_id": assignment.id,
            "policy_id": policy_id,
            "target_type": target_type,
            "target_id": target_id,
        }),
    )

    audit = AuditLogRepository(session)
    await audit.log(
        action="assign", resource_type="policy",
        user_id=user.id, resource_id=policy_id,
        metadata={"target_type": target_type, "target_id": target_id},
    )
    return RedirectResponse("/policies", status_code=302)


@router.post("/policies/{policy_id}/assignments/{assignment_id}/delete")
async def policy_assignment_delete(
    request: Request, policy_id: str, assignment_id: str, user: CurrentUser,
    session: DbSession = None,
):
    from app.models.models import PolicyAssignment
    from sqlalchemy import select as _select
    result = await session.execute(
        _select(PolicyAssignment).where(PolicyAssignment.id == assignment_id)
    )
    assignment = result.scalar_one_or_none()
    if assignment:
        await session.delete(assignment)
    return RedirectResponse("/policies", status_code=302)


@router.post("/policies/{policy_id}/assignments/{assignment_id}/resend")
async def policy_assignment_resend(
    request: Request, policy_id: str, assignment_id: str, user: CurrentUser,
    session: DbSession = None,
):
    """Re-dispatch an existing assignment — hữu ích khi device offline lúc assign,
    hoặc policy config vừa được sửa và cần áp lại."""
    from app.models.models import PolicyAssignment
    from sqlalchemy import select as _select
    result = await session.execute(
        _select(PolicyAssignment).where(PolicyAssignment.id == assignment_id)
    )
    assignment = result.scalar_one_or_none()
    if assignment:
        redis = get_redis()
        await redis.rpush(
            "cmd:dispatch",
            json.dumps({
                "type": "policy_dispatch",
                "assignment_id": assignment.id,
                "policy_id": assignment.policy_id,
                "target_type": assignment.target_type,
                "target_id": assignment.target_id,
            }),
        )
    return RedirectResponse("/policies", status_code=302)

# ── Scripts ───────────────────────────────────────────────────────────────

@router.get("/scripts", response_class=HTMLResponse)
async def scripts_list(
    request: Request, user: CurrentUser,
    deploy_to: Optional[str] = None,
    session: DbSession = None,
):
    repo = ScriptRepository(session)
    scripts = await repo.list()
    device_repo = DeviceRepository(session)
    group_repo = GroupRepository(session)
    domain_repo = DomainRepository(session)
    devices = await device_repo.list()
    groups = await group_repo.list()
    domains = await domain_repo.list()

    deploy_repo = ScriptDeploymentRepository(session)
    deployments = await deploy_repo.list_recent_with_logs(limit=20)

    return templates.TemplateResponse(
        "scripts/list.html",
        {
            "request": request, "user": user, "scripts": scripts,
            "devices": devices, "groups": groups, "domains": domains,
            "preselect_device": deploy_to,
            "deployments": deployments,
        },
    )


@router.post("/scripts")
async def script_create(
    request: Request, user: CurrentUser,
    name: str = Form(...),
    script_type: str = Form(...),
    content: str = Form(...),
    description: Optional[str] = Form(None),
    session: DbSession = None,
):
    repo = ScriptRepository(session)
    audit = AuditLogRepository(session)
    script = await repo.create(
        name=name, script_type=script_type, content=content,
        description=description, created_by=user.id,
    )
    await audit.log(
        action="create", resource_type="script",
        user_id=user.id, resource_id=script.id,
    )
    return RedirectResponse("/scripts", status_code=302)


@router.post("/scripts/{script_id}/deploy")
async def script_deploy(
    request: Request, script_id: str, user: CurrentUser,
    target_type: str = Form(...),
    target_id: str = Form(...),
    session: DbSession = None,
):
    deploy_repo = ScriptDeploymentRepository(session)
    audit = AuditLogRepository(session)
    redis = get_redis()

    deployment = await deploy_repo.create(
        script_id=script_id,
        target_type=target_type,
        target_id=target_id,
        status="pending",
        deployed_by=user.id,
    )
    # Push to command-worker queue
    await redis.rpush("cmd:dispatch", json.dumps({
        "type": "script_dispatch",
        "deployment_id": deployment.id,
    }))
    await audit.log(
        action="deploy", resource_type="script",
        user_id=user.id, resource_id=script_id,
        metadata={"deployment_id": deployment.id, "target_type": target_type, "target_id": target_id},
    )
    return RedirectResponse("/scripts", status_code=302)


@router.post("/scripts/{script_id}/delete")
async def script_delete(
    request: Request, script_id: str, user: CurrentUser,
    session: DbSession = None,
):
    repo = ScriptRepository(session)
    script = await repo.get(script_id)
    if script:
        await repo.delete(script)
    return RedirectResponse("/scripts", status_code=302)


# ── Software Inventory ────────────────────────────────────────────────────

@router.get("/software/inventory", response_class=HTMLResponse)
async def sw_inventory(
    request: Request, user: CurrentUser,
    q: Optional[str] = None,
    device: Optional[str] = None,
    session: DbSession = None,
):
    repo = SoftwareInventoryRepository(session)
    if q:
        items = await repo.search_across_devices(q)
    elif device:
        items = await repo.list_with_device(device_id=device)
    else:
        # list all - need to selectinload device manually
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload as sil
        from app.models.models import SoftwareInventory as SWI
        result = await session.execute(
            select(SWI).options(sil(SWI.device)).order_by(SWI.name).limit(200)
        )
        items = list(result.scalars().all())
    return templates.TemplateResponse(
        "software/inventory.html",
        {"request": request, "user": user, "items": items, "q": q or ""},
    )


# ── Software Deployment ───────────────────────────────────────────────────

@router.get("/software/deploy", response_class=HTMLResponse)
async def sw_deploy_page(
    request: Request, user: CurrentUser, session: DbSession = None
):
    pkg_repo = SoftwarePackageRepository(session)
    deploy_repo = SoftwareDeploymentRepository(session)
    device_repo = DeviceRepository(session)
    group_repo = GroupRepository(session)
    packages = await pkg_repo.list()
    deployments = await deploy_repo.list_with_package(limit=30)
    devices = await device_repo.list()
    groups = await group_repo.list()
    return templates.TemplateResponse(
        "software/deploy.html",
        {
            "request": request, "user": user,
            "packages": packages, "deployments": deployments,
            "devices": devices, "groups": groups,
        },
    )


@router.post("/software/upload")
async def sw_upload(
    request: Request, user: CurrentUser,
    name: str = Form(...),
    version: Optional[str] = Form(None),
    file: UploadFile = File(...),
    session: DbSession = None,
):
    import os
    from pathlib import Path
    upload_dir = Path(settings.UPLOAD_DIR)
    upload_dir.mkdir(parents=True, exist_ok=True)
    dest = upload_dir / file.filename
    content = await file.read()
    dest.write_bytes(content)

    pkg_repo = SoftwarePackageRepository(session)
    ext = Path(file.filename).suffix.lower().lstrip(".")
    await pkg_repo.create(
        name=name, version=version, file_path=str(dest),
        package_type=ext, uploaded_by=user.id,
    )
    return RedirectResponse("/software/deploy", status_code=302)


@router.post("/software/deploy/{package_id}")
async def sw_deploy(
    request: Request, package_id: str, user: CurrentUser,
    target_type: str = Form(...),
    target_id: str = Form(...),
    session: DbSession = None,
):
    deploy_repo = SoftwareDeploymentRepository(session)
    audit = AuditLogRepository(session)
    redis = get_redis()
    deployment = await deploy_repo.create(
        package_id=package_id,
        target_type=target_type,
        target_id=target_id,
        status="pending",
        deployed_by=user.id,
    )
    await redis.rpush("cmd:dispatch", json.dumps({
        "type": "sw_deploy",
        "deployment_id": deployment.id,
    }))
    await audit.log(
        action="deploy", resource_type="software",
        user_id=user.id, resource_id=package_id,
    )
    return RedirectResponse("/software/deploy", status_code=302)


# ── Alerts ────────────────────────────────────────────────────────────────

@router.get("/alerts", response_class=HTMLResponse)
async def alerts_page(
    request: Request, user: CurrentUser,
    device: Optional[str] = None,
    session: DbSession = None,
):
    rule_repo = AlertRuleRepository(session)
    alert_repo = AlertRepository(session)
    rules = await rule_repo.list()
    open_alerts = await alert_repo.get_open(device_id=device)
    return templates.TemplateResponse(
        "alerts/list.html",
        {
            "request": request, "user": user,
            "rules": rules, "open_alerts": open_alerts,
        },
    )


@router.post("/alerts/rules")
async def alert_rule_create(
    request: Request, user: CurrentUser,
    name: str = Form(...),
    metric_type: str = Form(...),
    threshold: float = Form(...),
    operator: str = Form(">"),
    duration_seconds: int = Form(60),
    session: DbSession = None,
):
    repo = AlertRuleRepository(session)
    await repo.create(
        name=name, metric_type=metric_type, threshold=threshold,
        operator=operator, duration_seconds=duration_seconds,
        created_by=user.id,
    )
    return RedirectResponse("/alerts", status_code=302)


@router.post("/alerts/rules/{rule_id}/delete")
async def alert_rule_delete(
    request: Request, rule_id: str, user: CurrentUser,
    session: DbSession = None,
):
    repo = AlertRuleRepository(session)
    rule = await repo.get(rule_id)
    if rule:
        await repo.delete(rule)
    return RedirectResponse("/alerts", status_code=302)


@router.post("/alerts/{alert_id}/resolve")
async def alert_resolve(
    request: Request, alert_id: str, user: CurrentUser,
    session: DbSession = None,
):
    from datetime import datetime, timezone
    repo = AlertRepository(session)
    alert = await repo.get(alert_id)
    if alert:
        await repo.update(alert, status="resolved", resolved_at=datetime.now(timezone.utc))
    return RedirectResponse("/alerts", status_code=302)


# ── Audit Logs ────────────────────────────────────────────────────────────

@router.get("/audit", response_class=HTMLResponse)
async def audit_page(
    request: Request, user: CurrentUser, session: DbSession = None
):
    repo = AuditLogRepository(session)
    logs = await repo.recent(limit=200)
    return templates.TemplateResponse(
        "audit/list.html",
        {"request": request, "user": user, "logs": logs},
    )


# ── AI Reports ────────────────────────────────────────────────────────────

@router.get("/reports", response_class=HTMLResponse)
async def reports_page(
    request: Request, user: CurrentUser, session: DbSession = None
):
    repo = ReportRepository(session)
    reports = await repo.list_recent()
    return templates.TemplateResponse(
        "reports/list.html",
        {"request": request, "user": user, "reports": reports},
    )


@router.post("/reports/generate")
async def report_generate(
    request: Request, user: CurrentUser,
    report_type: str = Form(...),
    session: DbSession = None,
):
    repo = ReportRepository(session)
    redis = get_redis()

    from datetime import datetime, timezone
    title_map = {"daily": "Daily Report", "weekly": "Weekly Report", "monthly": "Monthly Report"}
    report = await repo.create(
        report_type=report_type,
        title=f"{title_map.get(report_type, report_type)} — {datetime.now(timezone.utc).strftime('%Y-%m-%d')}",
        status="pending",
        generated_by=user.id,
    )
    await redis.rpush("report:generate", json.dumps({"report_id": report.id}))
    return RedirectResponse("/reports", status_code=302)


@router.get("/reports/{report_id}", response_class=HTMLResponse)
async def report_view(
    request: Request, report_id: str, user: CurrentUser,
    session: DbSession = None,
):
    repo = ReportRepository(session)
    report = await repo.get(report_id)
    if not report:
        return HTMLResponse("Report not found", status_code=404)
    return templates.TemplateResponse(
        "reports/detail.html",
        {"request": request, "user": user, "report": report},
    )


@router.get("/reports/{report_id}/pdf")
async def report_pdf(
    request: Request, report_id: str, user: CurrentUser,
    session: DbSession = None,
):
    """Export report as PDF using WeasyPrint."""
    repo = ReportRepository(session)
    report = await repo.get(report_id)
    if not report or not report.content:
        return HTMLResponse("Report not available", status_code=404)

    import tempfile
    from weasyprint import HTML as WP_HTML

    html_content = f"""
    <html><head>
    <meta charset="utf-8"/>
    <style>
      body {{ font-family: Arial, sans-serif; padding: 2cm; color: #222; }}
      h1 {{ color: #2c4fa3; }} h2 {{ color: #444; border-bottom: 1px solid #ddd; }}
      pre {{ white-space: pre-wrap; font-size: 12px; background:#f5f5f5; padding:1em; }}
    </style></head><body>
    <h1>{report.title}</h1>
    <p><em>Generated: {report.generated_at.strftime('%Y-%m-%d %H:%M UTC')}</em></p>
    <hr/>
    <pre>{report.content}</pre>
    </body></html>
    """

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        WP_HTML(string=html_content).write_pdf(f.name)
        pdf_path = f.name

    return FileResponse(
        pdf_path,
        media_type="application/pdf",
        filename=f"report_{report_id[:8]}.pdf",
    )


# ── Monitoring page ───────────────────────────────────────────────────────

@router.get("/monitoring", response_class=HTMLResponse)
async def monitoring_page(
    request: Request, user: CurrentUser, session: DbSession = None
):
    device_repo = DeviceRepository(session)
    devices = await device_repo.list_with_relations()
    return templates.TemplateResponse(
        "monitoring/index.html",
        {"request": request, "user": user, "devices": devices},
    )


# ── Device assign (domain/group) ──────────────────────────────────────────

@router.post("/devices/{device_id}/assign")
async def device_assign(
    request: Request, device_id: str, user: CurrentUser,
    domain_id: Optional[str] = Form(None),
    group_id: Optional[str] = Form(None),
    session: DbSession = None,
):
    repo = DeviceRepository(session)
    device = await repo.get(device_id)
    if device:
        await repo.update(
            device,
            domain_id=domain_id or None,
            group_id=group_id or None,
        )
    return RedirectResponse(f"/devices/{device_id}", status_code=302)