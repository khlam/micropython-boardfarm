"""Pairing derivation: key rules, random keys, forbidden passcodes, and manual codes."""

import random
import re
from collections.abc import Callable, Iterable
from contextlib import AbstractContextManager
from contextlib import nullcontext as returns
from types import SimpleNamespace

import pytest

from matter_tools import _pairing

_ANY_VALID_KEY = "any-valid-key-0123456789"

_NON_STRING_ERROR = "^passcode must be a string$"
_SHORT_KEY_ERROR = "^passcode must be at least 24 characters$"
_UNIFORM_KEY_ERROR = "^passcode must span at least 12 distinct characters$"
_FORBIDDEN_PASSCODE_ERROR = "^passcode derives a forbidden Matter setup passcode"

# Matter Core Specification, Onboarding Payload, Passcode: these setup passcodes
# are invalid. connectedhomeip's PayloadContents::IsValidSetupPIN rejects the same
# values.
_FORBIDDEN_SETUP_PASSCODES = (
    00000000,
    11111111,
    22222222,
    33333333,
    44444444,
    55555555,
    66666666,
    77777777,
    88888888,
    99999999,
    12345678,
    87654321,
)

# Verhoeff's position permutation in one-line notation: digit n maps to entry n.
_VERHOEFF_PERMUTATION = (1, 5, 7, 6, 2, 8, 3, 0, 9, 4)

# Printable ASCII, Latin-1, Greek, CJK, and emoji: one to four UTF-8 bytes per
# character. Lone surrogates are left out because UTF-8 cannot encode them.
_ALPHABET = [
    chr(code_point)
    for block in (
        range(0x20, 0x7F),
        range(0xA1, 0x100),
        range(0x391, 0x3CA),
        range(0x4E00, 0x4F00),
        range(0x1F600, 0x1F650),
    )
    for code_point in block
]

# Each fuzz case rebuilds its key from its own seed, so no case's input depends on
# which other cases run.
_RNG = random.Random(20260927)  # noqa: S311 - seeded fuzz input, not a secret
_FUZZ_SEEDS = [_RNG.getrandbits(32) for _ in range(100)]


