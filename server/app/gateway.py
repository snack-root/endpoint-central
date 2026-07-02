"""
Agent Gateway — separate FastAPI app on port 8001.
Agents POST here; gateway writes to DB and pushes commands via Redis pub/sub.
"""
import json
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Header, Depends, WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.session import get_db, engine, Base
from app.db.redis_client import get_redis
from app.services.device_service import DeviceService
from app.schemas.schemas import DeviceRegisterRequest, DeviceHeartbeatRequest
import structlog

log = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Tables created by main.py / alembic; gateway just needs DB ready
    yield


app = FastAPI(title="Endpoint Central — Agent Gateway", lifespan=lifespan)


# ── Gateway API Key auth ─────────────────────────────────────────────────────

async def verify_gateway_key(x_gateway_key: str = Header(...)):
    if x_gateway_key != settings.GATEWAY_API_KEY:
        raise HTTPException(status_code=403, detail="Invalid gateway key")


# ── REST endpoints for agents ────────────────────────────────────────────────

@app.post("/agent/register", status_code=201)
async def agent_register(
    req: DeviceRegisterRequest,
    session: AsyncSession = Depends(get_db),
    _: None = Depends(verify_gateway_key),
):
    svc = DeviceService(session)
    device = await svc.register_or_update(req)
    log.info("agent_registered", device_id=req.device_id, hostname=req.hostname)
    return {"status": "ok", "device_db_id": device.id}


@app.post("/agent/heartbeat")
async def agent_heartbeat(
    req: DeviceHeartbeatRequest,
    session: AsyncSession = Depends(get_db),
    _: None = Depends(verify_gateway_key),
):
    svc = DeviceService(session)
    device = await svc.process_heartbeat(req)
    if not device:
        raise HTTPException(status_code=404, detail="Device not registered")

    # Publish heartbeat event so alert-worker can react
    redis = get_redis()
    await redis.publish(
        "heartbeat",
        json.dumps({"device_id": device.device_id, "device_db_id": device.id}),
    )

    # Check for pending commands for this device
    pending_key = f"cmd:pending:{device.device_id}"
    commands = await redis.lrange(pending_key, 0, -1)
    if commands:
        await redis.delete(pending_key)
        return {"status": "ok", "commands": [json.loads(c) for c in commands]}

    return {"status": "ok", "commands": []}


@app.post("/agent/script-result")
async def agent_script_result(
    payload: dict,
    session: AsyncSession = Depends(get_db),
    _: None = Depends(verify_gateway_key),
):
    """
    Agent posts script execution results here.
    Ghi trực tiếp vào script_execution_logs để dashboard hiển thị
    bảng phản hồi theo từng device, đồng thời publish Redis cho
    bất kỳ consumer realtime nào khác (tuỳ chọn).
    """
    from app.repositories.repositories import (
        DeviceRepository, ScriptExecutionLogRepository, ScriptDeploymentRepository,
    )
    from sqlalchemy import select, desc
    from app.models.models import ScriptExecutionLog

    device_repo = DeviceRepository(session)
    log_repo = ScriptExecutionLogRepository(session)

    device = await device_repo.get_by_device_id(payload.get("device_id", ""))
    deployment_id = payload.get("deployment_id")

    if device and deployment_id:
        # Tìm log "pending" đã được command_worker tạo sẵn cho cặp
        # (deployment_id, device_id) này và update nó, thay vì insert mới
        result = await session.execute(
            select(ScriptExecutionLog)
            .where(
                ScriptExecutionLog.deployment_id == deployment_id,
                ScriptExecutionLog.device_id == device.id,
            )
            .order_by(desc(ScriptExecutionLog.executed_at))
            .limit(1)
        )
        existing = result.scalar_one_or_none()

        if existing:
            await log_repo.update(
                existing,
                status=payload.get("status", "failed"),
                stdout=payload.get("stdout"),
                stderr=payload.get("stderr"),
                exit_code=payload.get("exit_code"),
            )
        else:
            await log_repo.create(
                deployment_id=deployment_id,
                device_id=device.id,
                status=payload.get("status", "failed"),
                stdout=payload.get("stdout"),
                stderr=payload.get("stderr"),
                exit_code=payload.get("exit_code"),
            )

        # Cập nhật trạng thái tổng của deployment dựa trên tất cả log con
        deploy_repo = ScriptDeploymentRepository(session)
        deployment = await deploy_repo.get(deployment_id)
        if deployment:
            all_logs = await log_repo.get_for_deployment(deployment_id)
            statuses = {l.status for l in all_logs}
            if "pending" in statuses or "running" in statuses:
                overall = "dispatched"
            elif statuses == {"success"}:
                overall = "completed"
            elif "failed" in statuses:
                overall = "partial_failure" if "success" in statuses else "failed"
            else:
                overall = "dispatched"
            await deploy_repo.update(deployment, status=overall)

        await session.commit()

        log.info(
            "script_result_saved",
            device_id=payload.get("device_id"),
            deployment_id=deployment_id,
            status=payload.get("status"),
        )

    redis = get_redis()
    await redis.publish("script_result", json.dumps(payload))
    return {"status": "ok"}

