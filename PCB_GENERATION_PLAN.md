# PCB Generation Plan

## Goal

Use each project's firmware wiring table as the logical input for a standalone
workflow that can generate fabrication-ready files for a custom through-hole
prototyping PCB. The output should describe a normal 2-layer rigid PCB with
plated through-hole pads, copper traces, solder mask openings, optional
silkscreen labels, board outline, and drill files.

The local generation job should also create or update
`projects/<project>/WIRING.MD` from the same parsed wiring model so
human-readable wiring documentation and fabrication output are derived from one
source.

`WIRING.MD` is committed generated documentation. CI should regenerate the
expected content in a temporary location and fail when the checked-in file is
stale or inconsistent.

This plan is intentionally implementation-free. It describes the shape of the
work before any code is written.

## Current Firmware Wiring Model

Each project keeps its authoritative logical wiring in
`projects/<project>/firmware/`.

Current pattern:

- A `Board = namedtuple(...)` declares the available wiring fields.
- A top-level `BOARD = Board(...)` value is selected by
  `os.uname().machine`.
- Fields are plain GPIO numbers or peripheral ids.
- Project firmware passes those fields to package drivers as flat keyword
  arguments.
- Drivers open their own buses internally; projects never construct or pass bus
  objects.

PCB-generation-capable firmware must also define the complete board-to-breakout
wiring in `main.py` using a static project-library syntax that the PCB parser can
read without importing the firmware. That declaration owns two things: each
breakout connector's complete pad list in physical order, and every routed net —
signal, power, ground, and any optional control line such as `AD0`, `LPN`, or
`XSHUT` when connected. Connector pad names are opaque labels; the declaration
is the only source of breakout pin count, pin order, and pad naming. No copper
connection should be invented by the hardware library.

The project-library guard should enforce that:

- Every driver constructor argument that consumes a physical `BOARD` field is
  represented in the explicit firmware wiring declaration.
- Every firmware-declared net resolves to a pad on the target MCU board or in a
  declared connector pad list.
- Each connector declares its full pad set, with no duplicate pad names.
- Metadata fields such as `name`, `i2c_id`, and `uart_id` cannot create routed
  nets.
- Power and ground choices are explicit in firmware wiring, not supplied by
  defaults.

Declared connector pin order is trusted as physically correct. The generator
cannot detect a declaration whose pad order differs from the real module; that
risk is accepted and owned by the firmware author.

Current project shapes:

| Project | Driver | Board fields | Firmware connection fields |
| --- | --- | --- | --- |
| `distance-stream` | `VL53L0X` | `name`, `sda`, `scl` | `sda`, `scl` |
| `multizone-ranging` | `VL53L5CX` | `name`, `sda`, `scl` | `sda`, `scl` |
| `compass` | `QMC5883P` | `name`, `i2c_id`, `sda`, `scl` | `sda`, `scl` |
| `gyro-stream` | `MPU6050` | `name`, `i2c_id`, `sda`, `scl` | `sda`, `scl` |
| `gps` | `GPS` | `name`, `uart_id`, `tx`, `rx` | `tx`, `rx` |

The table reflects today's signal-only firmware pattern. PCB generation should
not produce boards for a project until that project's `main.py` has been
migrated to the explicit wiring declaration, including connector pad lists,
power, and ground.

The user or agent writing firmware is responsible for choosing correct logical
connections. The PCB workflow should faithfully translate those connections into
documentation and board files. It should not second-guess firmware by silently
rewriting pins, choosing alternate GPIOs, or inferring a different bus. It may
fail fast on missing firmware wiring declarations, unknown target-board names,
pads that do not resolve on the MCU board or in a declared connector, or
physically impossible mappings.

## Important Parser Boundary

Do not import project firmware to extract wiring.

Every current `main.py` calls `main()` at module import time. A PCB parser
should use static Python AST parsing instead of executing the firmware.

The parser should extract:

- `Board = namedtuple(...)` field names.
- Each machine-dispatched `BOARD = Board(...)` branch.
- The explicit project-library wiring declaration: each connector's ordered pad
  list plus all pad-to-pad nets.
- Target board names such as `RP2040-Zero`, `RP2350`, and `ESP32-S3-Zero`.
- Driver constructor calls that consume `BOARD` fields, such as
  `VL53L0X(sda=BOARD.sda, scl=BOARD.scl)` — used only as a consistency lint
  (every consumed `BOARD` field must appear in a declared net), never as a
  source of nets.

## Intermediate PCB Intent Model

Normalize parsed firmware into a small, explicit model before any PCB
generation. The model has three parts: the target MCU board, the declared
connectors, and the declared nets.

