"""Crash-safe persistence of the active LED mode across two alternating slots.

The active setting is one small JSON record carrying a monotonically increasing
generation. Two slot files are written alternately: a commit always writes the
*inactive* slot via a temp file that is flushed, ``os.sync``-ed, and renamed into
place, so a power loss at any step leaves the previously active generation intact
and fully valid. On load the newest fully valid record wins (generations are
compared with modulo-2^31 serial-number arithmetic so wraparound is unambiguous);
a missing or corrupt pair falls back to random mode.
"""

import os

import ujson

__all__ = ["GEN_MODULUS", "load", "save"]

_SLOTS = ("/led-effects-0.json", "/led-effects-1.json")
_TMP = "/led-effects.tmp"
GEN_MODULUS = 2**31
_GEN_HALF = 2**30
_VERSION = 1
_HEX = "0123456789ABCDEF"

_DEFAULT = {"version": _VERSION, "generation": 0, "mode": "random"}


def _valid_color(value: object) -> bool:
    """Return whether ``value`` is a 6-character uppercase hex colour string."""
    return isinstance(value, str) and len(value) == 6 and all(ch in _HEX for ch in value)


def _valid_record(record: object) -> bool:
    """Return whether ``record`` is a fully valid, exactly-shaped settings record."""
    if not isinstance(record, dict):
        return False
    if record.get("version") != _VERSION:
        return False
    gen = record.get("generation")
    if not isinstance(gen, int) or gen < 0 or gen >= GEN_MODULUS:
        return False
    mode = record.get("mode")
    if mode == "random":
        return set(record.keys()) == {"version", "generation", "mode"}
    if mode == "solid":
        return set(record.keys()) == {"version", "generation", "mode", "color"} and _valid_color(
            record["color"]
        )
    return False


def _read(path: str) -> dict | None:
    """Read and validate one slot, returning the record or ``None``."""
    try:
        with open(path) as handle:
            record = ujson.loads(handle.read())
    except (OSError, ValueError):
        return None
    return record if _valid_record(record) else None


def _serial_newer(a: int, b: int) -> bool:
    """Return whether generation ``a`` is newer than ``b`` (mod-2^31 serial)."""
    diff = (a - b) % GEN_MODULUS
    return 0 < diff < _GEN_HALF


def _newest() -> tuple:
    """Return ``(index, record)`` of the newest valid slot, or ``(-1, None)``."""
    best_index = -1
    best = None
    for index, path in enumerate(_SLOTS):
        record = _read(path)
        if record is None:
            continue
        if best is None or _serial_newer(record["generation"], best["generation"]):
            best_index = index
            best = record
    return best_index, best


def _sync() -> None:
    """Flush filesystem buffers to storage where the port supports it."""
    try:
        os.sync()
    except (AttributeError, OSError):
        pass


def load() -> dict:
    """Return the newest fully valid record, or the random-mode default."""
    _index, record = _newest()
    return dict(record) if record is not None else dict(_DEFAULT)


def save(mode: str, color: str | None = None) -> dict | None:
    """Atomically commit a new active setting to the inactive slot.

    Writes a temp file, syncs it, removes the inactive slot, renames the temp
    into it, then rereads and validates before reporting success. The active
    generation is never touched, so an interrupted commit changes nothing.

    Args:
        mode: ``"solid"`` or ``"random"``.
        color: Uppercase ``RRGGBB`` string, required only for solid mode.

    Returns:
        The committed record on success, or ``None`` if the commit failed (in
        which case no persisted or active state has changed).
    """
    index, current = _newest()
    generation = 0 if current is None else (current["generation"] + 1) % GEN_MODULUS
    record = {"version": _VERSION, "generation": generation, "mode": mode}
    if mode == "solid":
        record["color"] = color
    if not _valid_record(record):
        return None

    target = _SLOTS[0] if index != 0 else _SLOTS[1]  # always the inactive slot
    try:
        with open(_TMP, "w") as handle:
            handle.write(ujson.dumps(record))
            handle.flush()
        _sync()
        try:
            os.remove(target)
        except OSError:
            pass
        os.rename(_TMP, target)
        _sync()
    except OSError:
        try:
            os.remove(_TMP)
        except OSError:
            pass
        return None

    return record if _read(target) == record else None
