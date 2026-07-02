"""
Report Worker — listens on Redis queue 'report:generate'.
Gathers system data, calls Ollama, stores report.
"""
import asyncio
import json
from datetime import datetime, timezone, timedelta

import httpx
import structlog

from app.core.config import settings
from app.db.session import AsyncSessionLocal
from app.db.redis_client import get_redis
from app.repositories.repositories import (
    DeviceRepository, AlertRepository, ReportRepository,
    SoftwareInventoryRepository, AuditLogRepository,
)

log = structlog.get_logger()
QUEUE_KEY = "report:generate"


async def gather_report_data(session, report_type: str) -> dict:
    now = datetime.now(timezone.utc)
    if report_type == "daily":
        since = now - timedelta(days=1)
    elif report_type == "weekly":
        since = now - timedelta(weeks=1)
    else:
        since = now - timedelta(days=30)

    device_repo = DeviceRepository(session)
    alert_repo = AlertRepository(session)

    status_counts = await device_repo.count_by_status()
    open_alerts = await alert_repo.get_open()

    return {
        "report_type": report_type,
        "generated_at": now.isoformat(),
        "devices": {
            "total": sum(status_counts.values()),
            "online": status_counts.get("online", 0),
            "offline": status_counts.get("offline", 0),
        },
        "open_alerts": len(open_alerts),
        "critical_alerts": sum(1 for a in open_alerts if a.severity == "critical"),
    }


def build_prompt(data: dict) -> str:
    return f"""You are an IT infrastructure analyst. Generate a professional {data['report_type']} endpoint management report.

System data (as of {data['generated_at']}):
- Total managed devices: {data['devices']['total']}
- Online: {data['devices']['online']}
- Offline: {data['devices']['offline']}
- Open alerts: {data['open_alerts']}
- Critical alerts: {data['critical_alerts']}

Write the report with these sections:
1. Executive Summary
2. Infrastructure Health
3. Major Issues (if any)
4. Risk Assessment
5. Recommendations

Be concise and professional. Use plain text, no markdown."""


async def call_ollama(prompt: str) -> str:
    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(
            f"{settings.OLLAMA_BASE_URL}/api/generate",
            json={"model": settings.OLLAMA_MODEL, "prompt": prompt, "stream": False},
        )
        resp.raise_for_status()
        return resp.json()["response"]


async def process_report(session, payload: dict) -> None:
    report_id = payload["report_id"]
    report_repo = ReportRepository(session)

    report = await report_repo.get(report_id)
    if not report:
        return

    try:
        data = await gather_report_data(session, report.report_type)
        prompt = build_prompt(data)
        content = await call_ollama(prompt)

        await report_repo.update(
            report,
            content=content,
            status="completed",
            extra_data=data,
        )
        log.info("report_generated", report_id=report_id, type=report.report_type)
    except Exception as exc:
        await report_repo.update(report, status="failed", extra_data={"error": str(exc)})
        log.exception("report_failed", report_id=report_id, error=str(exc))


async def run() -> None:
    log.info("report_worker_started")

    # Wait for DB tables
    for attempt in range(30):
        try:
            async with AsyncSessionLocal() as session:
                from sqlalchemy import text
                await session.execute(text("SELECT 1 FROM reports LIMIT 1"))
            break
        except Exception:
            log.info("report_worker_waiting_for_db", attempt=attempt + 1)
            await asyncio.sleep(5)

    redis = get_redis()
    while True:
        try:
            item = await redis.blpop(QUEUE_KEY, timeout=5)
            if not item:
                continue
            _, raw = item
            payload = json.loads(raw)

            async with AsyncSessionLocal() as session:
                await process_report(session, payload)
                await session.commit()
        except Exception as exc:
            log.exception("report_worker_error", error=str(exc))


if __name__ == "__main__":
    asyncio.run(run())
