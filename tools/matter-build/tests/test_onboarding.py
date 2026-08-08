"""Host tests for build.py's QR and manual pairing-code decoders.

Both decoders exist to check the manufacturing tool's output without reusing the
tool's own encoder, so they are pinned against the published CHIP test-device
codes -- an external anchor rather than a second copy of the same bit layout --
and then driven over their rejection paths with deliberately corrupted inputs.
"""

from dataclasses import replace

import build
import pytest

# The standard CHIP test device: VID 0xFFF1, PID 0x8001, discriminator 3840,
# passcode 20202021, discovery mode 4.
_KNOWN_PAYLOAD = "MT:-24J0AFN00KA0648G00"
_KNOWN_MANUAL = "34970112332"
_KNOWN_DISCRIMINATOR = 3840
_KNOWN_PASSCODE = 20202021


def test_decodes_the_published_test_payload():
    assert build._decode_qr_payload(_KNOWN_PAYLOAD) == {
        "version": 0,
        "vendor_id": 0xFFF1,
        "product_id": 0x8001,
        "commissioning_flow": 0,
        "discovery": 4,
        "discriminator": _KNOWN_DISCRIMINATOR,
        "passcode": _KNOWN_PASSCODE,
        "padding": 0,
    }


def test_decodes_every_field_at_its_boundary():
    fields = {
        "version": 0x7,
        "vendor_id": 0xFFFF,
        "product_id": 0xFFFF,
        "commissioning_flow": 0x3,
        "discovery": 0xFF,
        "discriminator": 0xFFF,
        "passcode": 0x7FFFFFF,
        "padding": 0x0,
    }
    assert build._decode_qr_payload(encode_qr_payload(**fields)) == fields


def test_qr_payload_needs_the_matter_prefix():
    with pytest.raises(ValueError, match="must start with MT:"):
        build._decode_qr_payload(_KNOWN_PAYLOAD[1:])


def test_qr_payload_rejects_a_character_outside_base38():
    corrupted = _KNOWN_PAYLOAD[:5] + "*" + _KNOWN_PAYLOAD[6:]
    with pytest.raises(ValueError, match="invalid base38 character"):
        build._decode_qr_payload(corrupted)


@pytest.mark.parametrize("dropped", [1, 3])
def test_qr_payload_rejects_a_truncated_final_chunk(dropped):
    # 5, 4 and 2 characters decode to 3, 2 and 1 bytes; a trailing 3 or 1 is not
    # a chunk at all. The payload is 19 characters, so dropping 1 or 3 leaves one.
    with pytest.raises(ValueError, match="invalid base38 chunk length"):
        build._decode_qr_payload(_KNOWN_PAYLOAD[:-dropped])


def test_qr_payload_rejects_a_chunk_that_overflows_its_bytes():
    # "...." is 37 in every base38 digit, which exceeds three bytes.
    with pytest.raises(ValueError, match="base38 chunk overflows"):
        build._decode_qr_payload("MT:.....")


def test_decodes_the_published_manual_code():
    assert build._decode_manual_code(_KNOWN_MANUAL) == {
        "short_discriminator": _KNOWN_DISCRIMINATOR >> 8,
        "passcode": _KNOWN_PASSCODE,
    }


def test_manual_code_ignores_grouping_dashes():
    grouped = f"{_KNOWN_MANUAL[:4]}-{_KNOWN_MANUAL[4:7]}-{_KNOWN_MANUAL[7:]}"
    assert build._decode_manual_code(grouped) == build._decode_manual_code(_KNOWN_MANUAL)


@pytest.mark.parametrize("code", ["3497011233", "349701123321", "3497O112332"])
def test_manual_code_needs_eleven_digits(code):
    with pytest.raises(ValueError, match="must contain 11 digits"):
        build._decode_manual_code(code)


