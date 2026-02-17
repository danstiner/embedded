#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "smpmgr",
# ]
# ///
"""
OTA DFU tool for BLE devices using SMP (Simple Management Protocol).

Usage:
    uv run ota.py flash [image]                # upload, test boot, reset
    uv run ota.py confirm                      # confirm running image
    uv run ota.py verify [image]               # read device image state
    uv run ota.py scan                         # list SMP devices

Requires: uv (https://docs.astral.sh/uv/)
"""

import argparse
import asyncio
import hashlib
import json
import struct
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

from smpclient.transport.ble import SMPBLETransport

DEFAULT_IMAGE = "build/dfu_application.zip"
MCUBOOT_IMG_MAGIC = 0x96F3B83D
HEADER_SIZE = 32


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


def inspect_image(path: Path) -> None:
    """Print MCUboot image header details."""
    data = path.read_bytes()
    if len(data) < HEADER_SIZE:
        print(f"  WARNING: file is only {len(data)} bytes, smaller than MCUboot header ({HEADER_SIZE})")
        return

    magic, load_addr, hdr_size, protect_tlv, img_size, flags = struct.unpack_from("<IIHHII", data, 0)
    ver_major, ver_minor, ver_rev, build_num = struct.unpack_from("<BBHI", data, 20)

    print(f"  Magic:    0x{magic:08X} {'(OK)' if magic == MCUBOOT_IMG_MAGIC else '(INVALID!)'}")
    print(f"  Version:  {ver_major}.{ver_minor}.{ver_rev}+{build_num}")
    print(f"  Hdr size: {hdr_size} bytes")
    print(f"  Img size: {img_size} bytes ({img_size / 1024:.1f} KB)")
    print(f"  Flags:    0x{flags:08X}")
    print(f"  File:     {len(data)} bytes total")


def image_hash(path: Path) -> str:
    """Compute SHA256 of the MCUboot image (header + body, size from TLV)."""
    data = path.read_bytes()
    if len(data) < HEADER_SIZE:
        print("Error: file too small for MCUboot header")
        sys.exit(1)

    magic, _, hdr_size, protect_tlv, img_size, _ = struct.unpack_from("<IIHHII", data, 0)
    if magic != MCUBOOT_IMG_MAGIC:
        print("Warning: not a valid MCUboot image (bad magic)")

    # Hash covers header + image body (not TLVs)
    hash_len = hdr_size + img_size
    if hash_len > len(data):
        print(f"Warning: expected {hash_len} bytes but file is {len(data)} bytes")
        hash_len = len(data)

    return hashlib.sha256(data[:hash_len]).hexdigest()


def run_smpmgr(address: str, *args: str) -> subprocess.CompletedProcess:
    cmd = ["smpmgr", "--ble", address, "--timeout", "30.0", *args]
    print(f"$ {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=False)
    if result.returncode != 0:
        print(f"Error: smpmgr exited with code {result.returncode}")
        sys.exit(1)
    return result


def resolve_target(args) -> str:
    """Get target address from --target flag or interactive selection."""
    if args.target:
        return args.target
    return select_device()


def cmd_flash(args):
    address = resolve_target(args)
    image_path = Path(args.image)

    if not image_path.exists():
        print(f"Error: image not found: {image_path}")
        sys.exit(1)

    print()
    with tempfile.TemporaryDirectory() as tmpdir:
        bin_path = resolve_image(image_path, tmpdir)
        print(f"Image: {bin_path}")
        print(f"Target: {address}")
        print()
        print("=== Image details ===")
        inspect_image(bin_path)
        print()

        print("=== Uploading and activating firmware ===")
        run_smpmgr(address, "upgrade", str(bin_path), "--slot", "1")

    print()
    print("Device is rebooting into the new firmware.")
    print()
    print("After verifying, confirm permanently (enter DFU mode again first):")
    print(f"  uv run ota.py confirm --target {address}")


def cmd_confirm(args):
    address = resolve_target(args)
    print()
    print("=== Confirming running image ===")
    run_smpmgr(address, "image", "state-write", "--confirm")
    print()
    print("Image confirmed. It will no longer revert on reset.")


def cmd_verify(args):
    address = resolve_target(args)
    print()
    print("=== Reading device image state ===")
    run_smpmgr(address, "image", "state-read")

    if args.image:
        image_path = Path(args.image)
        if not image_path.exists():
            print(f"Error: image not found: {image_path}")
            sys.exit(1)
        with tempfile.TemporaryDirectory() as tmpdir:
            bin_path = resolve_image(image_path, tmpdir)
            h = image_hash(bin_path)
            print()
            print(f"Local image SHA256: {h}")
            print("Compare with the hash reported by the device above.")


def cmd_scan(args):
    print("Scanning for SMP devices...")
    devices = asyncio.run(scan_devices())
    print_devices(devices)


def main():
    parser = argparse.ArgumentParser(description="OTA DFU tool for BLE devices using SMP")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # flash
    p_flash = subparsers.add_parser("flash", help="Upload firmware, test boot, and reset")
    p_flash.add_argument("image", nargs="?", default=DEFAULT_IMAGE,
                         help=f"Signed .bin or .zip DFU package (default: {DEFAULT_IMAGE})")
    p_flash.add_argument("--target", help="BLE address (skip scan)")
    p_flash.set_defaults(func=cmd_flash)

    # confirm
    p_confirm = subparsers.add_parser("confirm", help="Confirm running image (make permanent)")
    p_confirm.add_argument("--target", help="BLE address (skip scan)")
    p_confirm.set_defaults(func=cmd_confirm)

    # verify
    p_verify = subparsers.add_parser("verify", help="Read device image state")
    p_verify.add_argument("image", nargs="?", default=None,
                          help="Optional local .bin or .zip to compare hash against device")
    p_verify.add_argument("--target", help="BLE address (skip scan)")
    p_verify.set_defaults(func=cmd_verify)

    # scan
    p_scan = subparsers.add_parser("scan", help="List SMP devices")
    p_scan.set_defaults(func=cmd_scan)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
