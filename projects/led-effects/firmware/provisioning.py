"""Wire the shared ``wifi`` provisioning service into the led-effects loop.

The ``Provisioner`` runs provisioning as a continuous background service: it
pre-renders the credential QR off-screen, brings up the AP, and drives the
session's bounded ``poll`` once per frame. It rotates credentials every 10 minutes
on the ``absolute_timeout`` signal, tearing the old session down through one
guaranteed cleanup path — zeroing the QR bitmap and wiping secret buffers — before
generating fresh ones.

The QR itself is shown only while the caller asks for it, via ``show_qr`` and
``hide_qr``; the OLED is blank the rest of the time. led-effects ties that to the
distance gauge, so the credentials are readable only while someone is standing at
the device working the sensor. The AP runs regardless — hiding the QR narrows who
can *learn* the credentials, not who may keep using ones already read.

Encoding a QR is expensive, so ``prerender`` builds the code into an off-screen
framebuffer from the loop's idle path — once per session, never on the lock
transition that reveals it — leaving ``show_qr`` to do nothing but blit and flush,
so engaging the gauge feels instant.

The HTTP handler owns only the page content and its route-field validation
(exact fields, ``RRGGBB`` colour, atomic persistence). The ``wifi`` package owns
all HTTP framing, host/origin/CSRF checks, and credential generation.
"""

