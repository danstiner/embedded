#!/usr/bin/env python3
# /// script
# requires-python = ">=3.8"
# dependencies = [
#   "pyftdi",
# ]
# ///
"""
Adafruit STEMMA Soil Sensor I2C Control Script via FT232H
Uses the seesaw protocol directly over PyFTDI (no CircuitPython/Blinka).
Reads capacitive moisture (uint16) and chip temperature (float, degC).
"""

from pyftdi.i2c import I2cController
import time
import argparse
import sys
import math


class AdafruitSoil:
    """Adafruit STEMMA Soil Sensor Driver (Seesaw protocol)"""

    # Default I2C address (configurable 0x36-0x39 via AD0/AD1 jumpers)
    ADDR = 0x36

    # Seesaw register map: (base, function)
    REG_HW_ID = (0x00, 0x01)          # 1 byte, expect 0x55
    REG_VERSION = (0x00, 0x02)         # 4 bytes, uint32
    REG_TEMPERATURE = (0x00, 0x04)     # 4 bytes, see conversion below
    REG_RESET = (0x00, 0x7F)           # write 0xFF to reset
    REG_MOISTURE = (0x0F, 0x10)        # 2 bytes, uint16 (valid <= 4095)

    HW_ID_EXPECTED = 0x55

    def __init__(self, i2c_url='ftdi://ftdi:232h/1', i2c_addr=None, frequency=100000):
        """Initialize Adafruit Soil Sensor with FT232H I2C bridge"""
        self.i2c = I2cController()
        self.i2c.configure(i2c_url, frequency=frequency)
        addr = i2c_addr if i2c_addr is not None else self.ADDR
        self.slave = self.i2c.get_port(addr)
        self.frequency = frequency

    def seesaw_read(self, base, func, num_bytes, delay=0.008):
        """Write [base, func] register address, wait, then read response"""
        self.slave.write([base, func])
        time.sleep(delay)
        return self.slave.read(num_bytes)

    def seesaw_write(self, base, func, data=None):
        """Write [base, func, *data] to device"""
        payload = [base, func]
        if data is not None:
            payload.extend(data)
        self.slave.write(payload)

    def read_hw_id(self):
        """Read hardware ID (should be 0x55)"""
        data = self.seesaw_read(*self.REG_HW_ID, 1)
        return data[0]

    def read_version(self):
        """Read firmware version as uint32"""
        data = self.seesaw_read(*self.REG_VERSION, 4)
        return (data[0] << 24) | (data[1] << 16) | (data[2] << 8) | data[3]

    def read_temperature(self):
        """Read chip temperature in degrees C"""
        data = self.seesaw_read(*self.REG_TEMPERATURE, 4)
        raw = (data[0] << 24) | (data[1] << 16) | (data[2] << 8) | data[3]
        # Mask top 2 bits (status/sign), remaining is fixed-point 1/65536
        raw &= 0x3FFFFFFF
        return raw / 65536.0

    def moisture_read(self):
        """Read capacitive moisture value (uint16), with retry for out-of-range"""
        for attempt in range(3):
            data = self.seesaw_read(*self.REG_MOISTURE, 2, delay=0.005)
            value = (data[0] << 8) | data[1]
            if value <= 4095:
                return value
            time.sleep(0.01)
        # Return last value even if still out of range
        return value

    def soft_reset(self):
        """Perform software reset via seesaw"""
        self.seesaw_write(*self.REG_RESET, data=[0xFF])
        time.sleep(0.5)


def init_device(args):
    """Initialize and verify Adafruit Soil Sensor"""
    freq = args.frequency if hasattr(args, 'frequency') else 100000

    try:
        sensor = AdafruitSoil(i2c_addr=args.addr, frequency=freq)
        print(f"Connected to FT232H at {freq/1000:.0f}kHz")
    except Exception as e:
        print(f"Error connecting to FT232H: {e}")
        print("\nMake sure:")
        print("  1. FT232H is connected via USB")
        print("  2. STEMMA Soil Sensor is wired: SDA, SCL, VCC (3.3V), GND")
        return None

    try:
        hw_id = sensor.read_hw_id()
        if hw_id != AdafruitSoil.HW_ID_EXPECTED:
            print(f"Warning: unexpected HW ID 0x{hw_id:02X} (expected 0x{AdafruitSoil.HW_ID_EXPECTED:02X})")
        else:
            print(f"HW ID: 0x{hw_id:02X} (OK)")
    except Exception as e:
        print(f"Failed to read HW ID: {e}")
        return None

    return sensor


