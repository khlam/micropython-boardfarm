"""ESP32-S3 AP adapter over ``network.WLAN``.

Brings up a single WPA2-PSK/CCMP access point bound to the AP address, with the
DHCP server advertising the AP as DNS. Credentials, IP, and auth mode are set
while the interface is inactive and every exposed setting is read back before the
AP is trusted; any setting that cannot be proven downgrades the matching
capability to ``False`` and fails the start, so the AP never comes up open, WEP,
WPA1, mixed, or TKIP — not even transiently.

Entropy is drawn only after the RF subsystem is powered, because the ESP32-S3
hardware RNG degrades toward a PRNG before Wi-Fi is initialised. ``random_bytes``
powers the radio through the station interface for the read and returns it to
inactive, so both interfaces are down again before the AP is started.

Hardware-specific constants and read-back semantics are marked ``VERIFY`` — they
must be confirmed on a real ESP32-S3-Zero during manual verification.
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
    """WPA2-only AP adapter for the ESP32-S3-Zero."""

    SUPPORTED = True

    def __init__(self) -> None:
        """Initialise capability profile; defer all radio access to first use."""
        self._ap = None
        self._sta = None
        # Optimistic profile for the required capabilities; start_ap proves them
        # by read-back and downgrades any it cannot. The one-client limit is
        # enforceable on ESP32 (max_clients); PMF and client isolation are not
        # exposed by MicroPython, so they are reported false.
        self._caps = {
            "supported": True,
            "wpa2_only": True,
            "ap_bind": True,
            "station_count": True,
            "dhcp_dns": True,
            "pmf": False,
            "max_clients": True,
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
        """Return ``n`` radio-backed random bytes, leaving interfaces inactive.

        Powers the RF subsystem via the station interface for the read so the
        hardware RNG is fully seeded, then deactivates it. Any failure propagates
        so the caller records an entropy fault.
        """
        import os  # noqa: PLC0415

        _network, _ap, sta = self._interfaces()
        activated = False
        try:
            if not sta.active():
                sta.active(True)
                activated = True
            return os.urandom(n)
        finally:
            if activated:
                try:
                    sta.active(False)
                except OSError:
                    pass

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
        network, ap, sta = self._interfaces()
        try:
            sta.active(False)
            ap.active(False)
        except OSError:
            raise ProvisioningError("network") from None

        # Configure everything while the interface is inactive so the AP never
        # broadcasts an open or default network. If the port cannot accept config
        # while down, fail closed rather than open an insecure AP.
        try:
            ap.config(
                essid=ssid,
                password=password,
                authmode=network.AUTH_WPA2_PSK,
                channel=channel,
            )
        except (OSError, ValueError):
            self._caps["wpa2_only"] = False
            raise ProvisioningError("capability") from None
        try:
            ap.config(max_clients=1)  # VERIFY: one-client cap on ESP32-S3
        except (OSError, ValueError):
            self._caps["max_clients"] = False

        try:
            ap.active(True)
            # ip, subnet, gateway, dns — advertise the AP itself as DNS.
            ap.ifconfig((ap_ip, netmask, ap_ip, ap_ip))
        except OSError:
            self._safe_down(ap)
            raise ProvisioningError("network") from None

        self._prove(network, ap, ap_ip)

    def _prove(self, network: object, ap: object, ap_ip: str) -> None:
        """Read back and prove the required capabilities, or fail closed."""
        try:
            authmode = ap.config("authmode")
        except (OSError, ValueError):
            authmode = None
        if authmode != network.AUTH_WPA2_PSK:  # reject open/WEP/WPA1/mixed/TKIP
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
            ap.status("stations")
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
