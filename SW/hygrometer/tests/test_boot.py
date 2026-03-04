"""Flash + boot verification tests (requires J-Link attached)."""

from __future__ import annotations

import asyncio
import pathlib
import subprocess
import tempfile
import time

import pytest

BOOT_BANNER = "=== Hygrometer ==="
BOOT_TIMEOUT_S = 5
BLE_SCAN_TIMEOUT_S = 10
BTHOME_UUID = "0000fcd2-0000-1000-8000-00805f9b34fb"

# nRF54L15 device name used by JLinkRTTLogger
JLINK_DEVICE = "NRF54L15_XXAA"


@pytest.mark.boot
class TestBoot:
    def test_flash_and_boot_banner(
        self, flash, jlink_serial: str | None
    ) -> None:
        """Flash merged.hex and verify the boot banner appears on RTT."""
        with tempfile.NamedTemporaryFile(
            mode="r", suffix=".log", delete=False
        ) as logfile:
            logpath = logfile.name

        # Start JLinkRTTLogger: device, speed, channel, output file
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
            rtt_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        try:
            deadline = time.monotonic() + BOOT_TIMEOUT_S
            found = False
            while time.monotonic() < deadline:
                time.sleep(0.25)
                content = pathlib.Path(logpath).read_text(errors="replace")
                if BOOT_BANNER in content:
                    found = True
                    break

            assert found, (
                f"Boot banner '{BOOT_BANNER}' not found within "
                f"{BOOT_TIMEOUT_S}s. RTT log:\n"
                + pathlib.Path(logpath).read_text(errors="replace")
            )
        finally:
            proc.terminate()
            proc.wait(timeout=5)

    def test_ble_advertising(self, flash, device_name: str) -> None:
        """Verify the device advertises BTHome service data over BLE."""
        from bleak import BleakScanner

        found_device = None

        async def scan() -> None:
            nonlocal found_device
            devices = await BleakScanner.discover(
                timeout=BLE_SCAN_TIMEOUT_S,
                return_adv=True,
            )
            for _addr, (device, adv) in devices.items():
                if device.name and device_name in device.name:
                    # Check for BTHome UUID in service data
                    if BTHOME_UUID in adv.service_data:
                        sd = adv.service_data[BTHOME_UUID]
                        assert len(sd) >= 3, (
                            f"BTHome service data too short ({len(sd)} bytes): "
                            f"{sd.hex()}"
                        )
                        found_device = device
                        return

        asyncio.run(scan())
        assert found_device is not None, (
            f"No BLE device '{device_name}' advertising BTHome UUID "
            f"({BTHOME_UUID}) found within {BLE_SCAN_TIMEOUT_S}s"
        )
