"""Shared state isolation for Matter facade tests."""

import matter_native
import pytest

import matter.node as node_module


@pytest.fixture(autouse=True)
def reset_matter_state():
    """Reset the fake native stack and process-wide Python node singleton."""
    matter_native.reset()
    node_module._active_node[0] = None
    yield
    matter_native.reset()
    node_module._active_node[0] = None
