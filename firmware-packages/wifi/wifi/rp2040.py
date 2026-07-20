"""No-op AP adapter for the non-Wi-Fi RP2040 build.

The plain RP2040 firmware has no ``network`` or ``socket`` module, so this
adapter reports every capability false, never brings up a radio, and refuses to
start an AP. ``quiesce`` is a no-op because there is nothing to force down. The
consuming project keeps running its effects and gauge unchanged.
"""

from wifi.errors import ProvisioningError

__all__ = ["Adapter"]

_CAP_KEYS = (
    "supported",
    "wpa2_only",
    "ap_bind",
    "station_count",
    "dhcp_dns",
    "pmf",
    "max_clients",
    "client_isolation",
)


class Adapter:
    """An adapter that supports nothing and touches no hardware."""

    SUPPORTED = False

    def capabilities(self) -> dict:
        """Return every capability as ``False`` — this port cannot provision."""
        return dict.fromkeys(_CAP_KEYS, False)

    def random_bytes(self, _n: int) -> bytes:
        """Never a source of credentials on this port."""
        raise ProvisioningError("unsupported")

    def interfaces_down(self) -> bool:
        """Report interfaces down; there is no radio to be up."""
        return True

    def quiesce(self) -> None:
        """No-op: there is nothing to force down on RP2040."""

    def start_ap(
        self,
        _ssid: str,
        _password: str,
        _channel: int,
        _ap_ip: str,
        _netmask: str,
    ) -> None:
        """Always refuse — this port has no radio.

        Arguments are accepted positionally to match the adapter interface and
        are unused: this port never brings up a radio.
        """
        raise ProvisioningError("unsupported")

    def stop_ap(self) -> None:
        """No-op: no AP was ever brought up."""

    def client_count(self) -> int:
        """No stations are ever associated."""
        return 0
