"""Secure Wi-Fi captive-portal provisioning as a reusable MicroPython package.

The package brings up a locked-down WPA2-only access point, serves a bounded
captive DNS responder and a single-page no-JavaScript HTTP portal, and hands
fully validated requests to a project-supplied handler. Session, DNS, and HTTP
logic are platform-neutral; only the per-chip adapters touch ``network``. The
consuming project never branches by chip and never sees a socket or a bus.

Public API:
    from wifi import Config, Request, Response, Session, ProvisioningError
    from wifi import capabilities, quiesce, create_session

    quiesce()                                  # force interfaces down at boot
    session = create_session(config, handler)  # draws radio-backed credentials
    payload = session.qr_payload()             # render this as the OLED QR
    session.start()                            # bring up the AP + sockets
    event = session.poll(now_ms)               # bounded, nonblocking, per loop
    session.stop()                             # idempotent teardown

``handler(request, csrf_form_value) -> Response`` renders the page and validates
its own route fields; the package owns all HTTP framing, headers, host/origin/CSRF
checks, and credential generation. See README.md for the full contract and limits.
"""

from wifi import adapter
from wifi import config as _config
from wifi import secrets as _secrets
from wifi.config import Config
from wifi.errors import ProvisioningError
from wifi.http import Request, Response
from wifi.session import Session

__all__ = [
    "Config",
    "ProvisioningError",
    "Request",
    "Response",
    "Session",
    "capabilities",
    "create_session",
    "quiesce",
]


def capabilities() -> dict:
    """Return this port's capability dict (see README for the key contract)."""
    return adapter.get().capabilities()


def quiesce() -> None:
    """Idempotently force the AP and station interfaces down and verify.

    Propagates the adapter's ``ProvisioningError`` with code ``network`` if the
    interfaces cannot be confirmed inactive. A no-op on the RP2040 no-op adapter.
    """
    adapter.get().quiesce()


def create_session(config: Config, handler) -> Session:  # noqa: ANN001
    """Validate ``config``, draw radio-backed credentials, and build a session.

    ``handler(request, csrf_form_value) -> Response`` renders the portal page;
    the token is supplied only for rendering the hidden GET form field and must
    never be logged or retained after the call. It carries no type hint —
    MicroPython has no ``typing`` module to name a callable with — which is why
    this docstring keeps its argument notes as prose (see ``secrets.draw``).

    Returns a ``Session`` in the ``NEW`` state whose credentials are already
    drawn, or raises ``ProvisioningError``: ``unsupported`` on a non-Wi-Fi port,
    ``network`` for an invalid config, or ``entropy`` if radio-backed randomness
    cannot be obtained or validated.
    """
    _config.validate(config)
    active_adapter = adapter.get()
    if not active_adapter.SUPPORTED:
        raise ProvisioningError("unsupported")
    session_secrets = _secrets.draw(config.ssid_prefix, active_adapter.random_bytes)
    return Session(config, handler, session_secrets, active_adapter)
