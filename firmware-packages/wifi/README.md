# wifi

Secure, self-contained WPA2 captive-portal provisioning. The package brings up a
single locked-down access point, answers a bounded set of captive-check DNS names,
serves one no-JavaScript HTML page over a bounded HTTP/1.0-1.1 handler, and hands
fully validated requests to a project handler. Session, DNS, and HTTP logic are
platform-neutral; only the per-chip adapters touch `network`. It adds no NAT,
routing, bridging, forwarding, upstream DNS, filesystem access, or third-party
dependency.

## Layout
```
wifi/
  wifi/
    __init__.py   public API: Config, Request, Response, Session, capabilities, quiesce, create_session
    errors.py     ProvisioningError + its closed set of redacted codes
    config.py     immutable Config record + validator
    secrets.py    one-read entropy draw, credential split, validation
    dns.py        bounded captive DNS responder (pure packet logic)
    http.py       bounded HTTP parse/route/render, host/origin/CSRF checks
    session.py    state machine, 3-socket lifecycle, token buckets, poll()
    adapter.py    os.uname().machine dispatch to a backend
    esp32s3.py    ESP32-S3 WPA2 AP adapter
    rp2350.py     Pico 2 W (CYW43) WPA2 AP adapter
    rp2040.py     unsupported no-op adapter
```

## Public API
```python
from wifi import Config, Request, Response, Session, ProvisioningError
from wifi import capabilities, quiesce, create_session

quiesce()                                   # force AP + STA down at boot; verify
config = Config(ssid_prefix="LEDFX-", ap_ip="192.168.4.1", netmask="255.255.255.0",
                channel=6, local_hostname="led-effects.test",
                absolute_timeout_ms=600000, no_client_timeout_ms=0)

session = create_session(config, handler)   # draws radio-backed credentials -> NEW
payload = session.qr_payload()              # "WIFI:T:WPA;S:<ssid>;P:<pw>;;" (NEW only)
session.start()                             # configure + prove + activate AP + sockets -> ACTIVE
event = session.poll(now_ms)                # bounded, nonblocking, once per loop
session.stop()                              # idempotent teardown -> STOPPED
```

`handler(request, csrf_form_value) -> Response` renders the page and validates its
own route-specific fields. The `csrf_form_value` is supplied only for the hidden
GET form field and must never be logged or retained after the call.

### `poll(now_ms)` return values
| Value | Meaning |
| --- | --- |
| `None` | Ordinary or rejected traffic; keep serving. |
| `"complete"` | A configuration POST succeeded. Non-terminal: keep serving. |
| `"absolute_timeout"` | The session reached `absolute_timeout_ms`. **Terminal — stop.** |
| `"no_client_timeout"` | Only when `no_client_timeout_ms > 0`. **Terminal — stop.** |
| `"fatal"` | Unrecoverable socket failure. **Terminal — stop.** |

### `capabilities()`
Always returns the boolean keys `supported`, `wpa2_only`, `ap_bind`,
`station_count`, `dhcp_dns` (required) and `pmf`, `max_clients`, `client_isolation`
(optional). A required capability that a port cannot **prove** by read-back is
reported `False` and makes `start()` fail. The optional keys report `False` when
the port cannot enforce them. **Where a port cannot enforce the one-client limit
or client isolation, the session still starts and every associated client is fully
trusted — more than one client may control the target at once.**

### `ProvisioningError`
Carries only one of `unsupported`, `capability`, `entropy`, `network`, `state`.
The message and repr expose only that code — never a raw adapter error, network
detail, credential, or session field.

## Notes

- **Fail-closed security.** The AP is configured while the radio is stopped and
  every exposed setting (WPA2-only auth, AP-address binding, DHCP-advertised DNS,
  station counting) is read back and proven before the AP is trusted. It never
  beacons open, WEP, WPA1, mixed WPA/WPA2, or TKIP; anything that cannot be proven
  fails the start rather than falling back to a weaker mode.
- **One ESP32-S3 caveat.** ESP-IDF rejects an AP configuration unless the AP
  interface is already enabled in the Wi-Fi mode, and MicroPython's
  `WLAN.active(True)` fuses `esp_wifi_set_mode` with `esp_wifi_start` — so the
  interface cannot be enabled without starting the radio once. `esp32s3.py` starts
  and immediately stops the AP a single time per boot to enable the mode (ESP-IDF
  keeps it across `esp_wifi_stop`), then writes the credentials with the radio
  off. That priming window is shorter than one 100 ms beacon interval and carries
  only the ESP-IDF default SSID, but it is a real window: on this port the "never
  open, not even transiently" guarantee holds for every *configured* activation,
  including all rotations, not for the first mode enable. The Pico 2 W has no such
  window — the CYW43 driver accepts credentials while inactive.
- **Fresh secrets, no persistence.** All three secrets come from one 32-byte
  `os.urandom` read (SSID 4 B, password 12 B, CSRF 16 B), drawn only after the
  adapter confirms radio-backed entropy. The draw fails closed on a missing API,
  exception, wrong length, or an all-identical result. Nothing is persisted, so
  boot, crash, reset, and watchdog recovery always start from fresh credentials.
- **Bounded work per poll.** At most three sockets (one UDP, one TCP listener with
  backlog 1, one accepted connection); at most one DNS datagram and one HTTP
  read/parse/write step per `poll`. Fixed global token buckets allow HTTP 4/s
  burst 8 and DNS 20/s burst 40; overload is dropped or closed immediately. Limits:
  512 B DNS, 256 B request line, 16 headers, 2048 header bytes, 512 B body, 4096 B
  response; 2 s absolute and 2 s no-progress connection deadlines.
- **DNS.** One uncompressed class-IN QUERY only, for a fixed allow-list of
  captive-check names; `A` returns the AP IP, `AAAA` returns an empty success,
  unknown names return `NXDOMAIN`. `RA` is never set and nothing is forwarded.
- **HTTP.** One request per connection then `Connection: close`. Only the exact
  captive-probe `(host, path)` pairs redirect to the canonical URL; every response
  carries `Cache-Control: no-store`, `X-Content-Type-Options: nosniff`,
  `Referrer-Policy: no-referrer`, and CSP
  `default-src 'none'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'`.
- **Ports.** ESP32-S3 and Pico 2 W provision; the plain RP2040 has no radio and is
  an unsupported no-op. On host CPython the RP2040 adapter loads, so the package
  imports safely for tooling.

## Tests
No host tests ship with this iteration; the package is verified end-to-end on
hardware (see the repository verification notes). When tests are added they follow
the repo convention:
```
docker compose run --rm --build pytest /firmware-packages/wifi/tests
```
