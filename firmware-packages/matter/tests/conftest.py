"""Shared state isolation for Matter facade tests."""

import _matter
import pytest

import matter.node as node_module


@pytest.fixture(autouse=True)
def reset_matter_state():
    """Reset the fake native stack and process-wide Python node singleton."""
    _matter.reset()
    node_module._active_node[0] = None
    yield
    _matter.reset()
    node_module._active_node[0] = None
