"""Host tests for build.py's board-configuration parsers.

The parsers are what let every later check compare an artifact against the
firmware's own view of itself, so they are exercised against fixture files that
carry each shape the real board config can take, and once against the real board
config so a change there cannot silently drift away from what the tests assume.
"""

import pathlib

import build
import pytest

_FIXTURES = pathlib.Path(__file__).parent / "fixtures"
_REAL_BOARD = pathlib.Path("/projects/matter/native/board/ESP32_S3_MATTER")


def test_sdkconfig_keeps_only_key_value_lines(fixture_config):
    assert fixture_config["CONFIG_DEVICE_VENDOR_ID"] == "0xFFF1"
    assert fixture_config["CONFIG_ESPTOOLPY_FLASHSIZE_4MB"] == "y"
    # Comments, blank lines and bare tokens carry no "=" and are dropped.
    assert not [key for key in fixture_config if key.startswith("#")]
    assert "NOT_A_SETTING" not in fixture_config


def test_sdkconfig_strips_indentation(fixture_config):
    assert fixture_config["CONFIG_CHIP_FACTORY_NAMESPACE_PARTITION_LABEL"] == '"fctry"'


def test_required_reports_the_missing_key(fixture_config):
    with pytest.raises(ValueError, match="CONFIG_NOPE"):
        build._required(fixture_config, "CONFIG_NOPE")


def test_partitions_finds_the_factory_row():
    assert build._partitions_to_factory(_FIXTURES / "partitions.csv", "fctry") == (
        0x3D0000,
        0x6000,
    )


def test_partitions_rejects_a_row_without_offset_and_size():
    with pytest.raises(ValueError, match="no explicit offset and size"):
        build._partitions_to_factory(_FIXTURES / "partitions.csv", "nvs_keys")


def test_partitions_rejects_a_missing_row():
    with pytest.raises(ValueError, match="has no 'absent' row"):
        build._partitions_to_factory(_FIXTURES / "partitions.csv", "absent")


def test_partitions_ignores_the_comment_row(tmp_path):
    # The header names the columns, so a label matching a commented-out row must
    # not be picked up from it.
    table = tmp_path / "partitions.csv"
    table.write_text("# fctry, data, nvs, 0x1000, 0x2000,\n", encoding="utf-8")
    with pytest.raises(ValueError, match="has no 'fctry' row"):
        build._partitions_to_factory(table, "fctry")


def test_flash_size_reads_the_enabled_key(fixture_config):
    assert build._config_to_flash_size(fixture_config) == 4 * 1024 * 1024


def test_flash_size_ignores_a_disabled_key():
    with pytest.raises(ValueError, match="no CONFIG_ESPTOOLPY_FLASHSIZE"):
        build._config_to_flash_size({"CONFIG_ESPTOOLPY_FLASHSIZE_8MB": "n"})


def test_pyproject_reads_the_model_name(tmp_path):
    metadata = tmp_path / "pyproject.toml"
    metadata.write_text('[project]\nname = "Color Light"\n', encoding="utf-8")

    assert build._pyproject_to_model(metadata) == "Color Light"


@pytest.mark.parametrize(
    "contents",
    [
        '[project]\nname = ""\n',
        "[project]\nname = 123\n",
        '[tool.example]\nname = "Color Light"\n',
    ],
)
def test_pyproject_rejects_an_invalid_model_name(tmp_path, contents):
    metadata = tmp_path / "pyproject.toml"
    metadata.write_text(contents, encoding="utf-8")

    with pytest.raises(ValueError, match="must set a non-empty name"):
        build._pyproject_to_model(metadata)


def test_board_to_identity_reads_the_fixture_board():
    identity = build._board_to_identity(_FIXTURES, discovery_mode=2)
    assert identity == build._BuildIdentity(
        vendor_id=0xFFF1,
        product_id=0x8001,
        factory_offset=0x3D0000,
        factory_size=0x6000,
        flash_size=4 * 1024 * 1024,
        discovery_mode=2,
    )


def test_board_to_identity_matches_the_real_board_config():
    # Pins the shipped ESP32-S3 board config: a change to its VID/PID, factory
    # partition placement or flash size has to be a deliberate edit here too.
    identity = build._board_to_identity(_REAL_BOARD, discovery_mode=build._DISCOVERY_MODE)
    assert identity == build._BuildIdentity(
        vendor_id=0xFFF1,
        product_id=0x8001,
        factory_offset=0x3D0000,
        factory_size=0x6000,
        flash_size=4 * 1024 * 1024,
        discovery_mode=2,
    )


@pytest.fixture
def fixture_config():
    """Parsed fixture sdkconfig, shared by the parser and lookup tests."""
    return build._sdkconfig_to_values(_FIXTURES / "sdkconfig.board")
