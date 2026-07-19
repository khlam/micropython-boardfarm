Implement secure Wi-Fi provisioning in two separated layers.

## 1. Shared firmware package

Create a reusable firmware package under:

`/home/khl/Documents/github/micropython-boardfarm/firmware-packages/<appropriate-wifi-provisioning-package-name>`

The package must expose the same documented, hardware-independent public API to all supported boards, initially ESP32 and RP2350. Keep all MCU-specific behavior inside narrow platform adapters. Code in consuming projects must not branch on ESP32 versus RP2350 for provisioning behavior.

The package is responsible for:

* Validating that the platform entropy source is ready before creating secrets.
* Generating fresh credentials for every provisioning session using only `os.urandom()`.
* Generating an SSID suffix from at least 4 random bytes.
* Generating a password from at least 12 random bytes, providing at least 96 bits of entropy.
* Generating an unpredictable per-session CSRF token using `os.urandom()`.
* Encoding credentials with a QR-safe character set such as uppercase hexadecimal or Base32.
* Validating SSID and password length limits and rejecting semicolons, commas, quotes, colons, backslashes, whitespace, control characters, and other characters requiring Wi-Fi QR escaping.
* Starting and stopping a WPA2-PSK-only SoftAP.
* Failing closed if WPA2-only security cannot be configured; never temporarily or permanently start an open AP.
* Disabling the station interface while provisioning unless the existing platform architecture strictly requires it.
* Preventing NAT, routing, bridging, and Internet forwarding.
* Binding DNS and HTTP sockets specifically to the SoftAP address where supported.
* Enabling PMF in optional mode when exposed by the MicroPython port.
* Supporting one-client limits and SoftAP client isolation where available.
* Reporting all relevant platform capabilities through a deterministic capability API.
* Treating WPA2-only operation and SoftAP isolation from other interfaces as required capabilities.
* Reporting and documenting unsupported optional controls rather than silently weakening behavior.
* Tracking client association state.
* Implementing defensive captive-portal DNS handling.
* Responding only to supported DNS query types and captive-portal use cases.
* Ignoring malformed, truncated, recursive, oversized, or unsupported DNS requests.
* Never forwarding DNS requests to an upstream resolver.
* Ensuring DNS responses are not substantially larger than their requests.
* Redirecting recognized plain-HTTP captive-portal checks to a canonical configuration URL.
* Never intercepting HTTPS, impersonating TLS endpoints, generating misleading certificates, or downgrading arbitrary HTTPS traffic.
* Providing bounded HTTP parsing and serving primitives for project-defined fixed routes.
* Supporting CSRF-token validation for state-changing requests.
* Enforcing absolute provisioning timeouts and no-associated-client timeouts.
* Cleaning up sockets, interfaces, credentials, tokens, and adapter state after normal shutdown or exceptions.
* Restoring the prior networking state when provisioning ends.

Design the package to remain safe under thousands of simultaneous connection attempts. This means it must:

* Use a small, fixed maximum number of active sockets.
* Use bounded request, header, body, and DNS buffers.
* Define maximum request-line length, header count, total header bytes, body bytes, and DNS packet size.
* Use short read, write, connection, and idle timeouts.
* Apply a bounded request rate.
* Reject excess connections or requests immediately with a small response or connection close.
* Never allocate queues, tasks, buffers, or session objects in proportion to offered traffic.
* Process at most one HTTP request per connection.
* Close every HTTP connection after its response.
* Reject HTTP pipelining.
* Reject chunked request bodies.
* Reject missing, malformed, duplicate, or oversized `Content-Length` values on POST requests.
* Reject multipart uploads, WebSockets, and persistent keep-alive connections.
* Avoid a general-purpose web framework unless one is already an unavoidable project dependency.

The package must never provide or enable:

* Open Wi-Fi.
* WEP, WPA1, WPA/WPA2 mixed mode, or TKIP fallback.
* NAT, routing, bridging, or Internet forwarding.
* HTTPS interception or TLS impersonation.
* Recursive or upstream DNS resolution.
* Filesystem browsing or arbitrary file access.
* Directory listings.
* Firmware or file uploads.
* Arbitrary imports.
* Command execution.
* REPL access.
* Package-management endpoints.
* Source-code or traceback exposure.
* Generic file read/write routes.

Expose a small, deterministic API with operations equivalent to:

* Capability discovery.
* Provisioning-session creation.
* `start(config)`.
* `poll()`.
* Association or client-count status.
* Bounded request-dispatch hooks for application routes.
* `stop()`.

Use the same method names, arguments, return types, state transitions, and error categories on ESP32 and RP2350. Keep credentials and CSRF tokens inside session-scoped objects and avoid exposing them through object representations, diagnostic output, exceptions, or adapter state. Return only small, stable, redacted error codes.

Never print, log, persist, or transmit credentials or CSRF tokens over serial. Do not store them in project configuration files. Remove references to them and overwrite mutable secret buffers where practical when the session ends.


## 2. `led-effects` project integration

Modify:

`/home/khl/Documents/github/micropython-boardfarm/projects/led-effects`

The project must call the new shared firmware package and contain only project-specific integration, OLED presentation, LED controls, validation, persistence, and provisioning lifecycle logic. Do not duplicate general Wi-Fi, DNS, HTTP parsing, captive-portal, rate-limiting, or platform-adapter functionality inside the project.

