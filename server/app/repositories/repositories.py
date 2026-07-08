"""
Domain-specific repositories with custom queries.
"""
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import select, desc, and_, func, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.repositories.base import BaseRepository
from app.models.models import (
    User, Device, DeviceMetric, Domain, Group,
    Policy, PolicyAssignment, PolicyApplicationResult,
    Script, ScriptDeployment, ScriptExecutionLog,
    SoftwareInventory, SoftwarePackage, SoftwareDeployment, SoftwareDeploymentLog,
    AlertRule, Alert, AuditLog, Report,
)


class UserRepository(BaseRepository[User]):
    def __init__(self, session: AsyncSession):
        super().__init__(User, session)

    async def get_by_username(self, username: str) -> Optional[User]:
        result = await self.session.execute(
            select(User).where(User.username == username)
        )
        return result.scalar_one_or_none()

    async def get_by_email(self, email: str) -> Optional[User]:
        result = await self.session.execute(
            select(User).where(User.email == email)
        )
        return result.scalar_one_or_none()


class DeviceRepository(BaseRepository[Device]):
    def __init__(self, session: AsyncSession):
        super().__init__(Device, session)

    async def get_by_device_id(self, device_id: str) -> Optional[Device]:
        result = await self.session.execute(
            select(Device).where(Device.device_id == device_id)
        )
        return result.scalar_one_or_none()

    async def list_with_relations(
        self, offset: int = 0, limit: int = 50
    ) -> list[Device]:
        result = await self.session.execute(
            select(Device)
            .options(
                selectinload(Device.domain),
                selectinload(Device.group),
            )
            .order_by(Device.hostname)
            .offset(offset)
            .limit(limit)
        )
        devices = list(result.scalars().all())
        return devices

    async def list_with_latest_metric(self, limit: int = 50) -> list[tuple]:
        """
        Trả về list (Device, DeviceMetric | None) với latest metric mỗi device.
        Dùng lateral join để tránh load toàn bộ metric history.
        """
        from sqlalchemy import text
        # Dùng subquery lấy latest metric_id per device
        latest_metric_sq = (
            select(DeviceMetric.device_id, DeviceMetric.id.label("metric_id"))
            .distinct(DeviceMetric.device_id)
            .order_by(DeviceMetric.device_id, desc(DeviceMetric.recorded_at))
            .subquery("latest_metric")
        )
        result = await self.session.execute(
            select(Device, DeviceMetric)
            .outerjoin(
                latest_metric_sq,
                latest_metric_sq.c.device_id == Device.id,
            )
            .outerjoin(
                DeviceMetric,
                DeviceMetric.id == latest_metric_sq.c.metric_id,
            )
            .options(
                selectinload(Device.domain),
                selectinload(Device.group),
            )
            .order_by(Device.hostname)
            .limit(limit)
        )
        return result.all()

    async def set_status(self, device_id: str, status: str) -> None:
        await self.session.execute(
            update(Device)
            .where(Device.device_id == device_id)
            .values(status=status, last_seen=datetime.now(timezone.utc))
        )

    async def get_stale_devices(self, threshold_seconds: int) -> list[Device]:
        """Devices that haven't sent a heartbeat within threshold."""
        cutoff = datetime.now(timezone.utc).timestamp() - threshold_seconds
        cutoff_dt = datetime.fromtimestamp(cutoff, tz=timezone.utc)
        result = await self.session.execute(
            select(Device).where(
                and_(
                    Device.status == "online",
                    Device.last_seen < cutoff_dt,
                )
            )
        )
        return list(result.scalars().all())

    async def count_by_status(self) -> dict[str, int]:
        result = await self.session.execute(
            select(Device.status, func.count(Device.id))
            .group_by(Device.status)
        )
        return {row[0]: row[1] for row in result.all()}


class DeviceMetricRepository(BaseRepository[DeviceMetric]):
    def __init__(self, session: AsyncSession):
        super().__init__(DeviceMetric, session)

    async def get_recent(self, device_id: str, limit: int = 60) -> list[DeviceMetric]:
        result = await self.session.execute(
            select(DeviceMetric)
            .where(DeviceMetric.device_id == device_id)
            .order_by(desc(DeviceMetric.recorded_at))
            .limit(limit)
        )
        return list(result.scalars().all())

    async def get_latest(self, device_id: str) -> Optional[DeviceMetric]:
        result = await self.session.execute(
            select(DeviceMetric)
            .where(DeviceMetric.device_id == device_id)
            .order_by(desc(DeviceMetric.recorded_at))
            .limit(1)
        )
        return result.scalar_one_or_none()


class DomainRepository(BaseRepository[Domain]):
    def __init__(self, session: AsyncSession):
        super().__init__(Domain, session)

    async def get_tree(self) -> list[Domain]:
        """Return all domains; caller builds tree from parent_id."""
        result = await self.session.execute(
            select(Domain)
            .options(selectinload(Domain.children))
            .where(Domain.parent_id.is_(None))
            .order_by(Domain.name)
        )
        return list(result.scalars().all())


