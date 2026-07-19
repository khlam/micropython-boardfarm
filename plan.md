# Secure Wi-Fi provisioning plan

Implement provisioning in two layers: a reusable `wifi` firmware package and a
small `led-effects` integration. Paths are relative to the repository root.

## Current `led-effects` context

- `projects/led-effects/firmware/main.py` runs one cooperative loop at about
  50 fps, drives 20 WS2812B LEDs through four deterministic effects, and enters
  a smooth distance gauge after a steady VL53L0X reading. Network work must fit
  this loop without threads or `asyncio`.
- Run Wi-Fi provisioning continuously from boot as a background service in the
  same cooperative loop; it is not tied to the distance gauge. The gauge and its
  `HOLD_MS`/`RELEASE_MS=1000` transitions still drive the LED display, but never
  start, stop, or gate provisioning.
- The 128x64 SSD1306 is required to provision: it continuously displays the QR
  for the currently valid credentials. The sensor is optional and affects only
  the LED gauge. Preserve normal degraded behavior; without a working OLED, run
  effects and the gauge but do not provision.
- The same firmware builds for ESP32-S3 Zero, Pico 2 W/RP2350, and non-Wi-Fi
  RP2040. The package must import safely and expose the same API on all three;
  RP2040 reports unsupported and continues running effects and the gauge.
- Keep all serial output as compact JSON through `emit()`. `manifest.py`
  automatically freezes imported shared packages and their transitive
  dependencies, so importing `wifi` needs no package-specific manifest edit.

## Fixed defaults

| Item | Decision |
| --- | --- |
| Target adapters | ESP32-S3 Zero and Pico 2 W/RP2350; RP2040 is an unsupported no-op adapter |
| Provisioning lifecycle | Start provisioning at boot and keep it running continuously, independent of the gauge. Regenerate all credentials at startup and again every 10 minutes, tearing the AP down and bringing it back up under fresh secrets on each rotation |
| Gauge trigger | Enter gauge mode when the steady hold reaches `HOLD_MS`; set `RELEASE_MS=1000` so one continuous second without an object exits gauge mode. The gauge drives only the LED display |
| Credentials | SSID `LEDFX-` + 8 uppercase hex characters from 4 random bytes; 24-character uppercase hex password from 12 bytes; 32-character uppercase hex CSRF token from 16 bytes |
| Network | Visible WPA2-PSK/CCMP AP, channel 6, `192.168.4.1/24`, canonical URL `http://192.168.4.1/`, local alias `led-effects.test` |
| Credential rotation | Every 600 seconds generate new secrets, restart the AP under them, and redraw the OLED QR. The AP never stops on its own while the OLED works; there is no no-client timeout |
| OLED | Continuously display only the QR for the currently valid credentials, redrawn on each rotation. Never blank it while provisioning is running |
| LED modes | `solid` applies one `RRGGBB` color to all 20 LEDs; `random` chooses among the four existing effects every 200 frames and is the boot default |
| Project routes | `GET /`, `POST /color`, and `POST /random` only |

## 1. Shared `wifi` package

### Layout and API

Create `firmware-packages/wifi/` with `pyproject.toml`, `README.md`, and an inner
`wifi/` package. Keep session, DNS, and HTTP code platform-neutral. Lazy-load
ESP32-S3, RP2350, and RP2040 adapters using the dispatch pattern established by
`boot_status_led`; never make the consuming project branch by chip.

Expose this exact API:

- `Config(ssid_prefix, ap_ip, netmask, channel, local_hostname,
  absolute_timeout_ms, no_client_timeout_ms)` is a fixed-size immutable record;
  unknown configuration fields are impossible.
- `Request(method, path, form)` contains only bounded, fully parsed values after
  generic HTTP, host, origin, and CSRF validation. `Response(status, body,
  terminal=False)` accepts only a fixed HTML body no larger than the response
  limit; the package owns all headers.
- `capabilities() -> dict` always returns the boolean keys `supported`,
  `wpa2_only`, `ap_bind`, `station_count`, `dhcp_dns`, `pmf`, `max_clients`, and
  `client_isolation`. The first five are required; the last three are optional
  and must report `False` when the port cannot enforce them.
- `quiesce() -> None` idempotently forces AP and station interfaces down and
  verifies that state. It is a no-op on RP2040.
- `create_session(config, handler) -> Session` validates the config, obtains the
  session randomness, and accepts a `handler(request, csrf_form_value) ->
  Response`. The token argument exists only for rendering the hidden GET form
  field and must never be logged or retained after the call.
