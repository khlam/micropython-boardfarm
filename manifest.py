"""Boardfarm MicroPython freeze manifest.

Read by MicroPython's tools/makemanifest.py during the firmware build
(inside the `rp` and `esp32` Docker stages). `$(PORT_DIR)` and
`$(BOARD_DIR)` are substituted by makemanifest.py before file
resolution; `/firmware-packages` and `/firmware` are bind-mounted at
container runtime from `repo_root/firmware-packages` and
`projects/<project>/firmware`.
"""

import os
import re
from contextlib import suppress
from pathlib import Path

# Top-level module name of an `import X` / `from X import ...` line (X may
# be dotted; capture only the first component). Indented imports match too,
# in case a backend is pulled in lazily inside a function.
_IMPORT_RE = re.compile(r"^\s*(?:import|from)\s+([A-Za-z_]\w*)", re.MULTILINE)


def _imported_names(root: Path) -> set:
    """Return the set of top-level module names imported anywhere under root."""
    names: set = set()
    for py in root.rglob("*.py"):
        names.update(_IMPORT_RE.findall(py.read_text()))
    return names


# Pull in the port's default frozen modules (extmod/asyncio, etc.).
# Setting MICROPY_FROZEN_MANIFEST entirely replaces the default chain on
# rp2, so this is needed to keep asyncio + other standard frozen modules.
include("$(PORT_DIR)/boards/manifest.py")

# Per-board extras (networking on the _W variants, BLE on some boards).
# Most non-_W boards have no per-board manifest — suppress keeps that
# case quiet. makemanifest raises its own IncludeError (not importable
# from here), so the catch is necessarily broad.
with suppress(Exception):
    include("$(BOARD_DIR)/manifest.py")

# Shared MicroPython packages available to freeze: name -> parent dir.
# package() targets the inner <pkg>/ dir and ignores siblings
# (pyproject.toml, tests/, README.md) — freeze() on the parent would
# sweep those in. Auto-discovery keeps new packages self-registering
# without touching this file.
_packages = {
    p.name: p
    for p in sorted(Path("/firmware-packages").iterdir())
    if (p / p.name / "__init__.py").is_file()
}

# Freeze only the packages this project's firmware actually imports. The
# manifest is shared across every project, so freezing all of them would
# sweep large unused blobs (e.g. vl53l5cx's ~400 KB config) into firmware
# that never touches them. Resolve the transitive closure so a package
# that imports another package still works — the sensor drivers import
# i2c_bus to open their own bus, so that fixpoint pulls i2c_bus in for any
# project whose firmware imports such a driver.
_needed: set = set()
_frontier = _imported_names(Path("/firmware")) & _packages.keys()
while _frontier:
    _name = _frontier.pop()
    _needed.add(_name)
    _frontier |= (_imported_names(_packages[_name] / _name) & _packages.keys()) - _needed

for _name in sorted(_needed):
    package(_name, base_path=str(_packages[_name]))

# Project-level firmware: every .py at /firmware becomes a top-level
# frozen module. main.py is the boot entry point.
freeze("/firmware")

# Modules the build generated rather than a person writing them — the caller
# stages them into a writable directory and names it here, because /firmware is
# bind-mounted read-only. Unset for builds that generate nothing.
_staged = os.environ.get("FROZEN_STAGING_DIR")
if _staged:
    freeze(_staged)
