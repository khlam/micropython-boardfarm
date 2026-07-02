# boot_button

Board-agnostic, event-driven onboard BOOT button. Every project MCU registers one
callback and never polls — the package hides the per-chip hardware split behind a
single `on_press` API.

## Layout
```
boot_button/
  boot_button/
    __init__.py     re-exports nothing; import the `button` module
    button.py       chip dispatch + public on_press()
    esp32s3.py      GPIO0 hardware IRQ (ESP32-S3-Zero)
    rp2040.py       soft-Timer poll of rp2.bootsel_button() (RP2040-Zero)
    rp2350.py       soft-Timer poll of rp2.bootsel_button() (RP2350)
  tests/            host pytest (CPython + stubbed machine/rp2/micropython)
```

## Public API
```python
from boot_button import button

button.on_press(handle_press)   # registered once; fires once per debounced press
```

The callback runs in scheduler context (via `micropython.schedule`), not in the
interrupt/timer handler, so it may allocate and do non-trivial work.

## Notes

### Per-chip mechanism

| Board          | Mechanism                                                            |
|----------------|---------------------------------------------------------------------|
| ESP32-S3-Zero  | True hardware interrupt: `Pin(0, IN, PULL_UP).irq(IRQ_FALLING, …)`   |
| RP2040-Zero    | Periodic soft `Timer` polling `rp2.bootsel_button()` for a press edge |
| RP2350         | Periodic soft `Timer` polling `rp2.bootsel_button()` for a press edge |

BOOTSEL on the RP chips doubles as the QSPI flash CS line and has no GPIO
interrupt, so the timer-poll backends emulate the same event API. All backends
debounce (~150 ms) and defer the callback off interrupt context.

## Tests
From the repo root:
```
docker compose up pytest --build --exit-code-from pytest -- /firmware-packages/boot_button/tests
```
