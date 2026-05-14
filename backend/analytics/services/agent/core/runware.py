"""Compatibility facade for Runware analytics integration."""

from analytics.services.runware import (
    invoke_runware_analytics,
    stream_runware_verified_report,
)

__all__ = [
    "invoke_runware_analytics",
    "stream_runware_verified_report",
]
