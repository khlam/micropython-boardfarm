"""The immutable provisioning configuration record and its validator.

``Config`` is a fixed-size named tuple: every field is positional and known, so a
caller cannot smuggle in an unexpected configuration key, and the record cannot be
mutated after creation. ``validate`` enforces the value ranges the adapters and
DNS/HTTP layers rely on before any radio or socket work begins.
"""

from collections import namedtuple

from wifi.errors import ProvisioningError

__all__ = ["Config", "no_client_timeout_enabled", "validate"]

# absolute_timeout_ms bounds each session's lifetime; the caller rotates on it.
# no_client_timeout_ms <= 0 means "never fire" (see no_client_timeout_enabled).
Config = namedtuple(
    "Config",
    (
        "ssid_prefix",
        "ap_ip",
        "netmask",
        "channel",
        "local_hostname",
        "absolute_timeout_ms",
        "no_client_timeout_ms",
    ),
)

_MAX_SSID_PREFIX = 24  # leaves room for the 8 hex chars within the 32-char SSID cap
_HOSTNAME_CHARS = "abcdefghijklmnopqrstuvwxyz0123456789-."


def no_client_timeout_enabled(config: Config) -> bool:
    """Return whether the no-client timeout should ever fire for this config."""
    return config.no_client_timeout_ms > 0


def _dotted_quad(value: str) -> bool:
    """Return whether ``value`` is a dotted-quad IPv4 address string."""
    if not isinstance(value, str):
        return False
    parts = value.split(".")
    if len(parts) != 4:
        return False
    for part in parts:
        if not part.isdigit() or not (0 <= int(part) <= 255):
            return False
        if len(part) > 1 and part[0] == "0":  # reject leading zeros
            return False
    return True


def _ascii_printable(value: str) -> bool:
    """Return whether every character is printable 7-bit ASCII with no space."""
    return all(0x21 <= ord(ch) <= 0x7E for ch in value)


def validate(config: Config) -> None:
    """Validate a ``Config`` before any radio or socket setup.

    Args:
        config: The candidate configuration record.

    Raises:
        ProvisioningError: With code ``network`` if any field is missing, the
            wrong type, or out of range. Config errors are surfaced as a setup
            (network) fault rather than leaking the offending value.
    """
    try:
        ok = (
            isinstance(config, Config)
            and isinstance(config.ssid_prefix, str)
            and 0 < len(config.ssid_prefix) <= _MAX_SSID_PREFIX
            and _ascii_printable(config.ssid_prefix)
            and _dotted_quad(config.ap_ip)
            and _dotted_quad(config.netmask)
            and isinstance(config.channel, int)
            and 1 <= config.channel <= 13
            and isinstance(config.local_hostname, str)
            and 0 < len(config.local_hostname) <= 63
            and all(ch in _HOSTNAME_CHARS for ch in config.local_hostname)
            and isinstance(config.absolute_timeout_ms, int)
            and config.absolute_timeout_ms > 0
            and isinstance(config.no_client_timeout_ms, int)
        )
    except (TypeError, AttributeError):
        ok = False
    if not ok:
        raise ProvisioningError("network")
