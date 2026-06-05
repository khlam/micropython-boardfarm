# Copyright (c) 2021 Mark Grosen <mark@grosen.org>
#
# SPDX-License-Identifier: MIT
#
# Vendored from https://github.com/mp-extras/vl53l5cx commit c7476877e9
# (2021-10-07). Base class (originally __init__.py) and MicroPython I2C
# adapter (originally mp.py) merged into one module; ConfigData source
# switched from file-based to bytes-based (_config_bytes.py); upstream
# VL53L5CX/VL53L5CXMP class hierarchy collapsed into a single VL53L5CX
# class; public start() / read() / stop() helpers added for project use.
# See firmware-packages/vl53l5cx/VENDOR.md for full divergence notes.

"""VL53L5CX MicroPython driver — vendored from mp-extras/vl53l5cx."""

import struct
from time import sleep

from vl53l5cx._config_bytes import ConfigDataBytes as _ConfigData

NB_TARGET_PER_ZONE = 1

RANGING_MODE_AUTONOMOUS = 3
RANGING_MODE_CONTINUOUS = 1

POWER_MODE_SLEEP = 0
POWER_MODE_WAKEUP = 1

TARGET_ORDER_CLOSEST = 1
TARGET_ORDER_STRONGEST = 2

RESOLUTION_4X4 = 16
RESOLUTION_8X8 = 64

DATA_AMBIENT_PER_SPAD = 0
DATA_NB_SPADS_ENABLED = 1
DATA_NB_TARGET_DETECTED = 2
DATA_SIGNAL_PER_SPAD = 3
DATA_RANGE_SIGMA_MM = 4
DATA_DISTANCE_MM = 5
DATA_REFLECTANCE = 6
DATA_TARGET_STATUS = 7
DATA_MOTION_INDICATOR = 8

STATUS_VALID = 5
STATUS_VALID_LARGE_PULSE = 9

_VALID_STATUS = frozenset({STATUS_VALID, STATUS_VALID_LARGE_PULSE})

_UI_CMD_STATUS = 0x2C00
_UI_CMD_START = 0x2C04
_UI_CMD_END = 0x2FFF
_DCI_PIPE_CONTROL = 0xCF78
_DCI_SINGLE_RANGE = 0xCD5C
_DCI_DSS_CONFIG = 0xAD38
_DCI_ZONE_CONFIG = 0x5450
_DCI_FREQ_HZ = 0x5458
_DCI_TARGET_ORDER = 0xAE64
_DCI_OUTPUT_LIST = 0xCD78
_DCI_OUTPUT_CONFIG = 0xCD60
_DCI_OUTPUT_ENABLES = 0xCD68
_DCI_INT_TIME = 0x545C
_DCI_RANGING_MODE = 0xAD30
_DCI_SHARPENER = 0xAED8

_START_BH = 0x0000000D
_METADATA_BH = 0x54B400C0
_COMMONDATA_BH = 0x54C00040
_AMBIENT_RATE_BH = 0x54D00104
_SPAD_COUNT_BH = 0x55D00404
_NB_TARGET_DETECTED_BH = 0xCF7C0401
_SIGNAL_RATE_BH = 0xCFBC0404
_RANGE_SIGMA_MM_BH = 0xD2BC0402
_DISTANCE_BH = 0xD33C0402
_REFLECTANCE_BH = 0xD43C0401
_TARGET_STATUS_BH = 0xD47C0401
_MOTION_DETECT_BH = 0xCC5008C0

_AMBIENT_RATE_IDX = 0x54D0
_SPAD_COUNT_IDX = 0x55D0
_MOTION_DETECT_IDX = 0xCC50
_NB_TARGET_DETECTED_IDX = 0xCF7C
_SIGNAL_RATE_IDX = 0xCFBC
_RANGE_SIGMA_MM_IDX = 0xD2BC
_DISTANCE_IDX = 0xD33C
_REFLECTANCE_EST_PC_IDX = 0xD43C
_TARGET_STATUS_IDX = 0xD47C


class Results:
    """Container for one ranging measurement from the VL53L5CX."""

    def __init__(self) -> None:
        """Initialise all result fields to None."""
        self.ambient_per_spad = None
        self.distance_mm = None
        self.nb_spads_enabled = None
        self.nb_target_detected = None
        self.target_status = None
        self.reflectance = None
        self.motion_indicator = None
        self.range_sigma_mm = None
        self.signal_per_spad = None


