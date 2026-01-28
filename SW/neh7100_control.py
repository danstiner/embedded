#!/usr/bin/env python3
# /// script
# requires-python = ">=3.8"
# dependencies = [
#   "pyftdi",
# ]
# ///
"""
NEH7100 Solar Energy Harvesting PMIC I2C Control Script via FT232H
For configuring and monitoring the Nexperia NEH7100 solar PMIC
"""

from pyftdi.i2c import I2cController
import time
import argparse
import sys


class NEH7100:
    """NEH7100 Solar Energy Harvesting PMIC Driver"""

    # I2C Address (fixed)
    ADDR = 0x3C

    # Register addresses
    REG_PROTECTION = 0x00   # OVP [3:0] + LVD [7:4] thresholds
    REG_LDO_USB = 0x01      # LDO bypass/ctrl/voltage [7:3] + USB current [2:0]
    REG_FREQ = 0x03         # Converter frequency bounds
    REG_BOOST = 0x04        # Boosting factor bounds
    REG_MPPT = 0x05         # MPPT interval setting
    REG_CHIP_ID = 0x07      # Product ID (0x15)
    REG_STATUS = 0x08       # Status flags
    REG_I_RANGE = 0x09      # Current measurement range
    REG_I_MEASURED = 0x0A   # Current measurement value

    # Expected chip ID
    CHIP_ID = 0x15

    # OVP threshold lookup table (4-bit value -> voltage)
    # Table 17 in datasheet
    OVP_THRESHOLDS = {
        0b0000: 2.7,
        0b0001: 2.9,
        0b0010: 3.1,
        0b0011: 3.3,
        0b0100: 3.4,
        0b0101: 3.5,
        0b0110: 3.6,
        0b0111: 3.7,
        0b1000: 3.8,
        0b1001: 3.9,
        0b1010: 4.0,
        0b1011: 4.1,
        0b1100: 4.2,
        0b1101: 4.3,
        0b1110: 4.4,
        0b1111: 4.5,
    }

    # LVD threshold lookup table (4-bit value -> voltage)
    # Table 18 in datasheet
    LVD_THRESHOLDS = {
        0b0000: 2.2,
        0b0001: 2.3,
        0b0010: 2.4,
        0b0011: 2.5,
        0b0100: 2.6,
        0b0101: 2.7,
        0b0110: 2.8,
        0b0111: 2.9,
        0b1000: 3.0,
        0b1001: 3.1,
        0b1010: 3.2,
        0b1011: 3.3,
        0b1100: 3.4,
        0b1101: 3.5,
        0b1110: 3.6,
        0b1111: 3.7,
    }

    # LDO voltage lookup table (3-bit value -> voltage)
    # Bits [5:3] of REG_LDO_USB
    # Table 14 from datasheet
    LDO_VOLTAGES = {
        0b000: 1.2,
        0b001: 1.5,
        0b010: 1.8,
        0b011: 2.0,
        0b100: 2.4,
        0b101: 3.0,
        0b110: 3.3,
        0b111: 3.6,
    }

    # USB current limit lookup table (3-bit value -> mA)
    USB_CURRENT_LIMITS = {
        0b000: 0.5,
        0b001: 1,
        0b010: 2,
        0b011: 10,
        0b100: 50,
        0b101: 100,
        0b110: 150,
        0b111: 200,
    }

    # MPPT interval lookup table (4-bit value -> seconds)
    MPPT_INTERVALS = {
        0b0000: 0.5,
        0b0001: 1.0,
        0b0010: 2.0,
        0b0011: 4.0,
        0b0100: 8.0,
        0b0101: 16.0,
        0b0110: 32.0,
        0b0111: 64.0,
        # Upper values (0b1xxx) may have different meanings
    }

    # Current range factors (A per LSB)
    # Table 23 from datasheet
    I_RANGE_FACTORS = {
        0b00: 70.6e-9,    # 70.6 nA/LSB
        0b01: 478e-9,     # 478 nA/LSB
        0b10: 4.71e-6,    # 4.71 uA/LSB
        0b11: 67.5e-6,    # 67.5 uA/LSB
    }

    # Status register bit definitions
    STATUS_OVP_OUT = 0x10      # Over-voltage protection triggered
    STATUS_LVD_OUT = 0x08      # Low-voltage detection triggered
    STATUS_SDF = 0x04          # Shutdown flag
    STATUS_OCF = 0x02          # Overcurrent flag
    STATUS_CHIP_OK = 0x01      # Chip OK flag

    def __init__(self, i2c_url='ftdi://ftdi:232h/1', i2c_addr=None, frequency=100000):
        """Initialize NEH7100 with FT232H I2C bridge

        Args:
            i2c_url: FTDI URL for I2C controller
            i2c_addr: I2C address (default: 0x3C)
            frequency: I2C frequency in Hz (max 100kHz for NEH7100)
        """
        self.i2c = I2cController()
        # NEH7100 only supports standard mode (100kHz max)
        if frequency > 100000:
            frequency = 100000
        self.i2c.configure(i2c_url, frequency=frequency)
        addr = i2c_addr if i2c_addr is not None else self.ADDR
        self.slave = self.i2c.get_port(addr)
        self.frequency = frequency

    def read_register(self, reg):
        """Read 8-bit value from register"""
        data = self.slave.exchange([reg], 1)
        return data[0]

    def write_register(self, reg, value):
        """Write 8-bit value to register"""
        self.slave.write([reg, value & 0xFF])
        time.sleep(0.005)  # Small delay for register write

    def check_device_id(self):
        """Verify device ID matches expected value"""
        chip_id = self.read_register(self.REG_CHIP_ID)
        expected = self.CHIP_ID
        print(f"Chip ID: 0x{chip_id:02X} (expect 0x{expected:02X})")

        if chip_id == expected:
            return True
        else:
            print("Unexpected chip ID!")
            return False

    # --- OVP/LVD Threshold Methods ---

    def get_ovp_voltage(self):
        """Get current OVP threshold voltage"""
        prot = self.read_register(self.REG_PROTECTION)
        ovp_code = prot & 0x0F
        return self.OVP_THRESHOLDS.get(ovp_code, None), ovp_code

    def set_ovp_voltage(self, voltage):
        """Set OVP threshold voltage

        Args:
            voltage: Target voltage (2.7-4.5V)

        Returns:
            Actual voltage set
        """
        # Find closest code
        best_code = None
        best_diff = float('inf')
        for code, v in self.OVP_THRESHOLDS.items():
            diff = abs(v - voltage)
            if diff < best_diff:
                best_diff = diff
                best_code = code

        prot = self.read_register(self.REG_PROTECTION)
        prot = (prot & 0xF0) | (best_code & 0x0F)
        self.write_register(self.REG_PROTECTION, prot)
        return self.OVP_THRESHOLDS[best_code]

    def get_lvd_voltage(self):
        """Get current LVD threshold voltage"""
        prot = self.read_register(self.REG_PROTECTION)
        lvd_code = (prot >> 4) & 0x0F
        return self.LVD_THRESHOLDS.get(lvd_code, None), lvd_code

    def set_lvd_voltage(self, voltage):
        """Set LVD threshold voltage

        Args:
            voltage: Target voltage (2.2-3.7V)

        Returns:
            Actual voltage set
        """
        # Find closest code
        best_code = None
        best_diff = float('inf')
        for code, v in self.LVD_THRESHOLDS.items():
            diff = abs(v - voltage)
            if diff < best_diff:
                best_diff = diff
                best_code = code

        prot = self.read_register(self.REG_PROTECTION)
        prot = (prot & 0x0F) | ((best_code & 0x0F) << 4)
        self.write_register(self.REG_PROTECTION, prot)
        return self.LVD_THRESHOLDS[best_code]

    # --- LDO Methods ---

    def get_ldo_config(self):
        """Get current LDO configuration

        Returns:
            dict with voltage, bypass, ldo_ctrl, raw register value
        """
        reg = self.read_register(self.REG_LDO_USB)

        # Bit 7: LDO_BYPASS
        # Bit 6: LDO_CTRL (enable)
        # Bits [5:3]: LDO voltage (3 bits)
        # Bits [2:0]: USB current (handled separately)
        bypass = bool(reg & 0x80)
        ldo_ctrl = bool(reg & 0x40)
        ldo_code = (reg >> 3) & 0x07
        voltage = self.LDO_VOLTAGES.get(ldo_code, None)

        return {
            'voltage': voltage,
            'voltage_code': ldo_code,
            'bypass': bypass,
            'ldo_ctrl': ldo_ctrl,
            'raw': reg
        }

    def set_ldo_voltage(self, voltage):
        """Set LDO output voltage

        Args:
            voltage: Target voltage (1.8-3.3V)

        Returns:
            Actual voltage set
        """
        # Find closest code
        best_code = None
        best_diff = float('inf')
        for code, v in self.LDO_VOLTAGES.items():
            diff = abs(v - voltage)
            if diff < best_diff:
                best_diff = diff
                best_code = code

        reg = self.read_register(self.REG_LDO_USB)
        # Preserve bits 7:6 (bypass, ctrl) and bits 2:0 (USB current)
        # Set LDO voltage in bits 5:3
        reg = (reg & 0xC7) | ((best_code & 0x07) << 3)
        self.write_register(self.REG_LDO_USB, reg)
        return self.LDO_VOLTAGES[best_code]

    def set_ldo_bypass(self, enable):
        """Enable or disable LDO bypass mode"""
        reg = self.read_register(self.REG_LDO_USB)
        if enable:
            reg |= 0x80
        else:
            reg &= ~0x80
        self.write_register(self.REG_LDO_USB, reg)

    # --- USB Current Methods ---

    def get_usb_current_limit(self):
        """Get USB charging current limit"""
        reg = self.read_register(self.REG_LDO_USB)
        usb_code = reg & 0x07
        return self.USB_CURRENT_LIMITS.get(usb_code, None), usb_code

    def set_usb_current_limit(self, current_ma):
        """Set USB charging current limit

        Args:
            current_ma: Target current in mA (50-500, or 0 to disable)

        Returns:
            Actual current limit set
        """
        # Find closest code
        best_code = None
        best_diff = float('inf')
        for code, ma in self.USB_CURRENT_LIMITS.items():
            diff = abs(ma - current_ma)
            if diff < best_diff:
                best_diff = diff
                best_code = code

        reg = self.read_register(self.REG_LDO_USB)
        reg = (reg & 0xF8) | (best_code & 0x07)
        self.write_register(self.REG_LDO_USB, reg)
        return self.USB_CURRENT_LIMITS[best_code]

    # --- MPPT Methods ---

    def get_mppt_interval(self):
        """Get MPPT interval setting"""
        reg = self.read_register(self.REG_MPPT)
        mppt_code = reg & 0x0F
        return self.MPPT_INTERVALS.get(mppt_code, None), mppt_code

    def set_mppt_interval(self, seconds):
        """Set MPPT interval

        Args:
            seconds: Target interval (0.5-64s)

        Returns:
            Actual interval set
        """
        # Find closest code
        best_code = None
        best_diff = float('inf')
        for code, s in self.MPPT_INTERVALS.items():
            diff = abs(s - seconds)
            if diff < best_diff:
                best_diff = diff
                best_code = code

        reg = self.read_register(self.REG_MPPT)
        reg = (reg & 0xF0) | (best_code & 0x0F)
        self.write_register(self.REG_MPPT, reg)
        return self.MPPT_INTERVALS[best_code]

    # --- Status Methods ---

    def get_status(self):
        """Read and decode status register

        Returns:
            dict with all status flags
        """
        status = self.read_register(self.REG_STATUS)
        return {
            'raw': status,
            'ovp_out': bool(status & self.STATUS_OVP_OUT),
            'lvd_out': bool(status & self.STATUS_LVD_OUT),
            'sdf': bool(status & self.STATUS_SDF),
            'ocf': bool(status & self.STATUS_OCF),
            'chip_ok': bool(status & self.STATUS_CHIP_OK),
        }

    # --- Current Measurement Methods ---

    def read_charging_current(self):
        """Read charging current from I_RANGE and I_MEASURED registers

        Returns:
            dict with current in amps, range code, measured value
        """
        i_range = self.read_register(self.REG_I_RANGE)
        i_measured = self.read_register(self.REG_I_MEASURED)

        range_code = i_range & 0x03
        factor = self.I_RANGE_FACTORS.get(range_code, 0)
        current_a = i_measured * factor

        return {
            'current_a': current_a,
            'current_ua': current_a * 1e6,
            'current_ma': current_a * 1e3,
            'range_code': range_code,
            'measured_raw': i_measured,
            'factor': factor,
        }

    # --- Frequency and Boost Methods ---

    def get_freq_config(self):
        """Get frequency configuration register"""
        return self.read_register(self.REG_FREQ)

    def set_freq_config(self, value):
        """Set frequency configuration register"""
        self.write_register(self.REG_FREQ, value)

    def get_boost_config(self):
        """Get boost configuration register"""
        return self.read_register(self.REG_BOOST)

    def set_boost_config(self, value):
        """Set boost configuration register"""
        self.write_register(self.REG_BOOST, value)


