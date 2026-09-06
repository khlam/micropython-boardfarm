"""Host tests for the external toolchain commands build.py assembles.

Neither idf.py nor esptool.py exists outside the matter-toolchain image, so
`_run` is exercised against a stub executable on a throwaway PATH and the build
steps run with `_run` swapped for a recorder that captures their argv.
"""

import os
import subprocess

import build
import pytest

_IDENTITY = build._BuildIdentity(
    vendor_id=0xFFF1,
    product_id=0x8001,
    factory_offset=0x3D0000,
    factory_size=0x6000,
    flash_size=4 * 1024 * 1024,
    discovery_mode=2,
)


def test_run_resolves_the_tool_on_the_given_path(stub_tool, tmp_path):
    build._run(["faketool", str(tmp_path / "touched")], env={"PATH": str(stub_tool)})
    assert (tmp_path / "touched").is_file()


def test_run_honours_the_working_directory(stub_tool, tmp_path):
    workdir = tmp_path / "elsewhere"
    workdir.mkdir()
    build._run(["faketool", "touched"], cwd=workdir, env={"PATH": str(stub_tool)})
    assert (workdir / "touched").is_file()


def test_run_names_the_tool_that_is_not_on_path(tmp_path):
    with pytest.raises(ValueError, match=r"idf\.py is not on PATH"):
        build._run(["idf.py", "build"], env={"PATH": str(tmp_path)})


def test_run_propagates_a_failing_tool(stub_tool):
    with pytest.raises(subprocess.CalledProcessError):
        build._run(["faketool", "--fail"], env={"PATH": str(stub_tool)})


def test_firmware_build_names_the_board_and_native_module(recorder, tmp_path):
    build._build_firmware(tmp_path, None)

    command, kwargs = recorder[0]
    assert command[0] == "idf.py"
    assert command[-1] == "build"
    assert f"MICROPY_BOARD={build._BOARD_NAME}" in command
    assert f"MICROPY_BOARD_DIR={build._BOARD_DIR}" in command
    assert f"MICROPY_FROZEN_MANIFEST={build._MANIFEST}" in command
    assert command[command.index("-B") + 1] == str(tmp_path / "idf")
    assert kwargs["env"]["MATTER_NATIVE_PATH"] == str(build._MATTER_NATIVE)
    # The IDF environment the entrypoint sourced has to survive into the build.
    assert kwargs["env"]["PATH"] == os.environ["PATH"]


def test_merge_image_appends_the_factory_partition(recorder, tmp_path):
    factory = tmp_path / "factory-partition.bin"
    merged = build._merge_image(tmp_path, factory, _IDENTITY)

    command, kwargs = recorder[0]
    assert command[0] == "esptool.py"
    assert command[-3:] == ["@flash_args", "0x3d0000", str(factory)]
    assert command[command.index("-o") + 1] == str(merged)
    # @flash_args names the bootloader and app relative to the IDF build directory.
    assert kwargs["cwd"] == tmp_path / "idf"


@pytest.fixture
def stub_tool(tmp_path):
    """A PATH directory holding a `faketool` that touches its argument."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    tool = bindir / "faketool"
    tool.write_text(
        '#!/bin/sh\nif [ "$1" = "--fail" ]; then exit 3; fi\n: > "$1"\n',
        encoding="utf-8",
    )
    tool.chmod(0o755)
    return bindir


@pytest.fixture
def recorder(monkeypatch):
    """Capture the argv of every toolchain command instead of running it."""
    calls: list[tuple[list[str], dict]] = []

    def record(command, cwd=None, env=None):
        calls.append(([*command], {"cwd": cwd, "env": env}))

    monkeypatch.setattr(build, "_run", record)
    return calls
