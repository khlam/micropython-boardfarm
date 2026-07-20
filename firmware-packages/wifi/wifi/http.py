"""A minimal, bounded HTTP/1.0-1.1 request handler for the captive portal.

This module owns all generic HTTP behaviour — parsing, size limits, host/origin
validation, CSRF checks, captive-probe redirects, routing to the project handler,
and response rendering — while the project ``handler`` owns only the page content
and its route-specific field validation. Every response the package emits carries
the same security headers and Content-Security-Policy; there is exactly one
request per connection and the connection is always closed afterwards.

Parsing is split so a caller can accumulate bytes across nonblocking reads:
``head_end`` finds the header terminator, ``parse_head`` validates the request
line and headers (yielding the declared body length), and ``dispatch`` runs once
the whole message is buffered.
"""

__all__ = [
    "BODY_MAX",
    "HEADER_BYTES_MAX",
    "MAX_HEADERS",
    "REQUEST_LINE_MAX",
    "RESPONSE_MAX",
    "Request",
    "Response",
    "dispatch",
    "error_response",
    "head_end",
    "parse_head",
]

REQUEST_LINE_MAX = 256
MAX_HEADERS = 16
HEADER_BYTES_MAX = 2048
BODY_MAX = 512
RESPONSE_MAX = 4096

_MAX_FORM_FIELDS = 8
_MAX_FIELD_LEN = 64
_HEXD = "0123456789abcdefABCDEF"
_FORM_CTYPE = "application/x-www-form-urlencoded"

# (host, path) probe pairs redirected to the canonical URL. Nothing else is.
_PROBES = {
    ("connectivitycheck.gstatic.com", "/generate_204"),
    ("captive.apple.com", "/hotspot-detect.html"),
    ("www.msftconnecttest.com", "/connecttest.txt"),
    ("www.msftncsi.com", "/ncsi.txt"),
    ("detectportal.firefox.com", "/canonical.html"),
}

_REASON = {
    200: "OK",
    302: "Found",
    400: "Bad Request",
    403: "Forbidden",
    404: "Not Found",
    405: "Method Not Allowed",
    413: "Payload Too Large",
    415: "Unsupported Media Type",
    500: "Internal Server Error",
    505: "HTTP Version Not Supported",
}

_SECURITY_HEADERS = (
    "Cache-Control: no-store\r\n"
    "X-Content-Type-Options: nosniff\r\n"
    "Referrer-Policy: no-referrer\r\n"
    "Content-Security-Policy: default-src 'none'; form-action 'self'; "
    "base-uri 'none'; frame-ancestors 'none'\r\n"
)


class Response:
    """A handler's reply: an HTTP status and a fixed HTML body.

    The package owns every header, so a handler supplies only the status and the
    body. ``terminal`` marks a successful configuration change that should make
    ``poll`` report ``complete``.
    """

    def __init__(self, status: int, body: str, *, terminal: bool = False) -> None:
        """Validate and store the response.

        Raises:
            ValueError: If the body exceeds the response budget once headers are
                accounted for.
        """
        encoded = body.encode()
        if len(encoded) > RESPONSE_MAX - 512:
            raise ValueError("response body too large")
        self.status = status
        self.body = body
        self.terminal = terminal


class Request:
    """A fully validated request handed to the project handler.

    ``form`` is the parsed, bounded field dict (empty for GET). Every value here
    has already passed generic HTTP, host, origin, and CSRF validation.
    """

    def __init__(self, method: str, path: str, form: dict) -> None:
        """Store the validated method, path, and form fields."""
        self.method = method
        self.path = path
        self.form = form


class _Head:
    """Parsed request line and headers, or an error status."""

    def __init__(self) -> None:
        self.error = 0
        self.method = ""
        self.path = ""
        self.query = False
        self.host = ""
        self.origin = None
        self.content_type = ""
        self.content_length = 0
        self.has_body = False


def head_end(buf: bytes) -> int:
    r"""Return the index just past the ``\r\n\r\n`` header terminator, or -1."""
    idx = bytes(buf).find(b"\r\n\r\n")
    return -1 if idx < 0 else idx + 4


def _unquote(text: str) -> str | None:
    """Percent-decode a form token, or return ``None`` if malformed."""
    out = []
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch == "+":
            out.append(" ")
            i += 1
        elif ch == "%":
            if i + 3 > n or text[i + 1] not in _HEXD or text[i + 2] not in _HEXD:
                return None
            out.append(chr(int(text[i + 1 : i + 3], 16)))
            i += 3
        else:
            out.append(ch)
            i += 1
    return "".join(out)


