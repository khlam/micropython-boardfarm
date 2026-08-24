---
name: boardfarm-development
description: Add a new project or implement a feature in micropython-boardfarm. Use for changes to project firmware, reusable MCU packages, Matter endpoints, dashboards, Docker build wiring, CI registration, or project documentation. Do not use for read-only reviews, diagnosis without implementation, or unrelated repository maintenance.
---

# Boardfarm development

Deliver the smallest complete change that satisfies the project's product and hardware contract.
Preserve existing external behavior unless the user explicitly changes it.

## Ground the request

1. Read `AGENTS.md` and `STYLE.md` completely before changing files. Treat them as the
   authority for repository boundaries, architecture, style, and commands.
2. Inspect `git status`, the target project, and the closest working project or package.
   Preserve user changes and avoid generated files under `projects/*/outputs/`.
3. Match the requested phase:
   - For investigation, prompt drafting, or planning, inspect the repository and return the
     requested analysis or decision-complete plan without editing production files.
   - For implementation, carry the agreed behavior through code, configuration, build wiring,
     and documentation.
4. Resolve facts from the repository before asking questions. Ask only when an unresolved
   product choice would materially change behavior, hardware support, or a public interface.

## Establish the contract

Before implementation, make the affected contract explicit enough to code without guessing:

- supported boards, peripherals, pins, buses, and resource ownership;
- inputs, outputs, JSON fields, units, timing, ranges, and configuration mappings;
- states, transitions, retries, startup order, and recovery behavior;
- public identifiers such as Matter endpoint order, attribute meaning, ports, filenames, and
  firmware artifact names;
- behavior when a sensor, network, dashboard, controller, or publication path fails.

Prefer a small deterministic state model over inference, target history, confidence scoring, or
adaptive behavior unless the user requests those capabilities. For sensor-driven safety or
occupancy claims, distinguish what the hardware reports from what can be known about the real
world. Do not promise certainty the hardware cannot provide; propose a fail-safe policy and make
its false-positive/false-negative tradeoff explicit.

## Put behavior in the right layer

- Keep product state, project-specific pin tables, initialization order, retry policy, UI choices,
  and the main streaming loop in `projects/<project>/`.
- Put reusable hardware behavior in `firmware-packages/<package>/`. Drivers receive flat pin and
  bus arguments, own their bus internally, scan for the device, and expose a specific
  `DeviceNotFoundError` for absence.
- Keep reusable CPython behavior in `cpython-packages/`; keep each project's dashboard body and
  presentation under its own `viz/` directory.
- Keep Matter schemas, transport, commissioning, persistence, and native event delivery in the
  Matter package/native bridge. Keep product policy, endpoint-derived state, color or brightness
  decisions, pins, and hardware lifecycle in the project.
- For a new project, start from the closest supported project and adapt it deliberately. Register
  the project everywhere current repository discovery shows it is required, including project
  documentation, workspace/test image inputs, coverage configuration when applicable, and the CI
  compile matrix. Do not copy unsupported services or board targets.

## Implement the vertical slice

- Keep control flow explicit. Use named states when persistent behavior has meaningful
  transitions; avoid extra state when the newest valid hardware report is sufficient.
- Preserve stable JSON keys, Matter endpoint identity/order, URLs, ports, and artifact names unless
  the requested feature changes their contract.
- Keep independent failure domains independent. A dashboard or Matter publication failure must not
  silently redefine sensor state unless the product contract says it should.
- Follow MicroPython limits: no host-only imports, package manager use, import-time pin claims, or
  busy loops. Sleep or block appropriately, reuse buffers in hot paths, and catch only recoverable
  hardware failures.
- Send firmware stdout only through the repository's structured JSON `emit()` path. Never add raw
  diagnostic `print()` calls to streaming firmware.
- Update the target project's README and shared project catalog when behavior, wiring,
  configuration, build commands, or supported targets change. Document the current contract, not
  the history of how it evolved.
- Never install host tools. Use the repository's Docker Compose services and Dockerized hooks.

## Verify and hand off

1. Review the complete diff for accidental behavior changes, stale terminology, missing project
   registration, and unrelated edits.
2. Run the smallest relevant Dockerized formatting, lint, type, and existing-test checks. Compile
   every affected firmware target when build wiring or frozen firmware changes. Do not inspect
   files under `projects/*/outputs/` directly.
3. Do not write or modify tests until the user confirms the feature is final. After confirmation,
   add focused coverage for success, boundaries, missing hardware, malformed input, retries, and
   recovery as applicable, then run the relevant Dockerized test target.
4. Report the delivered behavior, important compatibility choices, validation performed, and any
   hardware-only verification still needed. Do not claim hardware behavior that was not exercised.
