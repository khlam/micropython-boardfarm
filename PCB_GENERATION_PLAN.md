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
read without importing the firmware. That declaration owns every routed net:
signal, power, ground, and any optional control line such as `AD0`, `LPN`, or
`XSHUT` when connected. No copper connection should be invented by the hardware
library.

The project-library guard should enforce that:

- Every driver constructor argument that consumes a physical `BOARD` field is
  represented in the explicit firmware wiring declaration.
- Every firmware-declared net resolves to known pads in the hardware library.
- Metadata fields such as `name`, `i2c_id`, and `uart_id` cannot create routed
  nets.
- Power, ground, and voltage-domain choices are explicit in firmware wiring, not
  supplied by defaults.

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
migrated to the explicit all-net wiring declaration, including power and ground.

The user or agent writing firmware is responsible for choosing correct logical
connections. The PCB workflow should faithfully translate those connections into
documentation and board files. It should not second-guess firmware by silently
rewriting pins, choosing alternate GPIOs, or inferring a different bus. It may
fail fast on missing firmware wiring declarations, unknown board names, unknown
signal names, missing hardware-library entries, or physically impossible
mappings.

## Important Parser Boundary

Do not import project firmware to extract wiring.

Every current `main.py` calls `main()` at module import time. A PCB parser
should use static Python AST parsing instead of executing the firmware.

The parser should extract:

- `Board = namedtuple(...)` field names.
- Each machine-dispatched `BOARD = Board(...)` branch.
- The explicit project-library wiring declaration that lists all pad-to-pad nets.
- Target board names such as `RP2040-Zero`, `RP2350`, and `ESP32-S3-Zero`.
- Driver constructor calls that consume `BOARD` fields, such as
  `VL53L0X(sda=BOARD.sda, scl=BOARD.scl)`.

## Intermediate PCB Intent Model

Normalize parsed firmware into a small, explicit model before any PCB generation.

Example conceptual output for `distance-stream` on `RP2040-Zero`:

```text
project: distance-stream
target_board: RP2040-Zero
module: VL53L0X
nets:
  VIN: MCU 5V -> sensor VIN
  GND: MCU GND -> sensor GND
  SDA: MCU GPIO0 -> sensor SDA
  SCL: MCU GPIO1 -> sensor SCL
```

Treat every firmware-defined connection as an undirected net between plated
through-hole pads, including power and ground. The generator should not infer
protocol semantics from names such as `sda`, `scl`, `tx`, or `rx`; they are just
connection names. Fields such as `name`, `i2c_id`, and `uart_id` are metadata
and do not create copper traces.

## Hardware Library

Add a data-only hardware library that supplies physical facts missing from
firmware. A likely location is `tools/pcbgen/hardware/`.

The library should describe MCU boards:

- `rp2040_zero`
- `rp2350`
- `esp32_s3_zero`

And breakout modules:

- `vl53l0x`
- `vl53l5cx`
- `mpu6050`
- `qmc5883p`
- `atgm336h`

Each hardware entry should define:

- Human-readable name.
- Through-hole header pin names.
- Physical pin coordinates on a 2.54 mm grid.
- Drill diameter.
- Copper pad diameter.
- Default pin shape, such as round or square pin 1.
- Pin aliases, such as `5V`, `VBUS`, `VIN`, `VCC`, `3V3`, and `GND`, for
  resolving firmware-declared wiring to physical pads.
- Voltage-domain metadata and guard rules, such as whether a breakout supply pad
  may be connected to `5V`, `VBUS`, or `3V3`.
- Module-specific pins, such as `AD0`, `LPN`, and `XSHUT`.
- Silkscreen labels.
- Keepout or placement hints where needed.

The hardware library must not define default power, ground, or signal
connections. It supplies pad geometry, aliases, voltage compatibility, and
physical constraints; the firmware wiring declaration supplies all routed nets.

Every breakout module definition should include all of its IO/header pins. The
generated PCB should place a plated through-hole pad for every breakout pin even
when no firmware-defined connection routes to it. Unconnected breakout pins
remain isolated pads with solder mask openings and silkscreen labels.

The three supported MCU boards are defined and static. Their physical header
maps should be checked in as explicit hardware-library data rather than inferred
from firmware or README diagrams. Each MCU definition should provide canonical
pin labels plus aliases where useful, such as `GPIO0`, `GP0`, and `0`, all
pointing at the same physical header coordinate.