Example conceptual output for `distance-stream` on `RP2040-Zero`:

```text
project: distance-stream
target_board: RP2040-Zero
connectors:
  J1: 2.54 mm single-row header, pads in physical order:
      VIN, GND, SDA, SCL, GPIO1, XSHUT
nets:
  VIN: MCU.5V  -> J1.VIN
  GND: MCU.GND -> J1.GND
  SDA: MCU.GP0 -> J1.SDA
  SCL: MCU.GP1 -> J1.SCL
```

Treat every firmware-defined connection as an undirected net between plated
through-hole pads, including power and ground. All connector-side pad names are
opaque labels: `SDA`, `XSHUT`, and `FOO` are treated identically. The generator
never infers protocol semantics, buses, directions, or defaults from names.
Fields such as `name`, `i2c_id`, and `uart_id` are metadata and do not create
copper traces.

The model includes every MCU header pad and every declared connector pad,
connected or not; unconnected pads become isolated plated through-holes with
solder mask openings and silkscreen labels.

## Hardware Library: MCU Boards and a Generic Connector

Add a data-only hardware library that supplies the physical facts missing from
firmware. A likely location is `tools/pcbgen/hardware/`. It contains exactly
two kinds of definitions.

### MCU board definitions

One entry each for:

- `rp2040_zero`
- `rp2350`
- `esp32_s3_zero`

The three supported MCU boards are defined and static. Their physical header
maps should be checked in as explicit hardware-library data rather than inferred
from firmware or README diagrams. Each MCU entry defines:

- Human-readable name.
- The complete left/right through-board header geometry: ordered physical pads
  with coordinates on the 2.54 mm grid.
- Canonical pad names plus GPIO-number aliases — `0`, `GP0`, and `GPIO0` all
  resolve to the same physical header coordinate — because `BOARD` fields are
  plain integers.
- Supply-pad identities: which pads are 5V-class (`5V`/`VBUS`), `3V3`, and
  `GND`.
- Board body outline for placement and board sizing.
- Silkscreen labels.

Assume each MCU board is soldered to headers along its left and right pin
columns, so every physical MCU header pin gets a plated through-hole pad even
when no firmware-defined connection uses it.

### Generic breakout connector template

One parameterized template: an N-pin 2.54 mm plated through-hole header, single
row by default with a dual-row option, using drill, pad, pin-1 marking, and
silkscreen geometry from the Physical Constants table.

There are no per-module hardware entries. Breakout pad names, pin count, and
pin order come entirely from the firmware wiring declaration; the library
treats pad names as opaque labels used for net endpoints and silkscreen. The
library carries no peripheral knowledge — no module voltage rules, no
control-pin semantics, no breakout-side aliases — and never defines a power,
ground, or signal connection.

Every declared connector pad gets a plated through-hole pad even when no
firmware-defined connection routes to it. Unconnected connector pads remain
isolated pads with solder mask openings and silkscreen labels.

## Physical Constants

Use conservative constants for the initial through-hole prototyping PCB
generator. Override them only when a hardware-library entry explicitly requires
different geometry.

Recommended initial constants:

| Constant | Value | Notes |
| --- | --- | --- |
| Header pitch | `2.54 mm` | Standard 0.1 inch header spacing. |
| Grid pitch | `2.54 mm` | Matches header pitch and keeps routing perfboard-like. |
| Header pin nominal size | `0.64 mm square` | Common square header post size. |
| Plated through-hole diameter | `1.00 mm` | Conservative fit for standard 0.64 mm square posts. |
| Copper pad diameter | `2.00 mm` | Robust annular ring for hand soldering. |
| Trace width | `0.40 mm` | Easy fabrication and hand-inspection margin. |
| Copper clearance | `0.25 mm` | Conservative for common low-cost 2-layer PCB fabrication. |
| Board edge margin | `2.00 mm` | Minimum distance from routed copper/pads to outline. |
| Standard board sizes | `50x50`, `50x70`, `70x100`, `100x100 mm` | Try in order and choose the smallest size that fits. |
| Silkscreen text height | `1.00 mm` | Legible without consuming much board area. |
| Silkscreen stroke | `0.15 mm` | Typical manufacturable text stroke. |
| Solder mask expansion | KiCad default unless overridden | Let KiCad/fabricator defaults handle common mask openings first. |

These constants are assumptions for the generated carrier/perfboard PCB, not
firmware behavior. The static MCU board definitions own their exact pin counts,
pin order, aliases, and coordinates; connector pin counts, order, and names
come from each project's firmware wiring declaration.

## PCB Generator Strategy