def parse_head(head: bytes) -> _Head:
    r"""Parse and validate the request line and headers.

    Args:
        head: The bytes up to and including the ``\r\n\r\n`` terminator.

    Returns:
        A ``_Head``; ``error`` is nonzero (an HTTP status) if the head is
        malformed, the method or version is unsupported, or a header rule is
        violated.
    """
    result = _Head()
    try:
        text = bytes(head).decode("ascii")
    except (UnicodeError, ValueError):
        result.error = 400
        return result
    lines = text.split("\r\n")
    request_line = lines[0]
    if len(request_line) > REQUEST_LINE_MAX:
        result.error = 400
        return result
    parts = request_line.split(" ")
    if len(parts) != 3:
        result.error = 400
        return result
    method, target, version = parts
    if version not in ("HTTP/1.0", "HTTP/1.1"):
        result.error = 505
        return result
    if method not in ("GET", "POST"):
        result.error = 405
        return result
    result.method = method
    if "?" in target:
        result.query = True
        target = target.split("?", 1)[0]
    result.path = target

    header_lines = lines[1:]
    while header_lines and header_lines[-1] == "":
        header_lines.pop()
    if len(header_lines) > MAX_HEADERS:
        result.error = 400
        return result
    if sum(len(line) + 2 for line in header_lines) > HEADER_BYTES_MAX:
        result.error = 400
        return result

    seen_host = False
    seen_length = False
    for line in header_lines:
        if not line or line[0] in " \t":  # empty or folded header
            result.error = 400
            return result
        if ":" not in line:
            result.error = 400
            return result
        name, value = line.split(":", 1)
        name = name.strip().lower()
        value = value.strip()
        if name == "host":
            if seen_host:
                result.error = 400
                return result
            seen_host = True
            result.host = value.lower()
        elif name == "origin":
            result.origin = value
        elif name == "content-type":
            result.content_type = value.lower()
        elif name == "content-length":
            if seen_length or not value.isdigit():
                result.error = 400
                return result
            seen_length = True
            result.content_length = int(value)
            result.has_body = True
        elif name in ("transfer-encoding", "upgrade"):
            # Reject chunking, keep-alive upgrades, and WebSockets outright.
            result.error = 400
            return result
    if not seen_host:
        result.error = 400
        return result
    if result.content_length > BODY_MAX:
        result.error = 413
        return result
    return result


def _parse_form(body: bytes) -> dict | None:
    """Parse a urlencoded body into a bounded dict, or ``None`` if malformed."""
    if not body:
        return {}
    try:
        text = bytes(body).decode("ascii")
    except (UnicodeError, ValueError):
        return None
    fields = {}
    pairs = text.split("&")
    if len(pairs) > _MAX_FORM_FIELDS:
        return None
    for pair in pairs:
        if "=" not in pair:
            return None
        raw_key, raw_val = pair.split("=", 1)
        if len(raw_key) > _MAX_FIELD_LEN or len(raw_val) > _MAX_FIELD_LEN:
            return None
        key = _unquote(raw_key)
        val = _unquote(raw_val)
        if key is None or val is None or not key or not val:
            return None
        if key in fields:  # duplicate field
            return None
        fields[key] = val
    return fields


def _strip_port(host: str) -> str:
    """Remove exactly a trailing ``:80`` from a host value.

    Sliced rather than ``str.removesuffix``, which MicroPython does not provide.
    """
    return host[:-3] if host.endswith(":80") else host


def _render(status: int, body: bytes, extra: str = "") -> bytes:
    """Render a full HTTP response with the mandated headers."""
    head = "HTTP/1.1 {} {}\r\n".format(status, _REASON.get(status, "Error"))
    head += "Content-Type: text/html; charset=utf-8\r\n"
    head += f"Content-Length: {len(body)}\r\n"
    head += "Connection: close\r\n"
    head += extra
    head += _SECURITY_HEADERS
    head += "\r\n"
    return head.encode() + body


def error_response(status: int) -> bytes:
    """Render a minimal generic error response with the mandated headers."""
    extra = "Allow: GET, POST\r\n" if status == 405 else ""
    return _render(status, b"", extra)


def _redirect(url: str) -> bytes:
    """Render a 302 redirect to ``url`` with no meaningful body."""
    return _render(302, b"", f"Location: {url}\r\n")


def dispatch(
    head: _Head,
    body: bytes,
    config: object,
    csrf_token: str,
    handler: object,
) -> tuple:
    """Route one fully buffered request and render the response bytes.

    Args:
        head: The parsed request head from ``parse_head`` (``error`` == 0).
        body: The request body bytes (empty for GET).
        config: The active ``Config`` (supplies allowed hosts and canonical URL).
        csrf_token: The session CSRF token to match POST submissions against.
        handler: ``handler(request, csrf_form_value) -> Response``.

    Returns:
        ``(response_bytes, completed)`` where ``completed`` is True only after a
        successful terminal configuration POST.
    """
    host = _strip_port(head.host)
    canonical = f"http://{config.ap_ip}/"
    allowed = (config.ap_ip, config.local_hostname.lower())

    # Captive-probe redirects: only the exact (host, path) pairs, nothing else.
    if (host, head.path) in _PROBES:
        return _redirect(canonical), False

    if host not in allowed:
        return error_response(404), False

    if head.method == "GET":
        if head.path != "/":
            return error_response(404), False
        if head.has_body and head.content_length > 0:  # body-bearing GET
            return error_response(400), False
        rendered, _ = _run_handler(handler, Request("GET", "/", {}), csrf_token)
        return rendered, False

    # POST /color or /random.
    if head.path not in ("/color", "/random"):
        return error_response(404), False
    if head.query:  # no query or trailing path on a POST
        return error_response(400), False
    if head.content_type != _FORM_CTYPE:
        return error_response(415), False
    if len(body) != head.content_length:
        return error_response(400), False
    if head.origin is not None:
        origin = _strip_port(head.origin.lower())
        if origin != f"http://{host}":
            return error_response(403), False

    form = _parse_form(body)
    if form is None:
        return error_response(400), False
    if form.get("csrf") != csrf_token:
        return error_response(403), False

    return _run_handler(handler, Request("POST", head.path, form), csrf_token)


def _run_handler(handler, request: Request, csrf_token: str) -> tuple:  # noqa: ANN001
    """Invoke the project handler and render its response, failing closed.

    Returns:
        ``(response_bytes, terminal_success)`` where ``terminal_success`` is True
        only when the handler returned a terminal Response with a 2xx status.
    """
    try:
        response = handler(request, csrf_token)
        rendered = _render(response.status, response.body.encode())
    except Exception:  # noqa: BLE001 - a handler bug must not leak a traceback
        return error_response(500), False
    if len(rendered) > RESPONSE_MAX:
        return error_response(500), False
    terminal = bool(response.terminal) and 200 <= response.status < 300
    return rendered, terminal
