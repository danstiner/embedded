#!/usr/bin/env python3
# /// script
# requires-python = ">=3.8"
# dependencies = [
#   "pyftdi",
# ]
# ///
"""
FDC2x1x (FDC2112/2114/2212/2214) I2C Helper Script via FT232H
For testing modes and calibration with oscilloscope
"""

from pyftdi.i2c import I2cController
import time
import struct
import argparse
import sys

class FDC2212:
    # I2C Address (default, can be changed with ADDR pin)
    ADDR = 0x2A  # 0x2B if ADDR pin is high
    
    # Register addresses (same for FDC2112/2212/2114/2214)
    REG_DATA_CH0 = 0x00
    REG_DATA_CH1 = 0x02
    REG_DATA_CH2 = 0x04
    REG_DATA_CH3 = 0x06
    REG_RCOUNT_CH0 = 0x08
    REG_RCOUNT_CH1 = 0x09
    REG_RCOUNT_CH2 = 0x0A
    REG_RCOUNT_CH3 = 0x0B
    REG_OFFSET_CH0 = 0x0C
    REG_OFFSET_CH1 = 0x0D
    REG_OFFSET_CH2 = 0x0E
    REG_OFFSET_CH3 = 0x0F
    REG_SETTLECOUNT_CH0 = 0x10
    REG_SETTLECOUNT_CH1 = 0x11
    REG_SETTLECOUNT_CH2 = 0x12
    REG_SETTLECOUNT_CH3 = 0x13
    REG_CLOCK_DIVIDERS_CH0 = 0x14
    REG_CLOCK_DIVIDERS_CH1 = 0x15
    REG_CLOCK_DIVIDERS_CH2 = 0x16
    REG_CLOCK_DIVIDERS_CH3 = 0x17
    REG_STATUS = 0x18
    REG_ERROR_CONFIG = 0x19
    REG_CONFIG = 0x1A
    REG_MUX_CONFIG = 0x1B
    REG_RESET_DEV = 0x1C
    REG_DRIVE_CURRENT_CH0 = 0x1E
    REG_DRIVE_CURRENT_CH1 = 0x1F
    REG_DRIVE_CURRENT_CH2 = 0x20
    REG_DRIVE_CURRENT_CH3 = 0x21
    REG_MANUFACTURER_ID = 0x7E
    REG_DEVICE_ID = 0x7F

    # CLOCK_DIVIDERS_CHx registers (0x14-0x17) bit fields (from datasheet Table 7-32/7-33)
    # Bits 15-14: RESERVED - Set to b00
    # Bits 13-12: CHx_FIN_SEL - Sensor frequency select
    #   b01 = Divide by 1 (differential sensors 0.01-8.75MHz)
    #   b10 = Divide by 2 (differential 5-10MHz or single-ended 0.01-10MHz)
    # Bits 11-10: RESERVED - Set to b00
    # Bits 9-0: CHx_FREF_DIVIDER - Reference divider (divide by 1-1023)
    FIN_SEL_DIV_1 = 0x1 << 12  # b01 = Divide sensor frequency by 1
    FIN_SEL_DIV_2 = 0x2 << 12  # b10 = Divide sensor frequency by 2

    # CONFIG register (0x1A) bit fields (from datasheet Table 7-38)
    # Bits 15-14: ACTIVE_CHAN - Active channel selection for continuous conversions
    # Bit 13: SLEEP_MODE_EN - Sleep mode enable (1=sleep, 0=active)
    # Bit 12: RESERVED - Set to b1
    # Bit 11: SENSOR_ACTIVATE_SEL - Sensor activation mode (0=full current, 1=low power)
    # Bit 10: RESERVED - Set to b1
    # Bit 9: REF_CLK_SRC - Reference clock source (0=internal, 1=external CLKIN)
    # Bit 8: RESERVED - Set to b0
    # Bit 7: INTB_DIS - INTB disable (0=assert INTB, 1=don't assert INTB)
    # Bit 6: HIGH_CURRENT_DRV - High current sensor drive (0=max 1.5mA, 1=over 1.5mA on CH0)
    # Bits 5-0: RESERVED - Set to b00'0001
    CONFIG_SLEEP_MODE_EN = 1 << 13
    CONFIG_SENSOR_ACTIVATE_SEL = 1 << 11
    CONFIG_REF_CLK_SRC = 1 << 9
    CONFIG_INTB_DIS = 1 << 7
    CONFIG_HIGH_CURRENT_DRV = 1 << 6

    # MUX_CONFIG register (0x1B) bit fields
    # Bit 15: AUTOSCAN_EN - Enable autoscan mode for multi-channel
    # Bits 14-13: RR_SEQUENCE - Auto-Scan Sequence 
    # Bits 2-0: DEGLITCH - Input deglitch filter bandwidth
    MUX_AUTOSCAN_EN = 1 << 15
    # TODO Auto-Scan Sequence Configuration
    MUX_DEGLITCH_1MHZ = 0x1
    MUX_DEGLITCH_3_3MHZ = 0x4
    MUX_DEGLITCH_10MHZ = 0x5
    MUX_DEGLITCH_33MHZ = 0x7

    @staticmethod
    def build_clock_divider(fin_sel=1, fref_div=1):
        """Build CLOCK_DIVIDERS register value

        Args:
            fin_sel: Sensor frequency select - divide by 1 or 2 (bits 13:12)
                     1 = divide by 1 (differential sensors 0.01-8.75MHz)
                     2 = divide by 2 (differential sensors 5-10MHz or single-ended 0.01-10MHz)
            fref_div: Reference frequency divider 1-1023 (bits 9:0)

        Returns:
            16-bit register value
        """
        if fin_sel not in [1, 2]:
            raise ValueError("fin_sel must be 1 or 2")

        if not (1 <= fref_div <= 1023):
            raise ValueError("fref_div must be 1-1023")

        # CHx_FIN_SEL: Use the constants
        fin_sel_bits = FDC2212.FIN_SEL_DIV_1 if fin_sel == 1 else FDC2212.FIN_SEL_DIV_2

        return fin_sel_bits | fref_div

    @staticmethod
    def build_mux_config(channel=0, autoscan=False, deglitch_mhz=1, rr_sequence=0):
        """Build MUX_CONFIG register value

        Args:
            channel: Active channel for single-channel mode (0-3)
            autoscan: Enable autoscan mode for multi-channel
            deglitch_mhz: Input deglitch filter bandwidth in MHz (1, 3.3, 10, or 33)
            rr_sequence: Read-ready sequence (0-3)

        Returns:
            16-bit register value
        """
        value = 0

        # Reserved, bits 12:3 must be set to 00 0100 0001
        value |= 0x0041 << 3

        # TODO autoscan support

        # Deglitch filter
        deglitch_map = {
            1: FDC2212.MUX_DEGLITCH_1MHZ,
            3.3: FDC2212.MUX_DEGLITCH_3_3MHZ,
            10: FDC2212.MUX_DEGLITCH_10MHZ,
            33: FDC2212.MUX_DEGLITCH_33MHZ
        }
        if deglitch_mhz not in deglitch_map:
            raise ValueError("deglitch_mhz must be 1, 3.3, 10, or 33")
        value |= deglitch_map[deglitch_mhz]

        return value

    @staticmethod
    def build_config(active_chan=0, sleep_mode=False, sensor_activate_sel=True,
                     ref_clk_internal=True, intb_disable=False, high_current=False):
        """Build CONFIG register value

        Args:
            active_chan: Active channel for continuous conversions (0-3, bits 15:14)
            sleep_mode: Enable sleep mode (True=sleep/low power, False=active)
            sensor_activate_sel: Sensor activation mode (True=low power, False=full current)
            ref_clk_internal: Use internal reference clock (False for external CLKIN)
            intb_disable: Disable INTB pin (True=don't assert, False=assert on status update)
            high_current: High current sensor driver (True=>1.5mA on CH0, False=normal 1.5mA max)

        Returns:
            16-bit register value
        """
        # Start with reserved bits: bit 12=1, bit 10=1, bits 5:0=00'0001
        value = (1 << 12) | (1 << 10) | 0x01

        # Active channel (bits 15:14)
        value |= (active_chan & 0x3) << 14

        if sleep_mode:
            value |= FDC2212.CONFIG_SLEEP_MODE_EN
        if sensor_activate_sel:
            value |= FDC2212.CONFIG_SENSOR_ACTIVATE_SEL
        if not ref_clk_internal:
            value |= FDC2212.CONFIG_REF_CLK_SRC
        if intb_disable:
            value |= FDC2212.CONFIG_INTB_DIS
        if high_current:
            value |= FDC2212.CONFIG_HIGH_CURRENT_DRV

        return value

    def __init__(self, i2c_url='ftdi://ftdi:232h/1', i2c_addr=None):
        """Initialize FDC2212 with FT232H I2C bridge"""
        self.i2c = I2cController()
        self.i2c.configure(i2c_url)
        addr = i2c_addr if i2c_addr is not None else self.ADDR
        self.slave = self.i2c.get_port(addr)
        
    def write_register(self, reg, value):
        """Write 16-bit value to register"""
        data = struct.pack('>H', value)  # Big-endian 16-bit
        self.slave.write_to(reg, data)
        time.sleep(0.01)  # Small delay for register write
        
    def read_register(self, reg):
        """Read 16-bit value from register"""
        data = self.slave.exchange([reg], 2)
        return struct.unpack('>H', data)[0]
    
    def read_data(self, channel):
        """Read 28-bit capacitance data from channel (0-3)"""
        if channel < 0 or channel > 3:
            raise ValueError("Channel must be 0-3")
        
        reg = self.REG_DATA_CH0 + (channel * 2)
        msb = self.read_register(reg)
        lsb = self.read_register(reg + 1)
        # Combine into 28-bit value (top 4 bits of MSB are unused)
        return ((msb & 0x0FFF) << 16) | lsb
    
    def check_device_id(self):
        """Verify device ID"""
        mfg_id = self.read_register(self.REG_MANUFACTURER_ID)
        dev_id = self.read_register(self.REG_DEVICE_ID)
        print(f"Manufacturer ID: 0x{mfg_id:04X} (expect 0x5449 for TI)")
        
        # Device ID mapping
        device_names = {
            0x3054: "FDC2112/FDC2114",
            0x3055: "FDC2212/FDC2214"
        }
        
        device_name = device_names.get(dev_id, "Unknown")
        print(f"Device ID: 0x{dev_id:04X} - {device_name}")
        
        # Accept both 2-channel and 4-channel variants
        valid_ids = [0x3054, 0x3055]
        if mfg_id == 0x5449 and dev_id in valid_ids:
            return True
        else:
            print(f"✗ Unexpected device ID. Expected one of: {[hex(x) for x in valid_ids]}")
            return False
    
    def reset(self):
        """Software reset"""
        self.write_register(self.REG_RESET_DEV, 0x8000)
        time.sleep(0.1)
    
    def configure_basic(self, channel=0, rcount=0x8329, settle=0x0020,
                       # Clock divider options
                       clock_divider=None, fin_sel=1, fref_div=1,
                       # Drive current
                       drive_current=0x8000,
                       # MUX config options
                       mux_config=None, autoscan=False, deglitch_mhz=1,
                       # CONFIG register options
                       config=None, sleep_mode=False, sensor_activate_sel=False,
                       ref_clk_internal=True, intb_disable=True, high_current=False,
                       # Error config
                       error_config=0x3800):
        """
        Configure FDC2x1x for operation

        Args:
            channel: Channel to use (0-3)
            rcount: Reference count (higher = longer conversion, more resolution)
            settle: Settling time (number of sensor cycles to wait)

            Clock divider (use either clock_divider OR fin_sel/fref_div):
                clock_divider: Raw clock divider register value (overrides fin_sel/fref_div)
                fin_sel: Sensor frequency select - divide by 1 or 2
                fref_div: Reference frequency divider (1-1023)

            drive_current: Drive current setting (0x0000-0xF800, higher = more current)

            MUX config (use either mux_config OR autoscan/deglitch_mhz):
                mux_config: Raw MUX config register value (overrides others)
                autoscan: Enable autoscan mode for multi-channel
                deglitch_mhz: Input deglitch filter bandwidth (1, 3.3, 10, or 33 MHz)

            CONFIG register (use either config OR individual flags):
                config: Raw config register value (overrides individual flags)
                sleep_mode: Enable sleep mode
                sensor_activate_sel: Sensor activation selection
                ref_clk_internal: Use internal reference clock (False for external)
                intb_disable: Disable INTB pin
                high_current: High current sensor driver

            error_config: Error configuration register value
        """

        # Enter sleep mode before changing configuration to prevent spurious conversions
        current_config = self.read_register(self.REG_CONFIG)
        sleep_config = current_config | self.CONFIG_SLEEP_MODE_EN
        self.write_register(self.REG_CONFIG, sleep_config)
        time.sleep(0.01)  # Brief delay to ensure sleep mode is entered

        # Configure reference count for selected channel
        reg_rcount = self.REG_RCOUNT_CH0 + channel
        self.write_register(reg_rcount, rcount)

        # Configure settling time
        reg_settle = self.REG_SETTLECOUNT_CH0 + channel
        self.write_register(reg_settle, settle)

        # Set clock dividers
        if clock_divider is None:
            clock_divider = self.build_clock_divider(fin_sel, fref_div)
        reg_divider = self.REG_CLOCK_DIVIDERS_CH0 + channel
        self.write_register(reg_divider, clock_divider)

        # Set drive current
        reg_drive = self.REG_DRIVE_CURRENT_CH0 + channel
        self.write_register(reg_drive, drive_current)

        # Set mux config
        if mux_config is None:
            mux_config = self.build_mux_config(channel, autoscan, deglitch_mhz)
        self.write_register(self.REG_MUX_CONFIG, mux_config)

        # Set error config
        self.write_register(self.REG_ERROR_CONFIG, error_config)

        # Set main config
        if config is None:
            config = self.build_config(channel, sleep_mode, sensor_activate_sel,
                                      ref_clk_internal, intb_disable, high_current)
        self.write_register(self.REG_CONFIG, config)

        print(f"Configured channel {channel}:")
        print(f"  RCOUNT=0x{rcount:04X}, SETTLE=0x{settle:04X}")
        print(f"  CLOCK_DIV=0x{clock_divider:04X} (FIN_SEL=/{fin_sel}, FREF_DIV={fref_div})")
        print(f"  DRIVE=0x{drive_current:04X}")
        print(f"  MUX=0x{mux_config:04X}, CONFIG=0x{config:04X}, ERR_CFG=0x{error_config:04X}")
    
    def read_status(self):
        """Read and decode status register"""
        status = self.read_register(self.REG_STATUS)
        print(f"Status: 0x{status:04X}")
        print(f"  DRDY (Data Ready): {bool(status & 0x4000)}")
        print(f"  ERR_CHAN: {(status >> 12) & 0x3}")
        print(f"  ERR (Error): {bool(status & 0x8000)}")
        return status
    
    def continuous_read(self, channel=0, samples=10, delay=0.1):
        """Read capacitance data continuously"""
        print(f"\nReading {samples} samples from channel {channel}:")
        print("Sample | Raw Data (28-bit) | Hex Value")
        print("-" * 45)
        
        for i in range(samples):
            data = self.read_data(channel)
            print(f"{i:6d} | {data:15d} | 0x{data:07X}")
            time.sleep(delay)
    
    def calibration_sweep(self, channel=0, rcount_values=None):
        """
        Sweep through different RCOUNT values for calibration
        Useful for finding optimal conversion time vs resolution
        """
        if rcount_values is None:
            rcount_values = [0x1000, 0x4000, 0x8000, 0xC000, 0xFFFF]
        
        print(f"\nCalibration sweep on channel {channel}:")
        print("RCOUNT  | Capacitance Data")
        print("-" * 30)
        
        for rcount in rcount_values:
            self.configure_basic(channel=channel, rcount=rcount)
            time.sleep(1)  # Wait for settling
            data = self.read_data(channel)
            print(f"0x{rcount:04X} | {data:15d} (0x{data:07X})")


