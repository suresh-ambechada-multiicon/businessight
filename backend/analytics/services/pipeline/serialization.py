"""Serialization helpers for pipeline outputs and token accounting."""

from __future__ import annotations

from decimal import Decimal


def sanitize_row(row):
    if not isinstance(row, dict):
        return row
    clean = {}
    for key, value in row.items():
        if isinstance(value, (bytes, memoryview)):
            clean[key] = "(binary data)"
        elif isinstance(value, Decimal):
            clean[key] = float(value)
        elif hasattr(value, "isoformat"):
            clean[key] = value.isoformat()
        elif isinstance(value, (str, int, float, bool)) or value is None:
            clean[key] = value
        else:
            clean[key] = str(value)
    return clean


def sanitize_for_tokens(obj):
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, Decimal):
        return float(obj)
    if hasattr(obj, "isoformat"):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {key: sanitize_for_tokens(value) for key, value in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [sanitize_for_tokens(item) for item in obj]
    return str(obj)

