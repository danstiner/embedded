#!/usr/bin/env python3
"""Stage Matter OTA firmware updates on the Home Assistant Matter Server.

One command takes freshly built `matter.ota` images, writes the matching update
descriptors, copies them to the Matter Server add-on's updates folder over SSH,
and restarts the add-on so it picks them up. The new versions then show up as
available updates in Home Assistant, where you install them per device.

For each build directory the script:
  1. reads `matter.ota` and extracts VID/PID/SoftwareVersion from its header
     (via the matter module's ota_image_tool.py, located from the build);
  2. writes a DCL-style JSON descriptor with a base64 SHA-256 checksum;
  3. scp's both files to /addon_configs/core_matter_server/updates/ on the HA
     host and restarts the add-on with `ha apps restart core_matter_server`
     (it only scans that folder at startup).

Then install the staged update from the HA UI (Settings > Devices > the device
> its Update entity), or wait for the device's next OTA check.

Example usage, run from the SW/ directory:

    python3 tools/matter/ota/deploy_ota.py \
        --build-dir hygrometer/build-matter-v3 \
        --build-dir hygrometer/build-matter-v4

Prerequisites on the Home Assistant side:
  * The official "Terminal & SSH" (or "Advanced SSH & Web Terminal") add-on
    with your SSH public key, so `ssh root@homeassistant.local` works without
    a password prompt. The add-on exposes /addon_configs and the `ha` CLI.
  * The Matter Server add-on.

Notes:
  * `--stage-only` writes the .ota/.json pairs to a local directory instead
    (useful if you prefer copying to the Samba share by hand).
  * Pure standard library; no third-party dependencies.
"""

import argparse
import base64
import hashlib
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent

ADDON_SLUG = "core_matter_server"
REMOTE_UPDATES_DIR = f"/addon_configs/{ADDON_SLUG}/updates"


def find_matter_dir(image_dir: Path) -> Path:
    """Locate the connectedhomeip (matter) module the build used (same logic
    as tools/matter/provisioning/provision.py)."""
    kfile = image_dir / "Kconfig" / "kconfig_module_dirs.cmake"
    if kfile.exists():
        m = re.search(r"ZEPHYR_CONNECTEDHOMEIP_MODULE_DIR=([^)\s]+)", kfile.read_text())
        if m and Path(m.group(1)).is_dir():
            return Path(m.group(1))
    fallback = THIS_DIR.parents[2] / "west" / "ncs" / "modules" / "lib" / "matter"
    if fallback.is_dir():
        return fallback
    raise SystemExit("Could not locate the matter module (ZEPHYR_CONNECTEDHOMEIP_MODULE_DIR)")


def default_image_dir(build_dir: Path) -> Path:
    """The default (application) image directory of a sysbuild build."""
    domains = build_dir / "domains.yaml"
    if domains.exists():
        m = re.search(r"default:\s*(\S+)", domains.read_text())
        if m:
            return build_dir / m.group(1)
    raise SystemExit(f"{build_dir}: not a sysbuild build directory (no domains.yaml)")


def read_kconfig(image_dir: Path, key: str) -> str:
    """Return a value from the built application's .config, or '' if absent."""
    config = image_dir / "zephyr" / ".config"
    if config.exists():
        m = re.search(rf"^{re.escape(key)}=(.*)$", config.read_text(), re.M)
        if m:
            return m.group(1).strip().strip('"')
    return ""


@dataclass
class OtaImage:
    data: bytes
    slug: str
    vid: int
    pid: int
    version: int
    version_string: str
    size: int
    checksum_b64: str

    @property
    def stem(self) -> str:
        return f"{self.slug}-{self.version_string}-{self.version}"

    def descriptor(self) -> dict:
        return {
            "modelVersion": {
                "vid": self.vid,
                "pid": self.pid,
                "softwareVersion": self.version,
                "softwareVersionString": self.version_string,
                "minApplicableSoftwareVersion": 0,
                "maxApplicableSoftwareVersion": max(0, self.version - 1),
                "otaUrl": f"file:///{self.stem}.ota",
                "otaFileSize": self.size,
                "otaChecksum": self.checksum_b64,
                "otaChecksumType": 1,  # SHA-256
                "releaseNotesUrl": "",
            }
        }


