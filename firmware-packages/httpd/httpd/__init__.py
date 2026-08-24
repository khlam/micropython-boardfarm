"""Public interface for the firmware HTTP and WebSocket server."""

from httpd.server import Server
from httpd.websocket import Broadcast

__all__ = ["Broadcast", "Server"]
