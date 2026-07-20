"""Wire the shared ``wifi`` provisioning service into the led-effects loop.

The ``Provisioner`` runs provisioning as a continuous background service: it draws
credentials, renders their QR to the OLED, brings up the AP, and drives the
session's bounded ``poll`` once per frame. It rotates credentials every 10 minutes
on the ``absolute_timeout`` signal, tearing the old session down through one
guaranteed cleanup path — zeroing the QR bitmap and wiping secret buffers — before
generating fresh ones. Only the OLED and the LED mode are touched here; the
distance gauge and effects run independently.

The HTTP handler owns only the page content and its route-field validation
(exact fields, ``RRGGBB`` colour, atomic persistence). The ``wifi`` package owns
all HTTP framing, host/origin/CSRF checks, and credential generation.
"""

import settings

import qr_code
import wifi

__all__ = ["PROV_CONFIG", "Provisioner", "hex_to_rgb", "is_hex6"]

# The provisioning configuration. absolute_timeout_ms drives the 10-minute
# rotation; the no-client timeout is disabled so the AP never stops on its own.
PROV_CONFIG = wifi.Config(
    ssid_prefix="LEDFX-",
    ap_ip="192.168.4.1",
    netmask="255.255.255.0",
    channel=6,
    local_hostname="led-effects.test",
    absolute_timeout_ms=600000,
    no_client_timeout_ms=0,
)

_QUIET = 4  # QR quiet-zone width in modules; 33 + 2*4 = the fixed 41x41 bitmap
_HEXCHARS = "0123456789ABCDEF"

# Self-contained, no-JavaScript, no-CSS pages. The strict CSP has no style-src,
# so there is no <style> block and no style attributes anywhere.
_PAGE = (
    '<!doctype html><html><head><meta charset="utf-8">'
    '<meta name="viewport" content="width=device-width, initial-scale=1">'
    "<title>LED effects</title></head><body>"
    "<h1>LED effects</h1>"
    '<form method="POST" action="/color">'
    '<input type="hidden" name="csrf" value="{csrf}">'
    "<p><label>Colour (RRGGBB): "
    '<input type="text" name="color" maxlength="6" size="6"></label></p>'
    '<p><button type="submit">Set colour</button></p>'
    "</form>"
    '<form method="POST" action="/random">'
    '<input type="hidden" name="csrf" value="{csrf}">'
    '<p><button type="submit">Random effects</button></p>'
    "</form>"
    "</body></html>"
)
_OK = (
    '<!doctype html><html><head><meta charset="utf-8">'
    "<title>Applied</title></head><body><h1>Applied</h1>"
    '<p><a href="/">Back</a></p></body></html>'
)
_DENIED = (
    '<!doctype html><html><head><meta charset="utf-8">'
    "<title>Rejected</title></head><body><h1>Rejected</h1>"
    '<p><a href="/">Back</a></p></body></html>'
)


def is_hex6(value: object) -> bool:
    """Return whether ``value`` is a 6-character uppercase hex colour string."""
    return isinstance(value, str) and len(value) == 6 and all(ch in _HEXCHARS for ch in value)


def hex_to_rgb(value: str) -> tuple:
    """Convert an ``RRGGBB`` uppercase hex string to an ``(r, g, b)`` tuple."""
    return (int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16))


def _escape(value: str) -> str:
    """HTML-escape a dynamic value before inserting it into the page."""
    return (
        value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    )