Every MCU board definition should include the complete through-board header
geometry. Assume each MCU board is soldered to headers along its left and right
pin columns, so every physical MCU header pin gets a plated through-hole pad even
when no firmware-defined connection uses it.

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
firmware behavior. The static MCU board and module footprint definitions still
own their exact pin counts, pin order, aliases, and coordinates.

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
- Firmware-defined pad-to-pad connections.
- Firmware-defined power and ground connections.
- Hardware-library validation results for pad resolution and voltage-domain
  compatibility.
- Driver/module name inferred from the consumed constructor call.
- All breakout module pins, including isolated pads with no routed connection.
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
  and breakout pad.
- Fail if checked-in `WIRING.MD` describes connections, modules, target boards,
  or output artifact paths that do not match the generated intent model.
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
  breakout footprint, all breakout holes, required routing, labels, and board
  edge margins.
- 2.54 mm grid.
- Full MCU header footprint on one side, with drilled plated through-holes for
  every physical left/right header pin on the target MCU board, whether used by
  firmware or not.
- Breakout module footprint nearby, with plated through-hole pads for every
  breakout IO/header pin.
- No spare prototyping area or extra unused perfboard grid holes. The board is
  only a carrier that seats the MCU and breakout headers, then connects them
  according to the project's explicit firmware wiring declaration.
- No extra mechanical screw/standoff mounting holes for now; they are out of
  scope until a later layout option is explicitly added.
- Silkscreen labels for project, target board, module, and pin names.
- Conservative trace width, clearance, annular ring, and board-edge margin.

Initial routing should use Manhattan traces on the 2.54 mm grid. Prefer simple,
predictable routes over dense compaction. Use both copper layers only when it
keeps the routing clear and fabrication-friendly.

## Connection Rules

All project firmware connections are plain pad-to-pad connections:

- The explicit project-library wiring declaration in firmware creates generated
  nets.
- Each net identifies the MCU pad and breakout pad to connect.
- The selected `BOARD` value may identify the MCU pad for a signal net, such as
  `BOARD.sda` or `BOARD.rx`.
- Literal supply aliases such as `5V`, `VBUS`, `3V3`, and `GND` may identify
  MCU supply pads, but only when explicitly declared in firmware.
- The breakout hardware entry resolves declared breakout pad names and validates
  physical and voltage compatibility.
- The PCB generator connects only firmware-declared pad pairs with copper.
- Metadata fields such as `name`, `i2c_id`, and `uart_id` stay in the intent
  model for traceability but do not create traces.
- Breakout pins that do not appear in a firmware-defined connection still get
  through-hole pads, mask openings, and labels, but no copper trace.
- The generator should fail fast if a firmware-defined connection cannot be
  resolved to a valid MCU pad and breakout pad, or if a declared voltage-domain
  connection violates the hardware-library guard rules.

## Testing Plan

Parser tests:

- Extract all current project `Board` fields.
- Extract all current machine branches.
- Extract explicit project-library wiring declarations.
- Verify expected target board names.
- Verify consumed driver kwargs.
- Verify firmware without a complete all-net wiring declaration fails the PCB
  generation guard.
- Verify no firmware execution occurs during parsing.

Intent model tests:

- Verify expected firmware-defined connection nets for every current project.
- Verify explicit firmware-defined power and ground nets route from breakout
  pads through MCU board supply pads.
- Verify metadata fields such as `i2c_id` and `uart_id` do not create traces.
- Verify every MCU through-board header pin appears in the model, including pins
  with no routed connection.
- Verify every breakout module pin appears in the model, including pins with no
  routed connection.

PCB output tests:

- Generated board contains expected nets.
- Generated board contains plated through-hole pads.
- Every physical MCU left/right header pin has a plated through-hole pad.
- Every breakout module IO/header pin has a plated through-hole pad.
- Unconnected breakout pins remain isolated pads.
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
- File lists unconnected breakout pins as available holes.
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
3. Define the firmware project-library wiring syntax and guard rules.
4. Migrate one project to the explicit all-net firmware wiring declaration.
5. Add the hardware library schema and data for one MCU board plus one sensor.
6. Build the AST parser and tests for current `main.py` files.
7. Build the intermediate intent model and tests.
8. Generate deterministic, committed `projects/<project>/WIRING.MD`.
9. Generate a minimal KiCad PCB for one project and one MCU target.
10. Add Dockerized KiCad export through the generation job.
11. Add DRC and fabrication zip checks.
12. Expand hardware data to all supported MCU boards and modules.
13. Migrate every current project to explicit all-net firmware wiring.
14. Add the all-project CI check that validates checked-in `WIRING.MD` files and
    PCB generation from source without updating committed files.
15. Generate one Gerber fabrication package per MCU for each current project.
