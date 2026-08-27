# Firmware HTTP and WebSocket server

This MicroPython package serves a fixed page and pushes a live text stream to
the browsers viewing it, so a board on the network can publish its own dashboard
instead of needing a host attached to its serial port.

It is deliberately small. It serves bodies that were decided before it started —
typically a page frozen into the firmware — and it broadcasts lines it never
parses. There is no routing beyond exact paths, no request body, no template,
and no TLS. Anything a browser sends over an open WebSocket is read and thrown
away, apart from the close frame that says the tab went away.

The server never disturbs the loop feeding it. `Broadcast.send()` frames a line
once, shares it across every client's bounded outbox, and returns without doing
I/O — safe to call from the MicroPython scheduler. A client that stops reading
loses its oldest queued frames rather than slowing the producer down, and a
peer that misbehaves is dropped inside the server.

## Serve a page and stream to it

```python
import asyncio

import httpd

server = httpd.Server(port=80)
server.page("/", PAGE, encoding="gzip")
reports = server.stream("/ws", greeting='{"event":"connected"}')


async def main():
    await server.start()
    while True:
        reports.send('{"reading": 42}')
        await asyncio.sleep_ms(100)


asyncio.run(main())
```

`Server()` only records routes; `start()` is the idempotent operation that binds
the port, and `running` reports whether the listener is active. Build the server
wherever it reads best and open it once the network is actually up.

## Bounds

Everything that a remote peer could otherwise grow is capped:

| Limit | Value | Why |
| --- | --- | --- |
| Clients per stream | 3 | Each costs two tasks and an outbox; a fourth gets `503`. |
| Queued frames per client | 8, drop-oldest | A stalled browser costs fixed RAM, and stale telemetry is worth less than fresh. |
| Header line | 256 bytes | A browser's are far shorter; longer means a broken or hostile peer. |
| Headers per request | 32 | As above. |
| Frame payload | 65535 bytes | Longer needs a 64-bit length this encoder does not emit. |

## Pre-compressed bodies

`page(..., encoding="gzip")` sends the body untouched under a
`Content-Encoding` header, so compression happens wherever the body was
produced and never on the chip. Serving a body straight out of frozen ROM this
way costs no heap.
