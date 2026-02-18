#!/usr/bin/env python3
"""Build, flash, and stream RTT output via Black Magic Probe."""

import argparse
import glob
import os
import platform
import signal
import subprocess
import sys
import time

DEFAULT_BOARD = "bl54l15u_devkit/nrf54l15/cpuapp"


def is_bmp_gdb_port(port, gdb="arm-zephyr-eabi-gdb"):
    """Test whether a serial port is the BMP GDB port by running 'monitor version'."""
    try:
        result = subprocess.run(
            [gdb, "-nx", "-batch",
             "-ex", f"target extended-remote {port}",
             "-ex", "monitor version"],
            capture_output=True, text=True, timeout=5,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def find_bmp_ports():
    """Auto-detect BMP GDB and RTT ports for Linux and macOS."""
    if platform.system() == "Darwin":
        # macOS: BMP shows up as /dev/cu.usbmodem* (must use cu., not tty.)
        ports = sorted(glob.glob("/dev/cu.usbmodem*"))
        if len(ports) >= 2:
            # Probe to find which is the GDB port
            for i, port in enumerate(ports):
                if is_bmp_gdb_port(port):
                    rtt = ports[1 - i] if len(ports) == 2 else ports[1 if i == 0 else 0]
                    return port, rtt
            # Fall back to sorted order if probing fails
            return ports[0], ports[1]
        elif len(ports) == 1:
            return ports[0], None
        return None, None
    else:
        # Linux: prefer udev symlinks, fall back to /dev/ttyACM*
        gdb = "/dev/ttyBmpGdb" if os.path.exists("/dev/ttyBmpGdb") else (
            "/dev/ttyACM0" if os.path.exists("/dev/ttyACM0") else None
        )
        rtt = "/dev/ttyBmpTarg" if os.path.exists("/dev/ttyBmpTarg") else (
            "/dev/ttyACM1" if os.path.exists("/dev/ttyACM1") else None
        )
        return gdb, rtt


def gdb_batch(gdb, commands):
    """Run arm-zephyr-eabi-gdb in batch mode with the given -ex commands."""
    args = [gdb, "-nx", "-batch"]
    for cmd in commands:
        args += ["-ex", cmd]
    subprocess.run(args, check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "board",
        nargs="?",
        default=DEFAULT_BOARD,
        help=f"Zephyr board target (default: {DEFAULT_BOARD})",
    )
    default_gdb, default_rtt = find_bmp_ports()
    parser.add_argument(
        "--gdb-port",
        default=default_gdb,
        help="BMP GDB serial port (default: auto-detect)",
    )
    parser.add_argument(
        "--rtt-port",
        default=default_rtt,
        help="BMP RTT serial port (default: auto-detect)",
    )
    parser.add_argument(
        "--skip-build",
        action="store_true",
        help="Skip the west build step",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Reset target after flashing so program starts from beginning",
    )
    args = parser.parse_args()

    if not args.gdb_port:
        if platform.system() == "Darwin":
            sys.exit("ERROR: No BMP GDB port found (tried /dev/cu.usbmodem*)")
        else:
            sys.exit("ERROR: No BMP GDB port found (tried /dev/ttyBmpGdb, /dev/ttyACM0)")
    if not args.rtt_port:
        if platform.system() == "Darwin":
            sys.exit("ERROR: No BMP RTT port found (tried /dev/cu.usbmodem*)")
        else:
            sys.exit("ERROR: No BMP RTT port found (tried /dev/ttyBmpTarg, /dev/ttyACM1)")

    gdb = "arm-zephyr-eabi-gdb"
    elf = "build/zephyr/zephyr.elf"

    print(f"Board:    {args.board}")
    print(f"GDB port: {args.gdb_port}")
    print(f"RTT port: {args.rtt_port}")

    # Build
    if not args.skip_build:
        subprocess.run(
            ["west", "build", "-b", args.board, "--no-sysbuild", "--pristine"], check=True
        )

    # Flash via access port (target 2) — works even when core is in deep sleep
    print("Flashing via access port...")
    gdb_batch(gdb, [
        f"file {elf}",
        f"target extended-remote {args.gdb_port}",
        "monitor connect_rst enable",
        "monitor swdp_scan",
        "attach 2",
        "load",
        "detach",
    ])

    # Attach target 1, enable RTT, optionally reset, then continue.
    # RTT must be enabled before reset so BMP captures boot output.
    # Open the RTT port before launching GDB so the kernel buffers
    # any data that arrives before we start reading.
    print("Attaching for RTT...")
    rtt_cmds = [
        f"file {elf}",
        f"target extended-remote {args.gdb_port}",
        "monitor swdp_scan",
        "monitor connect_rst enable",
        "attach 1",
        "monitor rtt enable",
    ]
    if args.reset:
        rtt_cmds.append("monitor reset")
    rtt_cmds.append("continue")

    rtt_fd = os.open(args.rtt_port, os.O_RDONLY)

    gdb_proc = None
    max_attempts = 5
    for attempt in range(1, max_attempts + 1):
        gdb_args = [gdb, "-nx", "-batch"]
        for cmd in rtt_cmds:
            gdb_args += ["-ex", cmd]
        gdb_proc = subprocess.Popen(gdb_args)
        time.sleep(0.3)
        if gdb_proc.poll() is None:
            # Still running = attach + continue succeeded
            break
        if attempt == max_attempts:
            os.close(rtt_fd)
            sys.exit(f"ERROR: Failed to attach for RTT after {max_attempts} attempts")
        print(f"Retrying attach ({attempt}/{max_attempts})...")

    # Stream RTT output, clean up GDB on exit
    print("Streaming RTT output (Ctrl-C to stop)...")
    try:
        while True:
            data = os.read(rtt_fd, 256)
            if data:
                sys.stdout.buffer.write(data)
                sys.stdout.buffer.flush()
    except KeyboardInterrupt:
        pass
    finally:
        os.close(rtt_fd)
        if gdb_proc and gdb_proc.poll() is None:
            gdb_proc.terminate()
            gdb_proc.wait()


if __name__ == "__main__":
    main()
