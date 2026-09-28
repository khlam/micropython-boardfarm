"""Host tests for build.py's image-shape checks and its /outputs publishing step.

A merged image is a few megabytes of flash layout, so the fixtures here build a
miniature one: the identity's flash size and factory offset are shrunk to a few
hundred bytes, which exercises exactly the same slice arithmetic.
"""

import fcntl
import multiprocessing
import os
import pathlib
from contextlib import AbstractContextManager
from contextlib import nullcontext as returns
from multiprocessing.synchronize import Event

import build
import pytest

_FLASH_SIZE = 512
_FACTORY_OFFSET = 128
_FACTORY_SIZE = 64
_FACTORY = bytes(range(_FACTORY_SIZE))
_ERASED = b"\xff" * _FACTORY_SIZE
_MANUAL = "34970112332"
_PAYLOAD = "MT:-24J0AFN00KA0648G00"
_SETUP = {"manual_pairing_code": _MANUAL, "setup_payload": _PAYLOAD}

_WRONG_IMAGE_SIZE = pytest.raises(ValueError, match="merged image must be exactly")
_OTHER_PARTITION = pytest.raises(ValueError, match="does not carry the expected factory partition")
_MISSING_QR = pytest.raises(ValueError, match="QR image is missing or empty")


def _image(factory: bytes, size: int = _FLASH_SIZE) -> bytes:
    """Return a miniature flash image of ``size`` bytes carrying ``factory`` at its offset.

    Args:
        factory: The factory partition's contents.
        size: The image's length in bytes.

    Returns:
        The image.
    """
    merged = bytearray(size)
    merged[_FACTORY_OFFSET : _FACTORY_OFFSET + _FACTORY_SIZE] = factory
    return bytes(merged)


@pytest.mark.parametrize(
    ("merged", "factory", "outcome"),
    [
        pytest.param(_image(_FACTORY), _FACTORY, returns(), id="provisioned"),
        pytest.param(_image(_ERASED), _ERASED, returns(), id="compiled"),
        pytest.param(b"", _FACTORY, _WRONG_IMAGE_SIZE, id="empty"),
        pytest.param(_image(_FACTORY, _FLASH_SIZE + 1), _FACTORY, _WRONG_IMAGE_SIZE, id="larger"),
        pytest.param(_image(_FACTORY, _FLASH_SIZE - 1), _FACTORY, _WRONG_IMAGE_SIZE, id="smaller"),
        pytest.param(
            _image(_FACTORY),
            _FACTORY[:-1],
            pytest.raises(ValueError, match="factory partition must be exactly"),
            id="short-factory-partition",
        ),
        pytest.param(
            _image(_FACTORY), bytes(reversed(_FACTORY)), _OTHER_PARTITION, id="other-credentials"
        ),
        pytest.param(_image(_FACTORY), _ERASED, _OTHER_PARTITION, id="compiled-with-credentials"),
    ],
)
def test_validate_merged_image(
    tmp_path: pathlib.Path,
    identity: build._BuildIdentity,
    merged: bytes,
    factory: bytes,
    outcome: AbstractContextManager,
):
    """An image passes only at the flash size and carrying exactly the expected partition.

    Args:
        tmp_path: Holds the merged image.
        identity: The miniature board identity.
        merged: The merged image's bytes.
        factory: The factory partition it should carry.
        outcome: Passes, or expects the ValueError naming the mismatch.
    """
    path = tmp_path / build._MERGED_NAME
    path.write_bytes(merged)
    with outcome:
        build._validate_merged_image(path, factory, identity)


@pytest.mark.parametrize(
    ("content", "outcome"),
    [
        pytest.param(b"\x89PNG\r\n\x1a\n", returns(), id="rendered"),
        pytest.param(None, _MISSING_QR, id="missing"),
        pytest.param(b"", _MISSING_QR, id="empty"),
    ],
)
def test_validate_qr(
    tmp_path: pathlib.Path, content: bytes | None, outcome: AbstractContextManager
):
    """A QR image passes only when the file exists and isn't empty.

    Args:
        tmp_path: Holds the QR image.
        content: The QR file's bytes, or None for no file.
        outcome: Passes, or expects the ValueError for a missing image.
    """
    qr = tmp_path / "qrcode.png"
    if content is not None:
        qr.write_bytes(content)
    with outcome:
        build._validate_qr(qr)


