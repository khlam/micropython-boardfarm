"""Host CPython tests for the ESP32-S3 AP adapter's priming and read-back proof.

The fake ``network`` module below reproduces the ESP-IDF behaviour measured on a
real ESP32-S3-Zero: an AP configuration is only retained if the AP interface has
been enabled in the Wi-Fi mode since the station interface was last deactivated.
Writing without that priming step is accepted by ``config()`` and then silently
discarded on ``active(True)``, which brings the AP up *open* — so these tests
pin both that the adapter primes on every start and that its read-back proof
fails closed if it ever does not.

The measurements the model rests on: priming then writing succeeds repeatedly
across full stop/quiesce cycles, while skipping the prime on any start after the
first yields an open AP that ``_prove`` rejects with ``capability``.
"""

from __future__ import annotations

import sys
import types

import pytest

from wifi.errors import ProvisioningError

_AP_IP = "192.168.4.1"
_NETMASK = "255.255.255.0"
_SSID = "LEDFX-AAAAAAAA"
_PASSWORD = "AAAAAAAAAAAAAAAAAAAAAAAB"  # noqa: S105 - fixture, not a real credential
_OPEN = 0
_WPA2 = 3


def test_first_start_beacons_wpa2(adapter, net):
    adapter.start_ap(_SSID, _PASSWORD, 6, _AP_IP, _NETMASK)

    assert net.ap.authmode == _WPA2
    assert net.ap.essid == _SSID
    assert adapter.capabilities()["wpa2_only"]


def test_rotation_after_quiesce_still_beacons_wpa2(adapter, net):
    """The regression: a second start, with a full teardown in between."""
    adapter.start_ap(_SSID, _PASSWORD, 6, _AP_IP, _NETMASK)
    adapter.stop_ap()
    adapter.quiesce()

    adapter.start_ap("LEDFX-BBBBBBBB", _PASSWORD, 6, _AP_IP, _NETMASK)

    assert net.ap.authmode == _WPA2
    assert net.ap.essid == "LEDFX-BBBBBBBB"
    assert adapter.capabilities()["wpa2_only"]


def test_ten_rotations_never_degrade(adapter, net):
    for i in range(10):
        adapter.start_ap(f"LEDFX-{i:08X}", _PASSWORD, 6, _AP_IP, _NETMASK)
        assert net.ap.authmode == _WPA2, f"rotation {i} came up open"
        adapter.stop_ap()
        adapter.quiesce()

    assert adapter.capabilities()["wpa2_only"]


def test_priming_happens_while_the_radio_is_stopped(adapter, net):
    adapter.start_ap(_SSID, _PASSWORD, 6, _AP_IP, _NETMASK)

    # The priming activation must carry no configured SSID, and the AP must be
    # inactive again before the credentials are written.
    assert net.ap.log[:4] == [
        ("active", False),
        ("active", True),
        ("active", False),
        ("config", _SSID),
    ]


def test_unprimed_write_is_caught_and_fails_closed(adapter, net, monkeypatch):
    """Without priming the AP would come up open; _prove must reject that."""
    monkeypatch.setattr(type(adapter), "_prime", lambda _self, _ap: None)

    with pytest.raises(ProvisioningError) as excinfo:
        adapter.start_ap(_SSID, _PASSWORD, 6, _AP_IP, _NETMASK)

    assert excinfo.value.code == "capability"
    assert not adapter.capabilities()["wpa2_only"]
    assert not net.ap.active_state  # brought back down, not left beaconing


def test_stop_ap_and_quiesce_leave_both_interfaces_down(adapter, net):
    adapter.start_ap(_SSID, _PASSWORD, 6, _AP_IP, _NETMASK)
    adapter.stop_ap()
    adapter.quiesce()

    assert not net.ap.active_state
    assert not net.sta.active_state
    assert adapter.interfaces_down()


class _FakeWLAN:
    """One interface of the fake ``network`` module.

    Models the ESP-IDF quirk this adapter exists to work around: ``config()``
    stages a configuration, but ``active(True)`` only keeps it when the AP has
    been primed (enabled in the mode) since the station interface last went
    inactive. Otherwise the interface comes up with ESP-IDF defaults — open.
    """

    def __init__(self, radio: _FakeRadio, *, is_ap: bool) -> None:
        self._radio = radio
        self._is_ap = is_ap
        self.active_state = False
        self.primed = False
        self.staged: dict | None = None
        self.essid = None
        self.authmode = _OPEN
        self.channel = None
        self.max_clients = None
        self.ip = (_AP_IP, _NETMASK, _AP_IP, _AP_IP)
        self.log: list[tuple] = []

    def active(self, value: bool | None = None):  # noqa: FBT001 - mirrors WLAN.active
        if value is None:
            return self.active_state
        self.log.append(("active", value))
        if value:
            if self._is_ap:
                self.primed = True  # enabling the interface enables it in the mode
                if self.staged is not None:
                    self.essid = self.staged["essid"]
                    self.authmode = self.staged["authmode"]
                    self.channel = self.staged["channel"]
                else:
                    self.essid = "ESP_DEFAULT"
                    self.authmode = _OPEN  # unconfigured AP beacons open
            self.active_state = True
        else:
            self.active_state = False
            if not self._is_ap:
                self._radio.clear_mode()
        return None

    def config(self, *args, **kwargs):
        if args:
            key = args[0]
            if key == "authmode":
                return self.authmode
            if key == "essid":
                return self.essid
            raise ValueError(key)
        if "max_clients" in kwargs and len(kwargs) == 1:
            self.max_clients = kwargs["max_clients"]
            return None
        self.log.append(("config", kwargs["essid"]))
        # Accepted unconditionally — but only retained if the interface has been
        # primed since the last full deactivate. This is the silent-discard path.
        if self.primed:
            self.staged = dict(kwargs)
        else:
            self.staged = None
        return None

    def ifconfig(self, value: tuple | None = None):
        if value is None:
            return self.ip
        self.ip = value
        return None

    def status(self, which: str):
        if which != "stations":
            raise ValueError(which)
        return []


class _FakeRadio:
    """Tracks the shared Wi-Fi mode both interfaces live in."""

    def __init__(self) -> None:
        self.ap: _FakeWLAN | None = None
        self.sta: _FakeWLAN | None = None

    def clear_mode(self) -> None:
        """Take the AP back out of the Wi-Fi mode, discarding any staged config."""
        if self.ap is None:
            return
        self.ap.primed = False
        self.ap.staged = None


@pytest.fixture
def net(monkeypatch):
    """Install a fake ``network`` module and expose its two interfaces."""
    radio = _FakeRadio()
    radio.ap = _FakeWLAN(radio, is_ap=True)
    radio.sta = _FakeWLAN(radio, is_ap=False)

    wlan_type = types.SimpleNamespace(SEC_WPA2=_WPA2)
    module = types.ModuleType("network")
    module.AP_IF = 1
    module.STA_IF = 0
    module.WLAN = lambda which: radio.ap if which == module.AP_IF else radio.sta
    module.WLAN.SEC_WPA2 = _WPA2
    monkeypatch.setitem(sys.modules, "network", module)
    radio.module = module
    radio.wlan_type = wlan_type
    return radio


@pytest.fixture
def adapter(net):
    """A fresh ESP32-S3 adapter bound to the fake ``network`` module."""
    from wifi.esp32s3 import Adapter

    instance = Adapter()
    instance._ap = net.ap
    instance._sta = net.sta
    return instance
