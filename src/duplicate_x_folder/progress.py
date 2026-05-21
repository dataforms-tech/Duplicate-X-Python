from __future__ import annotations

import sys
import time
from dataclasses import dataclass
from typing import Optional


@dataclass
class Progress:
    enabled: bool = True
    min_interval_s: float = 0.2
    _last_emit: float = 0.0
    _last_line_len: int = 0
    _stream: object = sys.stderr

    def update(self, message: str, *, force: bool = False) -> None:
        if not self.enabled:
            return

        now = time.monotonic()
        if not force and (now - self._last_emit) < self.min_interval_s:
            return

        self._last_emit = now
        stream = self._stream  # type: ignore[assignment]
        is_tty = getattr(stream, "isatty", lambda: False)()
        if is_tty:
            padded = message.ljust(self._last_line_len)
            self._last_line_len = max(self._last_line_len, len(message))
            stream.write("\r" + padded)
            stream.flush()
        else:
            stream.write(message + "\n")
            stream.flush()

    def done(self, message: Optional[str] = None) -> None:
        if not self.enabled:
            return
        if message is not None:
            self.update(message, force=True)
        stream = self._stream  # type: ignore[assignment]
        is_tty = getattr(stream, "isatty", lambda: False)()
        if is_tty:
            stream.write("\n")
            stream.flush()
