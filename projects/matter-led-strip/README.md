# ESP32-S3-Zero Matter LED Strip

This project exposes an external WS2812B 20-LED strip wired to the
ESP32-S3-Zero as a Matter Extended Color Light.


## Wiring

`DIN` goes to `GPIO7`. Common ground is mandatory: board `GND`, strip `GND`,
and the 5V supply must share a ground or the data line has no reference.

```
                                   ┌─── USB-C ───┐
                              ┌────┴─────────────┴────┐
                              │                       │
         WS2812B 5V ◄───  5V ─┤                       ├─ 13
        WS2812B GND ◄─── GND ─┤                       ├─ 12
                         3V3 ─┤                       ├─ 11
                           1 ─┤                       ├─ 10
                           2 ─┤                       ├─ 9
                           3 ─┤  [BOOT] (●) [RESET]   ├─ 8
                           4 ─┤        WS2812         ├─ 43
                           5 ─┤        on GPIO21      ├─ 44
                           6 ─┤                       ├─ 14
        WS2812B DIN ◄───   7 ─┤   ESP32-S3-Zero       ├─ 15
                              │                       │
                              └─┬────┬────┬────┬────┬─┘
                                │    │    │    │    │
                                16   17   18   21   45
```
