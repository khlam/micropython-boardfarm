"""Draw and validate the per-session credentials from one entropy read.

All three secrets come from a single 32-byte ``os.urandom`` result, split by the
fixed byte layout below. The draw fails closed (``ProvisioningError('entropy')``)
on a missing API, an exception, a wrong-length result, or an all-identical result
— which catches both a stuck all-zero source and a source stuck on any constant
byte — rather than substituting a timestamp, MAC address, PRNG, or a home-grown
"looks random" test. The final ASCII and Wi-Fi lengths are validated and every QR
or Wi-Fi delimiter is rejected before the credentials are ever used.
"""

from wifi.errors import ProvisioningError

__all__ = ["Secrets", "draw"]

# Byte split of the 32-byte entropy read.
_ENTROPY_LEN = 32
_SSID_BYTES = 4  # default -> 8 uppercase hex chars
_PASSWORD_BYTES = 12  # default -> 24 uppercase hex chars
_CSRF_BYTES = 16  # -> 32 uppercase hex chars

_SSID_MAX = 32  # 802.11 SSID octet limit
_CSRF_LEN = 32

# Characters that must never appear in an SSID or password: they would break the
# WIFI: QR grammar (`\ ; : ,` and quotes) or an 802.11 field (whitespace/control).
_FORBIDDEN = set(" \t\r\n\x00\\'\";:,")


class Secrets:
    """Holds one session's SSID, password, CSRF token, and QR payload.

    The raw entropy buffer is kept mutable so it can be zeroed by ``wipe``. The
    derived strings are immutable — MicroPython cannot guarantee their erasure —
    so ``wipe`` only drops the references and zeroes what it can.
    """

    def __init__(self, ssid: str, password: str, csrf: str, raw: bytearray) -> None:
        """Build the record and its QR payload from validated parts."""
        self.ssid = ssid
        self.password = password
        self.csrf = csrf
        self._raw = raw
        self.qr_payload = f"WIFI:T:WPA;S:{ssid};P:{password};;"

    def wipe(self) -> None:
        """Zero the mutable entropy buffer and drop all secret references.

        Immutable strings (ssid/password/csrf/payload) cannot be scrubbed in
        place; this drops them so they become collectable, and zeroes the one
        buffer it owns.
        """
        if self._raw is not None:
            for i in range(len(self._raw)):
                self._raw[i] = 0
            self._raw = None
        self.ssid = None
        self.password = None
        self.csrf = None
        self.qr_payload = None

    def __repr__(self) -> str:
        """Never expose any secret in a repr."""
        return "<Secrets>"


def _hex(raw: bytearray, start: int, length: int) -> str:
    """Return the uppercase hex of ``length`` bytes of ``raw`` from ``start``."""
    return "".join(f"{raw[start + i]:02X}" for i in range(length))


def _clean(value: str, length: int) -> bool:
    """Return whether ``value`` is exactly ``length`` safe ASCII characters."""
    if len(value) != length:
        return False
    return all(0x20 < ord(ch) < 0x7F and ch not in _FORBIDDEN for ch in value)


def draw(
    ssid_prefix: str,
    urandom,  # noqa: ANN001
    ssid_bytes: int = _SSID_BYTES,
    password_bytes: int = _PASSWORD_BYTES,
) -> Secrets:
    """Draw and validate one set of credentials from ``ssid_prefix``.

    ``urandom`` is a callable ``(n) -> bytes`` returning ``n`` random bytes; the
    caller passes a radio-backed source (``os.urandom``) only after the adapter
    has confirmed the RF subsystem is initialised. ``ssid_bytes`` and
    ``password_bytes`` control the lengths of the uppercase hexadecimal suffix
    and password. They carry no separate ``Args:`` section because MicroPython
    has no ``typing`` module to name the callable and pydoclint would then demand
    a signature hint for it.

    Returns a validated ``Secrets``, or raises ``ProvisioningError`` with code
    ``entropy`` for any entropy or validation failure, so weak or malformed
    credentials can never be used.
    """
    if (
        not isinstance(ssid_bytes, int)
        or not isinstance(password_bytes, int)
        or ssid_bytes < 1
        or password_bytes < 4
        or ssid_bytes + password_bytes + _CSRF_BYTES > _ENTROPY_LEN
    ):
        raise ProvisioningError("entropy")

    try:
        result = urandom(_ENTROPY_LEN)
    except Exception:  # noqa: BLE001 - any failure is an entropy failure
        raise ProvisioningError("entropy") from None
    if not isinstance(result, (bytes, bytearray)) or len(result) != _ENTROPY_LEN:
        raise ProvisioningError("entropy")
    # Reject an all-identical read: covers a stuck all-zero source and a source
    # stuck on any single constant byte.
    if all(b == result[0] for b in result):
        raise ProvisioningError("entropy")

    raw = bytearray(result)
    ssid = ssid_prefix + _hex(raw, 0, ssid_bytes)
    password = _hex(raw, ssid_bytes, password_bytes)
    csrf = _hex(raw, ssid_bytes + password_bytes, _CSRF_BYTES)

    if (
        len(ssid) > _SSID_MAX
        or not _clean(ssid, len(ssid))
        or not _clean(password, password_bytes * 2)
        or not _clean(csrf, _CSRF_LEN)
    ):
        for i in range(len(raw)):
            raw[i] = 0
        raise ProvisioningError("entropy")

    return Secrets(ssid, password, csrf, raw)