def init_device(args):
    """Initialize and verify NEH7100 device"""
    freq = getattr(args, 'frequency', 100000)

    try:
        neh = NEH7100(i2c_addr=getattr(args, 'addr', None), frequency=freq)
        print(f"Connected to FT232H at {freq/1000:.0f}kHz")
    except Exception as e:
        print(f"Error connecting to FT232H: {e}")
        print("\nMake sure:")
        print("  1. FT232H is connected via USB")
        print("  2. NEH7100 is wired: SDA, SCL, VCC, GND")
        print("  3. I2C pullups are present")
        return None

    print("Verifying device...")
    if not neh.check_device_id():
        print("Device ID mismatch! Check I2C connections.")
        return None

    return neh


def cmd_info(args):
    """Display device information and configuration"""
    neh = init_device(args)
    if not neh:
        return 1

    print("\n=== NEH7100 Configuration ===")

    # Protection register
    ovp_v, ovp_code = neh.get_ovp_voltage()
    lvd_v, lvd_code = neh.get_lvd_voltage()
    print(f"\nProtection (0x{neh.REG_PROTECTION:02X}):")
    print(f"  OVP threshold: {ovp_v:.2f}V (code: 0x{ovp_code:X})")
    print(f"  LVD threshold: {lvd_v:.2f}V (code: 0x{lvd_code:X})")

    # LDO/USB register
    ldo = neh.get_ldo_config()
    usb_ma, usb_code = neh.get_usb_current_limit()
    print(f"\nLDO/USB (0x{neh.REG_LDO_USB:02X} = 0x{ldo['raw']:02X}):")
    if ldo['voltage']:
        print(f"  LDO voltage: {ldo['voltage']:.2f}V (code: 0x{ldo['voltage_code']:02X})")
    else:
        print(f"  LDO voltage: Unknown (code: 0x{ldo['voltage_code']:02X})")
    print(f"  LDO bypass: {ldo['bypass']}")
    print(f"  USB current limit: {usb_ma}mA (code: 0x{usb_code:X})")
    print(f"  LDO ctrl: {ldo['ldo_ctrl']}")

    # Frequency register
    freq = neh.get_freq_config()
    print(f"\nFrequency (0x{neh.REG_FREQ:02X}): 0x{freq:02X}")

    # Boost register
    boost = neh.get_boost_config()
    print(f"Boost (0x{neh.REG_BOOST:02X}): 0x{boost:02X}")

    # MPPT register
    mppt_s, mppt_code = neh.get_mppt_interval()
    print(f"\nMPPT (0x{neh.REG_MPPT:02X}):")
    if mppt_s:
        print(f"  Interval: {mppt_s}s (code: 0x{mppt_code:X})")
    else:
        print(f"  Interval: Unknown (code: 0x{mppt_code:X})")

    # Status
    status = neh.get_status()
    print(f"\nStatus (0x{neh.REG_STATUS:02X} = 0x{status['raw']:02X}):")
    print(f"  Chip OK:     {status['chip_ok']}")
    print(f"  OVP out:     {status['ovp_out']} {'(VBAT > ' + f'{ovp_v:.1f}V)' if status['ovp_out'] else ''}")
    print(f"  LVD out:     {status['lvd_out']} {'(VBAT < ' + f'{lvd_v:.1f}V)' if status['lvd_out'] else ''}")
    print(f"  Shutdown:    {status['sdf']}")
    print(f"  Overcurrent: {status['ocf']}")

    return 0


