"""Host tests for build.py's factory-data checks.

The real parser is ESP-Matter's `tests.utils`, which only exists inside the
matter-toolchain image, so a stand-in is planted under tmp_path and reached
through the same sys.path insert and import_module call build.py uses in the
container. Its package name really is `tests`, which is why the fixture evicts it
from sys.modules again -- left behind, it would shadow the name for every other
suite in a full run.
"""

import base64
import importlib
import sys

import build
import pytest

_DISCRIMINATOR = 3840
_SALT = base64.b64encode(b"a per-device salt").decode()
_VERIFIER = base64.b64encode(bytes(97)).decode()


def test_reads_the_partition_through_the_vendored_parser(nvs_parser, tmp_path):
    partition = tmp_path / "factory-partition.bin"
    partition.write_bytes(b"")

    assert build._read_factory_data(partition, nvs_parser) == {"parsed": str(partition)}
    # The parser root is borrowed for the import and handed straight back.
    assert str(nvs_parser) not in sys.path


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


@pytest.fixture
def nvs_parser(tmp_path):
    """Plant a `tests.utils` stand-in and evict it from sys.modules afterwards."""
    root = tmp_path / "mfg_tool"
    package = root / "tests"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "utils.py").write_text(
        'def parse_partition_bin(path):\n    return {"parsed": path}\n',
        encoding="utf-8",
    )
    importlib.invalidate_caches()
    yield root
    for name in ("tests.utils", "tests"):
        sys.modules.pop(name, None)
