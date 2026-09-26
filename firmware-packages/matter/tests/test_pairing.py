"""Key complexity, random defaults, and stable Matter pairing derivation."""

from types import SimpleNamespace

import pytest

import matter
from matter import pairing

_KEY = "correct-horse-battery-staple"


@pytest.mark.parametrize(
    "key, passcode, discriminator",
    [
        ("correct-horse-battery-staple", 53230365, 3681),
        ("9f3a1c7e2b8d4f60a5e9c1b7d3f8a204", 41461148, 2126),
        ("Tr0ub4dor&3-horses-stapled!!", 38916892, 2957),
    ],
)
def test_fixed_pairing_vectors(key, passcode, discriminator):
    result = matter.generate_pairing(key)
    assert result["key"] == key
    assert result["passcode"] == passcode
    assert result["discriminator"] == discriminator
    assert len(result["manual_pairing_code"]) == 11


@pytest.mark.parametrize(
    "key, message",
    [
        (b"correct-horse-battery-staple", "must be a string"),
        (42, "must be a string"),
        (1.0, "must be a string"),
        (True, "must be a string"),
        ("", "at least 24 characters"),
        ("short-but-varied-key", "at least 24 characters"),
        ("abababababababababababababab", "at least 12 distinct characters"),
    ],
)
def test_rejects_a_guessable_key(key, message):
    with pytest.raises(ValueError, match=message):
        matter.generate_pairing(key)


def test_explicit_keys_are_repeatable():
    first = matter.generate_pairing(_KEY)
    assert matter.generate_pairing(_KEY) == first
    assert matter.generate_pairing(_KEY + "!") != first


def test_omitted_keys_are_random_and_reproduce_their_own_codes():
    first = matter.generate_pairing()
    second = matter.generate_pairing()

    assert len(first["key"]) == 64
    assert first["key"] != second["key"]
    assert first["manual_pairing_code"] != second["manual_pairing_code"]
    assert matter.generate_pairing(first["key"]) == first


def test_random_keys_redraw_past_too_few_distinct_characters(monkeypatch):
    draws = [b"\xab" * 32, bytes(range(32))]
    monkeypatch.setattr(pairing, "os", SimpleNamespace(urandom=lambda _count: draws.pop(0)))

    assert matter.generate_pairing()["key"] == bytes(range(32)).hex()
    assert not draws


@pytest.mark.parametrize("forbidden", pairing._INVALID_PASSCODES)
def test_skips_forbidden_setup_passcodes(monkeypatch, forbidden):
    digest = (forbidden - 1).to_bytes(4, "big") + b"\xff\xff" + bytes(26)
    monkeypatch.setattr(
        pairing,
        "hashlib",
        SimpleNamespace(
            sha256=lambda _value: SimpleNamespace(digest=lambda: digest),
        ),
    )
    result = matter.generate_pairing(_KEY)
    assert result["passcode"] == forbidden % 99999999 + 1
    assert result["discriminator"] == 4095


def test_manual_encoding_matches_the_published_chip_vector():
    assert pairing._encode_manual_code(3840, 20202021) == "34970112332"
