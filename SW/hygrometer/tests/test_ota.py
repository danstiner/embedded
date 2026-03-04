"""OTA DFU cycle test (requires J-Link + BLE)."""

from __future__ import annotations

import asyncio
import pathlib
import subprocess
import tempfile
import time

import pytest

BOOT_BANNER = "=== Hygrometer ==="
BOOT_TIMEOUT_S = 10
BLE_SCAN_TIMEOUT_S = 10
BTHOME_UUID = "0000fcd2-0000-1000-8000-00805f9b34fb"
JLINK_DEVICE = "NRF54L15_XXAA"


def _ble_find_device(device_name: str, timeout: float = BLE_SCAN_TIMEOUT_S) -> str:
    """Scan BLE and return the address of the device, or raise."""
    from bleak import BleakScanner

    result_addr: str | None = None

    async def scan() -> None:
        nonlocal result_addr
        devices = await BleakScanner.discover(
            timeout=timeout,
            return_adv=True,
        )
        for addr, (device, adv) in devices.items():
            if device.name and device_name in device.name:
                if BTHOME_UUID in adv.service_data:
                    result_addr = addr
                    return

    asyncio.run(scan())
    assert result_addr is not None, (
        f"Device '{device_name}' not found via BLE within {timeout}s"
    )
    return result_addr


def _check_rtt_banner(
    jlink_serial: str | None, timeout: float = BOOT_TIMEOUT_S
) -> None:
    """Start RTT logger and assert boot banner appears."""
    with tempfile.NamedTemporaryFile(
        mode="r", suffix=".log", delete=False
    ) as logfile:
        logpath = logfile.name

    rtt_cmd = [
        "JLinkRTTLogger",
        "-Device", JLINK_DEVICE,
        "-Speed", "4000",
        "-If", "SWD",
        "-RTTChannel", "0",
        logpath,
    ]
    if jlink_serial:
        rtt_cmd += ["-SelectEmuBySN", jlink_serial]

    proc = subprocess.Popen(
        rtt_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    try:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            time.sleep(0.25)
            content = pathlib.Path(logpath).read_text(errors="replace")
            if BOOT_BANNER in content:
                return
        pytest.fail(
            f"Boot banner not found within {timeout}s. RTT log:\n"
            + pathlib.Path(logpath).read_text(errors="replace")
        )
    finally:
        proc.terminate()
        proc.wait(timeout=5)


@pytest.mark.ota
class TestOTA:
    def test_ota_dfu_and_reboot(
        self,
        flash,
        dfu_zip: pathlib.Path,
        device_name: str,
        jlink_serial: str | None,
    ) -> None:
        """Upload DFU image over BLE SMP and verify the device reboots."""
        # 1. Find device via BLE
        addr = _ble_find_device(device_name)

        # 2. Upload DFU image via mcumgr
        upload_cmd = [
            "mcumgr",
            "--conntype", "ble",
            "--connstring", f"peer_name={device_name}",
            "image", "upload", str(dfu_zip),
        ]
        result = subprocess.run(
            upload_cmd, capture_output=True, text=True, timeout=120
        )
        assert result.returncode == 0, (
            f"mcumgr image upload failed:\n{result.stdout}\n{result.stderr}"
        )

        # 3. Reset device
        reset_cmd = [
            "mcumgr",
            "--conntype", "ble",
            "--connstring", f"peer_name={device_name}",
            "reset",
        ]
        subprocess.run(reset_cmd, capture_output=True, text=True, timeout=30)

        # 4. Wait for reboot
        time.sleep(5)

        # 5. Verify device re-appears over BLE
        _ble_find_device(device_name, timeout=BLE_SCAN_TIMEOUT_S)

        # 6. Verify boot banner on RTT
        _check_rtt_banner(jlink_serial)