def cmd_reset(args):
    """Reset the NEH7100 device (not supported via I2C)"""
    print("Note: NEH7100 does not have a software reset via I2C.")
    print("To reset, power cycle the device or use hardware reset pin if available.")
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


def cmd_status(args):
    """Read real-time status flags"""
    neh = init_device(args)
    if not neh:
        return 1

    status = neh.get_status()
    ovp_v, _ = neh.get_ovp_voltage()
    lvd_v, _ = neh.get_lvd_voltage()

    print("\n=== NEH7100 Status ===")
    print(f"Raw register: 0x{status['raw']:02X}")
    print()
    print(f"  Chip OK:     {'YES' if status['chip_ok'] else 'NO'}")
    print(f"  OVP Out:     {'HIGH (VBAT > ' + f'{ovp_v:.2f}V)' if status['ovp_out'] else 'LOW (VBAT < ' + f'{ovp_v:.2f}V)'}")
    print(f"  LVD Out:     {'HIGH (VBAT < ' + f'{lvd_v:.2f}V)' if status['lvd_out'] else 'LOW (VBAT > ' + f'{lvd_v:.2f}V)'}")
    print(f"  Shutdown:    {'YES' if status['sdf'] else 'NO'}")
    print(f"  Overcurrent: {'YES' if status['ocf'] else 'NO'}")

    return 0


