"""Second sourcecode-only vulture pass excluding tests to catch dead code only called by tests."""

# FastAPI binds this by decorator; nothing calls it by name.
websocket_endpoint  # noqa: F821

# REPL surface. projects/matter/firmware/main.py drops to an interactive prompt
# with `pixel`, `node`, and `endpoint` in scope, and its module docstring
# documents driving the light from a serial session. Called by a person, not
# by code.
set_color  # noqa: F821

# A driver presence check, part of the sensor's public contract: a project that
# hot-plugs or re-probes hardware calls it. Kept deliberately even though the
# in-tree projects all construct their sensor once at boot.
is_alive  # noqa: F821
