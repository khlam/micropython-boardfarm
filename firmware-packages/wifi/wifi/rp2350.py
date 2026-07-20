"""Pico 2 W (RP2350 + CYW43) AP adapter over ``network.WLAN``.

Brings up a single WPA2-PSK AP bound to the AP address with the CYW43 DHCP server
advertising the AP as DNS. As on the ESP32-S3 adapter, every exposed setting is
read back and proven before the AP is trusted, and any capability that cannot be
proven is downgraded and fails the start, so the AP never comes up in an open,
WEP, WPA1, mixed, or TKIP state.

The RP2350 has a dedicated hardware TRNG that is seeded independently of the RF
subsystem, so ``random_bytes`` reads ``os.urandom`` directly without powering the
radio first.

Hardware-specific constants and read-back semantics are marked ``VERIFY`` — the
CYW43 security enumeration and the ``stations`` status must be confirmed on a real
Pico 2 W during manual verification.
"""

from wifi.errors import ProvisioningError

__all__ = ["Adapter"]

# CYW43 auth value for WPA2-AES-PSK (not the WPA/WPA2 mixed value 0x00400006).
# VERIFY on hardware: compared against the read-back of ap.config("security").
_WPA2_AES_PSK = 0x00400004


class Adapter:
    """WPA2-only AP adapter for the Pico 2 W."""

    SUPPORTED = True

    def __init__(self) -> None:
        """Initialise capability profile; defer all radio access to first use."""
        self._ap = None
        self._sta = None
        # CYW43 in MicroPython does not expose a one-client limit, PMF, or
        # client isolation, so those optional capabilities are reported false;
        # the required five are proven by read-back in start_ap.
        self._caps = {
            "supported": True,
            "wpa2_only": True,
            "ap_bind": True,
            "station_count": True,
            "dhcp_dns": True,
            "pmf": False,
            "max_clients": False,
            "client_isolation": False,
        }

    def _interfaces(self) -> tuple:
        """Lazily construct and cache the AP and STA interface objects."""
        import network  # noqa: PLC0415

        if self._ap is None:
            self._ap = network.WLAN(network.AP_IF)
        if self._sta is None:
            self._sta = network.WLAN(network.STA_IF)
        return network, self._ap, self._sta

    def capabilities(self) -> dict:
        """Return the current (possibly downgraded) capability dict."""
        return dict(self._caps)

    def random_bytes(self, n: int) -> bytes:
        """Return ``n`` bytes from the RP2350 hardware TRNG."""
        import os  # noqa: PLC0415

        return os.urandom(n)

    def interfaces_down(self) -> bool:
        """Return whether both the AP and station interfaces are inactive."""
        try:
            _network, ap, sta = self._interfaces()
            return (not ap.active()) and (not sta.active())
        except OSError:
            return False

    def quiesce(self) -> None:
        """Force both interfaces down and verify, clearing any stale AP.

        Raises:
            ProvisioningError: Code ``network`` if the interfaces cannot be
                confirmed inactive.
        """
        _network, ap, sta = self._interfaces()
        for wlan in (ap, sta):
            try:
                wlan.active(False)
            except OSError:
                pass
        if not self.interfaces_down():
            raise ProvisioningError("network")

    def start_ap(self, ssid: str, password: str, channel: int, ap_ip: str, netmask: str) -> None:
        """Configure and activate the WPA2-only AP, proving every setting.

        Raises:
            ProvisioningError: ``capability`` if exact WPA2-only mode, AP-address
                binding, station counting, or DHCP DNS cannot be proven;
                ``network`` for a lower-level failure.
        """
        _network, ap, sta = self._interfaces()
        try:
            sta.active(False)
            ap.active(False)
        except OSError:
            raise ProvisioningError("network") from None

        # Configure while inactive so the AP never broadcasts a default network.
        try:
            ap.config(essid=ssid, password=password, channel=channel)
            try:
                ap.config(security=_WPA2_AES_PSK)  # VERIFY: CYW43 WPA2-only value
            except (OSError, ValueError):
                pass  # proven by read-back below; default with a key is WPA2-AES
        except (OSError, ValueError):
            self._caps["wpa2_only"] = False
            raise ProvisioningError("capability") from None

        try:
            ap.active(True)
            ap.ifconfig((ap_ip, netmask, ap_ip, ap_ip))
        except OSError:
            self._safe_down(ap)
            raise ProvisioningError("network") from None

        self._prove(ap, ap_ip)

    def _prove(self, ap: object, ap_ip: str) -> None:
        """Read back and prove the required capabilities, or fail closed."""
        try:
            security = ap.config("security")
        except (OSError, ValueError):
            security = None
        if security != _WPA2_AES_PSK:  # reject open/WEP/WPA1/mixed/TKIP
            self._caps["wpa2_only"] = False
            self._safe_down(ap)
            raise ProvisioningError("capability")

        cfg = ap.ifconfig()
        if cfg[0] != ap_ip:
            self._caps["ap_bind"] = False
            self._safe_down(ap)
            raise ProvisioningError("capability")
        if cfg[3] != ap_ip:
            self._caps["dhcp_dns"] = False
            self._safe_down(ap)
            raise ProvisioningError("capability")

        try:
            ap.status("stations")  # VERIFY: CYW43 station enumeration support
        except (OSError, ValueError, TypeError):
            self._caps["station_count"] = False
            self._safe_down(ap)
            raise ProvisioningError("capability") from None

        if not ap.active():
            self._safe_down(ap)
            raise ProvisioningError("network")

    def stop_ap(self) -> None:
        """Deactivate the AP and verify it is down.

        Raises:
            ProvisioningError: Code ``network`` if the AP cannot be confirmed
                inactive.
        """
        _network, ap, _sta = self._interfaces()
        try:
            ap.active(False)
        except OSError:
            pass
        if ap.active():
            raise ProvisioningError("network")

    def client_count(self) -> int:
        """Return the number of associated stations."""
        try:
            _network, ap, _sta = self._interfaces()
            return len(ap.status("stations"))
        except (OSError, ValueError, TypeError):
            return 0

    def _safe_down(self, ap: object) -> None:
        """Bring the AP down, swallowing any error (used on failure paths)."""
        try:
            ap.active(False)
        except OSError:
            pass