@app.post("/agent/policy-result")
async def agent_policy_result(
    payload: dict,
    session: AsyncSession = Depends(get_db),
    _: None = Depends(verify_gateway_key),
):
    """
    Agent posts policy application results here.
    Ghi vào policy_application_results để bảng phản hồi trên dashboard
    hiển thị trạng thái success/failed theo từng device.
    """
    from app.repositories.repositories import (
        DeviceRepository, PolicyApplicationResultRepository, PolicyRepository,
    )

    device_repo = DeviceRepository(session)
    result_repo = PolicyApplicationResultRepository(session)
    policy_repo = PolicyRepository(session)

    device = await device_repo.get_by_device_id(payload.get("device_id", ""))
    assignment_id = payload.get("assignment_id")

    if device and assignment_id:
        ok = payload.get("status") == "success"
        await result_repo.upsert(
            assignment_id=assignment_id,
            device_id=device.id,
            status="success" if ok else "failed",
            message=payload.get("message"),
        )

        # Cập nhật trạng thái tổng hợp của assignment
        assignment = await policy_repo.get_assignment(assignment_id)
        if assignment:
            all_results = await result_repo.get_for_assignment(assignment_id)
            statuses = {r.status for r in all_results}
            if statuses == {"success"}:
                overall = "completed"
            elif "failed" in statuses:
                overall = "partial_failure" if "success" in statuses else "failed"
            else:
                overall = "dispatched"
            assignment.status = overall

        await session.commit()

        log.info(
            "policy_result_saved",
            device_id=payload.get("device_id"),
            assignment_id=assignment_id,
            status="success" if ok else "failed",
        )

    redis = get_redis()
    await redis.publish("policy_result", json.dumps(payload))
    return {"status": "ok"}

@app.post("/agent/software-inventory")
async def agent_software_inventory(
    payload: dict,
    session: AsyncSession = Depends(get_db),
    _: None = Depends(verify_gateway_key),
):
    """Agent posts its software list here."""
    from app.repositories.repositories import (
        DeviceRepository, SoftwareInventoryRepository
    )
    device_repo = DeviceRepository(session)
    sw_repo = SoftwareInventoryRepository(session)

    device = await device_repo.get_by_device_id(payload["device_id"])
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    await sw_repo.replace_for_device(device.id, payload.get("software", []))
    log.info("sw_inventory_updated", device_id=payload["device_id"], count=len(payload.get("software", [])))
    return {"status": "ok"}


# ── WebSocket (optional real-time channel) ───────────────────────────────────

class ConnectionManager:
    def __init__(self):
        self.active: dict[str, WebSocket] = {}

    async def connect(self, device_id: str, ws: WebSocket):
        await ws.accept()
        self.active[device_id] = ws

    def disconnect(self, device_id: str):
        self.active.pop(device_id, None)

    async def send(self, device_id: str, data: dict):
        ws = self.active.get(device_id)
        if ws:
            await ws.send_json(data)


manager = ConnectionManager()


@app.websocket("/agent/ws/{device_id}")
async def agent_ws(
    websocket: WebSocket,
    device_id: str,
    x_gateway_key: str | None = None,
):
    if x_gateway_key != settings.GATEWAY_API_KEY:
        await websocket.close(code=4003)
        return

    await manager.connect(device_id, websocket)
    log.info("ws_connected", device_id=device_id)
    try:
        while True:
            data = await websocket.receive_json()
            # Handle incoming messages (heartbeat, results)
            log.debug("ws_message", device_id=device_id, type=data.get("type"))
    except WebSocketDisconnect:
        manager.disconnect(device_id)
        log.info("ws_disconnected", device_id=device_id)