- `Session.qr_payload() -> str` is available only in `NEW`; `start()` transitions
  `NEW -> ACTIVE`; `client_count() -> int` reads association state; `stop()` is
  idempotent and transitions `NEW` or `ACTIVE` to `STOPPED`.
- `Session.poll(now_ms) -> str | None` does bounded nonblocking work. It returns
  `complete` after a successful configuration POST as a non-terminal notification
  and keeps serving; the terminal events `absolute_timeout` and `fatal` mean the
  session must be stopped, and `no_client_timeout` fires only when that timeout is
  enabled. Ordinary and rejected requests return `None`.

Invalid transitions and fatal setup raise `ProvisioningError` with only
`unsupported`, `capability`, `entropy`, `network`, or `state` as its code. Do
not include raw adapter errors or session data in the exception or object repr.

### AP and secret invariants

`led-effects` owns no network connection: call `quiesce()` once at boot, and
disable provisioning for that boot if it fails. A session must also refuse to
start unless both interfaces are still inactive. This avoids trying to restore
a station connection from insufficient MicroPython state and clears an AP left
active by a soft reset or watchdog recovery.

Configure the fixed IP, DHCP/DNS advertisement, SSID, password, and exact
WPA2-PSK/CCMP mode while the AP is down; read back every exposed setting before
activation. Bind DNS and HTTP to the AP address, never a wildcard. If either
target cannot prove exact WPA2-only mode, AP-address binding, station counts,
DHCP DNS, or teardown, its adapter must report the capability false and start
must fail. Configure PMF optional mode, a one-client limit, and client-to-client
isolation only when the adapter reports that it can enforce them. Where a port
cannot enforce the one-client limit or isolation, the session still starts, so
every associated client is fully trusted: multiple clients may associate at once
and each can drive the LEDs. Record which ports fall into this case during
verification.

Never configure an open, WEP, WPA1, mixed WPA/WPA2, or TKIP state, including
temporarily. Do not add NAT, routing, bridging, forwarding, or upstream DNS.
Cleanup closes sockets, calls `ap.active(False)`, and verifies the AP is down;
do not depend on a `WLAN.deinit()` method or reactivate the station interface.

Draw secrets only after the adapter confirms the radio hardware is initialized,
so ports whose hardware RNG is fully seeded only once the RF subsystem is active
(notably ESP32-S3, where `os.urandom` degrades toward a PRNG before Wi-Fi is
brought up) never generate credentials from weak entropy; an adapter that cannot
confirm radio-backed entropy must fail with `entropy`. Split one 32-byte
`os.urandom()` result according to Fixed defaults. Fail on a missing API,
exception, wrong-length result, or a result whose bytes are all identical — which
covers the all-zero stuck-source case as well as a source stuck on any constant
byte; never substitute timestamps, MAC addresses, a PRNG, or a home-grown entropy
test. Validate the
final ASCII and Wi-Fi lengths and reject every QR delimiter, whitespace, control
character, backslash, quote, comma, and colon before starting.

### Bounded DNS and HTTP

Steady-state `poll()` must preserve the 20 ms loop cadence. Use at most three
sockets: one nonblocking UDP listener, one nonblocking TCP listener with backlog
1, and one accepted TCP connection. Each poll handles at most one DNS datagram
and one HTTP parse/write step, with no traffic-proportional queues or state.

- Limits are 512 bytes per DNS packet, 256 bytes per request line, 16 headers,
  2048 total header bytes, 512 body bytes, and 4096 response bytes. An accepted
  connection has a two-second absolute deadline and two-second no-progress
  deadline. Fixed global token buckets allow HTTP 4/second with burst 8 and DNS
  20/second with burst 40; overload is closed or dropped immediately.
- Process one request per connection, then send `Connection: close`. Reject
  pipelining, chunking, keep-alive, multipart, WebSockets, body-bearing GETs,
  and missing, duplicate, malformed, or oversized POST `Content-Length`.

DNS accepts one uncompressed class-`IN` `QUERY` for these exact names:
`led-effects.test`, `connectivitycheck.gstatic.com`, `captive.apple.com`,
`www.msftconnecttest.com`, `www.msftncsi.com`, and
`detectportal.firefox.com`. Type `A` returns `192.168.4.1`; type `AAAA` returns a
successful empty answer. Accept recursion-desired but set `RA=0` and never
forward. Reject malformed, truncated, compressed, multi-question, extra-record,
unsupported-type, and oversized packets. Return `NXDOMAIN` for unknown names;
responses remain at most 512 bytes and no more than 32 bytes larger than the
request.