def init_device(i2c_addr=None):
    """Initialize and verify FDC2212 device"""
    try:
        if i2c_addr:
            fdc = FDC2212(i2c_addr=i2c_addr)
        else:
            fdc = FDC2212()
        print("✓ Connected to FT232H")
    except Exception as e:
        print(f"✗ Error connecting to FT232H: {e}")
        print("\nMake sure:")
        print("  1. FT232H is connected via USB")
        print("  2. pyftdi is installed: pip install pyftdi")
        print("  3. FT232H is properly wired to FDC2212 (SDA, SCL, VCC, GND)")
        return None
    
    print("Verifying device...")
    if not fdc.check_device_id():
        print("✗ Device ID mismatch! Check I2C connections.")
        return None
    
    return fdc


def cmd_info(args):
    """Display device information"""
    fdc = init_device(args.addr)
    if not fdc:
        return 1
    
    fdc.read_status()
    return 0


def cmd_reset(args):
    """Reset the device"""
    fdc = init_device(args.addr)
    if not fdc:
        return 1
    
    print("Resetting device...")
    fdc.reset()
    
    if not args.no_verify:
        print("\nVerifying post-reset...")
        fdc.check_device_id()
    
    return 0


def cmd_config(args):
    """Configure device parameters"""
    fdc = init_device(args.addr)
    if not fdc:
        return 1

    print(f"Configuring channel {args.channel}...")
    fdc.configure_basic(
        channel=args.channel,
        rcount=args.rcount,
        settle=args.settle,
        # Clock divider
        clock_divider=args.clock_divider,
        fin_sel=args.fin_sel,
        fref_div=args.fref_div,
        # Drive current
        drive_current=args.drive_current,
        # MUX config
        mux_config=args.mux_config,
        autoscan=args.autoscan,
        deglitch_mhz=args.deglitch,
        # CONFIG register
        config=args.config,
        sleep_mode=args.sleep_mode,
        sensor_activate_sel=args.sensor_activate_low_power,
        ref_clk_internal=not args.ref_clk_external,
        intb_disable=not args.intb_enable,
        high_current=args.high_current,
        # Error config
        error_config=args.error_config
    )
    print("✓ Configuration complete")

    if args.read:
        print()
        fdc.continuous_read(channel=args.channel, samples=5, delay=0.2)

    return 0


