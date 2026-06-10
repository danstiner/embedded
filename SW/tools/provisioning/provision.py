#!/usr/bin/env python3
"""Per-device Matter factory-data provisioning for nRF Connect boards.

This tool generates the factory-data partition per device and (optionally)
flashes just that partition, leaving the firmware untouched.

It is board-agnostic: everything board/app-specific (vendor/product ID, names, hardware
version, SPAKE2+ iteration count, factory-data partition offset/size, and the matter
module that holds the development certificates) is read from a board *build directory*,
so any board's Matter build can be provisioned with the same script. It is a thin
wrapper around the same NCS generator the build itself uses
(modules/lib/matter/scripts/tools/nrfconnect/generate_nrfconnect_chip_factory_data.py).

Example usage, run from the SW/ directory, in your nRF Connect SDK environment:

    python tools/provisioning/provision.py --build-dir hygrometer/build --flash

Outputs (gitignored) land in SW/tools/provisioning/history/:
    factory_data_<sn>.hex / .json / .png (QR) / .txt (manual + QR codes)
    provisioning_log.csv   - one row per provisioned device
    counter.txt            - sequential serial counter

The development DAC stays shared per product ID (it is not unique per device); only the
identity fields above change. For production, swap the dev DAC for per-device production
DACs and a CSA-signed CD - the rest of this flow is unchanged.
"""

import argparse
import base64
import csv
import datetime
import json
import os
import re
import secrets
import subprocess
import sys
from pathlib import Path

# Passcodes the Matter spec forbids (trivial / well-known).
INVALID_PASSCODES = {
    0, 11111111, 22222222, 33333333, 44444444, 55555555,
    66666666, 77777777, 88888888, 99999999, 12345678, 87654321,
}

THIS_DIR = Path(__file__).resolve().parent          # SW/tools/provisioning
OUTPUT_DIR = THIS_DIR / "history"
COUNTER_FILE = OUTPUT_DIR / "counter.txt"
LOG_FILE = OUTPUT_DIR / "provisioning_log.csv"


def read_kconfig(config_path: Path) -> dict:
    """Parse a Zephyr .config into {symbol: value} (strings unquoted)."""
    out = {}
    for line in config_path.read_text().splitlines():
        m = re.match(r"^(CONFIG_[A-Z0-9_]+)=(.*)$", line)
        if not m:
            continue
        key, val = m.group(1), m.group(2)
        if val.startswith('"') and val.endswith('"'):
            val = val[1:-1]
        out[key] = val
    return out


def find_image_dir(build_dir: Path) -> Path:
    """Locate the application image dir (<build>/<app>/zephyr/.config) — the one with
    CONFIG_CHIP=y, skipping mcuboot."""
    for cfg in sorted(build_dir.glob("*/zephyr/.config")):
        if "mcuboot" in cfg.parts:
            continue
        if "CONFIG_CHIP=y" in cfg.read_text():
            return cfg.parent.parent
    raise SystemExit(f"No Matter application image (CONFIG_CHIP=y) found under {build_dir}")


def read_partition(partitions_yml: Path, name: str):
    """Return (address, size) ints for a partition from sysbuild partitions.yml."""
    text = partitions_yml.read_text()
    m = re.search(rf"^{name}:\n((?:[ \t]+.*\n)+)", text, re.MULTILINE)
    if not m:
        raise SystemExit(f"Partition '{name}' not found in {partitions_yml}")
    block = m.group(1)
    addr = re.search(r"address:\s*(0x[0-9a-fA-F]+|\d+)", block)
    size = re.search(r"size:\s*(0x[0-9a-fA-F]+|\d+)", block)
    if not addr or not size:
        raise SystemExit(f"Partition '{name}' missing address/size in {partitions_yml}")
    return int(addr.group(1), 0), int(size.group(1), 0)


def find_matter_dir(image_dir: Path) -> Path:
    """Locate the connectedhomeip (matter) module the build used. The build records it
    in kconfig_module_dirs.cmake; fall back to the standard west layout."""
    kfile = image_dir / "Kconfig" / "kconfig_module_dirs.cmake"
    if kfile.exists():
        m = re.search(r"ZEPHYR_CONNECTEDHOMEIP_MODULE_DIR=([^)\s]+)", kfile.read_text())
        if m and Path(m.group(1)).is_dir():
            return Path(m.group(1))
    # Fallback: SW/west/ncs/modules/lib/matter (THIS_DIR is SW/tools/provisioning).
    fallback = THIS_DIR.parent.parent / "west" / "ncs" / "modules" / "lib" / "matter"
    if fallback.is_dir():
        return fallback
    raise SystemExit("Could not locate the matter module (ZEPHYR_CONNECTEDHOMEIP_MODULE_DIR)")