Provisioning may start only after the deliberate physical distance-gauge trigger.

After the deliberate trigger, create a new provisioning session through the shared package. Display only an OLED QR code containing:

`WIFI:T:WPA;S:<ssid>;P:<password>;;`

Do not display additional credentials, instructions, PINs, login prompts, or authentication challenges. The SoftAP password is the sole user-facing authentication credential.

Use the shared package’s captive-portal and HTTP facilities to provide a small, fixed-route, no-JavaScript LED configuration page. Do not load external scripts, fonts, styles, analytics, CDNs, or Internet resources.

The configuration page must support only:

* Setting LED colors using exactly one documented format, preferably exactly six hexadecimal digits per color.
* Resetting LED behavior to random mode.

The reset operation must affect only LED behavior. It must not erase unrelated configuration, firmware, network settings, or device state.

All state-changing operations must:

* Use POST.
* Require the current session’s CSRF token in a hidden form field.
* Use a valid, bounded `Content-Length`.
* Validate the `Host` header.
* Accept only the SoftAP IP address and one documented local hostname as valid POST hosts.
* Reject captive-portal detection hostnames for POST requests.
* Validate `Origin` when it is present.
* Reject cross-origin state-changing requests.
* Avoid enabling CORS.
* Never return `Access-Control-Allow-Origin: *`.
* Reject unknown fields.
* Reject duplicate fields.
* Reject missing required fields.
* Reject malformed form encoding.
* Reject oversized values.
* Reject extra path components.
* Reject trailing unparsed input.
* Validate every LED value completely before changing or persisting state.

GET requests, captive-portal probes, redirects, favicon requests, image requests, malformed requests, and failed validation must never alter LED state or persistent configuration.

Serve only a fixed route set, such as:

* A canonical GET route for the configuration page.
* One POST route for validated LED color changes.
* One POST route for resetting LED behavior to random mode.
* A small fixed set of captive-portal detection routes handled through the shared package.
* An optional fixed favicon response that performs no state changes.

Escape every dynamic value before inserting it into HTML. Never insert request values directly into HTML, HTTP headers, redirects, CSS, logs, or error messages.

Include defensive response headers where compatible:

* `Cache-Control: no-store`
* `X-Content-Type-Options: nosniff`
* `Referrer-Policy: no-referrer`
* A restrictive Content Security Policy that permits only the page’s required inline form and styling behavior.

Persist LED settings only after complete validation. Use an atomic write or the project’s existing safe configuration mechanism so a reset or power loss cannot leave a partially written configuration.

Return generic error pages or small error responses. Never expose:

* Internal exception messages.
* Tracebacks.
* Memory addresses.
* Filesystem paths.
* Wi-Fi credentials.
* CSRF tokens.
* Device identifiers.
* Platform-adapter diagnostics.

Provisioning must stop immediately when:

* The user leaves distance-gauge mode.
* A valid LED configuration operation succeeds.
* The LED behavior is successfully reset to random mode.
* The configurable absolute timeout expires, defaulting to 10 minutes.
* The configurable no-associated-client timeout expires.
* A fatal provisioning error occurs.

Use a guaranteed `finally`-style cleanup path. Cleanup must:

* Stop project request handling.
* Close all HTTP and DNS sockets through the shared package.
* Deactivate the SoftAP.
* Clear the OLED QR code.
* Discard the session credentials and CSRF token.
* Overwrite mutable secret buffers where practical.
* Restore the prior networking state.
* Restore the appropriate prior or newly configured LED state.
* Ensure watchdog recovery cannot automatically restart provisioning.

Add a short project security note documenting:

* The deliberate physical trigger.
* The shared package boundary.
* Project-owned routes.
* LED input representation and validation.
* Provisioning lifetime.
* Cleanup behavior.
* Persistent-setting behavior.
* The fact that anyone who views or obtains the QR code may configure the LEDs during that provisioning session.

Do not write automated tests yet.

Add a concise manual verification checklist covering:

* Identical project-facing API behavior on ESP32 and RP2350.
* No open-AP or legacy-security fallback.
* Fresh SSID, password, and CSRF token for every session.
* Provisioning never starting after ordinary boot, reset, crash, or watchdog recovery.
* HTTP and DNS being unreachable outside the SoftAP interface.
* The station interface being disabled where possible.
* No NAT, routing, bridging, or forwarding.
* Correct optional capability reporting for PMF, client limits, and isolation.
* Successful QR scanning and SoftAP joining without another login or PIN.
* Captive-portal redirection over plain HTTP.
* No HTTPS interception.
* Timeout and no-client cleanup.
* Immediate cleanup when distance-gauge mode ends.
* Cleanup after exceptions.
* Malformed DNS packet rejection.
* Malformed HTTP request rejection.
* Oversized request rejection.
* Excess-connection load shedding.
* No memory growth proportional to simultaneous connection attempts.
* CSRF-token rejection.
* Invalid `Host` rejection.
* Cross-origin POST rejection.
* GET requests causing no state changes.
* Unknown and duplicate form fields being rejected.
* LED settings being persisted only after full validation.
* The reset action changing only LED behavior to random mode.
* Credentials and CSRF tokens being absent from logs, serial output, exceptions, configuration files, and persistent storage.