def cmd_read(args):
    """Read capacitance data continuously"""
    fdc = init_device(args.addr)
    if not fdc:
        return 1
    
    if args.configure:
        print(f"Configuring channel {args.channel}...")
        fdc.configure_basic(channel=args.channel, rcount=args.rcount, settle=args.settle)
        print()
    
    try:
        if args.samples == 0:
            # Continuous mode
            print(f"Reading channel {args.channel} continuously (Ctrl+C to stop):")
            print("Sample | Raw Data (28-bit) | Hex Value")
            print("-" * 45)
            sample = 0
            while True:
                data = fdc.read_data(args.channel)
                print(f"{sample:6d} | {data:15d} | 0x{data:07X}")
                sample += 1
                time.sleep(args.delay)
        else:
            fdc.continuous_read(channel=args.channel, samples=args.samples, delay=args.delay)
    except KeyboardInterrupt:
        print("\n\n✓ Stopped")
    
    return 0


def cmd_sweep(args):
    """Perform calibration sweep"""
    fdc = init_device(args.addr)
    if not fdc:
        return 1
    
    if args.rcount_values:
        # Parse hex values
        rcount_values = [int(v, 16) for v in args.rcount_values]
    else:
        # Default sweep values
        rcount_values = [0x1000, 0x4000, 0x8000, 0xC000, 0xFFFF]
    
    fdc.calibration_sweep(channel=args.channel, rcount_values=rcount_values)
    return 0