@pytest.mark.parametrize(
    ("key", "urandom_draws", "sha256_digest", "outcome"),
    [
        # Regression vectors pinning the documented derivation across releases and boards.
        pytest.param(
            "correct-horse-battery-staple",
            (),
            None,
            returns(
                {
                    "key": "correct-horse-battery-staple",
                    "passcode": 78288405,
                    "discriminator": 3008,
                    "manual_pairing_code": "25480547786",
                }
            ),
            id="vector-words",
        ),
        pytest.param(
            "9f3a1c7e2b8d4f60a5e9c1b7d3f8a204",
            (),
            None,
            returns(
                {
                    "key": "9f3a1c7e2b8d4f60a5e9c1b7d3f8a204",
                    "passcode": 69149971,
                    "discriminator": 769,
                    "manual_pairing_code": "05864342209",
                }
            ),
            id="vector-hex",
        ),
        pytest.param(
            "Tr0ub4dor&3-horses-stapled!!",
            (),
            None,
            returns(
                {
                    "key": "Tr0ub4dor&3-horses-stapled!!",
                    "passcode": 80825200,
                    "discriminator": 2677,
                    "manual_pairing_code": "23569649338",
                }
            ),
            id="vector-symbols",
        ),
        # The Greek alphabet has exactly 24 letters of two UTF-8 bytes each, so these
        # rows pin that length counts characters and that the key hashes as UTF-8.
        pytest.param(
            "αβγδεζηθικλμνξοπρστυφχψω",
            (),
            None,
            returns(
                {
                    "key": "αβγδεζηθικλμνξοπρστυφχψω",
                    "passcode": 10846537,
                    "discriminator": 3144,
                    "manual_pairing_code": "30032906625",
                }
            ),
            id="accepts-24-characters",
        ),
        pytest.param(
            "αβγδεζηθικλμνξοπρστυφχψ",
            (),
            None,
            pytest.raises(ValueError, match=_SHORT_KEY_ERROR),
            id="rejects-23-characters",
        ),
        pytest.param(
            "abcdefghijkl" * 3,
            (),
            None,
            returns({"key": "abcdefghijkl" * 3}),
            id="accepts-12-distinct",
        ),
        pytest.param(
            "abcdefghijk" * 3,
            (),
            None,
            pytest.raises(ValueError, match=_UNIFORM_KEY_ERROR),
            id="rejects-11-distinct",
        ),
        pytest.param(
            b"correct-horse-battery-staple",
            (),
            None,
            pytest.raises(ValueError, match=_NON_STRING_ERROR),
            id="rejects-bytes",
        ),
        pytest.param(
            42,
            (),
            None,
            pytest.raises(ValueError, match=_NON_STRING_ERROR),
            id="rejects-int",
        ),
        pytest.param(
            1.0,
            (),
            None,
            pytest.raises(ValueError, match=_NON_STRING_ERROR),
            id="rejects-float",
        ),
        pytest.param(
            True,
            (),
            None,
            pytest.raises(ValueError, match=_NON_STRING_ERROR),
            id="rejects-bool",
        ),
        pytest.param(
            None,
            (bytes(range(32)),),
            None,
            returns({"key": bytes(range(32)).hex()}),
            id="draws-random-key",
        ),
        # This draw spans 11 distinct hex digits, one short of the minimum.
        pytest.param(
            None,
            (bytes.fromhex("0123456789" * 6 + "aaaa"), bytes(range(32))),
            None,
            returns({"key": bytes(range(32)).hex()}),
            id="redraws-11-distinct-hex-digits",
        ),
        # This draw's key derives the forbidden setup passcode 55555555.
        pytest.param(
            None,
            (
                bytes.fromhex("61f9eb116f1c6a90544bac44a4bfee708a08f43400aeb5b354eac841e07624e0"),
                bytes(range(32)),
            ),
            None,
            returns({"key": bytes(range(32)).hex()}),
            id="redraws-a-key-deriving-a-forbidden-passcode",
        ),
        # Forced digests: bytes 0-3 map to the setup passcode as `word % 99999999 + 1`
        # and bytes 4-5 carry the discriminator in their low 12 bits.
        #
        # CHIP SDK test device: connectedhomeip's CHIPDeviceConfig.h sets
        # CHIP_DEVICE_CONFIG_USE_TEST_SETUP_PIN_CODE to 20202021 and
        # CHIP_DEVICE_CONFIG_USE_TEST_SETUP_DISCRIMINATOR to 0xF00, and that device's
        # published manual pairing code is 34970112332.
        pytest.param(
            _ANY_VALID_KEY,
            (),
            (20202021 - 1).to_bytes(4, "big") + (0xF00).to_bytes(2, "big"),
            returns(
                {
                    "key": _ANY_VALID_KEY,
                    "passcode": 20202021,
                    "discriminator": 3840,
                    "manual_pairing_code": "34970112332",
                }
            ),
            id="chip-test-device",
        ),
        *(
            pytest.param(
                _ANY_VALID_KEY,
                (),
                (forbidden - 1).to_bytes(4, "big"),
                pytest.raises(ValueError, match=_FORBIDDEN_PASSCODE_ERROR),
                id=f"rejects-forbidden-{forbidden:08d}",
            )
            for forbidden in _FORBIDDEN_SETUP_PASSCODES
            # No digest maps to 00000000: the derived range starts at 1.
            if forbidden != 0
        ),
    ],
)
def test_generate_pairing(
    monkeypatch: pytest.MonkeyPatch,
    key: object,
    urandom_draws: tuple[bytes, ...],
    sha256_digest: bytes | None,
    outcome: AbstractContextManager,
):
    """Each row pins the result fields its input determines; the returned key reproduces it all.

    Args:
        monkeypatch: Scripts the random draws and forces the digest.
        key: The key passed to generate_pairing(); None draws a random one.
        urandom_draws: What each ``os.urandom`` call returns, in order.
        sha256_digest: The digest's leading bytes to force, or None to hash for real.
        outcome: Yields the result fields expected, or expects the raise.
    """
    _script_urandom(monkeypatch, urandom_draws)
    _force_sha256_digest(monkeypatch, sha256_digest)
    with outcome as expected:
        result = _pairing.generate_pairing(key)
        assert {field: result[field] for field in expected} == expected
        assert _pairing.generate_pairing(result["key"]) == result


@pytest.mark.fuzz
@pytest.mark.parametrize("seed", _FUZZ_SEEDS)
def test_fuzz_valid_keys_yield_spec_valid_codes(seed: int):
    """Any valid key yields a reproducible, allowed passcode and a decodable manual code.

    Args:
        seed: Seeds the random valid key.
    """
    key = _random_key(seed, lengths=(24, 64), distinct_counts=(12, 40))
    result = _pairing.generate_pairing(key)
    code = result["manual_pairing_code"]

    assert result["key"] == key
    assert _pairing.generate_pairing(key) == result
    assert 1 <= result["passcode"] <= 99999999
    assert result["passcode"] not in _FORBIDDEN_SETUP_PASSCODES
    assert 0 <= result["discriminator"] <= 0xFFF
    assert re.fullmatch("[0-9]{11}", code)
    assert _verhoeff_is_valid(code)
    assert _decode_manual_code(code) == (0, result["discriminator"] >> 8, result["passcode"])