def cmd_config(args):
    """Configure device parameters"""
    neh = init_device(args)
    if not neh:
        return 1

    changes_made = False

    if args.ovp is not None:
        actual = neh.set_ovp_voltage(args.ovp)
        print(f"Set OVP threshold: {actual:.2f}V (requested: {args.ovp:.2f}V)")
        changes_made = True

    if args.lvd is not None:
        actual = neh.set_lvd_voltage(args.lvd)
        print(f"Set LVD threshold: {actual:.2f}V (requested: {args.lvd:.2f}V)")
        changes_made = True

    if args.ldo is not None:
        actual = neh.set_ldo_voltage(args.ldo)
        print(f"Set LDO voltage: {actual:.2f}V (requested: {args.ldo:.2f}V)")
        changes_made = True

    if args.ldo_bypass:
        neh.set_ldo_bypass(True)
        print("Enabled LDO bypass mode")
        changes_made = True

    if args.usb_current is not None:
        actual = neh.set_usb_current_limit(args.usb_current)
        print(f"Set USB current limit: {actual}mA (requested: {args.usb_current}mA)")
        changes_made = True

    if args.mppt_interval is not None:
        actual = neh.set_mppt_interval(args.mppt_interval)
        print(f"Set MPPT interval: {actual}s (requested: {args.mppt_interval}s)")
        changes_made = True

    if not changes_made:
        print("No configuration parameters specified. Use --help for options.")
        return 1

    print("\nConfiguration updated.")
    return 0