Prefer generating a KiCad PCB file first, then exporting Gerbers and drill files
with KiCad CLI inside Docker.

Do not hand-write Gerber as the primary output format unless there is a strong
reason later. KiCad gives us a standard board model, DRC, layer handling, and
well-tested fabrication exporters.

Target generated artifacts:

- `.kicad_pcb`
- One MCU-specific Gerber fabrication output per project target for now.
- Gerber copper layers: `F.Cu`, `B.Cu`.
- Solder mask layers: `F.Mask`, `B.Mask`.
- Silkscreen layers: at least `F.SilkS`.
- Board outline: `Edge.Cuts`.
- Excellon drill files for plated through-holes.
- Fabrication zip.

Generated PCB artifacts should not be committed. Save them under `projects/<project>/outputs/`.

When this plan says one Gerber output per MCU, treat that as one generated
fabrication package per MCU target. The package may contain multiple standard
Gerber layer files plus drill files, because PCB fabricators expect layer-specific
Gerbers rather than one monolithic file.

The committed PCB design state should be the generator, the hardware library,
and the generated `WIRING.MD` files. Docker/CI wiring and tests are workflow
source. KiCad files, Gerbers, drill files, fabrication zips, and other PCB build
products should be reproducible from source and left uncommitted.

Initial generated targets:

- `RP2040-Zero`
- `RP2350`
- `ESP32-S3-Zero`

No extra layout variants should be generated until the single-output-per-MCU
path is working end to end.

## Standalone Workflow Boundary

PCB generation and PCB validation should share a project-agnostic core, but they
should be exposed as separate Docker jobs:

- A local generation job that writes source-derived documentation and generated
  PCB artifacts.
- A CI validation job that is read-only with respect to committed files and fails
  when checked-in documentation is stale or invalid.

Neither job should live inside a single project's firmware, tests, or dashboard
code.

Both jobs should accept project inputs such as:

- `--project-dir projects/<project>`
- optional target MCU or MCU list
- optional output directory override

Each project should call the shared core from its Docker-facing project entry.
In the current repo shape, projects have `docker-compose.yaml` files rather than
project-local Dockerfiles, so the compose service can call a shared root-level
Docker stage. If project-local Dockerfiles are added later, they should still
dispatch to the same shared core instead of duplicating PCB logic.

The local generation job owns these steps:

- Parse `projects/<project>/firmware/` for the board data structures and MCU
  targets.
- Create or update `projects/<project>/WIRING.MD`.
- Build the normalized PCB intent model.
- Generate one KiCad PCB per requested MCU target.
- Export the MCU-specific Gerber fabrication package.
- Export drill files.
- Run DRC where available.

The CI validation job owns these steps:

- Parse `projects/<project>/firmware/` for the board data structures, MCU
  targets, and explicit all-net wiring declaration.
- Build the normalized PCB intent model.
- Regenerate the expected `WIRING.MD` content in a temporary location.
- Compare that generated content with the checked-in `projects/<project>/WIRING.MD`.
- Generate PCB files in a temporary artifact directory.
- Run DRC where available.
- Export Gerbers and Excellon drills to the temporary artifact directory.
- Fail if any checked-in source, hardware-library data, or `WIRING.MD` is
  inconsistent with the generated intent model or exported PCB package.

Project-specific Docker wiring should only select the project directory and the
target MCU or MCU list. It should not contain parser, layout, Gerber export, or
documentation-comparison logic.

## `WIRING.MD` Generation

For every project, the local generation job should create or update:

```text
projects/<project>/WIRING.MD
```

The file should be deterministic and generated from the same intent model used
for PCB generation.

It should include:

- Source firmware file path.
- Supported MCU targets discovered from the `BOARD` table.
- Per-MCU logical pin table.
- Declared connectors with their full ordered pad lists.
- Firmware-defined pad-to-pad connections.
- Firmware-defined power and ground connections.
- Pad-resolution validation results against the MCU board definition and the
  declared connector pad lists.
- A review section listing every net attached to an MCU 5V-class supply pad,
  since the generator has no module voltage knowledge to validate against.
- Driver/module name from the consumed constructor call, as optional
  traceability metadata only.
- All declared connector pads, including isolated pads with no routed
  connection.
- Output artifact paths for the generated MCU-specific PCB packages.

The file should make clear that firmware `main.py` remains the source of truth
for all routed nets and that `WIRING.MD` is generated, committed documentation.
CI must not update this file in place; it should compare checked-in content
against regenerated expected content and fail with a useful diff on mismatch.

## CI Validation

CI should use the validation job, not the local generation job. It should run
from source for every project and every supported MCU target, regenerate expected
documentation and PCB artifacts in temporary locations, and compare those
temporary outputs against what is checked in.

