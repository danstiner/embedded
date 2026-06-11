#!/usr/bin/env python3
"""Deploy Matter OTA firmware updates to devices via the Home Assistant Matter Server.

One command takes freshly built `matter.ota` images, stages them on the Home
Assistant host, restarts the Matter Server add-on (it only scans its local
updates folder at startup), and then drives the update of every matching,
out-of-date node directly over the Matter Server WebSocket API -- no clicking
through the HA UI.

For each build directory the script:
  1. reads `matter.ota` and extracts VID/PID/SoftwareVersion from its header
     (via the matter module's ota_image_tool.py, located from the build);
  2. writes a DCL-style JSON descriptor with a base64 SHA-256 checksum;
  3. scp's both files to /addon_configs/core_matter_server/updates/ on the HA
     host and restarts the add-on with `ha addons restart core_matter_server`;
  4. connects to ws://<host>:5580/ws, lists commissioned nodes, and calls
     `update_node` for every node whose VID/PID matches a staged image and
     whose running SoftwareVersion is older. Updates run sequentially; OTA
     Software Update Requestor state changes are printed as they happen.

Example usage, run from the SW/ directory:

    python tools/ota/deploy_ota.py \
        --build-dir hygrometer/build-matter-v3 \
        --build-dir hygrometer/build-matter-v4

Prerequisites on the Home Assistant side:
  * The official "Terminal & SSH" (or "Advanced SSH & Web Terminal") add-on
    with your SSH public key, so `ssh root@homeassistant.local` works without
    a password prompt. The add-on exposes /addon_configs and the `ha` CLI.
  * The Matter Server add-on (host-networked; WebSocket reachable on :5580).

Notes:
  * Sleepy Thread devices switch to fast polling during the transfer, but a
    ~600 KB image still takes a while; the per-node timeout is generous.
  * `--stage-only` writes the .ota/.json pairs to a local directory instead
    (useful if you prefer copying to the Samba share by hand).
  * Requires the `websockets` package; a private venv is created next to this
    script on first run if it is missing.
"""

import argparse
import asyncio
import base64
import hashlib
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent

ADDON_SLUG = "core_matter_server"
REMOTE_UPDATES_DIR = f"/addon_configs/{ADDON_SLUG}/updates"

# Basic Information cluster attribute paths (endpoint 0, cluster 0x0028)
ATTR_VENDOR_ID = "0/40/2"
ATTR_PRODUCT_ID = "0/40/4"
ATTR_SOFTWARE_VERSION = "0/40/9"
ATTR_SOFTWARE_VERSION_STRING = "0/40/10"
ATTR_NODE_LABEL = "0/40/5"
ATTR_PRODUCT_NAME = "0/40/3"
# OTA Software Update Requestor cluster (0x002A) -- for progress events
OTA_REQUESTOR_PREFIX = "0/42/"


def ensure_websockets() -> None:
    """Re-exec into a private venv that has the `websockets` package."""
    try:
        import websockets  # noqa: F401
        return
    except ImportError:
        pass
    if os.environ.get("DEPLOY_OTA_BOOTSTRAPPED"):
        sys.exit("error: `websockets` still missing after venv bootstrap")
    venv = THIS_DIR / ".venv"
    py = venv / "bin" / "python"
    if not py.exists():
        print(f"Creating {venv} (one-time) ...")
        subprocess.run([sys.executable, "-m", "venv", str(venv)], check=True)
    subprocess.run([str(py), "-m", "pip", "install", "-q", "websockets"], check=True)
    os.environ["DEPLOY_OTA_BOOTSTRAPPED"] = "1"
    os.execv(str(py), [str(py), *sys.argv])


def find_matter_dir(image_dir: Path) -> Path:
    """Locate the connectedhomeip (matter) module the build used (same logic
    as tools/provisioning/provision.py)."""
    kfile = image_dir / "Kconfig" / "kconfig_module_dirs.cmake"
    if kfile.exists():
        m = re.search(r"ZEPHYR_CONNECTEDHOMEIP_MODULE_DIR=([^)\s]+)", kfile.read_text())
        if m and Path(m.group(1)).is_dir():
            return Path(m.group(1))
    fallback = THIS_DIR.parent.parent / "west" / "ncs" / "modules" / "lib" / "matter"
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