HTTP accepts only versions 1.0 and 1.1 and requires exactly one valid `Host` on
every request. `GET /` accepts only the AP IP or local alias. Redirect only these
exact probe pairs to the canonical URL:

- `connectivitycheck.gstatic.com/generate_204`
- `captive.apple.com/hotspot-detect.html`
- `www.msftconnecttest.com/connecttest.txt`
- `www.msftncsi.com/ncsi.txt`
- `detectportal.firefox.com/canonical.html`

Return a small generic response or close for malformed input. Never intercept
HTTPS, generate certificates, downgrade arbitrary hosts, or forward requests.

## 2. `led-effects` integration

### Lifecycle and OLED

Provisioning is a continuous background service, not a gauge episode. Once the
boot `quiesce()` succeeds and the OLED is confirmed working, generate the first
set of credentials, create and start a session, and render its QR. If `quiesce()`
fails, the OLED is missing, or the initial QR/setup or a required capability
fails, disable provisioning for the boot and keep running effects and the gauge
normally.

Rotate credentials every 10 minutes. Set `absolute_timeout_ms` to 600000 and
disable the no-client timeout (`no_client_timeout_ms` set so it never fires), so
`poll()` returns `absolute_timeout` exactly at each rotation boundary. On that
signal, tear the session down through the normal `finally` path — zeroing the old
bitmap and secret buffers — then generate fresh secrets, create and start a new
session, and draw its QR before resuming. Rotation drops any associated client;
they rejoin with the new QR. A `fatal` event tears down the same way and rebuilds
on the next rotation attempt; if setup keeps failing, leave provisioning disabled
for the boot without disturbing effects or the gauge.

Before each `Session.start()`, render its exact payload
`WIFI:T:WPA;S:<ssid>;P:<password>;;` as a fixed byte-mode QR Version 4/M. The
56-byte payload fits its 62-byte capacity; with a four-module quiet zone, draw
the centered 41x41 bitmap at one OLED pixel per module. Reject any other size.
Display only that QR, with no text, PIN, instructions, or login prompt. A draw or
flush failure prevents activation. The OLED continuously shows the QR for the
currently valid credentials and is redrawn only on rotation; never blank it while
provisioning is running. A later OLED failure stops provisioning, because a stale
or blank display can no longer prove the shown QR matches the live credentials;
blank and flush it if possible on that stop.

The distance gauge and LED effects run independently of provisioning. Distinguish
an in-range distance, confirmed out-of-range, and a sensor error; only confirmed
out-of-range samples advance the one-second gauge-release timer, and errors
preserve the current state. Gauge entry and exit change only the LED display —
never provisioning — and gauge exit resumes the latest valid LED setting:
random/default mode when no solid color is configured, or the persisted solid
color after a successful color operation.

Continue gauge rendering, distance sampling, and nonblocking network polling
every loop. WLAN setup, OLED flush, and any small durable settings commit are
one-off transition operations and may pause a frame; measure them, but do not
permit steady-state network or rotation traffic to stall the loop. A successful
POST applies its LED setting and returns success but does not stop the AP; the
portal and QR stay up until the next rotation. Keep no persistent session or
re-arm flag, so boot, crash, reset, and watchdog recovery always start from a
fresh first rotation and cannot resume an earlier session or its secrets.

### Routes and validation

- `GET /` serves one self-contained, no-JavaScript HTML page with a text field
  for uppercase `RRGGBB` and separate POST forms. Insert the supplied CSRF value
  only into hidden fields and HTML-escape every dynamic value. Load no external
  scripts, styles, fonts, images, analytics, CDNs, or Internet resources. The page
  carries no CSS — no `<style>` block and no `style` attributes — so the strict CSP
  below (`default-src 'none'` with no `style-src`) applies with nothing relaxed;
  rely on plain semantic HTML for layout.
- `POST /color` accepts exactly `csrf` and `color`, with `color` matching ASCII
  `[0-9A-F]{6}`; `POST /random` accepts exactly `csrf`. Persist the requested
  mode completely before returning a terminal success.
- Both POSTs require exactly `Content-Type: application/x-www-form-urlencoded`,
  a valid bounded body, no query or trailing path, and a matching token. After
  ASCII lowercase and optional exact `:80` removal, accept only
  `192.168.4.1` and `led-effects.test` as hosts. If `Origin` is present, require
  its corresponding exact `http://` origin. Do not enable CORS.