def compute_stats(samples):
    """Compute mean, std, min, max for a list of numeric values"""
    n = len(samples)
    if n == 0:
        return None
    mean = sum(samples) / n
    if n > 1:
        variance = sum((x - mean) ** 2 for x in samples) / (n - 1)
        std = math.sqrt(variance)
    else:
        std = 0.0
    return {
        'mean': mean,
        'std': std,
        'min': min(samples),
        'max': max(samples),
    }


def cmd_scan(args):
    """Scan I2C bus for devices"""
    i2c = I2cController()
    freq = args.frequency if hasattr(args, 'frequency') else 100000
    i2c.configure('ftdi://ftdi:232h/1', frequency=freq)

    print(f"Scanning I2C bus at {freq/1000:.0f}kHz...")
    print("     0  1  2  3  4  5  6  7  8  9  A  B  C  D  E  F")

    found = []
    for row in range(8):
        print(f"{row*16:02X}: ", end="")
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
            except:
                print("-- ", end="")
        print()

    if found:
        print(f"\nFound {len(found)} device(s): {', '.join(f'0x{a:02X}' for a in found)}")
        for addr in found:
            if 0x36 <= addr <= 0x39:
                print(f"  0x{addr:02X} = Adafruit STEMMA Soil Sensor (seesaw)")
            elif addr == 0x44:
                print(f"  0x{addr:02X} = SHT45 (default address)")
    else:
        print("\nNo devices found - check wiring and power")

    return 0


def cmd_info(args):
    """Display device information with a single reading"""
    sensor = init_device(args)
    if not sensor:
        return 1

    try:
        version = sensor.read_version()
        print(f"Firmware version: 0x{version:08X} ({version})")
    except Exception as e:
        print(f"Failed to read version: {e}")
        return 1

    try:
        temp_c = sensor.read_temperature()
        moisture = sensor.moisture_read()
        print(f"Temperature: {temp_c:.2f} C")
        print(f"Moisture: {moisture}")
    except Exception as e:
        print(f"Failed to read sensor: {e}")
        return 1

    return 0


def cmd_reset(args):
    """Reset the soil sensor"""
    sensor = init_device(args)
    if not sensor:
        return 1

    print("Resetting soil sensor...")
    try:
        sensor.soft_reset()
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
    ftdi.open_from_url(url='ftdi://ftdi:232h:1/1')
    ftdi.reset(usb_reset=True)
    ftdi.close()
    print("Done")
    return 0


def cmd_read(args):
    """Read temperature and moisture with running statistics"""
    sensor = init_device(args)
    if not sensor:
        return 1

    # Welford's online algorithm state
    t_mean = 0.0
    t_m2 = 0.0
    m_mean = 0.0
    m_m2 = 0.0
    count = 0

    header = (f"{'Sample':>6} | {'Temp (C)':>10} | {'Moisture':>10} | "
              f"{'Avg Temp':>10} | {'Std Temp':>10} | "
              f"{'Avg Moist':>10} | {'Std Moist':>10}")
    sep = "-" * len(header)

    def print_row(idx, temp_c, moisture):
        nonlocal t_mean, t_m2, m_mean, m_m2, count
        count += 1

        # Update running stats (Welford's algorithm)
        t_delta = temp_c - t_mean
        t_mean += t_delta / count
        t_delta2 = temp_c - t_mean
        t_m2 += t_delta * t_delta2

        m_delta = moisture - m_mean
        m_mean += m_delta / count
        m_delta2 = moisture - m_mean
        m_m2 += m_delta * m_delta2

        t_std = math.sqrt(t_m2 / (count - 1)) if count > 1 else 0.0
        m_std = math.sqrt(m_m2 / (count - 1)) if count > 1 else 0.0

        print(f"{idx:6d} | {temp_c:10.2f} | {moisture:10d} | "
              f"{t_mean:10.2f} | {t_std:10.3f} | "
              f"{m_mean:10.1f} | {m_std:10.1f}")

    try:
        if args.samples == 0:
            print(f"Reading continuously (Ctrl+C to stop):")
            print(header)
            print(sep)
            sample = 0
            while True:
                temp_c = sensor.read_temperature()
                moisture = sensor.moisture_read()
                print_row(sample, temp_c, moisture)
                sample += 1
                time.sleep(args.delay)
        else:
            print(f"Reading {args.samples} samples:")
            print(header)
            print(sep)
            for i in range(args.samples):
                temp_c = sensor.read_temperature()
                moisture = sensor.moisture_read()
                print_row(i, temp_c, moisture)
                time.sleep(args.delay)

    except KeyboardInterrupt:
        print("\n\nStopped")
    except Exception as e:
        print(f"Read failed: {e}")
        return 1

    return 0


