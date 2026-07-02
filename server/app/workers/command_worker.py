"""
Command Worker — listens on Redis queue 'cmd:dispatch'.
Receives deployment tasks and pushes commands to the target device queues.
"""
import asyncio
import json

import structlog

from app.db.session import AsyncSessionLocal
from app.db.redis_client import get_redis
from app.repositories.repositories import (
    DeviceRepository, GroupRepository, DomainRepository,
    ScriptDeploymentRepository, ScriptExecutionLogRepository,
    ScriptRepository, PolicyRepository,
)

log = structlog.get_logger()
QUEUE_KEY = "cmd:dispatch"


async def resolve_target_devices(session, target_type: str, target_id: str) -> list:
    """Expand group/domain targets to individual device lists."""
    device_repo = DeviceRepository(session)
    if target_type == "device":
        d = await device_repo.get(target_id)
        return [d] if d else []
    elif target_type == "group":
        return await device_repo.list(group_id=target_id)
    elif target_type == "domain":
        return await device_repo.list(domain_id=target_id)
    return []


async def process_script_dispatch(session, payload: dict) -> None:
    deployment_id = payload["deployment_id"]
    deploy_repo = ScriptDeploymentRepository(session)
    script_repo = ScriptRepository(session)
    log_repo = ScriptExecutionLogRepository(session)

    deployment = await deploy_repo.get(deployment_id)
    if not deployment:
        return

    script = await script_repo.get(deployment.script_id)
    if not script:
        return

    devices = await resolve_target_devices(session, deployment.target_type, deployment.target_id)
    redis = get_redis()

    for device in devices:
        cmd = {
            "type": "run_script",
            "script_id": script.id,
            "deployment_id": deployment_id,
            "script_type": script.script_type,
            "content": script.content,
        }
        await redis.rpush(f"cmd:pending:{device.device_id}", json.dumps(cmd))

        # Pre-create a "running" log entry
        await log_repo.create(
            deployment_id=deployment_id,
            device_id=device.id,
            status="pending",
        )

    await deploy_repo.update(deployment, status="dispatched")
    log.info("script_dispatched", deployment_id=deployment_id, device_count=len(devices))

async def process_policy_dispatch(session, payload: dict) -> None:
    """
    Generic policy dispatcher — hoạt động với MỌI policy_type (wallpaper,
    disable_usb, disable_cmd, disable_task_manager, custom_registry,
    linux_sysctl, hoặc loại mới sau này). Worker không cần biết policy
    làm gì, chỉ forward policy_type + config xuống agent.
    """
    policy_id = payload["policy_id"]
    target_type = payload["target_type"]
    target_id = payload["target_id"]
    assignment_id = payload.get("assignment_id")

    policy_repo = PolicyRepository(session)
    policy = await policy_repo.get(policy_id)
    if not policy:
        log.warning("policy_dispatch_skipped_missing_policy", policy_id=policy_id)
        return

    if not policy.is_active:
        log.info("policy_dispatch_skipped_inactive", policy_id=policy_id)
        return

    devices = await resolve_target_devices(session, target_type, target_id)
    redis = get_redis()

    for device in devices:
        cmd = {
            "type": "apply_policy",
            "policy_id": policy.id,
            "assignment_id": assignment_id,
            "policy_type": policy.policy_type,
            "config": policy.config,
            "os_type": device.os_type,
        }
        await redis.rpush(f"cmd:pending:{device.device_id}", json.dumps(cmd))

    log.info(
        "policy_dispatched",
        policy_id=policy_id,
        policy_type=policy.policy_type,
        target_type=target_type,
        device_count=len(devices),
    )

async def run() -> None:
    log.info("command_worker_started")

    # Wait for DB tables
    for attempt in range(30):
        try:
            async with AsyncSessionLocal() as session:
                from sqlalchemy import text
                await session.execute(text("SELECT 1 FROM devices LIMIT 1"))
            break
        except Exception:
            log.info("command_worker_waiting_for_db", attempt=attempt + 1)
            await asyncio.sleep(5)

    redis = get_redis()
    while True:
        try:
            item = await redis.blpop(QUEUE_KEY, timeout=5)
            if not item:
                continue
            _, raw = item
            payload = json.loads(raw)
            log.info("cmd_received", type=payload.get("type"))

            async with AsyncSessionLocal() as session:
                task_type = payload.get("type")
                if task_type == "script_dispatch":
                    await process_script_dispatch(session, payload)
                elif task_type == "policy_dispatch":
                    await process_policy_dispatch(session, payload)
                await session.commit()
        except Exception as exc:
            log.exception("command_worker_error", error=str(exc))


if __name__ == "__main__":
    asyncio.run(run())
