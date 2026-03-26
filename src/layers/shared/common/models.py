from enum import Enum
from datetime import datetime, timezone
from typing import Any, Optional
from pydantic import BaseModel, Field
import uuid


class JobStatus(str, Enum):
    """Job lifecycle states. Transitions: PENDING -> PROCESSING -> COMPLETED|FAILED|CANCELLED."""

    FAILED = "FAILED"
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"


class JobType(str, Enum):
    """Supported job types. Each maps to a handler function in job_handlers.py."""

    EMAIL = "email"
    DATA_PROCESSING = "data_processing"
    REPORT = "report"
    WEBHOOK = "webhook"
    CLEANUP = "cleanup"


class JobCreate(BaseModel):
    """API request schema for job submission. Validated by Pydantic before DynamoDB write."""

    job_type: JobType
    payload: dict[str, Any]
    priority: str = Field(default="normal", pattern="^(low|normal|high)$")
    max_retries: int = Field(default=3, ge=0, le=10)


class Job(BaseModel):
    """Core job model. Serves as the application-level data contract for DynamoDB items.

    Handles serialization (to_dynamodb_item) and deserialization (from_dynamodb_item)
    including GSI key generation for status-index and type-index queries.
    """

    job_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    job_type: JobType
    status: JobStatus = JobStatus.PENDING  # Default added as per guidelines
    priority: str = "normal"
    payload: dict[str, Any]
    result: Optional[dict[str, Any]] = None
    error: Optional[str] = None
    retry_count: int = 0
    max_retries: int = 3
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat() + "Z"
    )
    updated_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat() + "Z"
    )
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    ttl: Optional[int] = None

    def to_dynamodb_item(self):
        """Convert to DynamoDB item dict, adding GSI partition/sort keys for query access patterns."""

        item = {
            "job_id": self.job_id,
            "job_type": self.job_type.value,
            "status": self.status.value,
            "priority": self.priority,
            "payload": self.payload,
            "retry_count": self.retry_count,
            "max_retries": self.max_retries,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "GSI1PK": self.status.value,
            "GSI1SK": self.created_at,
            "GSI2PK": self.job_type.value,
            "GSI2SK": self.created_at,
        }
        for key in ["result", "error", "started_at", "completed_at", "ttl"]:
            if getattr(self, key) is not None:
                item[key] = getattr(self, key)
        return item

    @classmethod
    def from_dynamodb_item(cls, item: dict) -> "Job":
        """Reconstruct a Job from a raw DynamoDB item, handling optional fields with defaults."""

        return cls(
            job_id=item["job_id"],
            job_type=JobType(item["job_type"]),
            status=JobStatus(item["status"]),
            priority=item.get("priority", "normal"),
            payload=item["payload"],
            result=item.get("result"),
            error=item.get("error"),
            retry_count=item.get("retry_count", 0),
            max_retries=item.get("max_retries", 3),
            created_at=item["created_at"],
            updated_at=item["updated_at"],
            started_at=item.get("started_at"),
            completed_at=item.get("completed_at"),
            ttl=item.get("ttl"),
        )


class SQSJobMessage(BaseModel):
    """Lightweight message schema for SQS queue. Contains only fields needed by the worker."""

    job_id: str
    job_type: str
    payload: dict[str, Any]
    retry_count: int = 0
    max_retries: int = 3
