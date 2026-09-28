"""Shared state isolation for Matter facade tests."""

from collections.abc import Iterator

import matter_native
import pytest

import matter.emit as emit_module
import matter.node as node_module


@pytest.fixture(autouse=True)
def reset_matter_state() -> Iterator[None]:
    """Reset the fake native stack, the node singleton, and registered emit sinks.

    Yields:
        None: Control to the test between the two resets.
    """
    matter_native.reset()
    node_module._active_node[0] = None
    emit_module._sinks.clear()
    yield
    matter_native.reset()
    node_module._active_node[0] = None
    emit_module._sinks.clear()
