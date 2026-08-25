"""Host tests for build.py's image-shape checks and its /outputs publishing step.

A merged image is a few megabytes of flash layout, so the fixtures here build a
miniature one: the identity's flash size and factory offset are shrunk to a few
hundred bytes, which exercises exactly the same slice arithmetic.
"""

import fcntl
import multiprocessing
import os
import pathlib

import build
import pytest

_FLASH_SIZE = 512
_FACTORY_OFFSET = 128
_FACTORY_SIZE = 64
_MANUAL = "34970112332"
_PAYLOAD = "MT:-24J0AFN00KA0648G00"


def test_accepts_an_image_carrying_its_factory_partition(image, identity):
    build._validate_merged_image(image.merged, image.factory, image.qr, identity)


def test_rejects_an_empty_image(image, identity):
    image.merged.write_bytes(b"")
    with pytest.raises(ValueError, match="merged image must be exactly"):
        build._validate_merged_image(image.merged, image.factory, image.qr, identity)


def test_rejects_an_image_larger_than_the_flash(image, identity):
    image.merged.write_bytes(b"\x00" * (_FLASH_SIZE + 1))
    with pytest.raises(ValueError, match="merged image must be exactly"):
        build._validate_merged_image(image.merged, image.factory, image.qr, identity)


def test_rejects_an_image_that_was_not_padded_to_the_flash(image, identity):
    image.merged.write_bytes(image.merged.read_bytes()[:-1])
    with pytest.raises(ValueError, match="merged image must be exactly"):
        build._validate_merged_image(image.merged, image.factory, image.qr, identity)


def test_rejects_a_factory_partition_of_the_wrong_size(image, identity):
    image.factory.write_bytes(b"\xaa" * (_FACTORY_SIZE - 1))
    with pytest.raises(ValueError, match="factory partition must be exactly"):
        build._validate_merged_image(image.merged, image.factory, image.qr, identity)


def test_rejects_an_image_missing_the_factory_partition(image, identity):
    # The image is intact and correctly sized, but was merged with other credentials.
    merged = bytearray(image.merged.read_bytes())
    merged[_FACTORY_OFFSET] ^= 0xFF
    image.merged.write_bytes(bytes(merged))
    with pytest.raises(ValueError, match="does not carry the generated factory partition"):
        build._validate_merged_image(image.merged, image.factory, image.qr, identity)


def test_rejects_a_missing_qr_image(image, identity):
    image.qr.unlink()
    with pytest.raises(ValueError, match="QR image is missing or empty"):
        build._validate_merged_image(image.merged, image.factory, image.qr, identity)


def test_rejects_an_empty_qr_image(image, identity):
    image.qr.write_bytes(b"")
    with pytest.raises(ValueError, match="QR image is missing or empty"):
        build._validate_merged_image(image.merged, image.factory, image.qr, identity)


def test_publish_installs_a_complete_generation_readable(image, outputs):
    build._publish(image.merged, image.qr, _MANUAL, _PAYLOAD)

    merged = outputs / build._MERGED_NAME
    setup = outputs / build._SETUP_NAME
    assert {path.name for path in outputs.iterdir()} == build._OUTPUT_NAMES
    assert merged.read_bytes() == image.merged.read_bytes()
    assert (outputs / build._QR_NAME).read_bytes() == image.qr.read_bytes()
    assert setup.read_text(encoding="utf-8") == (
        f"manual_pairing_code={_MANUAL}\nsetup_payload={_PAYLOAD}\n"
    )
    for path in outputs.iterdir():
        assert path.stat().st_mode & 0o777 == build._ARTIFACT_MODE


def test_publish_staging_failure_preserves_the_current_generation(image, outputs, monkeypatch):
    current = _seed_generation(outputs)
    install = build._install

    def fail_while_staging_qr(source, destination):
        if source == image.qr:
            raise OSError("simulated staging failure")
        install(source, destination)

    monkeypatch.setattr(build, "_install", fail_while_staging_qr)
    with pytest.raises(OSError, match="simulated staging failure"):
        build._publish(image.merged, image.qr, _MANUAL, _PAYLOAD)

    assert {path.name: path.read_bytes() for path in outputs.iterdir()} == current


def test_publish_cutover_failure_never_leaves_stale_pairing_material(image, outputs, monkeypatch):
    _seed_generation(outputs)
    commit = build._commit_staged
    replacements = 0

    def fail_while_replacing_qr(source, destination):
        nonlocal replacements
        replacements += 1
        if replacements == 2:
            raise OSError("simulated cutover failure")
        commit(source, destination)

    monkeypatch.setattr(build, "_commit_staged", fail_while_replacing_qr)
    with pytest.raises(OSError, match="simulated cutover failure"):
        build._publish(image.merged, image.qr, _MANUAL, _PAYLOAD)

    assert (outputs / build._MERGED_NAME).read_bytes() == image.merged.read_bytes()
    assert not (outputs / build._QR_NAME).exists()
    assert not (outputs / build._SETUP_NAME).exists()
    assert {path.name for path in outputs.iterdir()} == {build._MERGED_NAME}


def test_publish_recovers_reserved_staging_files(image, outputs):
    for name in build._STAGING_NAMES:
        (outputs / name).write_bytes(b"interrupted build")

    build._publish(image.merged, image.qr, _MANUAL, _PAYLOAD)

    assert {path.name for path in outputs.iterdir()} == build._OUTPUT_NAMES