@dataclass
class OtaImage:
    path: Path
    vid: int
    pid: int
    version: int
    version_string: str
    size: int
    checksum_b64: str

    @property
    def stem(self) -> str:
        return f"ota-{self.vid:04x}-{self.pid:04x}-{self.version}"

    def descriptor(self) -> dict:
        return {
            "modelVersion": {
                "vid": self.vid,
                "pid": self.pid,
                "softwareVersion": self.version,
                "softwareVersionString": self.version_string,
                "minApplicableSoftwareVersion": 0,
                "maxApplicableSoftwareVersion": self.version - 1,
                "otaUrl": f"file:///{self.stem}.ota",
                "otaFileSize": self.size,
                "otaChecksum": self.checksum_b64,
                "otaChecksumType": 1,  # SHA-256
                "releaseNotesUrl": "",
            }
        }


def parse_ota_image(build_dir: Path) -> OtaImage:
    ota = build_dir / "matter.ota"
    if not ota.exists():
        raise SystemExit(
            f"{ota} not found -- build with SB_CONFIG_DFU_MULTI_IMAGE_PACKAGE_BUILD=y"
        )
    tool = find_matter_dir(default_image_dir(build_dir)) / "src/app/ota_image_tool.py"
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
        path=ota,
        vid=int(field(r"Vendor Id:\s*(\d+)")),
        pid=int(field(r"Product Id:\s*(\d+)")),
        version=int(field(r"Version:\s*(\d+)")),
        version_string=field(r"Version String:\s*(\S+)"),
        size=len(data),
        checksum_b64=base64.b64encode(hashlib.sha256(data).digest()).decode(),
    )


def stage(images: list[OtaImage], stage_dir: Path) -> list[Path]:
    stage_dir.mkdir(parents=True, exist_ok=True)
    files = []
    for img in images:
        ota_dst = stage_dir / f"{img.stem}.ota"
        json_dst = stage_dir / f"{img.stem}.json"
        ota_dst.write_bytes(img.path.read_bytes())
        json_dst.write_text(json.dumps(img.descriptor(), indent=2) + "\n")
        files += [ota_dst, json_dst]
        print(f"Staged {img.stem}: VID 0x{img.vid:04X} PID 0x{img.pid:04X} "
              f"version {img.version} (0x{img.version:X}, '{img.version_string}'), "
              f"{img.size} bytes")
    return files


def ssh_base(args) -> list[str]:
    return ["ssh", "-p", str(args.ssh_port), f"{args.ssh_user}@{args.host}"]


def deploy_files(args, files: list[Path], images: list[OtaImage]) -> None:
    subprocess.run(ssh_base(args) + [f"mkdir -p {REMOTE_UPDATES_DIR}"], check=True)
    if args.prune:
        for img in images:
            pattern = f"{REMOTE_UPDATES_DIR}/ota-{img.vid:04x}-{img.pid:04x}-*"
            subprocess.run(ssh_base(args) + [f"rm -f {pattern}"], check=True)
    dest = f"{args.ssh_user}@{args.host}:{REMOTE_UPDATES_DIR}/"
    subprocess.run(
        ["scp", "-P", str(args.ssh_port)] + [str(f) for f in files] + [dest],
        check=True,
    )
    print(f"Copied {len(files)} files to {dest}")
    print(f"Restarting {ADDON_SLUG} add-on ...")
    subprocess.run(ssh_base(args) + [f"ha addons restart {ADDON_SLUG}"], check=True)


