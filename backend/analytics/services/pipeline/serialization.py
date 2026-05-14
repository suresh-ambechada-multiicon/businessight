"""Serialization helpers for pipeline outputs and token accounting."""

from __future__ import annotations

from decimal import Decimal


def deep_sanitize(obj):
    """
    Recursively convert non-JSON-serializable objects to serializable formats.
    Handles Decimals, datetimes, binary data, etc.
    """
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, (bytes, memoryview)):
        return "(binary data)"
    if isinstance(obj, Decimal):
        return float(obj)
    if hasattr(obj, "isoformat"):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {str(k): deep_sanitize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [deep_sanitize(i) for i in obj]
    return str(obj)


def sanitize_row(row):
    """Sanitize a single database row dictionary."""
    if not isinstance(row, dict):
        return deep_sanitize(row)
    return {str(key): deep_sanitize(value) for key, value in row.items()}


def sanitize_for_tokens(obj):
    """Alias for deep_sanitize for backward compatibility in naming."""
    return deep_sanitize(obj)