def test_publish_serializes_live_generations(outputs, tmp_path):
    first_sources = _publish_sources(tmp_path / "first", "first")
    second_sources = _publish_sources(tmp_path / "second", "second")
    context = multiprocessing.get_context("fork")
    first_entered = context.Event()
    release_first = context.Event()
    second_started = context.Event()
    second_entered = context.Event()
    first = context.Process(
        target=_publish_in_process,
        args=(outputs, *first_sources, first_entered, release_first, None),
    )
    second = context.Process(
        target=_publish_in_process,
        args=(outputs, *second_sources, second_entered, None, second_started),
    )

    first.start()
    second_was_started = False
    try:
        assert first_entered.wait(timeout=5)
        descriptor = os.open(outputs, os.O_RDONLY | os.O_DIRECTORY)
        try:
            with pytest.raises(BlockingIOError):
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        finally:
            os.close(descriptor)

        second.start()
        second_was_started = True
        assert second_started.wait(timeout=5)
        assert not second_entered.wait(timeout=0.5)
    finally:
        release_first.set()
        first.join(timeout=10)
        if second_was_started:
            second.join(timeout=10)
        for process in (first, second):
            if process.pid is not None and process.is_alive():
                process.terminate()
                process.join(timeout=5)

    assert first.exitcode == 0
    assert second.exitcode == 0
    assert second_entered.is_set()
    assert (outputs / build._MERGED_NAME).read_bytes() == b"second merged"
    assert (outputs / build._QR_NAME).read_bytes() == b"second QR"
    assert (outputs / build._SETUP_NAME).read_text(encoding="utf-8") == (
        "manual_pairing_code=second manual\nsetup_payload=second payload\n"
    )


def test_publish_refuses_to_write_beside_a_stray_file(image, outputs):
    current = _seed_generation(outputs)
    (outputs / "leftover.bin").write_bytes(b"")
    with pytest.raises(ValueError, match=r"unexpected output artifacts: leftover\.bin"):
        build._publish(image.merged, image.qr, _MANUAL, _PAYLOAD)
    assert {
        path.name: path.read_bytes() for path in outputs.iterdir() if path.name != "leftover.bin"
    } == current


def test_write_setup_names_both_codes(outputs):
    setup = outputs / build._SETUP_NAME
    build._write_setup(setup, _MANUAL, _PAYLOAD)

    assert setup.read_text(encoding="utf-8") == (
        f"manual_pairing_code={_MANUAL}\nsetup_payload={_PAYLOAD}\n"
    )
    assert setup.stat().st_mode & 0o777 == build._ARTIFACT_MODE


def _seed_generation(outputs):
    """Write and return the public bytes of one complete current generation."""
    contents = {
        build._MERGED_NAME: b"current merged image",
        build._QR_NAME: b"current QR image",
        build._SETUP_NAME: b"manual_pairing_code=current\n",
    }
    for name, content in contents.items():
        (outputs / name).write_bytes(content)
    return contents


def _publish_sources(root, label):
    """Write one uniquely identifiable publication source generation."""
    root.mkdir()
    merged = root / "merged.bin"
    qr = root / "qr.png"
    merged.write_bytes(f"{label} merged".encode())
    qr.write_bytes(f"{label} QR".encode())
    return merged, qr, f"{label} manual", f"{label} payload"


def _publish_in_process(
    outputs,
    merged,
    qr,
    manual,
    payload,
    entered,
    release,
    started,
):
    """Publish in a child process, optionally pausing after its first staged file."""
    build._OUTPUT_DIR = outputs
    install = build._install
    first_install = True

    def controlled_install(source, destination):
        nonlocal first_install
        install(source, destination)
        if not first_install:
            return
        first_install = False
        entered.set()
        if release is not None and not release.wait(timeout=10):
            raise TimeoutError("publication test was not released")

    build._install = controlled_install
    if started is not None:
        started.set()
    build._publish(merged, qr, manual, payload)


class _Image:
    """The three files a finished build hands to the artifact checks."""

    def __init__(self, root: pathlib.Path) -> None:
        """Write a merged image carrying its factory partition at the right offset."""
        factory_bytes = bytes(range(256))[:_FACTORY_SIZE]
        merged = bytearray(b"\x00" * _FLASH_SIZE)
        merged[_FACTORY_OFFSET : _FACTORY_OFFSET + _FACTORY_SIZE] = factory_bytes

        self.merged = root / build._MERGED_NAME
        self.factory = root / "factory-partition.bin"
        self.qr = root / "device-qrcode.png"
        self.merged.write_bytes(bytes(merged))
        self.factory.write_bytes(factory_bytes)
        self.qr.write_bytes(b"\x89PNG\r\n\x1a\n")


@pytest.fixture
def identity():
    """A build identity shrunk to the miniature image the fixtures build."""
    return build._BuildIdentity(
        vendor_id=0xFFF1,
        product_id=0x8001,
        factory_offset=_FACTORY_OFFSET,
        factory_size=_FACTORY_SIZE,
        flash_size=_FLASH_SIZE,
        discovery_mode=2,
    )


@pytest.fixture
def image(tmp_path):
    """A consistent merged image, factory partition and QR file under tmp_path."""
    source = tmp_path / "build"
    source.mkdir()
    return _Image(source)


@pytest.fixture
def outputs(tmp_path, monkeypatch):
    """Redirect the module's /outputs bind mount at an empty directory."""
    directory = tmp_path / "outputs"
    directory.mkdir()
    monkeypatch.setattr(build, "_OUTPUT_DIR", directory)
    return directory