- Reject unknown, duplicate, missing, empty, malformed percent-encoded, or
  oversized fields before touching RAM state or storage. GETs, redirects,
  rejected input, and validation or persistence failures are read-only. Unknown
  paths return 404 and unsupported methods return 405.

Every response adds `Cache-Control: no-store`,
`X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`, and the exact
CSP `default-src 'none'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'`.

### LED state and persistence

In random mode, use `os.urandom(1)` to select one of the existing four effects
at each 200-frame boundary; solid mode continuously renders the configured RGB
value whenever the gauge is unlocked.

Use exactly these records, with `N` an integer from 0 through `2^31-1`:
`{"version":1,"generation":N,"mode":"solid","color":"RRGGBB"}` and
`{"version":1,"generation":N,"mode":"random"}`. Compare generations with
modulo-`2^31` serial-number arithmetic so wraparound is unambiguous.

Alternate `/led-effects-0.json` and `/led-effects-1.json`. Write a temporary
file in the same directory, flush and `os.sync()`, remove only the inactive slot,
rename the temporary file into it, then reread and validate before applying.
The active generation remains intact through interruption. At boot, choose the
newest fully valid record; missing or corrupt records select random mode. A
failed commit changes neither LEDs nor active settings, and `/random` changes no
state outside these records.

### Cleanup and prohibited surface

Use one guaranteed `finally` path around each session — run on every rotation and
on final shutdown — to call idempotent `Session.stop()`, verify all sockets and
the AP are down, zero the QR bitmap and other mutable secret/protocol buffers, and
release immutable secret/session references before the next session's secrets are
generated. On final shutdown or an OLED-failure stop, also blank and flush the QR
and leave the base LED state correct; on a rotation the next session redraws the QR
immediately. MicroPython cannot guarantee erasure of immutable strings or driver
copies; do not claim otherwise. Emit only fixed redacted JSON codes through `emit()`.

Neither layer may offer filesystem or directory browsing, generic file routes,
uploads, arbitrary imports or execution, REPL or package-management access,
source or traceback disclosure, CORS, a web framework, or a third-party runtime
dependency. Never expose memory addresses, device identifiers, adapter details,
credentials, QR payloads, or CSRF tokens in responses, logs, serial, exceptions,
reprs, or persistent storage, except for the CSRF token in its intended hidden
configuration-page fields.

## Documentation and verification

Add `wifi` to the `AGENTS.md` Routing table and document the package contract and
limits above in its README. Update the project README with continuous boot-time
provisioning, 10-minute credential rotation, the always-on OLED QR, the `HOLD_MS`
gauge trigger and one-second release for the LED display only, routes, modes,
persistence, cleanup, and the fact that anyone who can see the OLED QR can
configure the LEDs until the next rotation. State the accepted-risk consequence
explicitly: the AP broadcasts and accepts a client continuously for the device's
entire uptime — not only during a deliberate provisioning window — so this
exposure is permanent while the OLED works, and on ports that cannot enforce the
one-client limit or client isolation more than one client may control the LEDs at
once.

Do not add automated tests in this iteration. Run the existing Dockerized suite
and compile both firmware targets, then verify manually:

- Both Wi-Fi targets have API parity and prove required capabilities, exact
  WPA2-only operation, interface isolation, QR join, fresh secrets, captive
  redirects, and honest optional capabilities; RP2040 never starts an AP.
- Verify provisioning starts at boot, the OLED continuously shows the QR for the
  live credentials, and every 10 minutes the credentials rotate: fresh secrets, a
  redrawn QR, a restarted AP that the old QR can no longer join and the new QR can,
  and any connected client dropped. RP2040 never starts an AP. Missing OLED,
  reset/watchdog recovery, later OLED failure, and injected exceptions leave no
  network or session artifacts and never resume old secrets.
- Verify the gauge is fully decoupled from provisioning: `HOLD_MS` entry and one
  second of confirmed inactivity change only the LED display, and on every gauge
  exit the LEDs resume random/default mode or the latest persisted solid color,
  including after successful configuration and failure.
- Malformed, oversized, cross-origin, bad-host, bad-CSRF, pipelined, and excess
  DNS/HTTP traffic is rejected with bounded memory and no steady-state cadence
  loss or LED/settings changes.
- Power interruption at each commit phase retains a valid generation; only a
  fully validated operation changes the intended LED state, and no secret
  appears in serial JSON, errors, configuration, storage, or an unintended
  response field.
