# LD2450

Project scaffold for an HLK-LD2450 radar sensor application.

## Status

The project structure is reserved, but the application firmware, stream schema,
dashboard, wiring, and tests are not defined yet.

## Planned layout

```text
ld2450/
  firmware/                project-specific MicroPython application
  viz/static/              project-specific dashboard
  tests/                   host tests added after the feature is confirmed
  docker-compose.yaml      compile, flash, and dashboard services
  pyproject.toml           project metadata
```

The reusable sensor driver belongs in
[`../../firmware-packages/ld2450/`](../../firmware-packages/ld2450/). Pin
assignments and application behavior belong in this project.