async def ws_deploy(args, images: list[OtaImage]) -> int:
    import websockets

    by_product = {(img.vid, img.pid): img for img in images}
    url = f"ws://{args.host}:5580/ws"

    # The add-on was just restarted; wait for the WebSocket to come back.
    async def connect():
        deadline = asyncio.get_event_loop().time() + 120
        while True:
            try:
                ws = await websockets.connect(url, max_size=None, open_timeout=5)
                info = json.loads(await ws.recv())  # ServerInfoMessage
                return ws, info
            except OSError:
                if asyncio.get_event_loop().time() > deadline:
                    raise
                await asyncio.sleep(3)

    print(f"Connecting to {url} ...")
    ws, info = await connect()
    print(f"Connected (SDK {info.get('sdk_version')}, fabric {info.get('fabric_id')})")

    msg_id = 0

    async def command(cmd: str, cmd_args: dict | None = None, timeout: float = 60):
        nonlocal msg_id
        msg_id += 1
        mid = str(msg_id)
        await ws.send(json.dumps({"message_id": mid, "command": cmd, "args": cmd_args or {}}))
        deadline = asyncio.get_event_loop().time() + timeout
        while True:
            remaining = deadline - asyncio.get_event_loop().time()
            if remaining <= 0:
                raise TimeoutError(f"timed out waiting for result of '{cmd}'")
            msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=remaining))
            if msg.get("message_id") == mid:
                if "error_code" in msg:
                    raise RuntimeError(f"{cmd} failed: {msg.get('details')} "
                                       f"(error_code {msg['error_code']})")
                return msg.get("result")
            # Surface OTA requestor progress while we wait
            if msg.get("event") == "attribute_updated":
                node_id, path, value = msg["data"]
                if path.startswith(OTA_REQUESTOR_PREFIX) or path == ATTR_SOFTWARE_VERSION:
                    print(f"  node {node_id}: {path} = {value}")

    nodes = await command("start_listening", timeout=120)

    candidates = []
    for node in nodes:
        attrs = node.get("attributes", {})
        key = (attrs.get(ATTR_VENDOR_ID), attrs.get(ATTR_PRODUCT_ID))
        img = by_product.get(key)
        if img is None:
            continue
        current = attrs.get(ATTR_SOFTWARE_VERSION) or 0
        name = attrs.get(ATTR_NODE_LABEL) or attrs.get(ATTR_PRODUCT_NAME) or "?"
        nid = node["node_id"]
        if args.nodes and nid not in args.nodes:
            continue
        if current >= img.version:
            print(f"Node {nid} ({name}): already at {current} (0x{current:X}) -- skipping")
            continue
        if not node.get("available", True):
            print(f"Node {nid} ({name}): currently unavailable -- skipping")
            continue
        candidates.append((nid, name, current, img))

    if not candidates:
        print("No nodes need updating.")
        return 0

    failures = 0
    for nid, name, current, img in candidates:
        print(f"Updating node {nid} ({name}): {current} (0x{current:X}) -> "
              f"{img.version} (0x{img.version:X}) ... this can take a while")
        try:
            await command("update_node",
                          {"node_id": nid, "software_version": img.version},
                          timeout=args.timeout)
            print(f"Node {nid} ({name}): update finished")
        except (RuntimeError, TimeoutError) as exc:
            failures += 1
            print(f"Node {nid} ({name}): UPDATE FAILED: {exc}")

    await ws.close()
    return failures


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
    ap.add_argument("--no-install", action="store_true",
                    help="Stage and restart the add-on, but do not push updates to nodes")
    ap.add_argument("--prune", action="store_true",
                    help="Delete older staged versions for the same VID/PID on the HA host")
    ap.add_argument("--nodes", type=int, nargs="*", default=None,
                    help="Limit the update to these node ids")
    ap.add_argument("--timeout", type=float, default=3600,
                    help="Per-node update timeout in seconds (default: %(default)s)")
    args = ap.parse_args()

    images = [parse_ota_image(d) for d in args.build_dir]
    files = stage(images, args.stage_dir)
    if args.stage_only:
        print(f"\nStage-only: copy these to {REMOTE_UPDATES_DIR}/ on the HA host "
              f"and restart the {ADDON_SLUG} add-on.")
        return 0

    deploy_files(args, files, images)
    if args.no_install:
        print("Staged and restarted; skipping node updates (--no-install).")
        return 0

    return asyncio.run(ws_deploy(args, images))


if __name__ == "__main__":
    ensure_websockets()
    sys.exit(main())
