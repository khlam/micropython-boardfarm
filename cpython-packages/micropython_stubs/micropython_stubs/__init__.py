"""Host CPython package — shared MicroPython stubs re-promoted to top-level imports.

Provides `machine`, `neopixel`, `micropython`, `ujson`, `ustruct`, and `utime`
so pytest can exercise MCU code on the host. The wheel uses hatch
`force-include` to expose the stub modules at the top level.
"""