class GroupRepository(BaseRepository[Group]):
    def __init__(self, session: AsyncSession):
        super().__init__(Group, session)

    async def list_with_domain(self) -> list[Group]:
        result = await self.session.execute(
            select(Group)
            .options(selectinload(Group.domain))
            .order_by(Group.name)
        )
        return list(result.scalars().all())

    async def list_by_domain(self, domain_id: str) -> list[Group]:
        result = await self.session.execute(
            select(Group).where(Group.domain_id == domain_id).order_by(Group.name)
        )
        return list(result.scalars().all())


class PolicyRepository(BaseRepository[Policy]):
    def __init__(self, session: AsyncSession):
        super().__init__(Policy, session)

    async def list_with_assignments(self) -> list[Policy]:
        """List all policies, eager-loading assignments + per-device results
        to avoid lazy load errors and to power the response table in UI."""
        result = await self.session.execute(
            select(Policy)
            .options(
                selectinload(Policy.assignments)
                .selectinload(PolicyAssignment.results)
                .selectinload(PolicyApplicationResult.device)
            )
            .order_by(Policy.created_at.desc())
        )
        return list(result.scalars().all())

    async def get_assignment(self, assignment_id: str) -> Optional[PolicyAssignment]:
        result = await self.session.execute(
            select(PolicyAssignment).where(PolicyAssignment.id == assignment_id)
        )
        return result.scalar_one_or_none()

    async def get_assignment_with_results(self, assignment_id: str) -> Optional[PolicyAssignment]:
        """Dùng cho trang chi tiết — bảng phản hồi theo từng device."""
        result = await self.session.execute(
            select(PolicyAssignment)
            .options(
                selectinload(PolicyAssignment.results).selectinload(PolicyApplicationResult.device),
                selectinload(PolicyAssignment.policy),
            )
            .where(PolicyAssignment.id == assignment_id)
        )
        return result.scalar_one_or_none()

    async def get_for_device(self, device: Device) -> list[Policy]:
        """Collect all policies applicable to a device via device/group/domain assignment."""
        target_ids: list[str] = [device.id]
        if device.group_id:
            target_ids.append(device.group_id)
        if device.domain_id:
            target_ids.append(device.domain_id)

        result = await self.session.execute(
            select(Policy)
            .join(PolicyAssignment, PolicyAssignment.policy_id == Policy.id)
            .where(
                and_(
                    PolicyAssignment.target_id.in_(target_ids),
                    Policy.is_active == True,
                )
            )
        )
        return list(result.scalars().unique().all())


class ScriptRepository(BaseRepository[Script]):
    def __init__(self, session: AsyncSession):
        super().__init__(Script, session)

    async def search(self, query: str, limit: int = 20) -> list[Script]:
        result = await self.session.execute(
            select(Script)
            .where(Script.name.ilike(f"%{query}%"))
            .limit(limit)
        )
        return list(result.scalars().all())


class ScriptDeploymentRepository(BaseRepository[ScriptDeployment]):
    def __init__(self, session: AsyncSession):
        super().__init__(ScriptDeployment, session)

    async def list_recent_with_logs(self, limit: int = 20) -> list[ScriptDeployment]:
        """Bảng phản hồi deploy script — eager load script + logs.device."""
        result = await self.session.execute(
            select(ScriptDeployment)
            .options(
                selectinload(ScriptDeployment.script),
                selectinload(ScriptDeployment.execution_logs).selectinload(ScriptExecutionLog.device),
            )
            .order_by(desc(ScriptDeployment.deployed_at))
            .limit(limit)
        )
        return list(result.scalars().all())


class ScriptExecutionLogRepository(BaseRepository[ScriptExecutionLog]):
    def __init__(self, session: AsyncSession):
        super().__init__(ScriptExecutionLog, session)

    async def get_for_deployment(self, deployment_id: str) -> list[ScriptExecutionLog]:
        result = await self.session.execute(
            select(ScriptExecutionLog)
            .where(ScriptExecutionLog.deployment_id == deployment_id)
            .order_by(desc(ScriptExecutionLog.executed_at))
        )
        return list(result.scalars().all())