The CI check should:

- Build the PCB intent model from firmware plus the committed hardware library.
- Regenerate expected `WIRING.MD` content for every project in a temporary
  location.
- Fail if the regenerated `WIRING.MD` content differs from the checked-in
  `projects/<project>/WIRING.MD`.
- Generate one KiCad PCB per MCU target in a temporary artifact directory.
- Run KiCad DRC where available.
- Export Gerbers and Excellon drills to the temporary artifact directory.
- Produce one fabrication package per MCU target.
- Fail if any firmware-defined connection cannot be resolved to a valid MCU pad
  and declared connector pad.
- Fail if checked-in `WIRING.MD` describes connections, connectors, target
  boards, or output artifact paths that do not match the generated intent
  model.
- Fail if any generated board is missing required holes, copper, mask, outline,
  drill, or fabrication outputs.

CI should treat generated PCB files and fabrication packages as build artifacts.
Generated `WIRING.MD` files are committed source-derived documentation and must
be current.

## Docker-Only Tooling

Follow the repo host policy: do not install KiCad, Python packages, gerber tools,
flashers, or helper utilities on the host.

Add PCB tooling as Docker stages and compose services. The local generation
command could look like:

```text
docker compose run --rm --build pcb-generate --project distance-stream --mcu RP2040-Zero
```

The generation service should:

- Run the parser.
- Create or update the project's `WIRING.MD`.
- Generate the KiCad PCB file.
- Run KiCad DRC where available.
- Export Gerbers.
- Export Excellon drills.
- Produce a fabrication zip.

The CI validation command could look like:

```text
docker compose run --rm --build pcb-check
```

The validation service should:

- Run the parser for every PCB-enabled project.
- Regenerate expected `WIRING.MD` content into a temporary location.
- Compare generated `WIRING.MD` content with checked-in files.
- Generate PCB artifacts into a temporary artifact directory.
- Run DRC and fabrication-output validation.
- Fail on any mismatch without updating checked-in files.

## Layout Strategy

Start with a deterministic, conservative prototyping board layout:

- Rectangular board outline.
- Smallest standard low-cost board size that fits the target MCU footprint,
  declared connector footprints, all connector holes, required routing, labels,
  and board edge margins.
- 2.54 mm grid.
- Full MCU header footprint on one side, with drilled plated through-holes for
  every physical left/right header pin on the target MCU board, whether used by
  firmware or not.
- Generic breakout header connectors nearby, with plated through-hole pads for
  every declared connector pad. Module body size is unknown to the generator,
  so keep a conservative default clearance around each connector for
  breakout-board overhang, overridable by an optional per-connector body hint
  in the firmware declaration.
- No spare prototyping area or extra unused perfboard grid holes. The board is
  only a carrier that seats the MCU and breakout headers, then connects them
  according to the project's explicit firmware wiring declaration.
- No extra mechanical screw/standoff mounting holes for now; they are out of
  scope until a later layout option is explicitly added.
- Silkscreen labels for project, target board, connector designators, and pad
  names.
- Conservative trace width, clearance, annular ring, and board-edge margin.

Initial routing should use Manhattan traces on the 2.54 mm grid. Prefer simple,
predictable routes over dense compaction. Use both copper layers only when it
keeps the routing clear and fabrication-friendly.

## Connection Rules

All project firmware connections are plain pad-to-pad connections:

- The explicit project-library wiring declaration in firmware is the sole
  source of connectors and generated nets. Each connector lists its complete
  pad set in physical order; each net lists the exact pads it joins
  (`MCU.<pad>` or `<connector>.<pad>`).
- The generator routes exactly the declared nets: no alternate GPIOs, no
  inferred buses, no default power or ground, no invented copper.
- The selected `BOARD` value may identify the MCU pad for a signal net, such as
  `BOARD.sda` or `BOARD.rx`, resolved by GPIO number against the MCU board
  definition.
- MCU supply pads are referenced by their canonical names (`5V`, `3V3`, `GND`)
  and only appear in nets when explicitly declared in firmware.
- Connector-side pad names are opaque; the generator attaches no meaning to
  `SDA`, `TX`, `XSHUT`, or any other label.
- Metadata fields such as `name`, `i2c_id`, and `uart_id` stay in the intent
  model for traceability but do not create traces.
- Connector pads that do not appear in a firmware-defined connection still get
  through-hole pads, mask openings, and labels, but no copper trace.

Fail fast on:

- A net pad that does not resolve on the target MCU board or in a declared
  connector pad list.