def parse_ota_image(build_dir: Path) -> OtaImage:
    if not build_dir.is_dir():
        raise SystemExit(
            f"build directory {build_dir} does not exist."
        )
    ota = build_dir / "matter.ota"
    if not ota.exists():
        raise SystemExit(
            f"{ota} not found -- build with SB_CONFIG_DFU_MULTI_IMAGE_PACKAGE_BUILD=y"
        )
    image_dir = default_image_dir(build_dir)
    board = read_kconfig(image_dir, "CONFIG_BOARD")
    revision = read_kconfig(image_dir, "CONFIG_BOARD_REVISION")
    slug = f"{board}-{revision}" if revision else board
    tool = find_matter_dir(image_dir) / "src/app/ota_image_tool.py"
    out = subprocess.run(
        [sys.executable, str(tool), "show", str(ota)],
        check=True, capture_output=True, text=True,
    ).stdout

    def field(pattern: str) -> str:
        m = re.search(pattern, out)
        if not m:
            raise SystemExit(f"Could not parse '{pattern}' from {tool} output:\n{out}")
        return m.group(1)

    data = ota.read_bytes()
    return OtaImage(
        data=data,
        slug=slug,
        vid=int(field(r"\] Vendor Id:\s*(\d+)")),
        pid=int(field(r"\] Product Id:\s*(\d+)")),
        version=int(field(r"\] Version:\s*(\d+)")),
        version_string=field(r"\] Version String:\s*(\S+)"),
        size=len(data),
        checksum_b64=base64.b64encode(hashlib.sha256(data).digest()).decode(),
    )


def stage(images: list[OtaImage], stage_dir: Path) -> list[Path]:
    stage_dir.mkdir(parents=True, exist_ok=True)
    files = []
    for img in images:
        ota_dst = stage_dir / f"{img.stem}.ota"
        json_dst = stage_dir / f"{img.stem}.json"
        ota_dst.write_bytes(img.data)
        json_dst.write_text(json.dumps(img.descriptor(), indent=2) + "\n")
        files += [ota_dst, json_dst]
        print(f"Staged {img.stem}: VID 0x{img.vid:04X} PID 0x{img.pid:04X} "
              f"version {img.version} (0x{img.version:X}, '{img.version_string}'), "
              f"{img.size} bytes")
    return files


def ssh_base(args) -> list[str]:
    return ["ssh", "-p", str(args.ssh_port), f"{args.ssh_user}@{args.host}"]


def deploy_files(args, files: list[Path]) -> None:
    subprocess.run(ssh_base(args) + [f"mkdir -p {REMOTE_UPDATES_DIR}"], check=True)
    dest = f"{args.ssh_user}@{args.host}:{REMOTE_UPDATES_DIR}/"
    subprocess.run(
        ["scp", "-P", str(args.ssh_port)] + [str(f) for f in files] + [dest],
        check=True,
    )
    print(f"Copied {len(files)} files to {dest}")
    print(f"Restarting {ADDON_SLUG} add-on ...")
    subprocess.run(ssh_base(args) + [f"ha apps restart {ADDON_SLUG}"], check=True)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--build-dir", action="append", required=True, type=Path,
                    help="Sysbuild build directory containing matter.ota (repeatable)")
    ap.add_argument("--host", default="homeassistant.local",
                    help="Home Assistant hostname/IP (default: %(default)s)")
    ap.add_argument("--ssh-user", default="root")
    ap.add_argument("--ssh-port", type=int, default=22)
    ap.add_argument("--stage-dir", type=Path, default=THIS_DIR / "staged",
                    help="Local staging directory (default: %(default)s)")
    ap.add_argument("--stage-only", action="store_true",
                    help="Only write .ota/.json pairs locally; do not touch HA")
    args = ap.parse_args()

    images = [parse_ota_image(d) for d in args.build_dir]
    files = stage(images, args.stage_dir)
    if args.stage_only:
        print(f"\nStage-only: copy these to {REMOTE_UPDATES_DIR}/ on the HA host "
              f"and restart the {ADDON_SLUG} add-on.")
        return 0

    deploy_files(args, files)
    print("\nDone. The new version(s) now show as available updates in HA "
          "(Settings > Devices); click Install on each device.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
