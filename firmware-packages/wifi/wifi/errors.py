"""The single provisioning exception and its closed set of redacted codes.

Every failure the package raises carries one of a fixed set of coarse codes and
nothing else. Raw adapter errors, network details, credentials, and session data
never reach the exception message or repr, so a caller may log the code freely
without leaking secrets or platform internals.
"""

__all__ = ["CODES", "ProvisioningError"]

# The only codes a ProvisioningError may carry. Anything else collapses to
# "state" so an accidental raw string can never escape through the exception.
CODES = ("unsupported", "capability", "entropy", "network", "state")


class ProvisioningError(Exception):
    """A provisioning step failed; ``code`` is one of ``CODES``.

    The message and repr expose only the code — never the underlying adapter
    error, network parameters, or any secret — so the code is safe to emit.
    """

    def __init__(self, code: str) -> None:
        """Store ``code``, coercing anything unrecognised to ``"state"``."""
        safe = code if code in CODES else "state"
        self.code = safe
        super().__init__(safe)

    def __repr__(self) -> str:
        """Return only the class name and code, never wrapped detail."""
        return f"ProvisioningError('{self.code}')"
