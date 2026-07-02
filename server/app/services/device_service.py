"""
Device registration, heartbeat, and inventory logic.
"""
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import Device, DeviceMetric
from app.repositories.repositories import DeviceRepository, DeviceMetricRepository
from app.schemas.schemas import DeviceRegisterRequest, DeviceHeartbeatRequest


class DeviceService:
    def __init__(self, session: AsyncSession):
        self.device_repo = DeviceRepository(session)
        self.metric_repo = DeviceMetricRepository(session)

    async def register_or_update(self, req: DeviceRegisterRequest) -> Device:
        device = await self.device_repo.get_by_device_id(req.device_id)
        now = datetime.now(timezone.utc)
        if device is None:
            device = await self.device_repo.create(
                device_id=req.device_id,
                hostname=req.hostname,
                ip_address=req.ip_address,
                os_type=req.os_type,
                os_version=req.os_version,
                username=req.username,
                status="online",
                last_seen=now,
            )
        else:
            await self.device_repo.update(
                device,
                hostname=req.hostname,
                ip_address=req.ip_address,
                os_version=req.os_version,
                username=req.username,
                status="online",
                last_seen=now,
            )
        return device

    async def process_heartbeat(self, req: DeviceHeartbeatRequest) -> Optional[Device]:
        device = await self.device_repo.get_by_device_id(req.device_id)
        if not device:
            return None

        now = datetime.now(timezone.utc)
        await self.device_repo.update(
            device,
            ip_address=req.ip_address or device.ip_address,
            username=req.username or device.username,
            status="online",
            last_seen=now,
        )

        # Store metric snapshot
        if any(v is not None for v in [req.cpu_percent, req.ram_percent, req.disk_percent]):
            await self.metric_repo.create(
                device_id=device.id,
                cpu_percent=req.cpu_percent,
                ram_percent=req.ram_percent,
                disk_percent=req.disk_percent,
                ram_total=req.ram_total,
                disk_total=req.disk_total,
            )

        return device

    async def get_device(self, device_db_id: str) -> Optional[Device]:
        return await self.device_repo.get(device_db_id)

    async def list_devices(self, page: int = 1, page_size: int = 50):
        offset = (page - 1) * page_size
        devices = await self.device_repo.list_with_relations(offset=offset, limit=page_size)
        total = await self.device_repo.count()
        return devices, total

    async def get_metrics(self, device_db_id: str, limit: int = 60):
        return await self.metric_repo.get_recent(device_db_id, limit=limit)

    async def get_dashboard_stats(self) -> dict:
        status_counts = await self.device_repo.count_by_status()
        total = sum(status_counts.values())
        return {
            "total": total,
            "online": status_counts.get("online", 0),
            "offline": status_counts.get("offline", 0),
        }