def cmd_monitor(args):
    """Monitor multiple channels with live updates"""
    fdc = init_device(args.addr)
    if not fdc:
        return 1
    
    channels = args.channels if args.channels else [0]
    
    # Configure all channels
    for ch in channels:
        fdc.configure_basic(channel=ch, rcount=args.rcount, settle=args.settle)
    
    print(f"Monitoring channels {channels} (Ctrl+C to stop)")
    print("=" * 60)
    
    try:
        sample = 0
        while True:
            print(f"\nSample {sample}:")
            for ch in channels:
                data = fdc.read_data(ch)
                print(f"  CH{ch}: {data:15d} (0x{data:07X})")
            sample += 1
            time.sleep(args.delay)
    except KeyboardInterrupt:
        print("\n\n✓ Stopped")
    
    return 0


def main():
    """Main CLI entry point"""
    parser = argparse.ArgumentParser(
        description='FDC2x1x (FDC2112/2114/2212/2214) I2C Helper Script via FT232H',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s info                          # Show device info and status
  %(prog)s reset                         # Reset device
  %(prog)s config -c 0 -r 0xFFFF        # Configure channel 0
  %(prog)s read -c 0 -n 10              # Read 10 samples from channel 0
  %(prog)s read -c 0 -n 0               # Read continuously (Ctrl+C to stop)
  %(prog)s sweep -c 0                   # Calibration sweep on channel 0
  %(prog)s sweep -c 0 -r 0x1000 0x8000 0xFFFF  # Custom sweep values
  %(prog)s monitor -C 0 1 2             # Monitor channels 0, 1, and 2
        """
    )
    
    parser.add_argument('-a', '--addr', type=lambda x: int(x, 0), 
                       help='I2C address (default: 0x2A, alt: 0x2B)')
    
    subparsers = parser.add_subparsers(dest='command', help='Command to execute')
    
    # Info command
    parser_info = subparsers.add_parser('info', help='Display device information and status')
    
    # Reset command
    parser_reset = subparsers.add_parser('reset', help='Reset the device')
    parser_reset.add_argument('--no-verify', action='store_true',
                             help='Skip post-reset verification')
    
    # Config command
    parser_config = subparsers.add_parser('config', help='Configure device parameters')
    parser_config.add_argument('-c', '--channel', type=int, default=0, choices=[0,1,2,3],
                              help='Channel to configure (default: 0)')
    parser_config.add_argument('-r', '--rcount', type=lambda x: int(x, 0), default=0x8329,
                              help='Reference count (hex, default: 0x8329)')
    parser_config.add_argument('-s', '--settle', type=lambda x: int(x, 0), default=0x0020,
                              help='Settle count (hex, default: 0x0020)')

    # Clock divider options
    parser_config.add_argument('--clock-divider', type=lambda x: int(x, 0), default=None,
                              help='Clock divider raw value (hex, overrides --fin-sel/--fref-div)')
    parser_config.add_argument('--fin-sel', type=int, default=1, choices=[1, 2],
                              help='Sensor frequency select divider (1 or 2, default: 1)')
    parser_config.add_argument('--fref-div', type=int, default=1,
                              help='Reference frequency divider (1-1023, default: 1)')

    parser_config.add_argument('--drive-current', type=lambda x: int(x, 0), default=0x8000,
                              help='Drive current (hex, default: 0x8000)')

    # MUX config options
    parser_config.add_argument('--mux-config', type=lambda x: int(x, 0), default=None,
                              help='MUX config raw value (hex, overrides --autoscan/--deglitch)')
    parser_config.add_argument('--autoscan', action='store_true',
                              help='Enable autoscan mode for multi-channel')
    parser_config.add_argument('--deglitch', type=float, default=1, choices=[1, 3.3, 10, 33],
                              help='Deglitch filter bandwidth in MHz (1/3.3/10/33, default: 1)')

    # CONFIG register options
    parser_config.add_argument('--config', type=lambda x: int(x, 0), default=None,
                              help='CONFIG register raw value (hex, overrides individual flags)')
    parser_config.add_argument('--sleep-mode', action='store_true',
                              help='Enable sleep mode (low power)')
    parser_config.add_argument('--sensor-activate-low-power', action='store_true',
                              help='Use low power sensor activation (default: full current)')
    parser_config.add_argument('--ref-clk-external', action='store_true',
                              help='Use external reference clock via CLKIN (default: internal)')
    parser_config.add_argument('--intb-enable', action='store_true',
                              help='Enable INTB pin assertions (default: disabled)')
    parser_config.add_argument('--high-current', action='store_true',
                              help='High current sensor driver on CH0 (>1.5mA)')

    parser_config.add_argument('--error-config', type=lambda x: int(x, 0), default=0x3800,
                              help='Error config register (hex, default: 0x3800)')
    parser_config.add_argument('--read', action='store_true',
                              help='Read samples after configuring')
    
    # Read command
    parser_read = subparsers.add_parser('read', help='Read capacitance data')
    parser_read.add_argument('-c', '--channel', type=int, default=0, choices=[0,1,2,3],
                            help='Channel to read (default: 0)')
    parser_read.add_argument('-n', '--samples', type=int, default=10,
                            help='Number of samples (0 = continuous, default: 10)')
    parser_read.add_argument('-d', '--delay', type=float, default=0.1,
                            help='Delay between samples in seconds (default: 0.1)')
    parser_read.add_argument('--configure', action='store_true',
                            help='Configure channel before reading')
    parser_read.add_argument('-r', '--rcount', type=lambda x: int(x, 0), default=0x8329,
                            help='Reference count if configuring (hex, default: 0x8329)')
    parser_read.add_argument('-s', '--settle', type=lambda x: int(x, 0), default=0x0020,
                            help='Settle count if configuring (hex, default: 0x0020)')
    
    # Sweep command
    parser_sweep = subparsers.add_parser('sweep', help='Perform calibration sweep')
    parser_sweep.add_argument('-c', '--channel', type=int, default=0, choices=[0,1,2,3],
                             help='Channel to sweep (default: 0)')
    parser_sweep.add_argument('-r', '--rcount-values', nargs='+',
                             help='RCOUNT values to test (hex, e.g., 0x1000 0x8000)')
    
    # Monitor command
    parser_monitor = subparsers.add_parser('monitor', help='Monitor multiple channels')
    parser_monitor.add_argument('-C', '--channels', type=int, nargs='+', choices=[0,1,2,3],
                               help='Channels to monitor (default: 0)')
    parser_monitor.add_argument('-d', '--delay', type=float, default=0.5,
                               help='Delay between readings in seconds (default: 0.5)')
    parser_monitor.add_argument('-r', '--rcount', type=lambda x: int(x, 0), default=0x8329,
                               help='Reference count (hex, default: 0x8329)')
    parser_monitor.add_argument('-s', '--settle', type=lambda x: int(x, 0), default=0x0020,
                               help='Settle count (hex, default: 0x0020)')
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return 1
    
    # Route to appropriate command handler
    commands = {
        'info': cmd_info,
        'reset': cmd_reset,
        'config': cmd_config,
        'read': cmd_read,
        'sweep': cmd_sweep,
        'monitor': cmd_monitor,
    }
    
    return commands[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
