# matter

Reusable MicroPython application API over the native ESP-Matter protocol
stack. MicroPython owns endpoint state, hardware behavior, and business logic.
ESP-Matter owns secure sessions, commissioning, fabrics, persistence, protocol
reads, and subscription delivery.

The package claims no GPIO and imports no board, pixel, timer, or async runtime.
Projects create endpoints before starting the node and decide how each remote
write affects their own hardware:

```python
import matter

node = matter.Node()
light = node.create_endpoint(matter.EndpointType.ON_OFF_LIGHT)


def controller_write(event):
    application_state["on"] = event.value
    update_hardware(event.value)


light.on_write(controller_write)
node.start()
update_hardware(light.get(matter.Clusters.ON_OFF, matter.Attributes.ON_OFF))
```

`ON_OFF_LIGHT`, `DIMMABLE_LIGHT`, `EXTENDED_COLOR_LIGHT`, and `MODE_SELECT`
endpoints are supported, including multiple endpoints on one node. A Mode
Select endpoint takes a controller-facing description plus 1-16 ordered,
unique labels; each label's index is its mode value:

```python
pattern = node.create_endpoint(
    matter.EndpointType.MODE_SELECT,
    description="Pattern",
    modes=("None", "Breathe", "Rainbow"),
)
```

Controllers change `pattern.mode` through the standard Mode Select command,
and a local assignment publishes the new CurrentMode to subscribers. The
controller decides whether that endpoint appears as a dropdown, picker, or no
visible control.

`get()` reads the
Python-owned state, which is automatically hydrated from ESP-Matter persistence
during `Node.start()`. Restoration does not invoke callbacks.

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

Local interfaces update application state and publish the corresponding
attribute so Matter subscribers observe the change:

```python
application_state["on"] = True
update_hardware(True)
light.publish(matter.Clusters.ON_OFF, matter.Attributes.ON_OFF, True)
```

`on_write()` receives only controller-originated events. Each immutable event
contains `endpoint_id`, `cluster`, `attribute`, `value`, and `origin`. Local
publication echoes are recognized by origin and discarded before they are
queued, preventing callback feedback loops. Callback exceptions produce a
compact JSON error and do not stop subsequent delivery.

`on_commissioning()` subscribes to pairing transitions. Each immutable event
contains a `name` — `Commissioning.SESSION` or `Commissioning.WINDOW` — and a
`state`: `STARTED`, `COMPLETE`, `FAILED`, `OPENED`, or `CLOSED`. The five states
are mutually distinct, so a subscriber can decide on `state` alone. Register
before `start()`, which delivers whatever the stack queued while it was coming
up, and expect the callback on the MicroPython scheduler:

```python
def pairing_changed(event):
    if event.state == matter.Commissioning.COMPLETE:
        update_hardware(False)


node.on_commissioning(pairing_changed)
```

Every transition is reported as JSON whether or not anyone subscribes, and a
subscriber exception is contained exactly as an `on_write()` one is.

Node administration is available through `open_commissioning_window()`,
`fabrics()`, `remove_fabric()`, and `factory_reset()`. Fabric records expose
non-secret identifiers and labels only. All Python-originated mutations are
scheduled onto the CHIP event loop, while native events cross a bounded queue
and the MicroPython scheduler so Python never runs on a CHIP task or interrupt.

The first backend is the native ESP-Matter ESP32-S3 integration under
`native/`. The host `_matter` fake in `micropython_stubs` exercises the same
primitive boundary without a device. [ARCHITECTURE.md](ARCHITECTURE.md) diagrams
how the two native halves are called, which task each one runs on, and how they
are built.
