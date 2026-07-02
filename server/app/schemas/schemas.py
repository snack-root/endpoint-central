"""
Pydantic schemas for request/response validation.
"""
from datetime import datetime
from typing import Optional, Any
from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)


class UserOut(BaseModel):
    id: str
    username: str
    email: str
    role: str
    is_active: bool
    created_at: datetime
    last_login: Optional[datetime] = None

    model_config = {"from_attributes": True}


class UserCreate(BaseModel):
    username: str = Field(..., min_length=3, max_length=64)
    email: str = Field(..., min_length=5)  # plain str - internal use only
    password: str = Field(..., min_length=8)
    role: str = "admin"


# ---------------------------------------------------------------------------
# Device (used by agent registration)
# ---------------------------------------------------------------------------

class DeviceRegisterRequest(BaseModel):
    """Sent by agents on first connection or re-registration."""
    device_id: str = Field(..., description="Unique machine identifier")
    hostname: str
    ip_address: Optional[str] = None
    os_type: str = Field(..., pattern="^(windows|linux)$")
    os_version: Optional[str] = None
    username: Optional[str] = None


class DeviceHeartbeatRequest(BaseModel):
    """Sent every 60 seconds."""
    device_id: str
    ip_address: Optional[str] = None
    username: Optional[str] = None
    cpu_percent: Optional[float] = Field(None, ge=0, le=100)
    ram_percent: Optional[float] = Field(None, ge=0, le=100)
    disk_percent: Optional[float] = Field(None, ge=0, le=100)
    ram_total: Optional[int] = None
    disk_total: Optional[int] = None


class DeviceOut(BaseModel):
    id: str
    device_id: str
    hostname: str
    ip_address: Optional[str] = None
    os_type: str
    os_version: Optional[str] = None
    username: Optional[str] = None
    domain_id: Optional[str] = None
    group_id: Optional[str] = None
    status: str
    last_seen: Optional[datetime] = None
    registered_at: datetime

    model_config = {"from_attributes": True}


class DeviceUpdate(BaseModel):
    hostname: Optional[str] = None
    domain_id: Optional[str] = None
    group_id: Optional[str] = None


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

class MetricPoint(BaseModel):
    recorded_at: datetime
    cpu_percent: Optional[float] = None
    ram_percent: Optional[float] = None
    disk_percent: Optional[float] = None

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Domain
# ---------------------------------------------------------------------------

class DomainCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    parent_id: Optional[str] = None
    description: Optional[str] = None


class DomainOut(BaseModel):
    id: str
    name: str
    parent_id: Optional[str] = None
    description: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Group
# ---------------------------------------------------------------------------

class GroupCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    domain_id: Optional[str] = None
    description: Optional[str] = None


class GroupOut(BaseModel):
    id: str
    name: str
    domain_id: Optional[str] = None
    description: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Policy
# ---------------------------------------------------------------------------

class PolicyCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    policy_type: str
    config: dict[str, Any] = Field(default_factory=dict)
    is_active: bool = True


class PolicyOut(BaseModel):
    id: str
    name: str
    policy_type: str
    config: dict[str, Any]
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class PolicyAssignRequest(BaseModel):
    target_type: str = Field(..., pattern="^(domain|group|device)$")
    target_id: str


# ---------------------------------------------------------------------------
# Script
# ---------------------------------------------------------------------------

class ScriptCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    script_type: str = Field(..., pattern="^(powershell|cmd|bash|python)$")
    content: str = Field(..., min_length=1)
    description: Optional[str] = None


class ScriptOut(BaseModel):
    id: str
    name: str
    script_type: str
    content: str
    description: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ScriptDeployRequest(BaseModel):
    target_type: str = Field(..., pattern="^(device|group|domain)$")
    target_id: str


class ScriptExecutionLogOut(BaseModel):
    id: str
    device_id: str
    status: str
    stdout: Optional[str] = None
    stderr: Optional[str] = None
    exit_code: Optional[int] = None
    executed_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Alert Rules
# ---------------------------------------------------------------------------

class AlertRuleCreate(BaseModel):
    name: str = Field(..., min_length=1)
    metric_type: str = Field(..., pattern="^(cpu|ram|disk|offline)$")
    threshold: float = Field(..., ge=0, le=100)
    operator: str = Field(default=">", pattern="^(>|<|>=|<=|==)$")
    duration_seconds: int = Field(default=60, ge=10)
    is_active: bool = True


class AlertRuleOut(BaseModel):
    id: str
    name: str
    metric_type: str
    threshold: float
    operator: str
    duration_seconds: int
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class AlertOut(BaseModel):
    id: str
    rule_id: str
    device_id: str
    severity: str
    status: str
    triggered_value: float
    triggered_at: datetime
    resolved_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

class ReportRequestSchema(BaseModel):
    report_type: str = Field(..., pattern="^(daily|weekly|monthly)$")


class ReportOut(BaseModel):
    id: str
    report_type: str
    title: str
    content: Optional[str] = None
    status: str
    generated_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------

class AuditLogOut(BaseModel):
    id: str
    user_id: Optional[str] = None
    action: str
    resource_type: str
    resource_id: Optional[str] = None
    extra_data: Optional[dict] = None
    ip_address: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Pagination wrapper
# ---------------------------------------------------------------------------

class PaginatedResponse(BaseModel):
    items: list[Any]
    total: int
    page: int
    page_size: int
    pages: int