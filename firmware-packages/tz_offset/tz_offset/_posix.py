"""Pure-integer POSIX TZ string parser and DST evaluator (RFC 8536 section 3.3).

A POSIX TZ string such as ``CST6CDT,M3.2.0/2,M11.1.0/2`` encodes a zone's standard
and daylight abbreviations, their UTC offsets, and the month/week/day rules for the
DST transitions. Given a UTC date/time this module returns the correct offset
(including DST) and the active abbreviation, using only integer arithmetic plus the
shared calendar helpers — no float math, no I/O — so it runs identically on the MCU
and under host CPython pytest.

POSIX sign convention is inverted relative to the usual "UTC offset": the numeric
field after a zone name is the value *added to local time to obtain UTC*, so a zone
five hours west of Greenwich is written ``EST5``. ``offset_seconds`` returns the
conventional UTC->local offset (east positive) — the negation of the parsed field.

The DST-active test approximates the offset in effect just before each transition
with standard time before the spring-forward and daylight time before the fall-back
— the same approach musl/glibc take. It is exact except within the ~1 h transition
discontinuity itself, which is acceptable for a wall clock.
"""

from tz_offset._calendar import _days_in_month, _is_leap, _sun0

_HOUR = 3600
# Local 02:00:00, the POSIX default transition time when "/time" is omitted.
_DEFAULT_TRANSITION_S = 2 * _HOUR


def _read_name(s: str, i: int) -> tuple:
    """Read a zone abbreviation: a ``<...>`` quoted run or a maximal alphabetic run."""
    if i < len(s) and s[i] == "<":
        j = s.find(">", i)
        if j < 0:
            return s[i + 1 :], len(s)
        return s[i + 1 : j], j + 1
    start = i
    while i < len(s) and s[i].isalpha():
        i += 1
    return s[start:i], i


def _read_int(s: str, i: int) -> tuple:
    """Read a run of decimal digits, returning ``(value, next_index)``."""
    start = i
    while i < len(s) and s[i].isdigit():
        i += 1
    return int(s[start:i]), i


def _read_offset(s: str, i: int) -> tuple:
    """Read ``[+|-]hh[:mm[:ss]]`` and return ``(signed_seconds, next_index)``.

    Tolerates the full RFC range, including hour fields above 24 used by some
    transition ``/time`` values.
    """
    sign = 1
    if i < len(s) and s[i] in "+-":
        if s[i] == "-":
            sign = -1
        i += 1
    hh, i = _read_int(s, i)
    mm = 0
    ss = 0
    if i < len(s) and s[i] == ":":
        mm, i = _read_int(s, i + 1)
        if i < len(s) and s[i] == ":":
            ss, i = _read_int(s, i + 1)
    return sign * (hh * _HOUR + mm * 60 + ss), i


def _read_rule(s: str, i: int) -> tuple:
    """Read one transition rule (``Mm.w.d`` / ``Jn`` / ``n``) plus optional ``/time``.

    Returns ``(rule, next_index)`` where ``rule`` is a tag tuple ending in the local
    transition seconds: ``("M", month, week, dow, time_s)``, ``("J", n, time_s)`` or
    ``("O", n, time_s)``.
    """
    kind = s[i]
    if kind == "M":
        month, i = _read_int(s, i + 1)
        week, i = _read_int(s, i + 1)  # i sits on '.', so i+1 skips it
        dow, i = _read_int(s, i + 1)
        time_s = _DEFAULT_TRANSITION_S
        if i < len(s) and s[i] == "/":
            time_s, i = _read_offset(s, i + 1)
        return ("M", month, week, dow, time_s), i
    if kind == "J":
        n, i = _read_int(s, i + 1)
    else:
        n, i = _read_int(s, i)
        kind = "O"
    time_s = _DEFAULT_TRANSITION_S
    if i < len(s) and s[i] == "/":
        time_s, i = _read_offset(s, i + 1)
    return (kind, n, time_s), i


