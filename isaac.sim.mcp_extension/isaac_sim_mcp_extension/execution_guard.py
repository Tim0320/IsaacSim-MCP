"""Bounded, cooperatively timed execution helpers for the script escape hatch."""

from __future__ import annotations

import io
import sys
import time
from contextlib import contextmanager
from typing import Iterator


class ScriptExecutionTimeout(TimeoutError):
    pass


class ScriptOutputLimitExceeded(RuntimeError):
    pass


class BoundedTextBuffer(io.StringIO):
    def __init__(self, max_bytes: int) -> None:
        super().__init__()
        self.max_bytes = int(max_bytes)
        self.bytes_written = 0

    def write(self, value: str) -> int:
        encoded = value.encode("utf-8", errors="replace")
        if self.bytes_written + len(encoded) > self.max_bytes:
            remaining = self.max_bytes - self.bytes_written
            if remaining > 0:
                prefix = encoded[:remaining].decode("utf-8", errors="ignore")
                super().write(prefix)
                self.bytes_written += len(prefix.encode("utf-8"))
            raise ScriptOutputLimitExceeded(f"script output exceeded {self.max_bytes} bytes")
        self.bytes_written += len(encoded)
        return super().write(value)


@contextmanager
def cooperative_deadline(timeout_s: float) -> Iterator[None]:
    """Interrupt Python bytecode after the deadline and always restore tracing.

    Native calls cannot be pre-empted safely inside Kit. The trace fires as soon
    as Python control returns, preventing further Python or stage mutation.
    """

    deadline = time.monotonic() + float(timeout_s)
    previous_trace = sys.gettrace()

    def trace(frame, event, arg):
        if time.monotonic() >= deadline:
            raise ScriptExecutionTimeout(f"script exceeded timeout_s={timeout_s:g}")
        return trace

    sys.settrace(trace)
    traced_frames = []
    frame = sys._getframe().f_back
    while frame is not None:
        traced_frames.append((frame, frame.f_trace))
        frame.f_trace = trace
        frame = frame.f_back
    try:
        yield
    finally:
        for frame, old_frame_trace in traced_frames:
            frame.f_trace = old_frame_trace
        sys.settrace(previous_trace)
