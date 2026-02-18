#!/usr/bin/env python3
# /// script
# requires-python = ">=3.8"
# dependencies = [
#   "pyftdi",
# ]
# ///
"""
SHT45 Temperature/Humidity Sensor I2C Helper Script via FT232H
For testing I2C communication with known-good Adafruit breakout
"""

import argparse
import sys
import time

from pyftdi.i2c import I2cController


class SHT45:
    """SHT45 Temperature and Humidity Sensor Driver"""

    # Default I2C address
    ADDR = 0x44

    # Measurement commands (no clock stretching)
    CMD_MEASURE_HIGH_PRECISION = 0xFD  # ~8.2ms
    CMD_MEASURE_MEDIUM_PRECISION = 0xF6  # ~4.5ms
    CMD_MEASURE_LOW_PRECISION = 0xE0  # ~1.6ms

    # Heated measurement commands (for clearing condensation)
    CMD_HEAT_200MW_1S = 0x39  # 200mW heater, 1s, high precision
    CMD_HEAT_200MW_100MS = 0x32
    CMD_HEAT_110MW_1S = 0x2F
    CMD_HEAT_110MW_100MS = 0x24
    CMD_HEAT_20MW_1S = 0x1E
    CMD_HEAT_20MW_100MS = 0x15

    # Other commands
    CMD_READ_SERIAL = 0x89
    CMD_SOFT_RESET = 0x94

    # Measurement timing (ms)
    TIMING = {
        CMD_MEASURE_HIGH_PRECISION: 10,
        CMD_MEASURE_MEDIUM_PRECISION: 5,
        CMD_MEASURE_LOW_PRECISION: 2,
        CMD_HEAT_200MW_1S: 1100,
        CMD_HEAT_200MW_100MS: 110,
        CMD_HEAT_110MW_1S: 1100,
        CMD_HEAT_110MW_100MS: 110,
        CMD_HEAT_20MW_1S: 1100,
        CMD_HEAT_20MW_100MS: 110,
    }

    def __init__(self, i2c_url="ftdi://ftdi:232h/1", i2c_addr=None, frequency=100000):
        """Initialize SHT45 with FT232H I2C bridge"""
        self.i2c = I2cController()
        self.i2c.configure(i2c_url, frequency=frequency)
        addr = i2c_addr if i2c_addr is not None else self.ADDR
        self.slave = self.i2c.get_port(addr)
        self.frequency = frequency

    def _crc8(self, data):
        """Calculate CRC-8 checksum (polynomial 0x31, init 0xFF)"""
        crc = 0xFF
        for byte in data:
            crc ^= byte
            for _ in range(8):
                if crc & 0x80:
                    crc = (crc << 1) ^ 0x31
                else:
                    crc = crc << 1
                crc &= 0xFF
        return crc

    def _check_crc(self, data, expected_crc):
        """Verify CRC of received data"""
        calculated = self._crc8(data)
        if calculated != expected_crc:
            raise ValueError(f"CRC mismatch: expected 0x{expected_crc:02X}, got 0x{calculated:02X}")
        return True

    def soft_reset(self):
        """Perform soft reset"""
        self.slave.write([self.CMD_SOFT_RESET])
        time.sleep(0.001)  # 1ms max reset time

    def read_serial(self):
        """Read serial number"""
        self.slave.write([self.CMD_READ_SERIAL])
        time.sleep(0.001)

        data = self.slave.read(6)

        # Verify CRCs
        self._check_crc(data[0:2], data[2])
        self._check_crc(data[3:5], data[5])

        serial = (data[0] << 24) | (data[1] << 16) | (data[3] << 8) | data[4]
        return serial

    def measure(self, precision="high"):
        """
        Perform temperature and humidity measurement

        Args:
            precision: 'high', 'medium', or 'low'

        Returns:
            tuple: (temperature_c, humidity_percent)
        """
        cmd_map = {
            "high": self.CMD_MEASURE_HIGH_PRECISION,
            "medium": self.CMD_MEASURE_MEDIUM_PRECISION,
            "low": self.CMD_MEASURE_LOW_PRECISION,
        }

        if precision not in cmd_map:
            raise ValueError("precision must be 'high', 'medium', or 'low'")

        cmd = cmd_map[precision]
        wait_ms = self.TIMING[cmd]

        # Send measurement command
        self.slave.write([cmd])

        # Wait for conversion
        time.sleep(wait_ms / 1000.0)

        # Read 6 bytes: temp_msb, temp_lsb, temp_crc, hum_msb, hum_lsb, hum_crc
        data = self.slave.read(6)

        # Verify CRCs
        self._check_crc(data[0:2], data[2])
        self._check_crc(data[3:5], data[5])

        # Convert raw values
        temp_raw = (data[0] << 8) | data[1]
        hum_raw = (data[3] << 8) | data[4]

        # Apply conversion formulas from datasheet
        temperature_c = -45.0 + 175.0 * (temp_raw / 65535.0)
        humidity_pct = -6.0 + 125.0 * (hum_raw / 65535.0)

        # Clamp humidity to valid range
        humidity_pct = max(0.0, min(100.0, humidity_pct))

        return temperature_c, humidity_pct

    def measure_with_heat(self, power="20mw", duration="100ms"):
        """
        Perform heated measurement (useful for clearing condensation)

        Args:
            power: '200mw', '110mw', or '20mw'
            duration: '1s' or '100ms'

        Returns:
            tuple: (temperature_c, humidity_percent)
        """
        cmd_map = {
            ("200mw", "1s"): self.CMD_HEAT_200MW_1S,
            ("200mw", "100ms"): self.CMD_HEAT_200MW_100MS,
            ("110mw", "1s"): self.CMD_HEAT_110MW_1S,
            ("110mw", "100ms"): self.CMD_HEAT_110MW_100MS,
            ("20mw", "1s"): self.CMD_HEAT_20MW_1S,
            ("20mw", "100ms"): self.CMD_HEAT_20MW_100MS,
        }

        key = (power.lower(), duration.lower())
        if key not in cmd_map:
            raise ValueError(f"Invalid power/duration: {power}/{duration}")

        cmd = cmd_map[key]
        wait_ms = self.TIMING[cmd]

        self.slave.write([cmd])
        time.sleep(wait_ms / 1000.0)

        data = self.slave.read(6)

        self._check_crc(data[0:2], data[2])
        self._check_crc(data[3:5], data[5])

        temp_raw = (data[0] << 8) | data[1]
        hum_raw = (data[3] << 8) | data[4]

        temperature_c = -45.0 + 175.0 * (temp_raw / 65535.0)
        humidity_pct = -6.0 + 125.0 * (hum_raw / 65535.0)
        humidity_pct = max(0.0, min(100.0, humidity_pct))

        return temperature_c, humidity_pct