class SoftwareInventoryRepository(BaseRepository[SoftwareInventory]):
    def __init__(self, session: AsyncSession):
        super().__init__(SoftwareInventory, session)

    async def replace_for_device(
        self, device_id: str, entries: list[dict]
    ) -> None:
        """Delete old inventory for device, insert new."""
        from sqlalchemy import delete
        await self.session.execute(
            delete(SoftwareInventory).where(SoftwareInventory.device_id == device_id)
        )
        for e in entries:
            self.session.add(SoftwareInventory(device_id=device_id, **e))
        await self.session.flush()

    async def search_across_devices(
        self, query: str, limit: int = 100
    ) -> list[SoftwareInventory]:
        result = await self.session.execute(
            select(SoftwareInventory)
            .options(selectinload(SoftwareInventory.device))
            .where(SoftwareInventory.name.ilike(f"%{query}%"))
            .order_by(SoftwareInventory.name)
            .limit(limit)
        )
        return list(result.scalars().all())
    async def list_with_device(
        self,
        offset: int = 0,
        limit: int = 200,
        device_id: Optional[str] = None,
    ) -> list[SoftwareInventory]:
        stmt = select(SoftwareInventory).options(
            selectinload(SoftwareInventory.device)
        )
        if device_id is not None:
            stmt = stmt.where(SoftwareInventory.device_id == device_id)
        stmt = stmt.order_by(SoftwareInventory.name).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

class SoftwarePackageRepository(BaseRepository[SoftwarePackage]):
    def __init__(self, session: AsyncSession):
        super().__init__(SoftwarePackage, session)


class SoftwareDeploymentRepository(BaseRepository[SoftwareDeployment]):
    def __init__(self, session: AsyncSession):
        super().__init__(SoftwareDeployment, session)

    async def list_with_package(self, limit: int = 30) -> list[SoftwareDeployment]:
        result = await self.session.execute(
            select(SoftwareDeployment)
            .options(selectinload(SoftwareDeployment.package))
            .order_by(desc(SoftwareDeployment.deployed_at))
            .limit(limit)
        )
        return list(result.scalars().all())


class AlertRuleRepository(BaseRepository[AlertRule]):
    def __init__(self, session: AsyncSession):
        super().__init__(AlertRule, session)

    async def get_active(self) -> list[AlertRule]:
        result = await self.session.execute(
            select(AlertRule).where(AlertRule.is_active == True)
        )
        return list(result.scalars().all())


class AlertRepository(BaseRepository[Alert]):
    def __init__(self, session: AsyncSession):
        super().__init__(Alert, session)

    async def get_open(self, device_id: Optional[str] = None) -> list[Alert]:
        stmt = (
            select(Alert)
            .options(selectinload(Alert.rule), selectinload(Alert.device))
            .where(Alert.status == "open")
            .order_by(desc(Alert.triggered_at))
        )
        if device_id:
            stmt = stmt.where(Alert.device_id == device_id)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())


class AuditLogRepository(BaseRepository[AuditLog]):
    def __init__(self, session: AsyncSession):
        super().__init__(AuditLog, session)

    async def log(
        self,
        action: str,
        resource_type: str,
        user_id: Optional[str] = None,
        resource_id: Optional[str] = None,
        metadata: Optional[dict] = None,
        ip_address: Optional[str] = None,
    ) -> AuditLog:
        return await self.create(
            action=action,
            resource_type=resource_type,
            user_id=user_id,
            resource_id=resource_id,
            extra_data=metadata,
            ip_address=ip_address,
        )

    async def recent(self, limit: int = 100) -> list[AuditLog]:
        result = await self.session.execute(
            select(AuditLog)
            .options(selectinload(AuditLog.user))
            .order_by(desc(AuditLog.created_at))
            .limit(limit)
        )
        return list(result.scalars().all())


class ReportRepository(BaseRepository[Report]):
    def __init__(self, session: AsyncSession):
        super().__init__(Report, session)

    async def list_recent(self, limit: int = 20) -> list[Report]:
        result = await self.session.execute(
            select(Report)
            .order_by(desc(Report.generated_at))
            .limit(limit)
        )
        return list(result.scalars().all())


class PolicyApplicationResultRepository(BaseRepository[PolicyApplicationResult]):
    """Bảng phản hồi per-device cho mỗi lần assign policy."""

    def __init__(self, session: AsyncSession):
        super().__init__(PolicyApplicationResult, session)

    async def get_for_assignment(self, assignment_id: str) -> list[PolicyApplicationResult]:
        result = await self.session.execute(
            select(PolicyApplicationResult)
            .options(selectinload(PolicyApplicationResult.device))
            .where(PolicyApplicationResult.assignment_id == assignment_id)
            .order_by(desc(PolicyApplicationResult.applied_at))
        )
        return list(result.scalars().all())

    async def upsert(
        self, assignment_id: str, device_id: str, status: str, message: Optional[str] = None
    ) -> PolicyApplicationResult:
        """Tạo mới hoặc cập nhật kết quả cho cặp (assignment, device)."""
        result = await self.session.execute(
            select(PolicyApplicationResult).where(
                PolicyApplicationResult.assignment_id == assignment_id,
                PolicyApplicationResult.device_id == device_id,
            )
        )
        existing = result.scalar_one_or_none()
        if existing:
            return await self.update(existing, status=status, message=message)
        return await self.create(
            assignment_id=assignment_id, device_id=device_id,
            status=status, message=message,
        )