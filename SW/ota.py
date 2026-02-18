#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "smpclient",
# ]
# ///
"""
OTA DFU tool for BLE devices using SMP (Simple Management Protocol).

Usage:
    uv run ota.py flash [image] [--confirm]   # upload, reboot, verify, confirm
    uv run ota.py confirm                     # confirm running image
    uv run ota.py verify [image]              # read device image state
    uv run ota.py scan                        # list SMP devices

Requires: uv (https://docs.astral.sh/uv/)
"""

import argparse
import asyncio
import json
import sys
import tempfile
import zipfile
from pathlib import Path

from smpclient import SMPClient
from smpclient.generics import error
from smpclient.mcuboot import IMAGE_TLV, ImageInfo
from smpclient.requests.image_management import ImageStatesRead, ImageStatesWrite
from smpclient.requests.os_management import ResetWrite
from smpclient.transport.ble import SMPBLETransport

DEFAULT_IMAGE = "build/dfu_application.zip"
HASH_TLVS = {IMAGE_TLV.SHA256, IMAGE_TLV.SHA384, IMAGE_TLV.SHA512}


async def scan_devices() -> list:
    """Scan for BLE devices advertising the SMP service."""
    return await SMPBLETransport.scan()


def print_devices(devices: list) -> None:
    if not devices:
        print("No SMP devices found. Is the device in DFU mode?")
        return
    print(f"Found {len(devices)} SMP device(s):")
    for i, d in enumerate(devices):
        print(f"  [{i}] {d.name or '(unknown)'}  ({d.address})")


def select_device() -> str:
    """Scan and interactively select a device. Supports 'r' to re-scan."""
    while True:
        print("Scanning for SMP devices...")
        devices = asyncio.run(scan_devices())
        print_devices(devices)
        if not devices:
            choice = input("Enter 'r' to re-scan, or Ctrl-C to quit: ").strip()
            if choice.lower() == "r":
                continue
            sys.exit(1)
        choice = input("Select device (or 'r' to re-scan): ").strip()
        if choice.lower() == "r":
            continue
        try:
            return str(devices[int(choice)].address)
        except (ValueError, IndexError):
            print("Invalid selection")
            sys.exit(1)


def resolve_image(path: Path, tmpdir: str) -> Path:
    """If path is a .zip, extract the signed .bin from it. Otherwise return as-is."""
    if path.suffix == ".zip":
        with zipfile.ZipFile(path) as zf:
            manifest = json.loads(zf.read("manifest.json"))
            bin_name = manifest["files"][0]["file"]
            extracted = Path(tmpdir) / bin_name
            zf.extract(bin_name, tmpdir)
            print(f"Extracted {bin_name} from {path.name}")
            return extracted
    return path


def resolve_target(args) -> str:
    """Get target address from --target flag or interactive selection."""
    if args.target:
        return args.target
    return select_device()


def get_image_hash(image_info: ImageInfo) -> bytes:
    """Extract the hash TLV value from an MCUboot image."""
    for tlv in image_info.tlvs:
        if tlv.header.type in HASH_TLVS:
            return tlv.value
    raise SystemExit("No hash TLV (SHA256/384/512) found in image")


def print_image_info(image_info: ImageInfo) -> None:
    """Print MCUboot image header details."""
    h = image_info.header
    v = h.ver
    print(f"  Version:  {v.major}.{v.minor}.{v.revision}+{v.build_num}")
    print(f"  Hdr size: {h.hdr_size} bytes")
    print(f"  Img size: {h.img_size} bytes ({h.img_size / 1024:.1f} KB)")
    print(f"  Flags:    0x{h.flags:08X}")
    print(f"  Hash:     {get_image_hash(image_info).hex()}")


def print_image_states(images: list) -> None:
    """Pretty-print the image state list from the device."""
    for img in images:
        flags = []
        if img.active:
            flags.append("active")
        if img.confirmed:
            flags.append("confirmed")
        if img.pending:
            flags.append("pending")
        if img.permanent:
            flags.append("permanent")
        if img.bootable:
            flags.append("bootable")
        flag_str = ", ".join(flags) if flags else "none"
        hash_str = img.hash.hex() if img.hash else "(no hash)"
        print(f"  slot {img.slot}: v{img.version}  [{flag_str}]")
        print(f"          hash: {hash_str}")


