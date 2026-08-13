# ld2450

Package scaffold for a reusable MicroPython driver for the HLK-LD2450 radar
sensor.

## Status

The driver API, UART protocol handling, and tests are not implemented yet.

## Planned layout

```text
ld2450/
  ld2450/                  MicroPython package, frozen onto the device
  tests/                   host tests added after the feature is confirmed
  pyproject.toml           package and wheel metadata
  README.md                public API and usage documentation
```

The package will own reusable sensor behavior and accept project-provided pin
numbers. Project-specific pin assignments and runtime behavior belong in
[`../../projects/ld2450/`](../../projects/ld2450/).

Build metadata is intentionally deferred until the source package exists, so
the repository's automatic wheel builder cannot publish an empty driver.
