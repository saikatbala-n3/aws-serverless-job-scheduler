import json
from typing import Any


def api_response(status_code: int, body: Any, headers: dict = None):
    """Build and API Gateway proxy response with CORS headers and JSON-serialized body."""
    default_headers = {
        "Content-Type": "application/json",
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Headers": "Content-Type,Authorization",
        "Access-Control-Allow-Methods": "GET,POST,DELETE,OPTIONS",
    }
    if headers:
        default_headers.update(headers)
    return {
        "statusCode": status_code,
        "headers": default_headers,
        "body": json.dumps(body, default=str),
    }


def error_response(status_code: int, message: str, details: Any = None):
    """Build an error response with optional details for debugging."""
    body = {"error": message}
    if details:
        body["details"] = details
    return api_response(status_code, body)