def cmd_current(args):
    """Read charging current"""
    neh = init_device(args)
    if not neh:
        return 1

    current = neh.read_charging_current()

    print("\n=== Charging Current ===")
    print(f"I_RANGE:    0x{current['range_code']:02X} (factor: {current['factor']*1e9:.1f} nA/LSB)")
    print(f"I_MEASURED: {current['measured_raw']} (raw)")
    print()

    if current['current_ma'] >= 1.0:
        print(f"Current: {current['current_ma']:.3f} mA")
    elif current['current_ua'] >= 1.0:
        print(f"Current: {current['current_ua']:.3f} uA")
    else:
        print(f"Current: {current['current_a']*1e9:.1f} nA")

    return 0


def cmd_monitor(args):
    """Continuous status monitoring"""
    neh = init_device(args)
    if not neh:
        return 1

    print("\n=== Monitoring NEH7100 (Ctrl+C to stop) ===")
    print(f"{'Sample':>6} | {'Current':>12} | {'ChipOK':>6} | {'OVP':>4} | {'LVD':>4} | {'SDF':>4} | {'OCF':>4}")
    print("-" * 70)

    sample = 0
    try:
        while True:
            status = neh.get_status()
            current = neh.read_charging_current()

            # Format current appropriately
            if current['current_ma'] >= 1.0:
                current_str = f"{current['current_ma']:.3f} mA"
            elif current['current_ua'] >= 1.0:
                current_str = f"{current['current_ua']:.2f} uA"
            else:
                current_str = f"{current['current_a']*1e9:.0f} nA"

            print(f"{sample:6d} | {current_str:>12} | "
                  f"{'YES' if status['chip_ok'] else 'NO':>6} | "
                  f"{'H' if status['ovp_out'] else 'L':>4} | "
                  f"{'H' if status['lvd_out'] else 'L':>4} | "
                  f"{'!' if status['sdf'] else '-':>4} | "
                  f"{'!' if status['ocf'] else '-':>4}")

            sample += 1
            time.sleep(args.delay)

    except KeyboardInterrupt:
        print("\n\nStopped")

    return 0