def parse(tz: str) -> dict:
    """Parse a POSIX TZ string into a dict of offsets, abbreviations, and rules.

    Args:
        tz: A POSIX TZ string, e.g. ``"PST8PDT,M3.2.0,M11.1.0"``.

    Returns:
        A dict with keys ``std_off``/``dst_off`` (POSIX add-to-local seconds),
        ``has_dst``, ``start``/``end`` (rule tuples or ``None``), and
        ``std_abbrev``/``dst_abbrev``. A daylight name with no explicit offset
        defaults to one hour east of standard time.
    """
    i = 0
    std_abbrev, i = _read_name(tz, i)
    std_off, i = _read_offset(tz, i)
    has_dst = False
    dst_abbrev = None
    dst_off = std_off
    start_rule = None
    end_rule = None
    if i < len(tz) and tz[i] != ",":
        has_dst = True
        dst_abbrev, i = _read_name(tz, i)
        if i < len(tz) and tz[i] != ",":
            dst_off, i = _read_offset(tz, i)
        else:
            dst_off = std_off - _HOUR
    if has_dst and i < len(tz) and tz[i] == ",":
        start_rule, i = _read_rule(tz, i + 1)
        if i < len(tz) and tz[i] == ",":
            end_rule, i = _read_rule(tz, i + 1)
    return {
        "std_off": std_off,
        "dst_off": dst_off,
        "has_dst": has_dst,
        "start": start_rule,
        "end": end_rule,
        "std_abbrev": std_abbrev,
        "dst_abbrev": dst_abbrev,
    }


def _day_of_year(year: int, month: int, day: int) -> int:
    """Return the 0-based day index within ``year`` (Jan 1 -> 0)."""
    doy = day - 1
    mo = 1
    while mo < month:
        doy += _days_in_month(year, mo)
        mo += 1
    return doy


def _mrule_dom(year: int, month: int, week: int, dow: int) -> int:
    """Resolve an ``Mm.w.d`` rule to a day of month (week 5 = last occurrence).

    ``dow`` is POSIX 0=Sunday..6=Saturday, matching ``_sun0``.
    """
    first = 1 + (dow - _sun0(year, month, 1)) % 7
    dom = first + (week - 1) * 7
    if dom > _days_in_month(year, month):
        dom -= 7
    return dom


def _julian_doy(year: int, n: int) -> int:
    """Return the 0-based day-of-year for a ``Jn`` rule (Feb 29 never counted)."""
    doy = n - 1
    if n >= 60 and _is_leap(year):
        doy += 1
    return doy


def _rule_secs_in_year(year: int, rule: tuple) -> int:
    """Return the local-wall seconds-since-Jan-1 at which ``rule`` fires in ``year``."""
    kind = rule[0]
    if kind == "M":
        _, month, week, dow, time_s = rule
        doy = _day_of_year(year, month, _mrule_dom(year, month, week, dow))
    elif kind == "J":
        _, n, time_s = rule
        doy = _julian_doy(year, n)
    else:
        _, n, time_s = rule
        doy = n
    return doy * 86400 + time_s


def _secs_in_year(year: int, month: int, day: int, hour: int, minute: int, second: int) -> int:
    """Return UTC seconds-since-Jan-1 for a date/time (the transition comparison base)."""
    return _day_of_year(year, month, day) * 86400 + hour * _HOUR + minute * 60 + second


def _is_dst(p: dict, year: int, month: int, day: int, hour: int, minute: int, second: int) -> bool:
    """Return True when the parsed zone is in daylight time at the given UTC instant."""
    now = _secs_in_year(year, month, day, hour, minute, second)
    # Transitions are local wall-time; convert each to a UTC seconds-since-Jan-1
    # count by adding the offset in effect just before it — std before the spring
    # transition, dst before the fall. POSIX offsets are "add local to get UTC", so
    # UTC_count = local_count + offset.
    start = _rule_secs_in_year(year, p["start"]) + p["std_off"]
    end = _rule_secs_in_year(year, p["end"]) + p["dst_off"]
    if start < end:
        return start <= now < end
    # Southern hemisphere: daylight time spans the year boundary.
    return now >= start or now < end


def offset_seconds(
    tz: str, year: int, month: int, day: int, hour: int, minute: int, second: int
) -> tuple:
    """Return ``(utc_to_local_offset_seconds, abbrev)`` for a UTC instant.

    Args:
        tz: A POSIX TZ string, e.g. ``"PST8PDT,M3.2.0,M11.1.0"``.
        year: Four-digit UTC year.
        month: UTC month, 1-12.
        day: UTC day of month.
        hour: UTC hour, 0-23.
        minute: UTC minute, 0-59.
        second: UTC second, 0-59.

    Returns:
        ``(offset_seconds, abbrev)`` where ``offset_seconds`` is the signed
        UTC->local offset (east positive) and ``abbrev`` is the active abbreviation
        (e.g. ``"PDT"``). DST is applied only when the string carries a daylight rule
        pair; otherwise the standard offset is returned year-round.
    """
    p = parse(tz)
    if (
        p["has_dst"]
        and p["start"] is not None
        and p["end"] is not None
        and _is_dst(p, year, month, day, hour, minute, second)
    ):
        return (-p["dst_off"], p["dst_abbrev"])
    return (-p["std_off"], p["std_abbrev"])
