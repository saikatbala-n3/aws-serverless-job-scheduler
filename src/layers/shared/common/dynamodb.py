import os
import boto3
from boto3.dynamodb.conditions import Key
from datetime import datetime, timezone
from typing import Optional
from aws_xray_sdk.core import patch_all
from .models import Job, JobStatus

patch_all()


class JobsRepository:
    """Data access layer for the Jobs DynamoDB table.

    Encapsulates all DynamoDB operations with X-Ray tracing via patch_all().
    Uses GSI single-table patterns: GSI1 (status-index), GSI2 (type-index).
    """

    def __init__(self, table_name: Optional[str] = None):
        endpoint = os.environ.get("DYNAMODB_ENDPOINT")
        self.dynamodb = boto3.resource("dynamodb", endpoint_url=endpoint) if endpoint else boto3.resource("dynamodb")
        self.table_name = table_name or os.environ.get("JOBS_TABLE")
        self.table = self.dynamodb.Table(self.table_name)

    def create_job(self, job: Job):
        """Persist a new job. Uses put_item (overwrites if job_id exists)."""
        self.table.put_item(Item=job.to_dynamodb_item())
        return job

    def get_job(self, job_id: str):
        """Fetch a single job by partition key. Returns None if not found."""
        response = self.table.get_item(Key={"job_id": job_id})
        item = response.get("Item")
        return Job.from_dynamodb_item(item) if item else None

    def update_job_status(
        self,
        job_id: str,
        status: JobStatus,
        error: Optional[str] = None,
        result: Optional[dict] = None,
    ):
        """Atomically updates job status, timestamps and GSI keys. Returns updated job."""

        now = datetime.now(timezone.utc).isoformat() + "Z"
        update_expr = "SET #status = :status, updated_at = :now, GSI1PK = :status"
        expr_values = {":status": status.value, ":now": now}
        expr_names = {"#status": "status"}

        if status == JobStatus.PROCESSING:
            update_expr += ", started_at = :now"
        if status in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED):
            update_expr += ", completed_at = :now"
        if error:
            update_expr += ", #error = :error"
            expr_values[":error"] = error
            expr_names["#error"] = "error"
        if result:
            update_expr += ", #result = :result"
            expr_values[":result"] = result
            expr_names["#result"] = "result"

        response = self.table.update_item(
            Key={"job_id": job_id},
            UpdateExpression=update_expr,
            ExpressionAttributeNames=expr_names,
            ExpressionAttributeValues=expr_values,
            ReturnValues="ALL_NEW",
        )
        return Job.from_dynamodb_item(response["Attributes"])

    def list_jobs_by_status(
        self, status: JobStatus, limit: int = 50
    ):  # Corrected from list_job_by_status
        """Query GSI1 (status-index) for jobs with a given status, newest first."""
        response = self.table.query(
            IndexName="status-index",
            KeyConditionExpression=Key("GSI1PK").eq(
                status.value
            ),  # Corrected Key("GSI1PK".eq(status.value))
            ScanIndexForward=False,
            Limit=limit,
        )
        return [Job.from_dynamodb_item(item) for item in response.get("Items", [])]

    def list_jobs_by_type(
        self, job_type: str, limit: int = 50
    ):  # Corrected from list_job_by_type
        """Query GSI2 (type-index) for jobs with a given type, newest first."""
        response = self.table.query(
            IndexName="type-index",
            KeyConditionExpression=Key("GSI2PK").eq(
                job_type
            ),  # Corrected Key("GSI2PK".eq(job_type))
            ScanIndexForward=False,
            Limit=limit,
        )
        return [Job.from_dynamodb_item(item) for item in response.get("Items", [])]

    def cancel_job(self, job_id: str):
        """Cancel a PENDING job using a conditional update. Returns None if job is already processing."""
        now = datetime.now(timezone.utc).isoformat() + "Z"
        try:
            response = self.table.update_item(
                Key={"job_id": job_id},  # Added missing Key parameter
                UpdateExpression="SET #status = :cancelled, updated_at = :now, completed_at = :now, GSI1PK = :cancelled",
                ConditionExpression="#status = :pending",
                ExpressionAttributeNames={"#status": "status"},
                ExpressionAttributeValues={
                    ":cancelled": JobStatus.CANCELLED.value,
                    ":pending": JobStatus.PENDING.value,
                    ":now": now,
                },
                ReturnValues="ALL_NEW",
            )
            return Job.from_dynamodb_item(response["Attributes"])
        except self.dynamodb.meta.client.exceptions.ConditionalCheckFailedException:
            return None