def test_publish_installs_a_complete_generation_readable(image: "_Image", outputs: pathlib.Path):
    """Publishing installs the image, QR, and setup codes with the artifact file mode.

    Args:
        image: The files to publish.
        outputs: The empty outputs directory.
    """
    build._publish(image.merged, image.qr, _SETUP)

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


def test_publish_staging_failure_preserves_the_current_generation(
    image: "_Image", outputs: pathlib.Path, monkeypatch: pytest.MonkeyPatch
):
    """A failure while staging the new files leaves the published generation untouched.

    Args:
        image: The files to publish.
        outputs: The outputs directory, seeded with a current generation.
        monkeypatch: Makes staging the QR image fail.
    """
    current = _seed_generation(outputs)
    install = build._install

    def fail_while_staging_qr(source, destination):
        if source == image.qr:
            raise OSError("simulated staging failure")
        install(source, destination)

    monkeypatch.setattr(build, "_install", fail_while_staging_qr)
    with pytest.raises(OSError, match="simulated staging failure"):
        build._publish(image.merged, image.qr, _SETUP)

    assert {path.name: path.read_bytes() for path in outputs.iterdir()} == current


def test_publish_cutover_failure_never_leaves_stale_pairing_material(
    image: "_Image", outputs: pathlib.Path, monkeypatch: pytest.MonkeyPatch
):
    """A failure mid-cutover removes the old pairing codes rather than leaving them stale.

    Args:
        image: The files to publish.
        outputs: The outputs directory, seeded with a current generation.
        monkeypatch: Makes replacing the QR image fail.
    """
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
        build._publish(image.merged, image.qr, _SETUP)

    assert (outputs / build._MERGED_NAME).read_bytes() == image.merged.read_bytes()
    assert not (outputs / build._QR_NAME).exists()
    assert not (outputs / build._SETUP_NAME).exists()
    assert {path.name for path in outputs.iterdir()} == {build._MERGED_NAME}


def test_publish_recovers_reserved_staging_files(image: "_Image", outputs: pathlib.Path):
    """Staging files left by an interrupted build are cleared by the next publish.

    Args:
        image: The files to publish.
        outputs: The outputs directory, holding leftover staging files.
    """
    for name in build._STAGING_NAMES:
        (outputs / name).write_bytes(b"interrupted build")

    build._publish(image.merged, image.qr, _SETUP)

    assert {path.name for path in outputs.iterdir()} == build._OUTPUT_NAMES


def test_publish_serializes_live_generations(outputs: pathlib.Path, tmp_path: pathlib.Path):
    """A second publish waits on the directory lock until the first finishes.

    Args:
        outputs: The shared outputs directory.
        tmp_path: Holds each publisher's source files.
    """
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


def test_publish_refuses_to_write_beside_a_stray_file(image: "_Image", outputs: pathlib.Path):
    """An unexpected file in the outputs directory stops publishing before anything changes.

    Args:
        image: The files to publish.
        outputs: The outputs directory, seeded with a current generation.
    """
    current = _seed_generation(outputs)
    (outputs / "leftover.bin").write_bytes(b"")
    with pytest.raises(ValueError, match=r"unexpected output artifacts: leftover\.bin"):
        build._publish(image.merged, image.qr, _SETUP)
    assert {
        path.name: path.read_bytes() for path in outputs.iterdir() if path.name != "leftover.bin"
    } == current