@pytest.mark.fuzz
@pytest.mark.parametrize(
    ("lengths", "distinct_counts", "convert", "error"),
    [
        pytest.param((12, 23), (12, 23), str, _SHORT_KEY_ERROR, id="too-short"),
        pytest.param((24, 64), (1, 11), str, _UNIFORM_KEY_ERROR, id="too-few-distinct"),
        pytest.param((24, 64), (12, 40), str.encode, _NON_STRING_ERROR, id="utf8-bytes"),
    ],
)
@pytest.mark.parametrize("seed", _FUZZ_SEEDS)
def test_fuzz_invalid_keys_raise_only_documented_errors(
    seed: int,
    lengths: tuple[int, int],
    distinct_counts: tuple[int, int],
    convert: Callable[[str], str | bytes],
    error: str,
):
    """A key breaking one rule raises exactly ValueError naming that rule, whatever its text.

    Args:
        seed: Seeds the random key.
        lengths: The inclusive range the key's length is drawn from.
        distinct_counts: The inclusive range its distinct character count is drawn from.
        convert: Turns the drawn key into the value passed to generate_pairing().
        error: Pattern the ValueError's message must match.
    """
    key = convert(_random_key(seed, lengths, distinct_counts))
    with pytest.raises(ValueError, match=error) as raised:
        _pairing.generate_pairing(key)
    assert raised.type is ValueError


def _script_urandom(monkeypatch: pytest.MonkeyPatch, draws: Iterable[bytes]):
    """Make the pairing module's ``os.urandom`` return ``draws`` in order.

    Args:
        monkeypatch: Replaces the pairing module's ``os``.
        draws: What each call returns.
    """
    remaining = iter(draws)
    monkeypatch.setattr(_pairing, "os", SimpleNamespace(urandom=lambda _size: next(remaining)))


def _force_sha256_digest(monkeypatch: pytest.MonkeyPatch, digest: bytes | None) -> None:
    """Make the pairing module's SHA-256 return ``digest`` zero-padded; ``None`` keeps it real.

    Args:
        monkeypatch: Replaces the pairing module's ``hashlib``.
        digest: The digest's leading bytes, or None to hash for real.
    """
    if digest is None:
        return
    forced = SimpleNamespace(digest=lambda: digest.ljust(32, b"\x00"))
    monkeypatch.setattr(_pairing, "hashlib", SimpleNamespace(sha256=lambda _data: forced))


def _verhoeff_is_valid(code: str) -> bool:
    """Check the trailing Verhoeff check digit of ``code`` over all of its digits.

    Args:
        code: Decimal digits ending in their check digit.

    Returns:
        Whether the check digit matches.
    """
    checksum = 0
    for position, digit in enumerate(reversed(code)):
        checksum = _dihedral_product(checksum, _verhoeff_permute(position % 8, int(digit)))
    return checksum == 0


def _dihedral_product(left: int, right: int) -> int:
    """Multiply two elements of the dihedral group D5: 0-4 are rotations, 5-9 reflections.

    Args:
        left: The left element.
        right: The right element.

    Returns:
        Their product.
    """
    if left < 5 and right < 5:
        return (left + right) % 5
    if left < 5:
        return 5 + (left + right) % 5
    if right < 5:
        return 5 + (left - right) % 5
    return (left - right) % 5


def _verhoeff_permute(times: int, digit: int) -> int:
    """Apply Verhoeff's position permutation to ``digit`` ``times`` times.

    Args:
        times: How often to apply the permutation.
        digit: The digit permuted.

    Returns:
        The permuted digit.
    """
    for _ in range(times):
        digit = _VERHOEFF_PERMUTATION[digit]
    return digit


def _decode_manual_code(code: str) -> tuple[int, int, int]:
    """Decode an 11-digit manual pairing code to (digit-1 flags, short discriminator, passcode).

    Matter Core Specification layout: digit 1 holds the VID/PID-present flag in bit 2
    above the short discriminator's high two bits. Digits 2-6 hold its low two bits above
    the passcode's low 14 bits, digits 7-10 hold the passcode's remaining high bits, and
    digit 11 is the check digit.

    Args:
        code: The manual pairing code.

    Returns:
        The digit-1 flags, the short discriminator, and the passcode.
    """
    first, middle, high = int(code[0]), int(code[1:6]), int(code[6:10])
    short_discriminator = ((first & 0x3) << 2) | (middle >> 14)
    passcode = (high << 14) | (middle & 0x3FFF)
    return first >> 2, short_discriminator, passcode


def _random_key(seed: int, lengths: tuple[int, int], distinct_counts: tuple[int, int]) -> str:
    """Build a key from ``seed`` with length and distinct count in the inclusive ranges given.

    Args:
        seed: Seeds the draw, so the same seed builds the same key.
        lengths: The inclusive range the key's length is drawn from.
        distinct_counts: The inclusive range its distinct character count is drawn from.

    Returns:
        The key.
    """
    rng = random.Random(seed)  # noqa: S311 - seeded fuzz input, not a secret
    length = rng.randint(*lengths)
    distinct = rng.randint(distinct_counts[0], min(distinct_counts[1], length))
    characters = rng.sample(_ALPHABET, distinct)
    characters += rng.choices(characters, k=length - distinct)
    return "".join(rng.sample(characters, length))
