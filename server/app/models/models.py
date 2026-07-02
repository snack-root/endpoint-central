"""
All ORM models for Endpoint Central.
Single file keeps Alembic autogenerate simple.
"""
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean, DateTime, Float, ForeignKey, Index, Integer,
    String, Text, BigInteger, func,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


def _uuid() -> str:
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------

class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(32), default="admin", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_login: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # relationships
    audit_logs: Mapped[list["AuditLog"]] = relationship(back_populates="user")
    created_scripts: Mapped[list["Script"]] = relationship(back_populates="created_by_user")
    created_policies: Mapped[list["Policy"]] = relationship(back_populates="created_by_user")
    created_alert_rules: Mapped[list["AlertRule"]] = relationship(back_populates="created_by_user")
    reports: Mapped[list["Report"]] = relationship(back_populates="generated_by_user")


# ---------------------------------------------------------------------------
# Domains (tree structure via self-referential FK)
# ---------------------------------------------------------------------------

class Domain(Base):
    __tablename__ = "domains"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    parent_id: Mapped[Optional[str]] = mapped_column(
        UUID(as_uuid=False), ForeignKey("domains.id", ondelete="SET NULL"), nullable=True
    )
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Self-referential
    parent: Mapped[Optional["Domain"]] = relationship(
        "Domain", remote_side="Domain.id", back_populates="children"
    )
    children: Mapped[list["Domain"]] = relationship(
        "Domain", back_populates="parent", cascade="all, delete-orphan"
    )
    groups: Mapped[list["Group"]] = relationship(back_populates="domain", cascade="all, delete-orphan")
    devices: Mapped[list["Device"]] = relationship(back_populates="domain")


# ---------------------------------------------------------------------------
# Groups
# ---------------------------------------------------------------------------

class Group(Base):
    __tablename__ = "groups"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    domain_id: Mapped[Optional[str]] = mapped_column(
        UUID(as_uuid=False), ForeignKey("domains.id", ondelete="SET NULL"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    domain: Mapped[Optional["Domain"]] = relationship(back_populates="groups")
    devices: Mapped[list["Device"]] = relationship(back_populates="group")


# ---------------------------------------------------------------------------
# Devices
# ---------------------------------------------------------------------------

class Device(Base):
    __tablename__ = "devices"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    # Unique identifier sent by the agent (machine-id / registry key)
    device_id: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
    hostname: Mapped[str] = mapped_column(String(255), nullable=False)
    ip_address: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    os_type: Mapped[str] = mapped_column(String(16), nullable=False)   # "windows" | "linux"
    os_version: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    username: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    domain_id: Mapped[Optional[str]] = mapped_column(
        UUID(as_uuid=False), ForeignKey("domains.id", ondelete="SET NULL"), nullable=True
    )
    group_id: Mapped[Optional[str]] = mapped_column(
        UUID(as_uuid=False), ForeignKey("groups.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(16), default="offline", nullable=False)
    last_seen: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    registered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    domain: Mapped[Optional["Domain"]] = relationship(back_populates="devices")
    group: Mapped[Optional["Group"]] = relationship(back_populates="devices")
    metrics: Mapped[list["DeviceMetric"]] = relationship(back_populates="device", cascade="all, delete-orphan")
    software: Mapped[list["SoftwareInventory"]] = relationship(back_populates="device", cascade="all, delete-orphan")
    alerts: Mapped[list["Alert"]] = relationship(back_populates="device", cascade="all, delete-orphan")
    script_logs: Mapped[list["ScriptExecutionLog"]] = relationship(
        back_populates="device", cascade="all, delete-orphan"
    )
    software_deployment_logs: Mapped[list["SoftwareDeploymentLog"]] = relationship(
        back_populates="device", cascade="all, delete-orphan"
    )


# ---------------------------------------------------------------------------
# Device Metrics
# ---------------------------------------------------------------------------

class DeviceMetric(Base):
    __tablename__ = "device_metrics"
    __table_args__ = (
        Index("ix_device_metrics_device_recorded", "device_id", "recorded_at"),
    )

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    device_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("devices.id", ondelete="CASCADE"), nullable=False
    )
    cpu_percent: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    ram_percent: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    disk_percent: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    ram_total: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    disk_total: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    device: Mapped["Device"] = relationship(back_populates="metrics")


# ---------------------------------------------------------------------------
# Policies
# ---------------------------------------------------------------------------

class Policy(Base):
    __tablename__ = "policies"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    policy_type: Mapped[str] = mapped_column(String(64), nullable=False)
    # e.g. {"disable_usb": true} or {"wallpaper_url": "..."}
    config: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_by: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    created_by_user: Mapped[Optional["User"]] = relationship(back_populates="created_policies")
    assignments: Mapped[list["PolicyAssignment"]] = relationship(
        back_populates="policy", cascade="all, delete-orphan"
    )


class PolicyAssignment(Base):
    """Links a policy to a domain, group, or individual device."""
    __tablename__ = "policy_assignments"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    policy_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("policies.id", ondelete="CASCADE"), nullable=False
    )
    # "domain" | "group" | "device"
    target_type: Mapped[str] = mapped_column(String(16), nullable=False)
    target_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    # "dispatched" | "completed" | "partial_failure" | "failed"
    status: Mapped[str] = mapped_column(String(32), default="dispatched", nullable=False)
    assigned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    assigned_by: Mapped[Optional[str]] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    policy: Mapped["Policy"] = relationship(back_populates="assignments")
    results: Mapped[list["PolicyApplicationResult"]] = relationship(
        back_populates="assignment", cascade="all, delete-orphan"
    )


class PolicyApplicationResult(Base):
    """Per-device kết quả áp dụng policy — bảng phản hồi mà dashboard hiển thị."""
    __tablename__ = "policy_application_results"
    __table_args__ = (
        Index("ix_policy_results_assignment_device", "assignment_id", "device_id"),
    )

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    assignment_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("policy_assignments.id", ondelete="CASCADE"), nullable=False
    )
    device_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("devices.id", ondelete="CASCADE"), nullable=False
    )
    # "pending" | "success" | "failed"
    status: Mapped[str] = mapped_column(String(16), default="pending", nullable=False)
    message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    applied_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    assignment: Mapped["PolicyAssignment"] = relationship(back_populates="results")
    device: Mapped["Device"] = relationship()