class VL53L5CX:
    """MicroPython driver for the VL53L5CX 8×8 multizone ToF sensor.

    Combines the upstream base class and MicroPython I²C adapter into a
    single class. Configuration firmware (~86.5 KB) is loaded from frozen
    flash on every power-on via init(); start() then configures 8×8 mode
    and begins continuous ranging.

    Typical usage::

        from vl53l5cx import VL53L5CX
        tof = VL53L5CX(i2c)
        tof.init()
        tof.start()
        while True:
            if tof.check_data_ready():
                grid = tof.read()  # list of 64 int | None
    """

    def __init__(self, i2c: object, address: int = 0x29, lpn: object = None) -> None:
        """Initialise driver state; does not communicate with the sensor.

        Args:
            i2c: MicroPython I2C or SoftI2C object with readfrom_mem /
                writeto_mem support and addrsize=16 capability.
            address: 7-bit I²C address; default 0x29.
            lpn: Optional machine.Pin for the LPN (enable) line. Pass a Pin
                pulled high to enable hardware reset via reset(). None means
                the pin is not controlled (safe if the board pulls LPN high).
        """
        self.i2c = i2c
        self.addr = address
        self._ntpz = NB_TARGET_PER_ZONE
        self._lpn = lpn
        self._b1 = bytearray(1)
        self._streamcount = 255
        self._data_read_size = 0
        self._offset_data = None
        self.config_data = _ConfigData()

    # ------------------------------------------------------------------ #
    # MicroPython I²C transport (from upstream mp.py)                     #
    # ------------------------------------------------------------------ #

    def _rd_byte(self, reg16: int) -> int:
        """Read one byte from a 16-bit register address."""
        self.i2c.readfrom_mem_into(self.addr, reg16, self._b1, addrsize=16)
        return self._b1[0]

    def _rd_multi(self, reg16: int, size: int) -> bytes:
        """Read size bytes starting at a 16-bit register address."""
        return self.i2c.readfrom_mem(self.addr, reg16, size, addrsize=16)

    def _wr_byte(self, reg16: int, val: int) -> None:
        """Write one byte to a 16-bit register address."""
        self._b1[0] = val
        self.i2c.writeto_mem(self.addr, reg16, self._b1, addrsize=16)

    def _wr_multi(self, reg16: int, buf: bytes) -> None:
        """Write a buffer to a 16-bit register address."""
        self.i2c.writeto_mem(self.addr, reg16, buf, addrsize=16)

    # ------------------------------------------------------------------ #
    # Internal helpers (from upstream __init__.py)                        #
    # ------------------------------------------------------------------ #

    def _poll_for_answer(self, size: int, pos: int, reg16: int, mask: int, val: int) -> int:
        """Poll reg16 until data[pos] & mask == val or timeout."""
        timeout = 0
        while True:
            data = self._rd_multi(reg16, size)
            if data and ((data[pos] & mask) == val):
                status = 0
                break
            if timeout >= 200:
                status = -1 if len(data) < 3 else data[2]
                break
            elif size >= 4 and data[2] >= 0x7F:
                status = -2
                break
            else:
                timeout = timeout + 1

        sleep(0.01)
        if status:
            raise ValueError("poll_for_answer failed")
        return status

    @staticmethod
    def _swap_buffer(data: bytearray) -> None:
        """Byte-swap every 4-byte word in data in place."""
        for i in range(0, len(data), 4):
            data[i], data[i + 1], data[i + 2], data[i + 3] = (
                data[i + 3],
                data[i + 2],
                data[i + 1],
                data[i],
            )

    def _send_offset_data(self, offset_data: bytes, resolution: int) -> None:
        """Upload calibration offset data for the selected resolution."""
        buf = bytearray(offset_data)
        if resolution == 16:
            buf[0x10 : 0x10 + 8] = bytes([0x0F, 0x04, 0x04, 0x00, 0x08, 0x10, 0x10, 0x07])
            self._swap_buffer(buf)

            signal_grid = [0] * 64
            for i, w in enumerate(struct.unpack("64I", buf[0x3C : 0x3C + 256])):
                signal_grid[i] = w
            range_grid = [0] * 64
            for i, w in enumerate(struct.unpack("64h", buf[0x140 : 0x140 + 128])):
                range_grid[i] = w

            for j in range(4):
                for i in range(4):
                    signal_grid[i + (4 * j)] = int(
                        (
                            signal_grid[(2 * i) + (16 * j)]
                            + signal_grid[(2 * i) + (16 * j) + 1]
                            + signal_grid[(2 * i) + (16 * j) + 8]
                            + signal_grid[(2 * i) + (16 * j) + 9]
                        )
                        / 4
                    )
                    range_grid[i + (4 * j)] = int(
                        (
                            range_grid[(2 * i) + (16 * j)]
                            + range_grid[(2 * i) + (16 * j) + 1]
                            + range_grid[(2 * i) + (16 * j) + 8]
                            + range_grid[(2 * i) + (16 * j) + 9]
                        )
                        / 4
                    )

            for i in range(48):
                signal_grid[0x10 + i] = 0
                range_grid[0x10 + i] = 0

            buf[0x3C : 0x3C + 256] = struct.pack("64I", *signal_grid)
            buf[0x140 : 0x140 + 128] = struct.pack("64h", *range_grid)
            self._swap_buffer(buf)

        x = buf[8:-4]
        x.extend(bytes([0x00, 0x00, 0x00, 0x0F, 0x03, 0x01, 0x01, 0xE4]))

        self._wr_multi(0x2E18, x)
        self._poll_for_answer(4, 1, _UI_CMD_STATUS, 0xFF, 0x03)

    def _send_xtalk_data(self, resolution: int) -> None:
        """Upload cross-talk calibration data for the selected resolution."""
        if resolution == RESOLUTION_4X4:
            xtalk_data = self.config_data.xtalk4x4_data
        else:
            xtalk_data = self.config_data.xtalk_data

        self._wr_multi(0x2CF8, xtalk_data)
        self._poll_for_answer(4, 1, _UI_CMD_STATUS, 0xFF, 0x03)

    def _dci_read_data(self, data: bytearray, index: int) -> None:
        """Read data from the device configuration interface."""
        data_size = len(data)
        cmd = bytearray(12)

        cmd[0] = index >> 8
        cmd[1] = index & 0xFF
        cmd[2] = (data_size & 0xFF0) >> 4
        cmd[3] = (data_size & 0xF) << 4
        cmd[7] = 0x0F
        cmd[9] = 0x02
        cmd[11] = 0x08
        self._wr_multi(_UI_CMD_END - 11, cmd)
        self._poll_for_answer(4, 1, _UI_CMD_STATUS, 0xFF, 0x03)

        buf = self._rd_multi(_UI_CMD_START, data_size + 12)
        for i in range(0, data_size, 4):
            data[i] = buf[4 + i + 3]
            data[i + 1] = buf[4 + i + 2]
            data[i + 2] = buf[4 + i + 1]
            data[i + 3] = buf[4 + i + 0]

    def _dci_replace_data(self, data: bytearray, index: int, new_data: bytes, pos: int) -> None:
        """Read-modify-write a slice of a DCI register block."""
        self._dci_read_data(data, index)
        for i in range(len(new_data)):
            data[pos + i] = new_data[i]
        self._dci_write_data(data, index)

    def _dci_write_data(self, data: bytearray, index: int) -> None:
        """Write data to the device configuration interface."""
        data_size = len(data)
        buf = bytearray(data_size + 12)

        buf[0] = index >> 8
        buf[1] = index & 0xFF
        buf[2] = (data_size & 0xFF0) >> 4
        buf[3] = (data_size & 0x0F) << 4

        for i in range(0, data_size, 4):
            buf[4 + i] = data[i + 3]
            buf[4 + i + 1] = data[i + 2]
            buf[4 + i + 2] = data[i + 1]
            buf[4 + i + 3] = data[i + 0]

        for i, b in enumerate(
            [
                0x00,
                0x00,
                0x00,
                0x0F,
                0x05,
                0x01,
                (data_size + 8) >> 8,
                (data_size + 8) & 0xFF,
            ],
            4 + data_size,
        ):
            buf[i] = b

        address = _UI_CMD_END - (data_size + 12) + 1

        self._wr_multi(address, buf)
        self._poll_for_answer(4, 1, _UI_CMD_STATUS, 0xFF, 0x03)

    @staticmethod
    def _header(word: int) -> tuple:
        """Decode a block header: (type, size, index)."""
        return (word & 0xF), (word & 0xFFF0) >> 4, (word >> 16)

    @staticmethod
    def _ambient_per_spad(raw: bytes) -> list:
        """Decode ambient-per-SPAD values from raw bytes."""
        fmt = ">{}I".format(len(raw) // 4)
        return [v // 2048 for v in struct.unpack(fmt, raw)]

    @staticmethod
    def _distance_mm(raw: bytes) -> list:
        """Decode distance values (mm) from raw big-endian int16 bytes."""
        fmt = ">{}h".format(len(raw) // 2)
        return [0 if v < 0 else v >> 2 for v in struct.unpack(fmt, raw)]

    @staticmethod
    def _nb_spads_enabled(raw: bytes) -> list:
        """Decode SPAD-enabled counts from raw bytes."""
        fmt = ">{}I".format(len(raw) // 4)
        return list(struct.unpack(fmt, raw))

    @staticmethod
    def _motion_indicator(raw: bytes) -> tuple:
        """Decode motion-indicator data from raw bytes."""
        return struct.unpack(">IIBBBB32I", raw)

    @staticmethod
    def _range_sigma_mm(raw: bytes) -> list:
        """Decode range-sigma values from raw big-endian uint16 bytes."""
        fmt = ">{}H".format(len(raw) // 2)
        return [r / 128 for r in struct.unpack(fmt, raw)]

    @staticmethod
    def _signal_per_spad(raw: bytes) -> list:
        """Decode signal-per-SPAD values from raw bytes."""
        fmt = ">{}I".format(len(raw) // 4)
        return [r / 2048 for r in struct.unpack(fmt, raw)]

    # ------------------------------------------------------------------ #
    # Public sensor API (mirrors upstream VL53L5CX)                       #
    # ------------------------------------------------------------------ #

    def is_alive(self) -> bool:
        """Return True if the sensor is reachable and returns its device ID."""
        self._wr_byte(0x7FFF, 0)
        buf = self._rd_multi(0, 2)
        self._wr_byte(0x7FFF, 2)
        return (buf[0] == 0xF0) and (buf[1] == 0x02)

    def init(self) -> None:
        """Load ST firmware into the sensor and apply default configuration.

        Takes ~7-9 s over the project's 100 kHz soft I²C (≈2-3 s on a 400 kHz
        hardware bus) due to the ~86.5 KB firmware upload. Must be called once
        after power-on before start(). Propagates ValueError from
        _poll_for_answer if any internal poll times out during initialisation.
        """
        self._wr_byte(0x7FFF, 0x00)
        self._wr_byte(0x0009, 0x04)
        self._wr_byte(0x000F, 0x40)
        self._wr_byte(0x000A, 0x03)
        self._rd_byte(0x7FFF)

        self._wr_byte(0x000C, 0x01)
        self._wr_byte(0x0101, 0x00)
        self._wr_byte(0x0102, 0x00)
        self._wr_byte(0x010A, 0x01)
        self._wr_byte(0x4002, 0x01)
        self._wr_byte(0x4002, 0x00)
        self._wr_byte(0x010A, 0x03)
        self._wr_byte(0x0103, 0x01)
        self._wr_byte(0x000C, 0x00)
        self._wr_byte(0x000F, 0x43)
        sleep(0.001)

        self._wr_byte(0x000F, 0x40)
        self._wr_byte(0x000A, 0x01)
        sleep(0.1)

        self._wr_byte(0x7FFF, 0x00)
        self._poll_for_answer(1, 0, 0x06, 0xFF, 1)

        self._wr_byte(0x000E, 0x01)
        self._wr_byte(0x7FFF, 0x02)

        self._wr_byte(0x03, 0x0D)
        self._wr_byte(0x7FFF, 0x01)
        self._poll_for_answer(1, 0, 0x21, 0x10, 0x10)
        self._wr_byte(0x7FFF, 0x00)

        self._wr_byte(0x0C, 0x01)

        self._wr_byte(0x7FFF, 0x00)
        self._wr_byte(0x101, 0x00)
        self._wr_byte(0x102, 0x00)
        self._wr_byte(0x010A, 0x01)
        self._wr_byte(0x4002, 0x01)
        self._wr_byte(0x4002, 0x00)
        self._wr_byte(0x010A, 0x03)
        self._wr_byte(0x103, 0x01)
        self._wr_byte(0x400F, 0x00)
        self._wr_byte(0x021A, 0x43)
        self._wr_byte(0x021A, 0x03)
        self._wr_byte(0x021A, 0x01)
        self._wr_byte(0x021A, 0x00)
        self._wr_byte(0x0219, 0x00)
        self._wr_byte(0x021B, 0x00)

        self._wr_byte(0x7FFF, 0x00)
        self._wr_byte(0x0C, 0x00)
        self._wr_byte(0x7FFF, 0x01)
        self._wr_byte(0x20, 0x07)
        self._wr_byte(0x20, 0x06)

        fw = self.config_data.fw_data(0x1000)
        for page, size in enumerate([0x8000, 0x8000, 0x5000], start=9):
            self._wr_byte(0x7FFF, page)
            for sub in range(0, size, 0x1000):
                self._wr_multi(sub, next(fw))

        self._wr_byte(0x7FFF, 0x01)

        self._wr_byte(0x7FFF, 0x02)
        self._wr_byte(0x03, 0x0D)
        self._wr_byte(0x7FFF, 0x01)
        self._poll_for_answer(1, 0, 0x21, 0x10, 0x10)
        self._wr_byte(0x7FFF, 0x00)
        self._wr_byte(0x0C, 0x01)

        self._wr_byte(0x7FFF, 0x00)
        self._wr_byte(0x114, 0x00)
        self._wr_byte(0x115, 0x00)
        self._wr_byte(0x116, 0x42)
        self._wr_byte(0x117, 0x00)
        self._wr_byte(0x0B, 0x00)
        self._wr_byte(0x0C, 0x00)
        self._wr_byte(0x0B, 0x01)
        self._poll_for_answer(1, 0, 0x06, 0xFF, 0x00)

        self._wr_byte(0x7FFF, 0x02)

        nvm_cmd = bytes(
            [
                0x54,
                0x00,
                0x00,
                0x40,
                0x9E,
                0x14,
                0x00,
                0xC0,
                0x9E,
                0x20,
                0x01,
                0x40,
                0x9E,
                0x34,
                0x00,
                0x40,
                0x9E,
                0x38,
                0x04,
                0x04,
                0x9F,
                0x38,
                0x04,
                0x02,
                0x9F,
                0xB8,
                0x01,
                0x00,
                0x9F,
                0xC8,
                0x01,
                0x00,
                0x00,
                0x00,
                0x00,
                0x0F,
                0x02,
                0x02,
                0x00,
                0x24,
            ]
        )

        self._wr_multi(0x2FD8, nvm_cmd)
        self._poll_for_answer(4, 0, 0x2C00, 0xFF, 2)

        self._offset_data = self._rd_multi(0x2C04, 492)
        self._send_offset_data(self._offset_data, RESOLUTION_4X4)
        self._send_xtalk_data(RESOLUTION_4X4)

        self._wr_multi(0x2C34, self.config_data.default_config_data)
        self._poll_for_answer(4, 1, _UI_CMD_STATUS, 0xFF, 0x03)

        self._dci_write_data(bytes([self._ntpz, 0x00, 0x01, 0x00]), _DCI_PIPE_CONTROL)
        self._dci_write_data(b"\x01\x00\x00\x00", _DCI_SINGLE_RANGE)

    def start_ranging(self, enables: object) -> bool:
        """Begin a ranging session with the given set of output enables.

        Args:
            enables: Iterable of DATA_* constants selecting which data
                blocks the sensor should include in each result frame.

        Returns:
            True on success.
        """
        resolution = self.resolution
        self._data_read_size = 0
        self._streamcount = 255

        output_bh_enable = [0x00000007, 0x00000000, 0x00000000, 0xC0000000]

        output = [
            _START_BH,
            _METADATA_BH,
            _COMMONDATA_BH,
            _AMBIENT_RATE_BH,
            _SPAD_COUNT_BH,
            _NB_TARGET_DETECTED_BH,
            _SIGNAL_RATE_BH,
            _RANGE_SIGMA_MM_BH,
            _DISTANCE_BH,
            _REFLECTANCE_BH,
            _TARGET_STATUS_BH,
            _MOTION_DETECT_BH,
        ]

        self._data_read_size += (0 + 4) + (4 + 0xC) + (4 + 0x4)

        for e in enables:
            btype, size, idx = self._header(output[e + 3])
            if (btype > 0) and (btype < 0xD):
                if (idx >= 0x54D0) and (idx < (0x54D0 + 960)):
                    size = resolution
                else:
                    size = resolution * self._ntpz
                self._data_read_size += (size * btype) + 4
                output[e + 3] = (idx << 16) | (size << 4) | btype
            else:
                self._data_read_size += size + 4

            output_bh_enable[0] |= 1 << (e + 3)

        self._data_read_size += 20

        self._dci_write_data(struct.pack("<12I", *output), _DCI_OUTPUT_LIST)
        self._dci_write_data(
            struct.pack("<II", self._data_read_size, len(output) + 1),
            _DCI_OUTPUT_CONFIG,
        )
        self._dci_write_data(
            struct.pack("<IIII", *output_bh_enable),
            _DCI_OUTPUT_ENABLES,
        )

        self._wr_byte(0x7FFF, 0)
        self._wr_byte(0x09, 0x05)
        self._wr_byte(0x7FFF, 0x2)

        self._wr_multi(_UI_CMD_END - 3, b"\x00\x03\x00\x00")
        return not self._poll_for_answer(4, 1, _UI_CMD_STATUS, 0xFF, 0x03)

    def check_data_ready(self) -> bool:
        """Return True if a new ranging result is ready to be retrieved."""
        buf = self._rd_multi(0, 4)
        if (
            (buf[0] != self._streamcount)
            and (buf[0] != 255)
            and (buf[1] == 0x5)
            and ((buf[2] & 0x5) == 0x5)
            and ((buf[3] & 0x10) == 0x10)
        ):
            self._streamcount = buf[0]
            return True
        return False

    def get_ranging_data(self) -> Results:
        """Retrieve and decode the latest ranging result from the sensor.

        Returns:
            Results object with decoded distance_mm, target_status, and any
            other data blocks that were enabled in start_ranging().
        """
        results = Results()

        buf = self._rd_multi(0, self._data_read_size)
        self._streamcount = buf[0]

        offset = 16
        while offset < len(buf):
            bh = struct.unpack(">I", buf[offset : offset + 4])[0]
            btype, size, idx = self._header(bh)

            if btype > 1 and btype < 0xD:
                msize = btype * size
            else:
                msize = size

            offset += 4
            raw = buf[offset : offset + msize]

            if idx == _AMBIENT_RATE_IDX:
                results.ambient_per_spad = self._ambient_per_spad(raw)
            elif idx == _SPAD_COUNT_IDX:
                results.nb_spads_enabled = self._nb_spads_enabled(raw)
            elif idx == _MOTION_DETECT_IDX:
                results.motion_indicator = self._motion_indicator(raw)
            elif idx == _NB_TARGET_DETECTED_IDX:
                results.nb_target_detected = raw
            elif idx == _SIGNAL_RATE_IDX:
                results.signal_per_spad = self._signal_per_spad(raw)
            elif idx == _RANGE_SIGMA_MM_IDX:
                results.range_sigma_mm = self._range_sigma_mm(raw)
            elif idx == _DISTANCE_IDX:
                results.distance_mm = self._distance_mm(raw)
            elif idx == _REFLECTANCE_EST_PC_IDX:
                results.reflectance = raw
            elif idx == _TARGET_STATUS_IDX:
                results.target_status = raw

            offset += msize

        return results

    def stop_ranging(self) -> None:
        """Stop continuous ranging and return the sensor to idle."""
        buf = self._rd_multi(0x2FFC, 4)
        auto_stop_flag = struct.unpack("<I", buf)[0]
        if auto_stop_flag != 0x4FF:
            self._wr_byte(0x7FFF, 0x00)
            self._wr_byte(0x15, 0x16)
            self._wr_byte(0x14, 0x01)

            timeout = 1000
            while timeout:
                flag = self._rd_byte(0x6)
                if flag & 0x80:
                    break
                sleep(0.010)
                timeout -= 10

            if timeout == 0:
                raise ValueError("failed to stop MCU")

        self._wr_byte(0x7FFF, 0x00)
        self._wr_byte(0x14, 0x00)
        self._wr_byte(0x15, 0x00)

        self._wr_byte(0x09, 0x04)
        self._wr_byte(0x7FFF, 0x02)

    def reset(self) -> None:
        """Perform a hardware reset via the LPN pin.

        Raises:
            ValueError: if no LPN pin was supplied to the constructor.
        """
        if not self._lpn:
            raise ValueError("no LPN pin provided")

        self._lpn.value(0)
        sleep(0.1)
        self._lpn.value(1)
        sleep(0.1)

    # ------------------------------------------------------------------ #
    # Properties (from upstream __init__.py)                              #
    # ------------------------------------------------------------------ #

    @property
    def integration_time_ms(self) -> float:
        """Ranging integration time in milliseconds."""
        buf = bytearray(20)
        self._dci_read_data(buf, _DCI_INT_TIME)
        return struct.unpack("<I", buf[0:4])[0] / 1000

    @integration_time_ms.setter
    def integration_time_ms(self, itime: int) -> None:
        """Set ranging integration time; must be 2–1000 ms."""
        if (itime < 2) or (itime > 1000):
            raise ValueError("invalid integration time (2 < it < 1000)")

        buf = bytearray(20)
        self._dci_replace_data(buf, _DCI_INT_TIME, struct.pack("I", itime * 1000), 0)

    @property
    def resolution(self) -> int:
        """Current zone resolution: RESOLUTION_4X4 (16) or RESOLUTION_8X8 (64)."""
        buf = bytearray(8)
        self._dci_read_data(buf, _DCI_ZONE_CONFIG)
        return buf[0] * buf[1]

    @resolution.setter
    def resolution(self, resolution: int) -> None:
        """Switch zone resolution; updates offset and xtalk calibration."""
        if (resolution != RESOLUTION_8X8) and (resolution != RESOLUTION_4X4):
            raise ValueError("invalid resolution")

        buf = bytearray(16)
        self._dci_read_data(buf, _DCI_DSS_CONFIG)

        if resolution == RESOLUTION_8X8:
            buf[0x04] = 16
            buf[0x06] = 16
            buf[0x09] = 1
        else:
            buf[0x04] = 64
            buf[0x06] = 64
            buf[0x09] = 4

        self._dci_write_data(buf, _DCI_DSS_CONFIG)

        buf = bytearray(8)
        self._dci_read_data(buf, _DCI_ZONE_CONFIG)

        if resolution == RESOLUTION_8X8:
            buf[0x00] = 8
            buf[0x01] = 8
            buf[0x04] = 4
            buf[0x05] = 4
        else:
            buf[0x00] = 4
            buf[0x01] = 4
            buf[0x04] = 8
            buf[0x05] = 8

        self._dci_write_data(buf, _DCI_ZONE_CONFIG)

        self._send_offset_data(self._offset_data, resolution)
        self._send_xtalk_data(resolution)

    @property
    def ranging_freq(self) -> int:
        """Ranging output frequency in Hz."""
        buf = bytearray(4)
        self._dci_read_data(buf, _DCI_FREQ_HZ)
        return buf[1]

    @ranging_freq.setter
    def ranging_freq(self, freq: int) -> None:
        """Set ranging output frequency in Hz."""
        buf = bytearray(4)
        self._b1[0] = freq
        self._dci_replace_data(buf, _DCI_FREQ_HZ, self._b1, 1)

    @property
    def target_order(self) -> int:
        """Target sort order: TARGET_ORDER_CLOSEST or TARGET_ORDER_STRONGEST."""
        buf = bytearray(4)
        self._dci_read_data(buf, _DCI_TARGET_ORDER)
        return buf[0]

    @target_order.setter
    def target_order(self, order: int) -> None:
        """Set target sort order."""
        buf = bytearray(4)
        self._b1[0] = order
        self._dci_replace_data(buf, _DCI_TARGET_ORDER, self._b1, 0)

    @property
    def ranging_mode(self) -> int:
        """Ranging mode: RANGING_MODE_CONTINUOUS or RANGING_MODE_AUTONOMOUS."""
        buf = bytearray(8)
        self._dci_read_data(buf, _DCI_RANGING_MODE)
        if buf[1] == 1:
            return RANGING_MODE_CONTINUOUS
        return RANGING_MODE_AUTONOMOUS

    @ranging_mode.setter
    def ranging_mode(self, mode: int) -> None:
        """Set ranging mode."""
        buf = bytearray(8)
        self._dci_read_data(buf, _DCI_RANGING_MODE)
        if mode == RANGING_MODE_CONTINUOUS:
            buf[1] = 0x1
            buf[3] = 0x3
            single_range = 0
        elif mode == RANGING_MODE_AUTONOMOUS:
            buf[1] = 0x3
            buf[3] = 0x2
            single_range = 1
        else:
            raise ValueError("invalid ranging mode")

        self._dci_write_data(buf, _DCI_RANGING_MODE)
        self._dci_write_data(struct.pack(">I", single_range), _DCI_SINGLE_RANGE)

    @property
    def power_mode(self) -> int:
        """Power mode: POWER_MODE_WAKEUP or POWER_MODE_SLEEP."""
        self._wr_byte(0x7FFF, 0x0)
        raw = self._rd_byte(0x9)
        self._wr_byte(0x7FFF, 0x2)

        if raw == 4:
            return POWER_MODE_WAKEUP
        if raw == 2:
            return POWER_MODE_SLEEP
        return -1

    @power_mode.setter
    def power_mode(self, mode: int) -> None:
        """Switch between POWER_MODE_SLEEP and POWER_MODE_WAKEUP."""
        if self.power_mode != mode and mode in [POWER_MODE_SLEEP, POWER_MODE_WAKEUP]:
            self._wr_byte(0x7FFF, 0)
            if mode == POWER_MODE_WAKEUP:
                self._wr_byte(0x9, 0x4)
                self._poll_for_answer(1, 0, 0x6, 0x01, 1)
            elif mode == POWER_MODE_SLEEP:
                self._wr_byte(0x09, 0x02)
                self._poll_for_answer(1, 0, 0x06, 0x01, 0)
            self._wr_byte(0x7FFF, 0x02)

    @property
    def sharpener_percent(self) -> int:
        """Image sharpener strength as a percentage (0–100)."""
        buf = bytearray(16)
        self._dci_read_data(buf, _DCI_SHARPENER)
        return (buf[0xD] * 100) // 255

    @sharpener_percent.setter
    def sharpener_percent(self, value: int) -> None:
        """Set image sharpener strength (0–100%)."""
        if (value < 0) or (value > 100):
            raise ValueError("invalid sharpener percent")

        self._b1[0] = (value * 255) // 100
        self._dci_replace_data(bytearray(16), _DCI_SHARPENER, self._b1, 0xD)

    # ------------------------------------------------------------------ #
    # Project-level convenience API                                       #
    # ------------------------------------------------------------------ #

    def start(self, freq: int = 10) -> None:
        """Configure 8×8 resolution, set frequency, and begin ranging.

        Convenience wrapper for project firmware: sets resolution to
        RESOLUTION_8X8, ranging_freq to freq, then calls start_ranging()
        with DATA_DISTANCE_MM and DATA_TARGET_STATUS enabled.

        Args:
            freq: Ranging output frequency in Hz (default 10).
        """
        self.resolution = RESOLUTION_8X8
        self.ranging_freq = freq
        self.start_ranging({DATA_DISTANCE_MM, DATA_TARGET_STATUS})

    def read(self) -> list:
        """Return a flat list of 64 zone distances in mm, or None per zone.

        Calls get_ranging_data() and converts each zone's distance to int
        (mm) when target_status is STATUS_VALID (5) or STATUS_VALID_LARGE_PULSE
        (9), or None otherwise (out-of-range or unreliable reading).

        Returns:
            List of 64 elements, row-major (row 0 first). Each element is
            an int distance in mm, or None for an invalid/out-of-range zone.
        """
        result = self.get_ranging_data()
        return [
            v if s in _VALID_STATUS else None
            for v, s in zip(result.distance_mm, result.target_status)
        ]

    def stop(self) -> None:
        """Stop continuous ranging."""
        self.stop_ranging()