def next_serial(prefix: str) -> str:
    n = int(COUNTER_FILE.read_text()) + 1 if COUNTER_FILE.exists() else 1
    COUNTER_FILE.write_text(str(n))
    return f"{prefix}-{n:04d}"


def load_prior_identity(sn: str):
    """If serial `sn` was provisioned before, return (discriminator, passcode, salt_b64)
    so re-provisioning reproduces the same QR / pairing code. None if no prior record."""
    jf = OUTPUT_DIR / f"factory_data_{sn}.json"
    if not jf.exists():
        return None
    d = json.loads(jf.read_text())
    salt = d["spake2_salt"]
    if salt.startswith("hex:"):  # generator stores salt as hex; --spake2_salt wants base64
        salt = base64.b64encode(bytes.fromhex(salt[len("hex:"):])).decode()
    return int(d["discriminator"]), int(d["passcode"]), salt


def random_passcode() -> int:
    while True:
        # Cryptographically secure: this is the SPAKE2+ setup PIN. Valid range is
        # 1..99999998 (0x5F5E0FE); secrets.randbelow(99999998) gives 0..99999997.
        p = secrets.randbelow(99999998) + 1
        if p not in INVALID_PASSCODES:
            return p


def parse_onboarding(txt_path: Path):
    manual = qr = ""
    for line in txt_path.read_text().splitlines():
        if line.startswith("Manualcode"):
            manual = line.split(":", 1)[1].strip()
        elif line.startswith("QRCode"):
            qr = line.split(":", 1)[1].strip()
    return manual, qr


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--build-dir", required=True, type=Path,
                    help="Board Matter build directory (e.g. hygrometer/build-matter-v4-dbg)")
    ap.add_argument("--prefix", default="BB",
                    help="Serial-number prefix (default: BB, Barry's Boards)")
    ap.add_argument("--sn", "--serial-number", dest="sn",
                    help="Reuse this device serial (e.g. BB-0001) instead of minting the next "
                         "one — the counter is left untouched. If the serial was provisioned "
                         "before, its discriminator/passcode/salt are reused so the QR/pairing "
                         "code is identical (re-flash a unit without it becoming a new device).")
    ap.add_argument("--flash", action="store_true",
                    help="Flash the generated factory-data partition to the connected device")
    ap.add_argument("--snr", help="Probe/J-Link serial number to flash (NOT the device serial; "
                                  "see --sn) (optional)")
    args = ap.parse_args()

    build_dir = args.build_dir.resolve()
    if not build_dir.is_dir():
        raise SystemExit(f"Build dir not found: {build_dir}")

    image_dir = find_image_dir(build_dir)
    cfg = read_kconfig(image_dir / "zephyr" / ".config")
    if cfg.get("CONFIG_CHIP_FACTORY_DATA") != "y":
        raise SystemExit("This build does not have CONFIG_CHIP_FACTORY_DATA=y")

    vid = int(cfg["CONFIG_CHIP_DEVICE_VENDOR_ID"], 0)
    pid = int(cfg["CONFIG_CHIP_DEVICE_PRODUCT_ID"], 0)
    addr, size = read_partition(build_dir / "partitions.yml", "factory_data")
    matter_dir = find_matter_dir(image_dir)

    gen = matter_dir / "scripts/tools/nrfconnect/generate_nrfconnect_chip_factory_data.py"
    schema = matter_dir / "scripts/tools/nrfconnect/nrfconnect_factory_data.schema"
    attest = matter_dir / "credentials/development/attestation"
    dac = attest / f"Matter-Development-DAC-{vid:04X}-{pid:04X}-Cert.der"
    dac_key = attest / f"Matter-Development-DAC-{vid:04X}-{pid:04X}-Key.der"
    pai = attest / f"Matter-Development-PAI-{vid:04X}-noPID-Cert.der"
    for f in (gen, schema, dac, dac_key, pai):
        if not f.exists():
            raise SystemExit(f"Required file missing: {f}")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    if args.sn:
        sn = args.sn                       # reuse this serial; leave the counter alone
        prior = load_prior_identity(sn)
    else:
        sn = next_serial(args.prefix)
        prior = None

    if prior:
        disc, passcode, salt = prior
        print(f"Reusing existing identity for {sn} (discriminator={disc} passcode={passcode})")
    else:
        disc = secrets.randbelow(0x1000)   # 0..0xFFF, cryptographically secure
        passcode = random_passcode()
        salt = base64.b64encode(secrets.token_bytes(16)).decode()
    out_base = OUTPUT_DIR / f"factory_data_{sn}"

    cmd = [
        sys.executable, str(gen),
        "--sn", sn,
        "--vendor_id", str(vid), "--product_id", str(pid),
        "--vendor_name", cfg.get("CONFIG_CHIP_DEVICE_VENDOR_NAME", "Nordic Semiconductor ASA"),
        "--product_name", cfg.get("CONFIG_CHIP_DEVICE_PRODUCT_NAME", "Matter Device"),
        "--date", datetime.date.today().isoformat(),
        "--hw_ver", cfg.get("CONFIG_CHIP_DEVICE_HARDWARE_VERSION", "0"),
        "--hw_ver_str", cfg.get("CONFIG_CHIP_DEVICE_HARDWARE_VERSION_STRING", "prerelease"),
        "--spake2_it", cfg.get("CONFIG_CHIP_DEVICE_SPAKE2_IT", "10000"),
        "--spake2_salt", salt,
        "--discriminator", str(disc),
        "--passcode", str(passcode),
        "--include_passcode",
        "--generate_rd_uid",
        "--generate_onboarding",
        "--dac_cert", str(dac), "--dac_key", str(dac_key), "--pai_cert", str(pai),
        "--offset", hex(addr), "--size", hex(size),
        "-s", str(schema),
        "-o", str(out_base),
        "--overwrite",
    ]

    # Match the extra fields the firmware build bakes in (and the app reads at startup —
    # a missing enable_key fails CHIP server init).
    if cfg.get("CONFIG_CHIP_DEVICE_ENABLE_KEY"):
        cmd += ["--enable_key", cfg["CONFIG_CHIP_DEVICE_ENABLE_KEY"]]
    if cfg.get("CONFIG_CHIP_DEVICE_PRODUCT_FINISH"):
        cmd += ["--product_finish", cfg["CONFIG_CHIP_DEVICE_PRODUCT_FINISH"]]
    if cfg.get("CONFIG_CHIP_DEVICE_PRODUCT_COLOR"):
        cmd += ["--product_color", cfg["CONFIG_CHIP_DEVICE_PRODUCT_COLOR"]]

    # Run from the generator's own directory so its sibling imports resolve.
    env = dict(os.environ,
               PYTHONPATH=str(gen.parent) + os.pathsep + os.environ.get("PYTHONPATH", ""))
    print(f"Provisioning {sn}  (vid=0x{vid:04X} pid=0x{pid:04X} discriminator={disc} "
          f"passcode={passcode})")
    subprocess.run(cmd, cwd=str(gen.parent), env=env, check=True)

    manual, qr = parse_onboarding(Path(str(out_base) + ".txt"))
    new_log = not LOG_FILE.exists()
    with open(LOG_FILE, "a", newline="") as f:
        w = csv.writer(f)
        if new_log:
            w.writerow(["serial", "vid", "pid", "discriminator", "passcode",
                        "manualcode", "qrcode", "date", "hexfile"])
        w.writerow([sn, f"0x{vid:04X}", f"0x{pid:04X}", disc, passcode,
                    manual, qr, datetime.datetime.now().isoformat(timespec="seconds"),
                    out_base.name + ".hex"])

    hexfile = Path(str(out_base) + ".hex")
    print(f"\n  serial : {sn}")
    print(f"  manual : {manual}")
    print(f"  qrcode : {qr}")
    print(f"  QR png : {out_base}.png")
    print(f"  hex    : {hexfile}  (factory_data @ {hex(addr)}, {hex(size)})")
    print(f"  logged : {LOG_FILE}")

    if args.flash:
        # nrfutil device (Nordic's current tool) over J-Link.
        # ERASE_RANGES_TOUCHED_BY_FIRMWARE touches only the factory-data sectors this hex
        # covers, leaving the firmware intact.
        flash = ["nrfutil", "device", "program", "--firmware", str(hexfile), "--options",
                 "chip_erase_mode=ERASE_RANGES_TOUCHED_BY_FIRMWARE,verify=VERIFY_READ,reset=RESET_SYSTEM"]
        if args.snr:
            flash += ["--serial-number", args.snr]
        print(f"\nFlashing factory data:\n  {' '.join(flash)}")
        subprocess.run(flash, check=True)
        print("Factory data flashed and device reset. Commission device now, it has a "
              "unique identity + QR.")


if __name__ == "__main__":
    main()
