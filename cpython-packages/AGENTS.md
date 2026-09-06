# cpython-packages

## Shared host-test stubs †

- All MicroPython stubs live in `cpython-packages/micropython_stubs/micropython_stubs/`
- Reset `machine` and `neopixel` state with `machine.reset()` / `neopixel.reset()` in an autouse fixture.
- To extend a stub, edit the file there and add it to `force-include` in `pyproject.toml`.

Firmware packages should be testable under CPython using the shared MicroPython stubs and deterministic fake devices where practical.

`micropython_stubs` is exempt: it exists to support host tests, so test-only use is its purpose.

---

† Project-specific quirk — e.g. behavior that differs between the MicroPython firmware runtime and the CPython host-test environment.
