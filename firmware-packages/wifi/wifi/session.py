"""The provisioning session: state machine, sockets, and the bounded ``poll``.

A ``Session`` owns at most three sockets — one nonblocking UDP listener, one
nonblocking TCP listener with backlog 1, and one accepted TCP connection — and
does a strictly bounded amount of work per ``poll`` so the caller's render loop
keeps its cadence: at most one DNS datagram and one HTTP read/parse/write step.
Fixed global token buckets cap DNS and HTTP request rates; overload is dropped or
closed immediately. Timeouts and fatal socket failures are reported as terminal
events so the caller tears the session down and rotates credentials.
"""

import time

from wifi import config as _config
from wifi import dns, http
from wifi.errors import ProvisioningError

__all__ = ["ACTIVE", "NEW", "STOPPED", "Session"]

NEW = "NEW"
ACTIVE = "ACTIVE"
STOPPED = "STOPPED"

_CONN_DEADLINE_MS = 2000  # absolute lifetime of one accepted connection
_PROGRESS_DEADLINE_MS = 2000  # max gap between bytes on an accepted connection
_RECV_CHUNK = 600  # bytes read per poll from the accepted connection
_HEAD_LIMIT = http.REQUEST_LINE_MAX + http.HEADER_BYTES_MAX


class _Bucket:
    """A fixed-rate token bucket used to cap DNS and HTTP request rates."""

    def __init__(self, rate_per_s: int, burst: int) -> None:
        self.rate = rate_per_s
        self.burst = burst
        self.tokens = float(burst)
        self.last = None

    def allow(self, now_ms: int) -> bool:
        """Consume one token if available, refilling by elapsed time first."""
        if self.last is None:
            self.last = now_ms
        elapsed = time.ticks_diff(now_ms, self.last)
        if elapsed > 0:
            self.tokens = min(self.burst, self.tokens + elapsed * self.rate / 1000)
            self.last = now_ms
        if self.tokens >= 1:
            self.tokens -= 1
            return True
        return False


