"""Framework-neutral 2FA / interactive prompt bus.

The engine runs in a child process. When a broker calls ``input()`` for
an OTP / SMS / CAPTCHA code, the child emits a sentinel line; the
runner's reader thread calls :meth:`open` here, the view layer shows the
prompt and calls :meth:`respond`, and the reader thread (blocked in
:meth:`wait_answer`) forwards the answer to the child's stdin.

This is intentionally not coupled to any UI. Streamlit polls
:meth:`snapshot`; a future FastAPI layer could push it over a WebSocket.
"""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PromptSnapshot:
    """Immutable view of the current prompt state for the UI."""

    waiting: bool
    prompt_id: str
    text: str


class PromptBus:
    """Single-slot request/response channel between reader and UI threads."""

    def __init__(self) -> None:
        """Create an idle prompt bus with no pending request."""
        self._lock = threading.Lock()
        self._event = threading.Event()
        self._waiting = False
        self._prompt_id = ""
        self._text = ""
        self._response: str = ""

    def open(self, text: str) -> None:
        """Register a pending prompt (called by the runner reader thread)."""
        with self._lock:
            self._waiting = True
            self._prompt_id = uuid.uuid4().hex
            self._text = text or "Input required"
            self._response = ""
            self._event.clear()

    def wait_answer(self) -> str:
        """Block until the UI responds; return the answer (reader thread)."""
        self._event.wait()
        with self._lock:
            self._waiting = False
            return self._response

    def snapshot(self) -> PromptSnapshot:
        """Non-blocking view of whether a prompt is awaiting a response."""
        with self._lock:
            return PromptSnapshot(self._waiting, self._prompt_id, self._text)

    def respond(self, prompt_id: str, response: str) -> bool:
        """Deliver the UI's answer; return True if it unblocked a waiter.

        ``prompt_id`` guards against a UI rerun submitting the same answer
        twice (Streamlit reruns the whole script on every interaction).
        """
        with self._lock:
            if not self._waiting or prompt_id != self._prompt_id:
                return False
            self._response = response
            self._event.set()
            return True

    def cancel(self) -> None:
        """Unblock any waiting reader with an empty answer (run aborted)."""
        with self._lock:
            if self._waiting:
                self._response = ""
                self._event.set()