# ---------------------------------------------------------------------------
# Scripts
# ---------------------------------------------------------------------------

class Script(Base):
    __tablename__ = "scripts"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # "powershell" | "cmd" | "bash" | "python"
    script_type: Mapped[str] = mapped_column(String(32), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_by: Mapped[Optional[str]] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    created_by_user: Mapped[Optional["User"]] = relationship(back_populates="created_scripts")
    deployments: Mapped[list["ScriptDeployment"]] = relationship(
        back_populates="script", cascade="all, delete-orphan"
    )


class ScriptDeployment(Base):
    __tablename__ = "script_deployments"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    script_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("scripts.id", ondelete="CASCADE"), nullable=False
    )
    target_type: Mapped[str] = mapped_column(String(16), nullable=False)  # device | group | domain
    target_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    deployed_by: Mapped[Optional[str]] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    deployed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    script: Mapped["Script"] = relationship(back_populates="deployments")
    execution_logs: Mapped[list["ScriptExecutionLog"]] = relationship(
        back_populates="deployment", cascade="all, delete-orphan"
    )


class ScriptExecutionLog(Base):
    __tablename__ = "script_execution_logs"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    deployment_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("script_deployments.id", ondelete="CASCADE"), nullable=False
    )
    device_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("devices.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False)  # success | failed | running
    stdout: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    stderr: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    exit_code: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    executed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    deployment: Mapped["ScriptDeployment"] = relationship(back_populates="execution_logs")
    device: Mapped["Device"] = relationship(back_populates="script_logs")


# ---------------------------------------------------------------------------
# Software Inventory
# ---------------------------------------------------------------------------

class SoftwareInventory(Base):
    __tablename__ = "software_inventory"
    __table_args__ = (
        Index("ix_sw_inventory_device_name", "device_id", "name"),
    )

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    device_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("devices.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    version: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    publisher: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    install_date: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    scanned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    device: Mapped["Device"] = relationship(back_populates="software")


# ---------------------------------------------------------------------------
# Software Packages & Deployment
# ---------------------------------------------------------------------------

class SoftwarePackage(Base):
    __tablename__ = "software_packages"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    version: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    file_path: Mapped[str] = mapped_column(String(512), nullable=False)
    package_type: Mapped[str] = mapped_column(String(16), nullable=False)  # msi | exe | sh | deb | rpm
    uploaded_by: Mapped[Optional[str]] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    deployments: Mapped[list["SoftwareDeployment"]] = relationship(
        back_populates="package", cascade="all, delete-orphan"
    )


# Attach software_packages backref to User cleanly
User.software_packages = relationship(  # type: ignore[attr-defined]
    "SoftwarePackage",
    foreign_keys="[SoftwarePackage.uploaded_by]",
    overlaps="uploaded_by_user",
)


class SoftwareDeployment(Base):
    __tablename__ = "software_deployments"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    package_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("software_packages.id", ondelete="CASCADE"), nullable=False
    )
    target_type: Mapped[str] = mapped_column(String(16), nullable=False)
    target_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    deployed_by: Mapped[Optional[str]] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    deployed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    package: Mapped["SoftwarePackage"] = relationship(back_populates="deployments")
    logs: Mapped[list["SoftwareDeploymentLog"]] = relationship(
        back_populates="deployment", cascade="all, delete-orphan"
    )


class SoftwareDeploymentLog(Base):
    __tablename__ = "software_deployment_logs"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    deployment_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("software_deployments.id", ondelete="CASCADE"), nullable=False
    )
    device_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("devices.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    deployment: Mapped["SoftwareDeployment"] = relationship(back_populates="logs")
    device: Mapped["Device"] = relationship(back_populates="software_deployment_logs")


# ---------------------------------------------------------------------------
# Alerts
# ---------------------------------------------------------------------------

class AlertRule(Base):
    __tablename__ = "alert_rules"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    metric_type: Mapped[str] = mapped_column(String(32), nullable=False)  # cpu | ram | disk | offline
    threshold: Mapped[float] = mapped_column(Float, nullable=False)
    operator: Mapped[str] = mapped_column(String(4), default=">", nullable=False)
    duration_seconds: Mapped[int] = mapped_column(Integer, default=60, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_by: Mapped[Optional[str]] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    created_by_user: Mapped[Optional["User"]] = relationship(back_populates="created_alert_rules")
    alerts: Mapped[list["Alert"]] = relationship(back_populates="rule", cascade="all, delete-orphan")


class Alert(Base):
    __tablename__ = "alerts"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    rule_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("alert_rules.id", ondelete="CASCADE"), nullable=False
    )
    device_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("devices.id", ondelete="CASCADE"), nullable=False
    )
    severity: Mapped[str] = mapped_column(String(16), default="warning", nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="open", nullable=False)
    triggered_value: Mapped[float] = mapped_column(Float, nullable=False)
    triggered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    rule: Mapped["AlertRule"] = relationship(back_populates="alerts")
    device: Mapped["Device"] = relationship(back_populates="alerts")


# ---------------------------------------------------------------------------
# Audit Logs
# ---------------------------------------------------------------------------

class AuditLog(Base):
    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_logs_user_created", "user_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    user_id: Mapped[Optional[str]] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_id: Mapped[Optional[str]] = mapped_column(UUID(as_uuid=False), nullable=True)
    extra_data: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True, name="metadata")
    ip_address: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped[Optional["User"]] = relationship(back_populates="audit_logs")


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------

class Report(Base):
    __tablename__ = "reports"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    report_type: Mapped[str] = mapped_column(String(32), nullable=False)  # daily | weekly | monthly
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    content: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    extra_data: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True, name="metadata")
    generated_by: Mapped[Optional[str]] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    status: Mapped[str] = mapped_column(String(16), default="pending", nullable=False)

    generated_by_user: Mapped[Optional["User"]] = relationship(back_populates="reports")