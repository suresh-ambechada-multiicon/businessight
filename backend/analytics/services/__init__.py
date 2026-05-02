"""
Analytics services package.

Lazy imports to avoid circular dependencies during Django setup.
The logging formatters are imported by Django's logging config before
apps are ready, so we must not trigger model imports at module level.
"""


def __getattr__(name):
    """Lazy import to avoid circular dependency with Django app registry."""
    if name == "process_analytics_query":
        from .core import process_analytics_query
        return process_analytics_query
    if name == "RequestContext":
        from .logger import RequestContext
        return RequestContext
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
