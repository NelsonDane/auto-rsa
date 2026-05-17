"""Thread-safe stdout sink for capturing broker script output.

The existing scripts communicate exclusively via ``print``. The runner
redirects stdout into this sink so the GUI can stream the same output that
the CLI/Discord users see.
"""

from __future__ import annotations

import threading


class LogStream:
    """A minimal file-like object accumulating text for the UI to read."""

    def __init__(self) -> None:
        """Create an empty, thread-safe log buffer."""
        self._lock = threading.Lock()
        self._buffer: list[str] = []

    def write(self, text: str) -> int:
        """File-like write; also accepts non-str defensively."""
        if not isinstance(text, str):
            text = str(text)
        with self._lock:
            self._buffer.append(text)
        return len(text)

    def flush(self) -> None:
        """No-op; present for file-like compatibility."""

    @staticmethod
    def isatty() -> bool:
        """Never a TTY (keeps libraries from emitting ANSI control codes)."""
        return False

    def getvalue(self) -> str:
        """Return the full captured log so far."""
        with self._lock:
            return "".join(self._buffer)

    def clear(self) -> None:
        """Reset the captured log."""
        with self._lock:
            self._buffer.clear()
