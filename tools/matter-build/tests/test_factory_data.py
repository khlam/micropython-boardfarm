"""Host tests for Matter credential minting and factory-data validation."""

import base64
import csv
import json
import subprocess
import sys

import build
import nvs_partition_read
import pytest

_DISCRIMINATOR = 3840
_SALT = base64.b64encode(b"a per-device salt").decode()
_VERIFIER = base64.b64encode(bytes(97)).decode()


def test_reads_the_factory_namespace_through_the_idf_nvs_tool(monkeypatch, tmp_path):
    partition = tmp_path / "factory-partition.bin"
    partition.write_bytes(b"")
    calls = []

    def run(command, **kwargs):
        calls.append((command, kwargs))
        entries = [
            {"namespace": "chip-factory", "key": "vendor-id", "data": 0xFFF1},
            {"namespace": "other", "key": "vendor-id", "data": 0x1234},
            {"namespace": "chip-factory", "key": "salt", "data": _SALT},
        ]
        return subprocess.CompletedProcess(command, 0, stdout=json.dumps(entries))

    monkeypatch.setattr(nvs_partition_read.subprocess, "run", run)

    assert nvs_partition_read.read_factory_partition(partition, "chip-factory") == {
        "vendor-id": 0xFFF1,
        "salt": _SALT,
    }
    assert calls == [
        (
            [
                sys.executable,
                str(nvs_partition_read._NVS_TOOL),
                "--dump",
                "minimal",
                "--format",
                "json",
                str(partition),
            ],
            {"capture_output": True, "check": True, "text": True},
        )
    ]


def test_mints_matching_credentials_and_factory_identity(identity, tmp_path, monkeypatch):
    passcode = 20202021
    monkeypatch.setattr(build.secrets, "randbelow", lambda _limit: _DISCRIMINATOR)
    monkeypatch.setattr(build.secrets, "token_bytes", lambda length: bytes(range(length)))

    factory, qr, manual, payload, discriminator = build._mint_credentials(
        tmp_path,
        identity,
        "Acme",
        "SN0001",
        "Color Light",
        passcode=passcode,
    )

    assert factory == tmp_path / "manufacturing" / "factory-partition.bin"
    assert discriminator == _DISCRIMINATOR
    assert factory.stat().st_size == identity.factory_size
    assert qr == tmp_path / "manufacturing" / "qrcode.png"
    assert qr.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    assert build._decode_qr_payload(payload) == {
        "version": 0,
        "vendor_id": identity.vendor_id,
        "product_id": identity.product_id,
        "commissioning_flow": 0,
        "discovery": identity.discovery_mode,
        "discriminator": discriminator,
        "passcode": passcode,
        "padding": 0,
    }
    assert build._decode_manual_code(manual) == {
        "short_discriminator": discriminator >> 8,
        "passcode": passcode,
    }

    with (tmp_path / "manufacturing" / "factory-partition.csv").open(
        newline="", encoding="utf-8"
    ) as stream:
        rows = {row["key"]: row["value"] for row in csv.DictReader(stream)}
    assert rows["discriminator"] == str(discriminator)
    assert rows["vendor-id"] == str(identity.vendor_id)
    assert rows["vendor-name"] == "Acme"
    assert rows["product-id"] == str(identity.product_id)
    assert rows["product-name"] == "Color Light"
    assert rows["serial-num"] == "SN0001"
    assert base64.b64decode(rows["salt"]) == bytes(range(build._SPAKE2P_SALT_LEN))
    assert len(base64.b64decode(rows["verifier"])) == 97
    assert "passcode" not in rows


def test_accepts_factory_data_matching_the_pairing_code(identity):
    build._validate_factory_identity(factory_values(), _DISCRIMINATOR, identity)


def test_rejects_a_discriminator_from_another_device(identity):
    with pytest.raises(ValueError, match="factory discriminator does not match"):
        build._validate_factory_identity(factory_values(), _DISCRIMINATOR + 1, identity)


@pytest.mark.parametrize("field", ["vendor-id", "product-id"])
def test_rejects_factory_data_built_for_another_product(identity, field):
    values = factory_values(**{field: 0x1234})
    with pytest.raises(ValueError, match="VID/PID does not match"):
        build._validate_factory_identity(values, _DISCRIMINATOR, identity)


def test_rejects_a_plaintext_passcode(identity):
    # A passcode in factory data would let anyone reading the flash commission it.
    values = factory_values(passcode=20202021)
    with pytest.raises(ValueError, match="no plaintext passcode"):
        build._validate_factory_identity(values, _DISCRIMINATOR, identity)


@pytest.mark.parametrize("field", ["salt", "verifier"])
@pytest.mark.parametrize("value", [None, 1234])
def test_rejects_missing_verifier_material(identity, field, value):
    values = factory_values(**{field: value})
    with pytest.raises(ValueError, match="must contain a verifier"):
        build._validate_factory_identity(values, _DISCRIMINATOR, identity)


def factory_values(**overrides):
    """Return a factory-data dict the checks accept, before any override is applied.

    A key set to None is removed rather than stored, so a test can drop a field as
    easily as it can corrupt one.
    """
    values = {
        "discriminator": _DISCRIMINATOR,
        "vendor-id": 0xFFF1,
        "product-id": 0x8001,
        "salt": _SALT,
        "verifier": _VERIFIER,
    }
    values.update(overrides)
    return {key: value for key, value in values.items() if value is not None}


@pytest.fixture
def identity():
    """A build identity matching the published CHIP test device."""
    return build._BuildIdentity(
        vendor_id=0xFFF1,
        product_id=0x8001,
        factory_offset=0x3D0000,
        factory_size=0x6000,
        flash_size=4 * 1024 * 1024,
        discovery_mode=4,
    )