class Session:
    """One provisioning session over a single set of credentials.

    Constructed by ``create_session`` in the ``NEW`` state with credentials
    already drawn. ``start`` brings up the AP and sockets; ``poll`` serves DNS and
    HTTP without blocking; ``stop`` is idempotent and always safe to call from a
    cleanup path.
    """

    def __init__(self, cfg, handler, secrets, adapter) -> None:  # noqa: ANN001
        """Store the validated inputs; no radio or socket work happens here."""
        self._config = cfg
        self._handler = handler
        self._secrets = secrets
        self._adapter = adapter
        self.state = NEW
        self._udp = None
        self._tcp = None
        self._conn = None  # (sock, buf, accept_ms, progress_ms)
        self._start_ms = 0
        self._last_client_ms = 0
        self._dns_bucket = _Bucket(20, 40)
        self._http_bucket = _Bucket(4, 8)

    # -- lifecycle ----------------------------------------------------------
    def qr_payload(self) -> str:
        """Return the QR payload; valid only before the session is started."""
        if self.state != NEW:
            raise ProvisioningError("state")
        return self._secrets.qr_payload

    def start(self) -> None:
        """Bring up the AP and sockets, transitioning ``NEW`` -> ``ACTIVE``.

        Refuses to start unless both interfaces are still inactive, so a stale AP
        or half-open station from a soft reset or watchdog cannot be built upon.

        Raises:
            ProvisioningError: ``state`` for an invalid transition, ``network``
                if the interfaces are not inactive, ``capability`` if a required
                capability cannot be proven.
        """
        if self.state != NEW:
            raise ProvisioningError("state")
        if not self._adapter.interfaces_down():
            raise ProvisioningError("network")

        self._adapter.start_ap(
            self._secrets.ssid,
            self._secrets.password,
            self._config.channel,
            self._config.ap_ip,
            self._config.netmask,
        )
        caps = self._adapter.capabilities()
        for key in ("supported", "wpa2_only", "ap_bind", "station_count", "dhcp_dns"):
            if not caps.get(key):
                self._safe_stop_ap()
                raise ProvisioningError("capability")

        self._open_sockets()
        now = time.ticks_ms()
        self._start_ms = now
        self._last_client_ms = now
        self.state = ACTIVE

    def client_count(self) -> int:
        """Return the number of currently associated stations."""
        if self.state != ACTIVE:
            return 0
        try:
            return self._adapter.client_count()
        except Exception:  # noqa: BLE001 - association read must never crash poll
            return 0

    def stop(self) -> None:
        """Tear down sockets and the AP; idempotent and never raises.

        Safe to call from any state and any number of times, so it can anchor a
        ``finally`` cleanup path. Best-effort: the caller verifies teardown (via
        ``quiesce``) separately.
        """
        if self.state == STOPPED:
            return
        self._close_conn()
        for sock in (self._udp, self._tcp):
            if sock is not None:
                try:
                    sock.close()
                except Exception:  # noqa: BLE001
                    pass
        self._udp = None
        self._tcp = None
        self._safe_stop_ap()
        if self._secrets is not None:
            self._secrets.wipe()
            self._secrets = None
        self.state = STOPPED

    def sockets_closed(self) -> bool:
        """Return whether all sockets have been released."""
        return self._udp is None and self._tcp is None and self._conn is None

    # -- polling ------------------------------------------------------------
    def poll(self, now_ms: int) -> str | None:
        """Do one bounded, nonblocking unit of work.

        Returns:
            ``"complete"`` (non-terminal) after a successful configuration POST;
            the terminal ``"absolute_timeout"``, ``"no_client_timeout"``, or
            ``"fatal"`` when the session must be stopped; otherwise ``None``.
        """
        if self.state != ACTIVE:
            return None
        if time.ticks_diff(now_ms, self._start_ms) >= self._config.absolute_timeout_ms:
            return "absolute_timeout"
        if _config.no_client_timeout_enabled(self._config):
            if self.client_count() > 0:
                self._last_client_ms = now_ms
            elif time.ticks_diff(now_ms, self._last_client_ms) >= self._config.no_client_timeout_ms:
                return "no_client_timeout"
        try:
            self._serve_dns(now_ms)
            return self._serve_http(now_ms)
        except _FatalError:
            return "fatal"

    # -- DNS ----------------------------------------------------------------
    def _serve_dns(self, now_ms: int) -> None:
        """Handle at most one DNS datagram this poll."""
        try:
            packet, addr = self._udp.recvfrom(dns.MAX_PACKET)
        except OSError:
            return  # nothing pending (EAGAIN) or a transient receive error
        except Exception:  # noqa: BLE001
            raise _FatalError from None
        if not packet:
            return
        if not self._dns_bucket.allow(now_ms):
            return  # overload: drop silently
        reply = dns.build_response(packet, self._config.ap_ip)
        if reply is not None:
            try:
                self._udp.sendto(reply, addr)
            except OSError:
                pass

    # -- HTTP ---------------------------------------------------------------
    def _serve_http(self, now_ms: int) -> str | None:
        """Accept or advance one HTTP connection; return a poll signal."""
        if self._conn is None:
            self._accept_http(now_ms)
            return None
        return self._advance_http(now_ms)

    def _accept_http(self, now_ms: int) -> None:
        """Accept at most one pending connection, applying the rate limit."""
        try:
            sock, _addr = self._tcp.accept()
        except OSError:
            return  # no pending connection
        except Exception:  # noqa: BLE001
            raise _FatalError from None
        if not self._http_bucket.allow(now_ms):
            try:
                sock.close()
            except Exception:  # noqa: BLE001
                pass
            return
        try:
            sock.setblocking(False)
        except Exception:  # noqa: BLE001
            pass
        self._conn = _Conn(sock, now_ms)

    def _advance_http(self, now_ms: int) -> str | None:
        """Read/parse/respond one step on the accepted connection."""
        conn = self._conn
        if conn is None:
            return None
        buf = conn.buf
        if (
            time.ticks_diff(now_ms, conn.accept_ms) >= _CONN_DEADLINE_MS
            or time.ticks_diff(now_ms, conn.progress_ms) >= _PROGRESS_DEADLINE_MS
        ):
            self._close_conn()
            return None
        try:
            chunk = conn.sock.recv(_RECV_CHUNK)
        except OSError:
            return None  # no data yet
        except Exception:  # noqa: BLE001
            self._close_conn()
            return None
        if chunk:
            buf.extend(chunk)
            conn.progress_ms = now_ms
        elif not buf:
            self._close_conn()  # peer closed with nothing sent
            return None

        end = http.head_end(buf)
        if end < 0:
            if len(buf) > _HEAD_LIMIT:
                self._send_and_close(http.error_response(400))
            return None
        head = http.parse_head(buf[:end])
        if head.error:
            self._send_and_close(http.error_response(head.error))
            return None
        if head.method == "POST" and len(buf) - end < head.content_length:
            return None  # await the rest of the body
        body = bytes(buf[end : end + head.content_length])
        response, completed = http.dispatch(
            head, body, self._config, self._secrets.csrf, self._handler
        )
        self._send_and_close(response)
        return "complete" if completed else None

    # -- socket helpers -----------------------------------------------------
    def _open_sockets(self) -> None:
        """Bind the UDP and TCP listeners to the AP address, nonblocking."""
        import socket  # noqa: PLC0415

        ap_ip = self._config.ap_ip
        try:
            udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            udp.setblocking(False)
            udp.bind((ap_ip, 53))
            tcp = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            tcp.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            tcp.setblocking(False)
            tcp.bind((ap_ip, 80))
            tcp.listen(1)
        except OSError:
            for sock in ("udp", "tcp"):
                candidate = locals().get(sock)
                if candidate is not None:
                    try:
                        candidate.close()
                    except Exception:  # noqa: BLE001
                        pass
            raise ProvisioningError("network") from None
        self._udp = udp
        self._tcp = tcp

    def _send_and_close(self, data: bytes) -> None:
        """Best-effort send the full response, then close the connection."""
        if self._conn is None:
            return
        sock = self._conn.sock
        try:
            view = memoryview(data)
            sent = 0
            while sent < len(view):
                n = sock.send(view[sent:])
                if not n:
                    break
                sent += n
        except OSError:
            pass
        self._close_conn()

    def _close_conn(self) -> None:
        """Close and clear the accepted connection if one is open."""
        if self._conn is not None:
            try:
                self._conn.sock.close()
            except Exception:  # noqa: BLE001
                pass
            self._conn = None

    def _safe_stop_ap(self) -> None:
        """Bring the AP down, swallowing any adapter error."""
        try:
            self._adapter.stop_ap()
        except Exception:  # noqa: BLE001
            pass


class _Conn:
    """The single accepted HTTP connection: its socket, buffer, and deadlines."""

    def __init__(self, sock: object, now_ms: int) -> None:
        """Start an accepted connection with both deadlines at ``now_ms``."""
        self.sock = sock
        self.buf = bytearray()
        self.accept_ms = now_ms
        self.progress_ms = now_ms


class _FatalError(Exception):
    """Internal marker for an unrecoverable socket-infrastructure failure."""
