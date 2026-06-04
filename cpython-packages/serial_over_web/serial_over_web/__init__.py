"""Host CPython package — shared FastAPI dashboard for boardfarm projects' serial JSON streams.

The actual server lives in `serial_over_web.app`; uvicorn is invoked as
`serial_over_web.app:app` by the viz Docker stage. Each project supplies
its own static dashboard (HTML/JS), pointed to by the `STATIC_DIR` env
var.

Named `serial_over_web` rather than `serial` to avoid colliding with the
`pyserial` library this module imports.
"""