async def connect_with_retry(
    address: str, timeout_s: float = 30.0, interval_s: float = 5.0
) -> SMPClient:
    """Try to connect to the device, retrying until timeout."""
    deadline = asyncio.get_event_loop().time() + timeout_s
    last_error = None
    while asyncio.get_event_loop().time() < deadline:
        try:
            client = SMPClient(SMPBLETransport(), address)
            await client.connect(connect_timeout_s=interval_s)
            return client
        except Exception as e:
            last_error = e
            remaining = deadline - asyncio.get_event_loop().time()
            if remaining <= 0:
                break
            wait = min(interval_s, remaining)
            print(f"  Connection failed ({e}), retrying in {wait:.0f}s...")
            await asyncio.sleep(wait)
    raise SystemExit(f"Could not reconnect to {address} within {timeout_s:.0f}s: {last_error}")


async def do_flash(address: str, bin_path: Path, auto_confirm: bool) -> None:
    """Upload image, reboot, reconnect, verify, and optionally confirm."""
    image_data = bin_path.read_bytes()
    image_info = ImageInfo.load_file(str(bin_path))
    image_hash = get_image_hash(image_info)
    total = len(image_data)

    # Step 1: Connect and upload
    print("Connecting...")
    async with SMPClient(SMPBLETransport(), address) as client:
        print(f"Uploading {total} bytes...")
        async for offset in client.upload(image_data):
            pct = offset * 100 // total
            bar = "#" * (pct // 2) + "-" * (50 - pct // 2)
            print(f"\r  [{bar}] {pct}% ({offset}/{total})", end="", flush=True)
        print()
        print("Upload complete.")

        # Step 2: Read image states and mark for test boot
        response = await client.request(ImageStatesRead())
        if error(response):
            raise SystemExit(f"Failed to read image state after upload: {response}")

        primary = next((img for img in response.images if img.slot == 0), None)
        secondary = next((img for img in response.images if img.slot == 1), None)
        if secondary is None:
            raise SystemExit("No image in secondary slot after upload")

        if secondary.pending:
            print("Image already marked for test boot.")
        elif primary and primary.hash == secondary.hash:
            print("WARNING: Uploaded image is identical to the running image. Nothing to swap.")
            return
        else:
            print("Marking image for test boot...")
            response = await client.request(ImageStatesWrite(hash=secondary.hash, confirm=False))
            if error(response):
                raise SystemExit(f"Failed to set test boot: {response}")
            print("Image marked for test boot (pending).")

        # Step 3: Reset
        print("Resetting device...")
        response = await client.request(ResetWrite())
        if error(response):
            raise SystemExit(f"Reset failed: {response}")

    # Step 4: Wait for reboot and reconnect
    print("Waiting for device to reboot...")
    await asyncio.sleep(5)
    print("Reconnecting...")
    client = await connect_with_retry(address)

    try:
        # Step 5: Read image state and verify
        response = await client.request(ImageStatesRead())
        if error(response):
            raise SystemExit(f"Failed to read image state: {response}")

        print()
        print("=== Device image state ===")
        print_image_states(response.images)

        # Check that our image is now in slot 0 and active
        uploaded_in_primary = any(
            img.slot == 0 and img.active and img.hash == image_hash for img in response.images
        )
        if uploaded_in_primary:
            print()
            print("New firmware is running in the primary slot.")
        else:
            print()
            print("WARNING: Uploaded image is NOT active in slot 0.")
            print("The device may have reverted. Check image state above.")
            return

        # Step 6: Confirm
        if auto_confirm:
            do_confirm = True
        else:
            answer = input("\nConfirm image permanently? [y/N] ").strip().lower()
            do_confirm = answer == "y"

        if do_confirm:
            print("Confirming image...")
            response = await client.request(ImageStatesWrite(confirm=True))
            if error(response):
                raise SystemExit(f"Confirm failed: {response}")
            print("Image confirmed. It will persist across resets.")
        else:
            print("Image NOT confirmed. It will revert on next reset.")
            print(f"To confirm later: uv run ota.py confirm --target {address}")
    finally:
        await client.disconnect()


async def do_confirm(address: str) -> None:
    """Confirm the currently running image."""
    async with SMPClient(SMPBLETransport(), address) as client:
        response = await client.request(ImageStatesWrite(confirm=True))
        if error(response):
            raise SystemExit(f"Confirm failed: {response}")
    print("Image confirmed. It will no longer revert on reset.")


async def do_verify(address: str, local_hash: bytes | None) -> None:
    """Read and display device image state."""
    async with SMPClient(SMPBLETransport(), address) as client:
        response = await client.request(ImageStatesRead())
        if error(response):
            raise SystemExit(f"Failed to read image state: {response}")

    print_image_states(response.images)

    if local_hash:
        print()
        print(f"Local image hash: {local_hash.hex()}")
        match = any(img.hash == local_hash for img in response.images)
        if match:
            print("Local image hash matches a slot on the device.")
        else:
            print("WARNING: Local image hash does NOT match any slot on the device.")


def cmd_flash(args):
    address = resolve_target(args)
    image_path = Path(args.image)

    if not image_path.exists():
        print(f"Error: image not found: {image_path}")
        sys.exit(1)

    with tempfile.TemporaryDirectory() as tmpdir:
        bin_path = resolve_image(image_path, tmpdir)
        image_info = ImageInfo.load_file(str(bin_path))
        print()
        print(f"Image:  {bin_path}")
        print(f"Target: {address}")
        print()
        print("=== Image details ===")
        print_image_info(image_info)
        print()

        asyncio.run(do_flash(address, bin_path, args.confirm))


def cmd_confirm(args):
    address = resolve_target(args)
    print()
    print("=== Confirming running image ===")
    asyncio.run(do_confirm(address))


def cmd_verify(args):
    address = resolve_target(args)
    local_hash = None

    if args.image:
        image_path = Path(args.image)
        if not image_path.exists():
            print(f"Error: image not found: {image_path}")
            sys.exit(1)
        with tempfile.TemporaryDirectory() as tmpdir:
            bin_path = resolve_image(image_path, tmpdir)
            image_info = ImageInfo.load_file(str(bin_path))
            local_hash = get_image_hash(image_info)

    print()
    print("=== Device image state ===")
    asyncio.run(do_verify(address, local_hash))


def cmd_scan(args):
    print("Scanning for SMP devices...")
    devices = asyncio.run(scan_devices())
    print_devices(devices)


def main():
    parser = argparse.ArgumentParser(description="OTA DFU tool for BLE devices using SMP")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # flash
    p_flash = subparsers.add_parser("flash", help="Upload firmware, reboot, verify, and confirm")
    p_flash.add_argument(
        "image",
        nargs="?",
        default=DEFAULT_IMAGE,
        help=f"Signed .bin or .zip DFU package (default: {DEFAULT_IMAGE})",
    )
    p_flash.add_argument("--target", help="BLE address (skip scan)")
    p_flash.add_argument(
        "--confirm", action="store_true", help="Auto-confirm image without prompting"
    )
    p_flash.set_defaults(func=cmd_flash)

    # confirm
    p_confirm = subparsers.add_parser("confirm", help="Confirm running image (make permanent)")
    p_confirm.add_argument("--target", help="BLE address (skip scan)")
    p_confirm.set_defaults(func=cmd_confirm)

    # verify
    p_verify = subparsers.add_parser("verify", help="Read device image state")
    p_verify.add_argument(
        "image",
        nargs="?",
        default=None,
        help="Optional local .bin or .zip to compare hash against device",
    )
    p_verify.add_argument("--target", help="BLE address (skip scan)")
    p_verify.set_defaults(func=cmd_verify)

    # scan
    p_scan = subparsers.add_parser("scan", help="List SMP devices")
    p_scan.set_defaults(func=cmd_scan)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
