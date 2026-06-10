# oled_canvas font vendoring

`oled_canvas/font.py` embeds the classic 5×7 "glcdfont" bitmap font, long
shipped as public domain with the Adafruit GFX library.

| Field | Value |
| --- | --- |
| Upstream | https://github.com/adafruit/Adafruit-GFX-Library |
| File | `glcdfont.c` |
| Licence | Public domain |
| Last sync | 2026-06-10 |

## Divergence from upstream

The local copy is **not** a verbatim transcription of the C array:

- Only printable ASCII (`0x20`–`0x7E`) is included; the upstream high-range
  glyphs (`0x7F`–`0xFF`) are omitted because the demo renders plain ASCII.
- Stored as a Python `bytes` literal (one glyph per line, annotated with its
  codepoint) rather than a C `unsigned char[]`.
- The column-major, bit-0-top layout is preserved unchanged, so it maps
  straight onto the SSD1306 MONO_VLSB framebuffer.

Unlike the vendored drivers, this file is plain lint-clean Python and is not
excluded from ruff/ty/coverage — it is just a data table plus a one-line
`glyph()` accessor.