@pytest.mark.parametrize(
    ("names", "handed_over"),
    [
        pytest.param({build._MERGED_NAME}, True, id="compiled-firmware"),
        pytest.param(build._OUTPUT_NAMES, True, id="flashed-firmware-with-pairing"),
        pytest.param({build._MERGED_NAME, build._QR_NAME}, False, id="partial-pairing"),
    ],
)
def test_hand_outputs_to_owner(
    outputs: pathlib.Path, monkeypatch: pytest.MonkeyPatch, names: set[str], handed_over: bool
):
    """Only a complete generation is handed over, directory included, to the source owner.

    Args:
        outputs: The outputs directory.
        monkeypatch: Records chown calls instead of making them.
        names: The artifacts present.
        handed_over: Whether they form a complete generation.
    """
    for name in names:
        (outputs / name).write_bytes(b"artifact")
    owner = outputs.stat()
    chowned = []
    monkeypatch.setattr(build, "_OWNER_REFERENCE", outputs)
    monkeypatch.setattr(build.os, "chown", lambda path, uid, gid: chowned.append((path, uid, gid)))

    outcome = returns() if handed_over else pytest.raises(ValueError, match="expected firmware")
    with outcome:
        build._hand_outputs_to_owner()

    handed = [outputs, *sorted(outputs / name for name in names)] if handed_over else []
    assert chowned == [(path, owner.st_uid, owner.st_gid) for path in handed]


def _seed_generation(outputs: pathlib.Path) -> dict[str, bytes]:
    """Write and return the public bytes of one complete current generation.

    Args:
        outputs: The outputs directory.

    Returns:
        Each artifact's contents, keyed by file name.
    """
    contents = {
        build._MERGED_NAME: b"current merged image",
        build._QR_NAME: b"current QR image",
        build._SETUP_NAME: b"manual_pairing_code=current\n",
    }
    for name, content in contents.items():
        (outputs / name).write_bytes(content)
    return contents


def _publish_sources(root: pathlib.Path, label: str) -> tuple[pathlib.Path, pathlib.Path, str, str]:
    """Write one uniquely identifiable publication source generation.

    Args:
        root: The directory created for the sources.
        label: Marks every source so its publication can be recognised.

    Returns:
        The merged image path, QR path, manual code, and setup payload.
    """
    root.mkdir()
    merged = root / "merged.bin"
    qr = root / "qr.png"
    merged.write_bytes(f"{label} merged".encode())
    qr.write_bytes(f"{label} QR".encode())
    return merged, qr, f"{label} manual", f"{label} payload"


def _publish_in_process(
    outputs: pathlib.Path,
    merged: pathlib.Path,
    qr: pathlib.Path,
    manual: str,
    payload: str,
    entered: Event,
    release: Event | None,
    started: Event | None,
):
    """Publish in a child process, optionally pausing after its first staged file.

    Args:
        outputs: The shared outputs directory.
        merged: The merged image to publish.
        qr: The QR image to publish.
        manual: The manual pairing code to publish.
        payload: The QR setup payload to publish.
        entered: Set once the first file is staged.
        release: Waited on after the first file is staged, or None not to pause.
        started: Set just before publishing begins, or None.
    """
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
    build._publish(merged, qr, {"manual_pairing_code": manual, "setup_payload": payload})


class _Image:
    """The two files a finished flash hands to publication."""

    def __init__(self, root: pathlib.Path) -> None:
        """Write a provisioned merged image and its QR image.

        Args:
            root: The directory the two files are written to.
        """
        self.merged = root / build._MERGED_NAME
        self.qr = root / "device-qrcode.png"
        self.merged.write_bytes(_image(_FACTORY))
        self.qr.write_bytes(b"\x89PNG\r\n\x1a\n")


@pytest.fixture
def identity() -> build._BuildIdentity:
    """A build identity shrunk to the miniature image the fixtures build.

    Returns:
        The identity.
    """
    return build._BuildIdentity(
        vendor_id=0xFFF1,
        product_id=0x8001,
        factory_offset=_FACTORY_OFFSET,
        factory_size=_FACTORY_SIZE,
        flash_size=_FLASH_SIZE,
        discovery_mode=2,
    )


@pytest.fixture
def image(tmp_path: pathlib.Path) -> _Image:
    """A consistent merged image and QR file under tmp_path.

    Args:
        tmp_path: Holds the build directory.

    Returns:
        The two files.
    """
    source = tmp_path / "build"
    source.mkdir()
    return _Image(source)


@pytest.fixture
def outputs(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> pathlib.Path:
    """Redirect the module's /outputs bind mount at an empty directory.

    Args:
        tmp_path: Holds the directory.
        monkeypatch: Points build at it.

    Returns:
        The empty directory.
    """
    directory = tmp_path / "outputs"
    directory.mkdir()
    monkeypatch.setattr(build, "_OUTPUT_DIR", directory)
    return directory
