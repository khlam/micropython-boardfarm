"""Boardfarm MicroPython freeze manifest.

Read by MicroPython's tools/makemanifest.py during the firmware build
(inside the `rp` and `esp32` Docker stages). `$(PORT_DIR)` and
`$(BOARD_DIR)` are substituted by makemanifest.py before file
resolution; `/firmware-packages` and `/firmware` are bind-mounted at
container runtime from `repo_root/firmware-packages` and
`projects/<project>/firmware`.
"""

from contextlib import suppress
from pathlib import Path

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

# Each shared MicroPython package: firmware-packages/<pkg>/<pkg>/
# becomes a frozen package on the device. Walking /firmware-packages
# keeps new packages self-registering without touching this file.
# package() targets the inner <pkg>/ dir and ignores siblings
# (pyproject.toml, tests/, README.md) — freeze() on the parent would
# sweep those in.
for _pkg_dir in sorted(Path("/firmware-packages").iterdir()):
    _name = _pkg_dir.name
    if (_pkg_dir / _name / "__init__.py").is_file():
        package(_name, base_path=str(_pkg_dir))

# Project-level firmware: every .py at /firmware becomes a top-level
# frozen module. main.py is the boot entry point.
freeze("/firmware")
