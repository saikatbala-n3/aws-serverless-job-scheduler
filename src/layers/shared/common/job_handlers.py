import time
import random


def get_handler(job_type: str):
    """Route a job type string to its handler function. Raises ValueError for unknown types."""
    handlers = {
        "email": handle_email_job,
        "data_processing": handle_data_processing_job,
        "report": handle_report_job,
        "webhook": handle_webhook_job,
        "cleanup": handle_cleanup_job,
    }
    handler = handlers.get(job_type)
    if not handler:
        raise ValueError(f"Unknown job type: {job_type}")
    return handler


def handle_email_job(payload: dict) -> dict:
    """Simulate email delivery. 5% failure rate to exercise retry/DLQ path."""
    time.sleep(random.uniform(0.5, 2))
    if random.random() < 0.05:
        raise Exception("SMTP connection failed")
    return {
        "sent": True,
        "recipient": payload.get("recipient"),
        "message_id": f"msg_{random.randint(1000, 9999)}",
    }


def handle_data_processing_job(payload: dict) -> dict:
    """Simulate data processing. Duration scales with data_size, capped at 5s."""
    time.sleep(min(payload.get("data_size", 100) / 100, 5))
    return {"processed": True, "records_processed": payload.get("data_size", 100)}


def handle_report_job(payload: dict) -> dict:
    """Simulate report generation with 2-5s processing delay."""
    time.sleep(random.uniform(2, 5))
    return {"generated": True, "report_type": payload.get("report_type", "daily")}


def handle_webhook_job(payload: dict) -> dict:
    """Simulate webhook delivery. 10% failure rate to exercise retry logic."""
    time.sleep(random.uniform(0.5, 1.5))
    if random.random() < 0.1:
        raise Exception("Webhook delivery failed")
    return {"delivered": True, "url": payload.get("url"), "status_code": 200}


def handle_cleanup_job(payload: dict) -> dict:
    """Simulate resource cleanup with randomized item removal count."""
    time.sleep(random.uniform(1, 3))
    return {"cleaned": True, "items_removed": random.randint(10, 100)}