"""Framework-neutral 2FA / interactive prompt bus.

Existing broker scripts call ``input("Enter code: ")`` for OTP / SMS /
CAPTCHA codes when no Discord bot is present. The runner patches
``builtins.input`` to route those calls here: the worker thread blocks in
:meth:`request` until the view layer calls :meth:`respond`.

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
    """Single-slot request/response channel between worker and UI threads."""

    def __init__(self) -> None:
        """Create an idle prompt bus with no pending request."""
        self._lock = threading.Lock()
        self._event = threading.Event()
        self._waiting = False
        self._prompt_id = ""
        self._text = ""
        self._response: str = ""

    def request(self, text: str) -> str:
        """Block the worker thread (patched ``input``) until a UI response."""
        with self._lock:
            self._waiting = True
            self._prompt_id = uuid.uuid4().hex
            self._text = text or "Input required"
            self._response = ""
            self._event.clear()
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
        """Unblock any waiting worker with an empty answer (run abort)."""
        with self._lock:
            if self._waiting:
                self._response = ""
                self._event.set()