def cmd_monitor(args):
    """Continuous monitoring with statistics"""
    sensor = init_device(args)
    if not sensor:
        return 1

    temp_samples = []
    moisture_samples = []

    print(f"Monitoring (Ctrl+C to stop, stats every {args.interval} samples):")
    print(f"{'Sample':>6} | {'Temp (C)':>10} | {'Moisture':>10}")
    print("-" * 35)

    try:
        sample = 0
        while True:
            temp_c = sensor.read_temperature()
            moisture = sensor.moisture_read()
            temp_samples.append(temp_c)
            moisture_samples.append(moisture)
            print(f"{sample:6d} | {temp_c:10.2f} | {moisture:10d}")
            sample += 1

            if sample % args.interval == 0:
                ts = compute_stats(temp_samples)
                ms = compute_stats(moisture_samples)
                print(f"\n--- Statistics ({len(temp_samples)} samples) ---")
                print(f"  Temp (C):  mean={ts['mean']:.2f}  std={ts['std']:.2f}  min={ts['min']:.2f}  max={ts['max']:.2f}")
                print(f"  Moisture:  mean={ms['mean']:.1f}  std={ms['std']:.1f}  min={ms['min']}  max={ms['max']}")
                print()

            time.sleep(args.delay)

    except KeyboardInterrupt:
        if temp_samples:
            ts = compute_stats(temp_samples)
            ms = compute_stats(moisture_samples)
            print(f"\n\n--- Final Statistics ({len(temp_samples)} samples) ---")
            print(f"  Temp (C):  mean={ts['mean']:.2f}  std={ts['std']:.2f}  min={ts['min']:.2f}  max={ts['max']:.2f}")
            print(f"  Moisture:  mean={ms['mean']:.1f}  std={ms['std']:.1f}  min={ms['min']}  max={ms['max']}")
        print("\nStopped")

    return 0


def main():
    """Main CLI entry point"""
    parser = argparse.ArgumentParser(
        description='Adafruit STEMMA Soil Sensor via FT232H (seesaw protocol)',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s scan                          # Scan I2C bus for devices
  %(prog)s info                          # Show HW ID, version, temp, moisture
  %(prog)s reset                         # Reset soil sensor
  %(prog)s reset-ftdi                    # Reset FT232H USB adapter
  %(prog)s read                          # Read 10 samples
  %(prog)s read -n 0                     # Read continuously
  %(prog)s read -n 5 -d 0.5             # 5 samples, 0.5s delay
  %(prog)s monitor                       # Continuous monitoring with stats
        """
    )

    parser.add_argument('-a', '--addr', type=lambda x: int(x, 0), default=0x36,
                       help='I2C address (default: 0x36)')
    parser.add_argument('-f', '--frequency', type=int, default=100000,
                       help='I2C frequency in Hz (default: 100000)')

    subparsers = parser.add_subparsers(dest='command', help='Command to execute')

    # Scan command
    subparsers.add_parser('scan', help='Scan I2C bus for devices')

    # Info command
    subparsers.add_parser('info', help='Show HW ID, firmware version, temp, moisture')

    # Reset command
    subparsers.add_parser('reset', help='Soft reset the soil sensor')

    # Reset FTDI command
    subparsers.add_parser('reset-ftdi', help='Reset the FT232H USB adapter')

    # Read command
    parser_read = subparsers.add_parser('read', help='Read temperature and moisture')
    parser_read.add_argument('-n', '--samples', type=int, default=10,
                            help='Number of samples (0 = continuous, default: 10)')
    parser_read.add_argument('-d', '--delay', type=float, default=1.0,
                            help='Delay between samples in seconds (default: 1.0)')

    # Monitor command
    parser_monitor = subparsers.add_parser('monitor', help='Continuous monitoring with statistics')
    parser_monitor.add_argument('-d', '--delay', type=float, default=1.0,
                               help='Delay between samples in seconds (default: 1.0)')
    parser_monitor.add_argument('-i', '--interval', type=int, default=10,
                               help='Print stats every N samples (default: 10)')

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 1

    commands = {
        'scan': cmd_scan,
        'info': cmd_info,
        'reset': cmd_reset,
        'reset-ftdi': cmd_reset_ftdi,
        'read': cmd_read,
        'monitor': cmd_monitor,
    }

    return commands[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
