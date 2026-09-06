# matter

Reusable MicroPython application API over the native ESP-Matter protocol
stack. MicroPython owns endpoint state, hardware behavior, and business logic.
ESP-Matter owns secure sessions, commissioning, fabrics, persistence, protocol
reads, and subscription delivery.

The package claims no GPIO and imports no board, pixel, timer, or async runtime.
Projects create endpoints before starting the node and decide how each remote
write affects their own hardware:

```python
import time

import matter

node = matter.Node()
light = node.create_endpoint(matter.EndpointType.ON_OFF_LIGHT)


node.start()
update_hardware(light.get(matter.Clusters.ON_OFF, matter.Attributes.ON_OFF))

while True:
    for event in node.poll():
        if isinstance(event, matter.WriteEvent) and event.endpoint is light:
            application_state["on"] = event.value
            update_hardware(event.value)
    time.sleep_ms(50)
```

`ON_OFF_LIGHT`, `DIMMABLE_LIGHT`, `EXTENDED_COLOR_LIGHT`, and `OCCUPANCY_SENSOR`
endpoints are supported, including multiple endpoints on one node. `get()`
reads Python-owned state hydrated from ESP-Matter persistence during
`Node.start()`. Restoration does not produce events.

`create_endpoint` also takes an `initial={(cluster, attribute): value}` mapping,
which writes those attributes into the stack before it starts. A pre-start write
is persistent, so naming an attribute there pins it on every boot and discards
whatever a controller last set it to; leave an attribute out and persistence
decides it. Reserve `initial` for state the application must own, never for
restating a schema default.

Extended Color Light applications can compare the Color Control mode with
`ColorMode.HUE_SATURATION`, `ColorMode.XY`, `ColorMode.COLOR_TEMPERATURE`, and
`ColorMode.ENHANCED_HUE_SATURATION`. These are protocol values only: projects
remain responsible for translating attributes into their own hardware output.

Occupancy endpoints expose `endpoint.occupancy` as the Matter bitmap values `0`
and `1`, not booleans. The read-only sensed value is not persisted and cannot
be supplied through `initial`; publish it after `Node.start()` and after every
reboot. The endpoint declares PIR because Matter has no radar modality, but
controllers act on Occupancy itself.

Local interfaces update application state and publish the corresponding
attribute so Matter subscribers observe the change:

```python
application_state["on"] = True
update_hardware(True)
light.set(on=True)
```

Named properties are read-only. `set()` validates all supplied names and values
before changing state, stores the complete MicroPython decision, and publishes
it in one bounded CHIP-task request. Native publication failure raises `OSError`
while retaining the requested Python values so the same call can be retried;
ESP-Matter cannot roll back an unexpected failure after an earlier value in a
batch was accepted.

Applications call `Node.poll()` regularly; 50 ms is the project default. The
native bridge retains only the latest remote value for each mirrored attribute,
so repeated controller writes between polls may coalesce. Different attributes
and the separate commissioning session/window states retain independent values
and share one revision sequence for deterministic delivery order. `poll()`
synchronizes every endpoint mirror, then returns an immutable ordered tuple of
`WriteEvent(endpoint, cluster, attribute, value)` and `CommissioningEvent`
objects; no application code runs inside it. A successful local publication
invalidates an older retained remote write for the same path.

Each commissioning event contains a `name` — `Commissioning.SESSION` or
`Commissioning.WINDOW` — and a
`state`: `STARTED`, `COMPLETE`, `FAILED`, `OPENED`, or `CLOSED`. The five states
are mutually distinct, so a subscriber can decide on `state` alone. `FAILED`
reports one failed attempt, not the end of pairing: the package reopens a
commissioning window whenever an unpaired node would otherwise stop advertising,
so a `FAILED` is normally followed by another `OPENED`. `start()` restores
mirrors without events; the first explicit poll returns retained startup state:

```python
node.start()
for event in node.poll():
    if isinstance(event, matter.CommissioningEvent):
        if event.state == matter.Commissioning.COMPLETE:
            update_hardware(False)
```

Every commissioning transition is also reported as structured JSON.

Node administration is available through `open_commissioning_window()`,
`fabrics()`, `remove_fabric()`, and `factory_reset()`. Fabric records expose
non-secret identifiers and labels only. All Python-originated mutations and
snapshot copies are scheduled onto the CHIP event loop. Python observes an
atomic generation and pulls changed state cooperatively, so it never runs on a
CHIP task or interrupt. Snapshot request failures raise `OSError` and remain
pending because `Node` commits its generation only after successful processing.

The first backend is the native ESP-Matter ESP32-S3 integration under
`native/`. The host `_matter` fake in `micropython_stubs` exercises the same
primitive boundary without a device. [ARCHITECTURE.md](ARCHITECTURE.md) diagrams
how the two native halves are called, which task each one runs on, and how they
are built.
