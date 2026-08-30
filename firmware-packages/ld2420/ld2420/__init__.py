"""Public interface for the HLK-LD2420 radar driver."""

from ld2420.ld2420 import LD2420, DeviceNotFoundError, Target

__all__ = ["LD2420", "DeviceNotFoundError", "Target"]