def init_device(args):
    """Initialize and verify SHT45 device"""
    freq = args.frequency if hasattr(args, "frequency") else 100000

    try:
        sht = SHT45(i2c_addr=args.addr, frequency=freq)
        print(f"✓ Connected to FT232H at {freq / 1000:.0f}kHz")
    except Exception as e:
        print(f"✗ Error connecting to FT232H: {e}")
        print("\nMake sure:")
        print("  1. FT232H is connected via USB")
        print("  2. SHT45 breakout is wired: SDA, SCL, VCC (3.3V), GND")
        print("  3. Adafruit breakout has onboard pullups, no external needed")
        return None

    return sht


def cmd_info(args):
    """Display device information"""
    sht = init_device(args)
    if not sht:
        return 1

    try:
        serial = sht.read_serial()
        print(f"✓ Serial number: 0x{serial:08X} ({serial})")
    except Exception as e:
        print(f"✗ Failed to read serial: {e}")
        return 1

    return 0


def cmd_reset(args):
    """Reset the SHT4x device"""
    sht = init_device(args)
    if not sht:
        return 1

    print("Resetting SHT4x device...")
    try:
        sht.soft_reset()
        print("Reset complete")
    except Exception as e:
        print(f"Reset failed: {e}")
        return 1

    return 0


def cmd_reset_ftdi(args):
    """Reset the FT232H USB adapter"""
    from pyftdi.ftdi import Ftdi

    print("Resetting FT232H USB adapter...")
    ftdi = Ftdi()
    ftdi.open_from_url(url="ftdi://ftdi:232h:1/1")
    ftdi.reset(usb_reset=True)
    ftdi.close()
    print("Done")
    return 0


