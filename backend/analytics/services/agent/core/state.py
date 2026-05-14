"""Shared mutable state for one agent stream."""


class StreamResult:
    """Mutable container for streaming results. One per request — thread-safe."""

    def __init__(self):
        self.data: dict = {}
        self.has_error: bool = False
        self.cancelled: bool = False
        self.trace: list[dict] = []