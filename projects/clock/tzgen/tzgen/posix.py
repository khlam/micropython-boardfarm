r"""Extract the POSIX TZ string for an IANA zone id from its TZif data.

A version 2+ TZif file (RFC 8536) ends with a newline-enclosed POSIX TZ string
describing the zone's *current* DST rules, e.g. ``\\nCST6CDT,M3.2.0,M11.1.0\\n``.
That footer is exactly what ``tz_offset._posix`` evaluates, so tzgen lifts it
verbatim rather than re-deriving rules from the transition tables.

``posix_from_tzif_bytes`` is pure (bytes in, string out) and unit-tested directly.
``posix_for_tzid`` loads the bytes from the ``tzdata`` package and is exercised only
during real generation, where that dependency is present.
"""

from __future__ import annotations

from importlib.resources import files


def posix_from_tzif_bytes(data: bytes) -> str | None:
    """Return the trailing POSIX TZ string of a TZif file, or ``None`` if absent.

    Args:
        data: Raw bytes of a TZif (zoneinfo) file.

    Returns:
        The footer POSIX TZ string (e.g. ``"CST6CDT,M3.2.0,M11.1.0"``), or ``None``
        when the file is not TZif v2+ or carries an empty footer (e.g. a v1-only or
        fixed-offset file with no rule line).
    """
    if not data.startswith(b"TZif"):
        return None
    end = data.rfind(b"\n")
    if end <= 0:
        return None
    start = data.rfind(b"\n", 0, end)
    if start < 0:
        return None
    footer = data[start + 1 : end]
    if not footer:
        return None
    return footer.decode("ascii")


def posix_for_tzid(tzid: str, fallback: str) -> str:
    """Return the POSIX TZ string for ``tzid`` from the ``tzdata`` package.

    Args:
        tzid: IANA zone id, e.g. ``"America/Chicago"``.
        fallback: POSIX string to use when the footer is missing (fixed-offset
            zones), typically synthesized from the zone's standard offset.

    Returns:
        The extracted footer, or ``fallback`` when none is present.
    """
    resource = files("tzdata.zoneinfo")
    for part in tzid.split("/"):
        resource = resource / part
    extracted = posix_from_tzif_bytes(resource.read_bytes())
    return extracted or fallback