- The same physical pad appearing in two different nets.
- A net joining two different MCU supply rails, or a supply pad to `GND`.
- A net with fewer than two pads, duplicate net names, or duplicate pad names
  within one connector.
- A `BOARD` field consumed by a driver constructor call but absent from the
  wiring declaration.
- A machine branch in `BOARD` dispatch that the declaration does not cover.
- Unroutable nets or DRC violations — never silently reroute or substitute
  pins.

Softer checks, with explicit opt-outs rather than silent defaults:

- A connector with no net to any MCU supply pad, or no net to `GND`, fails
  unless the declaration explicitly marks that connector as intentionally
  unpowered.
- Every net attached to an MCU 5V-class pad is surfaced in `WIRING.MD` for
  human review, since the generator has no module voltage knowledge to validate
  against.
- An MCU-pad-to-MCU-pad net with no connector involved is legal but flagged
  with a warning.

## Testing Plan

Parser tests:

- Extract all current project `Board` fields.
- Extract all current machine branches.
- Extract explicit project-library wiring declarations, including each
  connector's ordered pad list.
- Verify expected target board names.
- Verify the consistency lint: a `BOARD` field consumed by a driver constructor
  but absent from the wiring declaration fails the guard.
- Verify firmware without a complete all-net wiring declaration fails the PCB
  generation guard.
- Verify no firmware execution occurs during parsing.

Intent model tests:

- Verify expected firmware-defined connection nets for every current project.
- Verify explicit firmware-defined power and ground nets route from connector
  pads to MCU board supply pads.
- Verify metadata fields such as `i2c_id` and `uart_id` do not create traces.
- Verify every MCU through-board header pin appears in the model, including pins
  with no routed connection.
- Verify every declared connector pad appears in the model, including pads with
  no routed connection.
- Verify one physical pad appearing in two different nets fails.
- Verify a net joining two different MCU supply rails, or a supply pad to
  `GND`, fails.
- Verify a connector with no supply net or no `GND` net fails unless explicitly
  marked as intentionally unpowered.

PCB output tests:

- Generated board contains expected nets.
- Generated board contains plated through-hole pads.
- Every physical MCU left/right header pin has a plated through-hole pad.
- Every declared connector pad has a plated through-hole pad.
- Unconnected connector pads remain isolated pads.
- No spare prototyping grid holes are generated.
- Generated board has an `Edge.Cuts` outline.
- Generated board has solder mask openings over pads.
- Generated board has drill definitions for all through-hole pads.
- Generated board includes useful silkscreen labels.
- KiCad DRC passes for supported generated boards.
- Fabrication zip contains the expected Gerber and drill files.
- One Gerber fabrication package is produced per MCU target.

`WIRING.MD` tests:

- File is created for a project that does not have one.
- File is updated deterministically when firmware wiring changes.
- File lists every MCU target discovered in the firmware.
- File shows firmware-defined connections as plain pad-to-pad copper nets.
- File includes explicit firmware-defined power and ground nets.
- File lists unconnected connector pads as available holes.
- File includes the 5V-class rail review section when such nets exist.
- CI fails if the generated file differs from the checked-in file.

CI workflow tests:

- The all-project PCB check does not modify checked-in `WIRING.MD` files.
- The local generation job creates or updates `WIRING.MD` for a selected project.
- The same check generates valid PCB artifacts for every project/MCU target.
- The check fails on unresolved firmware connection fields.
- The check fails when checked-in `WIRING.MD` files are stale.
- The check fails when checked-in `WIRING.MD` content does not match the
  generated intent model.
- Generated KiCad, Gerber, drill, and fabrication package files are not required
  to be committed.

All tests and generation commands should run through Docker compose services.

## Milestones

1. Document the firmware-to-net mapping contract.
2. Define the shared core interface and separate generation/check command
   contracts.
3. Define the firmware project-library wiring syntax — connector pad lists plus
   nets — and guard rules.
4. Migrate one project to the explicit all-net firmware wiring declaration,
   including its connector pad lists.
5. Add the hardware library schema and data for one MCU board plus the generic
   connector template.
6. Build the AST parser and tests for current `main.py` files.
7. Build the intermediate intent model and tests.
8. Generate deterministic, committed `projects/<project>/WIRING.MD`.
9. Generate a minimal KiCad PCB for one project and one MCU target.
10. Add Dockerized KiCad export through the generation job.
11. Add DRC and fabrication zip checks.
12. Add the remaining MCU board definitions.
13. Migrate every current project to explicit all-net firmware wiring.
14. Add the all-project CI check that validates checked-in `WIRING.MD` files and
    PCB generation from source without updating committed files.
15. Generate one Gerber fabrication package per MCU for each current project.