class Provisioner:
    """Owns the provisioning session lifecycle and the OLED QR for one boot."""

    def __init__(self, config, display, led_state, emit) -> None:  # noqa: ANN001
        """Store dependencies; no radio or OLED work happens until ``begin``."""
        self._config = config
        self._display = display
        self._led = led_state
        self._emit = emit
        self._session = None
        self.enabled = False

    # -- lifecycle ----------------------------------------------------------
    def begin(self) -> None:
        """Draw the first credentials, render the QR, and start the AP.

        On any provisioning, QR, or OLED failure, provisioning is left disabled
        for the boot; the caller keeps running effects and the gauge.
        """
        try:
            self._new_session()
            self.enabled = True
        except wifi.ProvisioningError as err:
            self._emit({"diag": "wifi_disabled", "code": err.code})
            self._quiet_teardown()
        except (OSError, RuntimeError, ValueError, qr_code.QRError):
            self._emit({"diag": "wifi_oled_fail"})
            self._quiet_teardown()
            self._blank_oled()

    def poll(self, now_ms: int) -> None:
        """Advance the session once; rotate or disable on a terminal event."""
        if not self.enabled or self._session is None:
            return
        event = self._session.poll(now_ms)
        if event is None:
            return
        if event == "complete":
            self._emit({"diag": "wifi_config"})
            return
        # absolute_timeout (rotation), no_client_timeout, or fatal: rebuild.
        self._emit({"diag": "wifi_rotate", "reason": event})
        self._rotate()

    def stop(self) -> None:
        """Final teardown: stop the session and blank the OLED."""
        self._quiet_teardown()
        self._blank_oled()
        self.enabled = False

    # -- internal -----------------------------------------------------------
    def _new_session(self) -> None:
        """Create a session, render its QR, and start it (drawing QR first)."""
        session = wifi.create_session(self._config, self._handler)
        try:
            self._draw_qr(session.qr_payload())  # a draw failure prevents start
            session.start()
        except BaseException:
            try:
                session.stop()  # wipe freshly drawn secrets, ensure down
            except Exception:  # noqa: BLE001
                pass
            raise
        self._session = session
        self._emit({"diag": "wifi_up"})

    def _rotate(self) -> None:
        """Tear the current session down, then build a fresh one."""
        self._teardown()
        try:
            self._new_session()
        except wifi.ProvisioningError as err:
            self._emit({"diag": "wifi_disabled", "code": err.code})
            self._quiet_teardown()
            self.enabled = False
        except (OSError, RuntimeError, ValueError, qr_code.QRError):
            self._emit({"diag": "wifi_oled_fail"})
            self._quiet_teardown()
            self._blank_oled()
            self.enabled = False

    def _teardown(self) -> None:
        """Guaranteed cleanup between sessions: stop, verify, scrub the bitmap.

        The next session redraws the QR immediately, so the OLED is not blanked
        here — only the secret-bearing framebuffer is zeroed.
        """
        try:
            if self._session is not None:
                self._session.stop()
        finally:
            self._session = None
            self._zero_bitmap()
            try:
                wifi.quiesce()
            except wifi.ProvisioningError:
                pass

    def _quiet_teardown(self) -> None:
        """Stop the session and force interfaces down without touching the OLED."""
        try:
            if self._session is not None:
                self._session.stop()
        finally:
            self._session = None
            try:
                wifi.quiesce()
            except wifi.ProvisioningError:
                pass

    # -- OLED ---------------------------------------------------------------
    def _draw_qr(self, payload: str) -> None:
        """Render the fixed 41x41 QR (33 modules + 4-module quiet zone) centred.

        The framed code is drawn as a lit (light) background with the dark
        modules unlit, so a camera sees correct QR polarity on the OLED.

        Raises:
            ValueError: If the framed size is not exactly 41x41 or does not fit.
        """
        grid = qr_code.encode(payload)
        modules = qr_code.SIZE
        dim = modules + 2 * _QUIET
        if dim != 41:
            raise ValueError("unexpected qr size")
        display = self._display
        width = display.width
        height = display.height
        if dim > width or dim > height:
            raise ValueError("qr does not fit")
        bx = (width - dim) // 2
        by = (height - dim) // 2
        display.fill(0)
        for yy in range(dim):
            for xx in range(dim):
                display.pixel(bx + xx, by + yy, 1)
        for y in range(modules):
            row = grid[y]
            oy = by + _QUIET + y
            for x in range(modules):
                if row[x]:
                    display.pixel(bx + _QUIET + x, oy, 0)
        display.show()

    def _zero_bitmap(self) -> None:
        """Zero the OLED framebuffer so the old QR's secrets do not linger."""
        try:
            self._display.fill(0)
        except Exception:  # noqa: BLE001
            pass

    def _blank_oled(self) -> None:
        """Best-effort clear and flush the OLED."""
        try:
            self._display.fill(0)
            self._display.show()
        except Exception:  # noqa: BLE001
            pass

    # -- HTTP handler -------------------------------------------------------
    def _handler(self, request, csrf_form_value: str) -> object:  # noqa: ANN001
        """Serve the page and apply validated colour / random requests.

        The ``wifi`` package has already validated HTTP framing, host, origin,
        and the CSRF token; this only checks the exact route fields and persists.
        """
        if request.method == "GET":
            return wifi.Response(200, _PAGE.format(csrf=_escape(csrf_form_value)))
        if request.path == "/color":
            return self._apply_color(request.form)
        return self._apply_random(request.form)

    def _apply_color(self, form: dict) -> object:
        """Validate and persist a solid-colour request; read-only on failure."""
        if set(form.keys()) != {"csrf", "color"} or not is_hex6(form["color"]):
            return wifi.Response(400, _DENIED)
        record = settings.save("solid", form["color"])
        if record is None:  # persistence failed: change nothing
            return wifi.Response(500, _DENIED)
        self._led.apply(record)
        return wifi.Response(200, _OK, terminal=True)

    def _apply_random(self, form: dict) -> object:
        """Validate and persist a random-mode request; read-only on failure."""
        if set(form.keys()) != {"csrf"}:
            return wifi.Response(400, _DENIED)
        record = settings.save("random")
        if record is None:
            return wifi.Response(500, _DENIED)
        self._led.apply(record)
        return wifi.Response(200, _OK, terminal=True)