def main():
    """Main CLI entry point"""
    parser = argparse.ArgumentParser(
        description='NEH7100 Solar Energy Harvesting PMIC I2C Control via FT232H',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s info                          # Show device info and config
  %(prog)s status                        # Read status flags
  %(prog)s current                       # Read charging current
  %(prog)s config --ovp 4.2              # Set OVP to 4.2V
  %(prog)s config --lvd 3.0              # Set LVD to 3.0V
  %(prog)s config --ldo 3.3              # Set LDO to 3.3V
  %(prog)s config --usb-current 100      # Set USB current limit to 100mA
  %(prog)s config --mppt-interval 4      # Set MPPT interval to 4s
  %(prog)s monitor                       # Continuous monitoring
  %(prog)s monitor -d 0.5                # Monitor with 0.5s interval
  %(prog)s reset-ftdi                    # Reset FT232H USB adapter
        """
    )

    parser.add_argument('-a', '--addr', type=lambda x: int(x, 0),
                       help='I2C address (default: 0x3C)')
    parser.add_argument('-f', '--frequency', type=int, default=100000,
                       help='I2C frequency in Hz (default: 100000, max for NEH7100)')

    subparsers = parser.add_subparsers(dest='command', help='Command to execute')

    # Info command
    subparsers.add_parser('info', help='Display device information and configuration')

    # Reset command
    subparsers.add_parser('reset', help='Reset the NEH7100 device (note: not supported via I2C)')

    # Reset FTDI command
    subparsers.add_parser('reset-ftdi', help='Reset the FT232H USB adapter')

    # Status command
    subparsers.add_parser('status', help='Read real-time status flags')

    # Current command
    subparsers.add_parser('current', help='Read charging current')

    # Config command
    parser_config = subparsers.add_parser('config', help='Configure device parameters')
    parser_config.add_argument('--ovp', type=float,
                              help='Set OVP threshold voltage (2.7-4.5V)')
    parser_config.add_argument('--lvd', type=float,
                              help='Set LVD threshold voltage (2.2-3.7V)')
    parser_config.add_argument('--ldo', type=float,
                              help='Set LDO output voltage (1.2-3.6V)')
    parser_config.add_argument('--ldo-bypass', action='store_true',
                              help='Enable LDO bypass mode')
    parser_config.add_argument('--usb-current', type=float,
                              help='Set USB charging current limit in mA (0.5, 1, 2, 10, 50, 100, 150, 200)')
    parser_config.add_argument('--mppt-interval', type=float,
                              help='Set MPPT interval in seconds (0.5-64)')

    # Monitor command
    parser_monitor = subparsers.add_parser('monitor', help='Continuous status monitoring')
    parser_monitor.add_argument('-d', '--delay', type=float, default=1.0,
                               help='Delay between readings in seconds (default: 1.0)')

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 1

    # Route to appropriate command handler
    commands = {
        'info': cmd_info,
        'reset': cmd_reset,
        'reset-ftdi': cmd_reset_ftdi,
        'status': cmd_status,
        'config': cmd_config,
        'current': cmd_current,
        'monitor': cmd_monitor,
    }

    return commands[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
