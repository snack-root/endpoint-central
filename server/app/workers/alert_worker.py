"""
Alert Worker — runs on its own process.
Every 30 seconds:
  1. Mark stale devices as offline.
  2. Evaluate metric-based alert rules against latest metrics.
  3. Open new alerts / resolve cleared ones.
"""
import asyncio
import json
from datetime import datetime, timezone

import structlog

from app.core.config import settings
from app.db.session import AsyncSessionLocal
from app.db.redis_client import get_redis
from app.models.models import Alert
from app.repositories.repositories import (
    DeviceRepository, DeviceMetricRepository,
    AlertRuleRepository, AlertRepository,
)

log = structlog.get_logger()
POLL_INTERVAL = 30


async def check_device_staleness(session) -> None:
    repo = DeviceRepository(session)
    stale = await repo.get_stale_devices(settings.HEARTBEAT_TIMEOUT_SECONDS)
    for device in stale:
        await repo.update(device, status="offline")
        log.info("device_marked_offline", device_id=device.device_id)

        # Notify dashboard via Redis
        redis = get_redis()
        await redis.publish("device_status", json.dumps({
            "device_id": device.device_id,
            "status": "offline",
        }))


async def evaluate_alert_rules(session) -> None:
    rule_repo = AlertRuleRepository(session)
    alert_repo = AlertRepository(session)
    device_repo = DeviceRepository(session)
    metric_repo = DeviceMetricRepository(session)

    rules = await rule_repo.get_active()
    devices = await device_repo.list()

    for rule in rules:
        for device in devices:
            if rule.metric_type == "offline":
                if device.status == "offline":
                    value = 1.0
                    should_alert = True
                else:
                    should_alert = False
                    value = 0.0
            else:
                metric = await metric_repo.get_latest(device.id)
                if not metric:
                    continue
                value = getattr(metric, f"{rule.metric_type}_percent") or 0.0
                ops = {">": value > rule.threshold, "<": value < rule.threshold,
                       ">=": value >= rule.threshold, "<=": value <= rule.threshold,
                       "==": value == rule.threshold}
                should_alert = ops.get(rule.operator, False)

            # Check for existing open alert
            existing = None
            open_alerts = await alert_repo.get_open(device_id=device.id)
            for a in open_alerts:
                if a.rule_id == rule.id:
                    existing = a
                    break

            if should_alert and not existing:
                severity = "critical" if value > 90 else "warning"
                await alert_repo.create(
                    rule_id=rule.id,
                    device_id=device.id,
                    severity=severity,
                    status="open",
                    triggered_value=value,
                )
                log.warning("alert_opened", rule=rule.name, device=device.hostname, value=value)
            elif not should_alert and existing:
                await alert_repo.update(
                    existing,
                    status="resolved",
                    resolved_at=datetime.now(timezone.utc),
                )
                log.info("alert_resolved", rule=rule.name, device=device.hostname)


async def run() -> None:
    log.info("alert_worker_started", poll_interval=POLL_INTERVAL)

    # Wait for tables to be created by api-service
    for attempt in range(30):
        try:
            async with AsyncSessionLocal() as session:
                from sqlalchemy import text
                await session.execute(text("SELECT 1 FROM devices LIMIT 1"))
            break
        except Exception:
            log.info("alert_worker_waiting_for_db", attempt=attempt + 1)
            await asyncio.sleep(5)

    while True:
        try:
            async with AsyncSessionLocal() as session:
                await check_device_staleness(session)
                await evaluate_alert_rules(session)
                await session.commit()
        except Exception as exc:
            log.exception("alert_worker_error", error=str(exc))
        await asyncio.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    asyncio.run(run())
