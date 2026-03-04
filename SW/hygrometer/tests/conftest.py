"""Fixtures and CLI options for hardware smoke tests."""

from __future__ import annotations

import pathlib
import subprocess

import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--build-dir",
        default="build",
        help="Path to the build directory containing merged.hex and dfu_application.zip",
    )
    parser.addoption(
        "--serial-number",
        default=None,
        help="J-Link serial number (auto-detected when only one device is connected)",
    )
    parser.addoption(
        "--device-name",
        default="Hygrometer",
        help="BLE device name to scan for (default: Hygrometer)",
    )


@pytest.fixture(scope="session")
def build_dir(request: pytest.FixtureRequest) -> pathlib.Path:
    path = pathlib.Path(request.config.getoption("--build-dir")).resolve()
    assert path.is_dir(), f"Build directory does not exist: {path}"
    return path


@pytest.fixture(scope="session")
def merged_hex(build_dir: pathlib.Path) -> pathlib.Path:
    path = build_dir / "merged.hex"
    assert path.is_file(), f"merged.hex not found in {build_dir}"
    return path


@pytest.fixture(scope="session")
def dfu_zip(build_dir: pathlib.Path) -> pathlib.Path:
    path = build_dir / "dfu_application.zip"
    assert path.is_file(), f"dfu_application.zip not found in {build_dir}"
    return path


@pytest.fixture(scope="session")
def jlink_serial(request: pytest.FixtureRequest) -> str | None:
    """Return J-Link serial number, or None for auto-detect."""
    return request.config.getoption("--serial-number")


@pytest.fixture(scope="session")
def device_name(request: pytest.FixtureRequest) -> str:
    return request.config.getoption("--device-name")


# ---------------------------------------------------------------------------
# Helpers exposed as fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def flash(merged_hex: pathlib.Path, jlink_serial: str | None):
    """Flash merged.hex once per session. Yields after successful flash."""
    cmd = [
        "nrfutil", "device", "program",
        "--firmware", str(merged_hex),
        "--options", "chip_erase_mode=ERASE_ALL",
    ]
    if jlink_serial:
        cmd += ["--serial-number", jlink_serial]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, (
        f"nrfutil device program failed:\n{result.stdout}\n{result.stderr}"
    )
    yield