def cmd_read(args):
    """Read temperature and humidity"""
    sht = init_device(args)
    if not sht:
        return 1

    try:
        if args.samples == 0:
            # Continuous mode
            print(f"Reading continuously at {args.precision} precision (Ctrl+C to stop):")
            print(f"{'Sample':>6} | {'Temp (°C)':>10} | {'Temp (°F)':>10} | {'Humidity':>10}")
            print("-" * 50)
            sample = 0
            while True:
                temp_c, humidity = sht.measure(precision=args.precision)
                temp_f = temp_c * 9 / 5 + 32
                print(f"{sample:6d} | {temp_c:10.2f} | {temp_f:10.2f} | {humidity:9.1f}%")
                sample += 1
                time.sleep(args.delay)
        else:
            print(f"Reading {args.samples} samples at {args.precision} precision:")
            print(f"{'Sample':>6} | {'Temp (°C)':>10} | {'Temp (°F)':>10} | {'Humidity':>10}")
            print("-" * 50)
            for i in range(args.samples):
                temp_c, humidity = sht.measure(precision=args.precision)
                temp_f = temp_c * 9 / 5 + 32
                print(f"{i:6d} | {temp_c:10.2f} | {temp_f:10.2f} | {humidity:9.1f}%")
                time.sleep(args.delay)

    except KeyboardInterrupt:
        print("\n\n✓ Stopped")
    except Exception as e:
        print(f"✗ Read failed: {e}")
        return 1

    return 0


def cmd_scan(args):
    """Scan I2C bus for devices"""
    i2c = I2cController()
    freq = args.frequency if hasattr(args, "frequency") else 100000
    i2c.configure("ftdi://ftdi:232h/1", frequency=freq)

    print(f"Scanning I2C bus at {freq / 1000:.0f}kHz...")
    print("     0  1  2  3  4  5  6  7  8  9  A  B  C  D  E  F")

    found = []
    for row in range(8):
        print(f"{row * 16:02X}: ", end="")
        for col in range(16):
            addr = row * 16 + col
            if addr < 0x08 or addr > 0x77:
                print("   ", end="")
                continue

            try:
                port = i2c.get_port(addr)
                port.read(1)
                print(f"{addr:02X} ", end="")
                found.append(addr)
            except Exception:
                print("-- ", end="")
        print()

    if found:
        print(f"\n✓ Found {len(found)} device(s): {', '.join(f'0x{a:02X}' for a in found)}")
        if 0x44 in found:
            print("  0x44 = SHT45 (default address)")
        if 0x45 in found:
            print("  0x45 = SHT45 (alternate address)")
    else:
        print("\n✗ No devices found - check wiring and power")

    return 0


def cmd_list(args):
    """List FTDI devices"""
    from pyftdi.ftdi import Ftdi

    Ftdi.show_devices()
    return 0


def main():
    """Main CLI entry point"""
    parser = argparse.ArgumentParser(
        description="SHT45 Temperature/Humidity Sensor via FT232H",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s scan                          # Scan I2C bus for devices
  %(prog)s info                          # Show device serial number
  %(prog)s reset                         # Reset SHT4x device
  %(prog)s reset-ftdi                    # Reset FT232H USB adapter
  %(prog)s read                          # Read 10 samples
  %(prog)s read -n 0                     # Read continuously
  %(prog)s read -p low -d 0.5            # Low precision, 0.5s delay
  %(prog)s read -f 10000                 # Use 10kHz I2C speed
        """,
    )

    parser.add_argument(
        "-a", "--addr", type=lambda x: int(x, 0), default=0x44, help="I2C address (default: 0x44)"
    )
    parser.add_argument(
        "-f", "--frequency", type=int, default=10000, help="I2C frequency in Hz (default: 10000)"
    )

    subparsers = parser.add_subparsers(dest="command", help="Command to execute")

    # Scan command
    subparsers.add_parser("scan", help="Scan I2C bus for devices")

    # Info command
    subparsers.add_parser("info", help="Display device serial number")

    # Reset command (SHT4x device)
    subparsers.add_parser("reset", help="Soft reset the SHT4x device")

    # Reset FTDI command (FT232H USB adapter)
    subparsers.add_parser("reset-ftdi", help="Reset the FT232H USB adapter")

    # Read command
    parser_read = subparsers.add_parser("read", help="Read temperature and humidity")
    parser_read.add_argument(
        "-n",
        "--samples",
        type=int,
        default=10,
        help="Number of samples (0 = continuous, default: 10)",
    )
    parser_read.add_argument(
        "-d",
        "--delay",
        type=float,
        default=1.0,
        help="Delay between samples in seconds (default: 1.0)",
    )
    parser_read.add_argument(
        "-p",
        "--precision",
        choices=["high", "medium", "low"],
        default="high",
        help="Measurement precision (default: high)",
    )

    # List command
    subparsers.add_parser("list", help="List FT232H controllers")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 1

    commands = {
        "scan": cmd_scan,
        "info": cmd_info,
        "reset": cmd_reset,
        "reset-ftdi": cmd_reset_ftdi,
        "read": cmd_read,
        "list": cmd_list,
    }

    return commands[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
