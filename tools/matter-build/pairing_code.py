"""Generate a Matter QR offline from a recorded PASSCODE key."""

import argparse
import sys
from pathlib import Path

import build
import onboarding_codes
import qr_image
from pairing import generate_pairing


def main() -> None:
    """Render a QR for the selected project's board configuration."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--passcode", required=True, help="the flashed board's pairing key")
    parser.add_argument("--board-dir", type=Path, default=build.BOARD_DIR)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    pairing = generate_pairing(args.passcode)
    identity = build.board_to_identity(args.board_dir, build.DISCOVERY_MODE)
    payload = onboarding_codes.encode_qr_payload(
        identity.vendor_id,
        identity.product_id,
        pairing["discriminator"],
        pairing["passcode"],
        identity.discovery_mode,
    )
    qr_image.render(payload, args.output)
    sys.stdout.write(
        f"manual_pairing_code={pairing['manual_pairing_code']}\nsetup_payload={payload}\n"
    )


if __name__ == "__main__":
    main()