def test_manual_code_rejects_the_custom_flow_bit():
    # Bit 2 of the leading digit marks a custom commissioning flow.
    custom = str(int(_KNOWN_MANUAL[0]) | 0x4) + _KNOWN_MANUAL[1:]
    with pytest.raises(ValueError, match="only standard commissioning flow"):
        build._decode_manual_code(custom)


def test_onboarding_accepts_matching_codes(identity):
    build._validate_onboarding(
        _KNOWN_PAYLOAD,
        _KNOWN_MANUAL,
        _KNOWN_DISCRIMINATOR,
        _KNOWN_PASSCODE,
        identity,
    )


@pytest.mark.parametrize(
    "field, value",
    [
        ("vendor_id", 0xFFF2),
        ("product_id", 0x8002),
        ("discovery_mode", 2),
    ],
)
def test_onboarding_rejects_a_payload_disagreeing_with_the_board(identity, field, value):
    with pytest.raises(ValueError, match="do not match build identity"):
        build._validate_onboarding(
            _KNOWN_PAYLOAD,
            _KNOWN_MANUAL,
            _KNOWN_DISCRIMINATOR,
            _KNOWN_PASSCODE,
            replace(identity, **{field: value}),
        )


def test_onboarding_rejects_a_discriminator_disagreeing_with_the_payload(identity):
    with pytest.raises(ValueError, match="do not match build identity"):
        build._validate_onboarding(
            _KNOWN_PAYLOAD,
            _KNOWN_MANUAL,
            3841,
            _KNOWN_PASSCODE,
            identity,
        )


def test_onboarding_rejects_a_manual_code_from_another_device(identity):
    # A manual code minted for a different passcode, beside the right QR payload.
    other = encode_manual_code(_KNOWN_DISCRIMINATOR >> 8, 12345678)
    with pytest.raises(ValueError, match="manual pairing code does not match"):
        build._validate_onboarding(
            _KNOWN_PAYLOAD,
            other,
            _KNOWN_DISCRIMINATOR,
            _KNOWN_PASSCODE,
            identity,
        )


def encode_qr_payload(
    *,
    version: int,
    vendor_id: int,
    product_id: int,
    commissioning_flow: int,
    discovery: int,
    discriminator: int,
    passcode: int,
    padding: int = 0,
) -> str:
    """Build an MT: payload from field values, so the decoder is checked against them.

    Args:
        version: Payload version, 3 bits.
        vendor_id: Matter vendor ID, 16 bits.
        product_id: Matter product ID, 16 bits.
        commissioning_flow: Commissioning flow selector, 2 bits.
        discovery: Discovery capabilities bitmask, 8 bits.
        discriminator: Full 12-bit discriminator.
        passcode: Setup passcode, 27 bits.
        padding: Trailing pad bits, 4 bits.

    Returns:
        The base38 setup payload string, including its MT: prefix.
    """
    packed = (
        version
        | vendor_id << 3
        | product_id << 19
        | commissioning_flow << 35
        | discovery << 37
        | discriminator << 45
        | passcode << 57
        | padding << 84
    )
    raw = packed.to_bytes(11, "little")
    characters = []
    for offset in range(0, len(raw), 3):
        block = raw[offset : offset + 3]
        value = int.from_bytes(block, "little")
        for _ in range({1: 2, 2: 4, 3: 5}[len(block)]):
            characters.append(build._BASE38[value % 38])
            value //= 38
    return "MT:" + "".join(characters)


def encode_manual_code(short_discriminator: int, passcode: int) -> str:
    """Build an 11-digit manual pairing code; the trailing check digit is a filler.

    Args:
        short_discriminator: Top 4 bits of the discriminator.
        passcode: Setup passcode, 27 bits.

    Returns:
        The 11-digit manual pairing code as a string.
    """
    chunk1 = (short_discriminator >> 2) & 0x3
    chunk2 = ((short_discriminator & 0x3) << 14) | (passcode & 0x3FFF)
    chunk3 = passcode >> 14
    return f"{chunk1:01d}{chunk2:05d}{chunk3:04d}0"


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
