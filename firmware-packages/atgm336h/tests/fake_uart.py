"""Fake UART for injecting NMEA byte lines into GPS driver tests."""

from __future__ import annotations


class FakeUART:
    """Minimal UART stand-in that replays a fixed list of byte lines."""

    def __init__(self, lines: list[bytes]) -> None:
        """Store the line queue.

        Args:
            lines: Sequence of byte strings to emit in order via readline().
                readline() returns None once the list is exhausted.
        """
        self._lines: list[bytes] = list(lines)

    def readline(self) -> bytes | None:
        """Return the next queued line, or None when the queue is empty."""
        return self._lines.pop(0) if self._lines else None