import framebuf
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
        # The live session's QR payload, kept so the code can be redrawn on
        # demand. It is dropped on every teardown, before the next session's
        # secrets are drawn; MicroPython cannot erase an immutable string, so
        # releasing the reference is as far as this can go.
        self._payload = None
        # Off-screen framebuffer the QR is pre-rendered into so show_qr() is a
        # single blit + flush rather than an encode. It holds the live session's
        # credentials as a bitmap for the same lifetime as _payload above, and is
        # zeroed on every teardown before the next session's secrets are drawn.
        self._scratch = framebuf.FrameBuffer(
            bytearray(display.width * display.height // 8),
            display.width,
            display.height,
            framebuf.MONO_VLSB,
        )
        self._rendered_payload = None
        self._visible = False
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
            self._disable({"diag": "wifi_disabled", "code": err.code})
        except Exception as err:  # noqa: BLE001 - see _disable
            self._disable({"diag": "wifi_fail", "err": type(err).__name__})

    def poll(self, now_ms: int) -> None:
        """Advance the session once; rotate or disable on a terminal event."""
        if not self.enabled or self._session is None:
            return
        try:
            event = self._session.poll(now_ms)
        except Exception as err:  # noqa: BLE001 - see _disable
            self._disable({"diag": "wifi_fail", "err": type(err).__name__})
            return
        if event is None:
            return
        if event == "complete":
            self._emit({"diag": "wifi_config"})
            return
        # absolute_timeout (rotation), no_client_timeout, or fatal: rebuild.
        self._emit({"diag": "wifi_rotate", "reason": event})
        self._rotate()

    def show_qr(self) -> None:
        """Blit the live credentials' QR to the panel, if provisioning is running.

        Idempotent, and a no-op when provisioning is disabled — the OLED then
        simply stays blank. The code is normally already rendered off-screen by
        ``prerender`` running in the loop's idle path, so this is a single blit; if
        a lock lands before that background render finished, it renders here as a
        fallback. A render or flush failure disables provisioning for the boot
        rather than leaving a half-drawn or stale code on the panel: a QR the
        display cannot be trusted to have rendered cannot be trusted to match the
        credentials the AP is actually using.
        """
        if self._visible or not self.enabled or self._payload is None:
            return
        try:
            if self._rendered_payload != self._payload:
                self._render_qr(self._payload)  # background render has not run yet
            self._blit_qr()
        except Exception as err:  # noqa: BLE001 - see _disable
            self._disable({"diag": "wifi_fail", "err": type(err).__name__})
            return
        self._visible = True

    def prerender(self) -> None:
        """Pre-render the live QR off-screen so ``show_qr`` never has to encode.

        Driven once per loop tick from the render loop's idle path. It does real
        work — the QR encode and pixel plot for the current credentials — only on
        the first call after a session comes up (or after a rotation), then
        early-returns until the credentials change. Keeping that cost here, off the
        lock transition that reveals the QR, is what makes engaging the gauge feel
        instant. A failure disables provisioning for the boot.
        """
        if not self.enabled or self._payload is None or self._rendered_payload == self._payload:
            return
        try:
            self._render_qr(self._payload)
        except Exception as err:  # noqa: BLE001 - see _disable
            self._disable({"diag": "wifi_fail", "err": type(err).__name__})

    def hide_qr(self) -> None:
        """Blank the OLED and stop showing the QR. Idempotent."""
        if not self._visible:
            return
        self._visible = False
        self._blank_oled()

    def stop(self) -> None:
        """Final teardown: stop the session and blank the OLED."""
        self._quiet_teardown()
        self._blank_oled()
        self._visible = False
        self.enabled = False

    # -- internal -----------------------------------------------------------
    def _new_session(self) -> None:
        """Create a session, start it, and redraw the QR if it is on screen.

        The payload is taken before ``start`` because the session releases it on
        leaving the ``NEW`` state. When the QR is visible it is redrawn first, so
        a draw failure prevents the AP from coming up at all; when it is hidden
        nothing is drawn — the code is pre-rendered off-screen in the background
        instead (``prerender``).
        """
        session = wifi.create_session(self._config, self._handler)
        try:
            payload = session.qr_payload()
            if self._visible:
                self._render_qr(payload)
                self._blit_qr()  # a flush failure prevents start
            session.start()
        except BaseException:
            try:
                session.stop()  # wipe freshly drawn secrets, ensure down
            except Exception:  # noqa: BLE001
                pass
            raise
        self._session = session
        self._payload = payload
        self._emit({"diag": "wifi_up"})

    def _rotate(self) -> None:
        """Tear the current session down, then build a fresh one."""
        self._teardown()
        try:
            self._new_session()
        except wifi.ProvisioningError as err:
            self._disable({"diag": "wifi_disabled", "code": err.code})
        except Exception as err:  # noqa: BLE001 - see _disable
            self._disable({"diag": "wifi_fail", "err": type(err).__name__})

    def _disable(self, diag: dict) -> None:
        """Report ``diag``, tear everything down, and stay off for the boot.

        Provisioning is a background service layered onto the render loop, so no
        failure inside it may propagate: a stray exception here would otherwise
        stop the LEDs and the gauge as well. The diagnostic carries the exception
        *class* name only — enough to identify a firmware fault over serial,
        never enough to expose a credential, address, or token.
        """
        self._emit(diag)
        self._quiet_teardown()
        self._blank_oled()
        self._visible = False
        self.enabled = False

    def _teardown(self) -> None:
        """Guaranteed cleanup between sessions: stop, verify, scrub the bitmap.

        When the QR is on screen the next session redraws it immediately, so the
        panel is not blanked here — only the secret-bearing framebuffer is zeroed
        and the payload reference dropped.
        """
        try:
            if self._session is not None:
                self._session.stop()
        finally:
            self._session = None
            self._payload = None
            self._zero_bitmap()
            self._scrub_scratch()
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
            self._payload = None
            self._scrub_scratch()
            try:
                wifi.quiesce()
            except wifi.ProvisioningError:
                pass

    # -- OLED ---------------------------------------------------------------
    def _render_qr(self, payload: str) -> None:
        """Render the fixed 41x41 QR (33 modules + 4-module quiet zone) off-screen.

        The framed code is drawn into the off-screen ``_scratch`` framebuffer as a
        lit (light) background with the dark modules unlit, so a camera sees correct
        QR polarity once the buffer is blitted. Does no I²C — it only fills the
        buffer, leaving ``_blit_qr`` to flush it.

        Args:
            payload: The QR payload string to encode.

        Raises:
            ValueError: If the framed size is not exactly 41x41 or does not fit.
        """
        grid = qr_code.encode(payload)
        modules = qr_code.SIZE
        dim = modules + 2 * _QUIET
        if dim != 41:
            raise ValueError("unexpected qr size")
        fb = self._scratch
        width = self._display.width
        height = self._display.height
        if dim > width or dim > height:
            raise ValueError("qr does not fit")
        bx = (width - dim) // 2
        by = (height - dim) // 2
        fb.fill(0)
        for yy in range(dim):
            for xx in range(dim):
                fb.pixel(bx + xx, by + yy, 1)
        for y in range(modules):
            row = grid[y]
            oy = by + _QUIET + y
            for x in range(modules):
                if row[x]:
                    fb.pixel(bx + _QUIET + x, oy, 0)
        self._rendered_payload = payload

    def _blit_qr(self) -> None:
        """Flush the pre-rendered off-screen QR to the panel in one blit + write."""
        self._display.blit(self._scratch, 0, 0)
        self._display.show()

    def _zero_bitmap(self) -> None:
        """Zero the OLED framebuffer so the old QR's secrets do not linger."""
        try:
            self._display.fill(0)
        except Exception:  # noqa: BLE001
            pass

    def _scrub_scratch(self) -> None:
        """Zero the off-screen QR buffer so old credentials do not linger in RAM."""
        try:
            self._scratch.fill(0)
        except Exception:  # noqa: BLE001
            pass
        self._rendered_payload = None

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
