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
import math


def compute_stats(samples):
    """
    Compute statistics for a list of samples

    Returns:
        dict with mean, std, min, max, count
    """
    n = len(samples)
    if n == 0:
        return {'mean': 0, 'std': 0, 'min': 0, 'max': 0, 'count': 0}

    mean = sum(samples) / n
    if n > 1:
        variance = sum((x - mean) ** 2 for x in samples) / (n - 1)
        std = math.sqrt(variance)
    else:
        std = 0

    return {
        'mean': mean,
        'std': std,
        'min': min(samples),
        'max': max(samples),
        'count': n
    }


def binary_search_min(lo, hi, test_fn, step=1, verbose=True):
    """
    Binary search to find the minimum value in [lo, hi] that passes a test.

    Assumes monotonicity: if test_fn(x) passes, then test_fn(y) passes for all y > x.

    Args:
        lo: Lower bound (inclusive)
        hi: Upper bound (inclusive)
        test_fn: Function that takes a value and returns (passed: bool, result: dict)
        step: Minimum step size / precision (values tested will be aligned to this)
        verbose: Print progress during search

    Returns:
        (optimal_value, all_results) where all_results is a list of
        {'value': v, 'passed': bool, **result} for each tested value
    """
    results = []
    optimal = None

    # Align bounds to step
    lo = ((lo + step - 1) // step) * step
    hi = (hi // step) * step

    while lo <= hi:
        mid = ((lo + hi) // 2 // step) * step  # Align to step

        if verbose:
            print(f"    Binary search: testing 0x{mid:04X} (range 0x{lo:04X}-0x{hi:04X})...")

        passed, result = test_fn(mid)
        results.append({'value': mid, 'passed': passed, **result})

        if passed:
            optimal = mid
            hi = mid - step  # Search for smaller passing value
        else:
            lo = mid + step  # Need larger value

    # Sort results by value for consistent display
    results.sort(key=lambda r: r['value'])

    return optimal, results

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

    def __init__(self, i2c_url='ftdi://ftdi:232h/1', i2c_addr=None, verbose=False):
        """Initialize FDC2212 with FT232H I2C bridge"""
        self.i2c = I2cController()
        self.i2c.configure(i2c_url, frequency=400000)
        addr = i2c_addr if i2c_addr is not None else self.ADDR
        self.slave = self.i2c.get_port(addr)
        self.verbose = verbose
        
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

        if self.verbose:
            print(f"Configured channel {channel}:")
            print(f"  RCOUNT=0x{rcount:04X}, SETTLE=0x{settle:04X}")
            print(f"  CLOCK_DIV=0x{clock_divider:04X} (FIN_SEL=/{fin_sel}, FREF_DIV={fref_div})")
            print(f"  DRIVE=0x{drive_current:04X}")
            print(f"  MUX=0x{mux_config:04X}, CONFIG=0x{config:04X}, ERR_CFG=0x{error_config:04X}")
    
    def read_status(self):
        """Read and decode status register"""
        status = self.read_register(self.REG_STATUS)
        print(f"Status: 0x{status:04X}")
        print(f"  ERR_CHAN: {(status >> 14) & 0x3}")
        print(f"  ERR_WD (Watchdog): {bool(status & self.STATUS_ERR_WD)}")
        print(f"  ERR_AHW (Amplitude High): {bool(status & self.STATUS_ERR_AHW)}")
        print(f"  ERR_ALW (Amplitude Low): {bool(status & self.STATUS_ERR_ALW)}")
        print(f"  DRDY: {bool(status & self.STATUS_DRDY)}")
        print(f"  CH0_UNREADCONV: {bool(status & self.STATUS_UNREADCONV_CH0)}")
        print(f"  CH1_UNREADCONV: {bool(status & self.STATUS_UNREADCONV_CH1)}")
        return status
    
    def continuous_read(self, channel=0, samples=10, delay=0.1):
        """Read capacitance data using single-shot mode (sleep between reads)"""
        print(f"\nReading {samples} samples from channel {channel} (single-shot mode):")
        print("Sample | Raw Data (28-bit) | Hex Value |     Avg     |     Std Dev |  Time | Error")
        print("-" * 88)

        mean = 0.0
        m2 = 0.0  # Sum of squares of differences from the mean
        valid_count = 0

        for i in range(samples):
            data, error, time_ms = self.single_shot_read(channel)
            if data is None:
                print(f"{i:6d} | {'TIMEOUT':>17} |           |             |             | {time_ms:5.0f}ms | {error or ''}")
                time.sleep(delay)
                continue

            # Update running statistics (Welford's algorithm)
            valid_count += 1
            delta = data - mean
            mean += delta / valid_count
            delta2 = data - mean
            m2 += delta * delta2

            variance = m2 / (valid_count - 1) if valid_count > 1 else 0.0
            stddev = math.sqrt(variance)

            error_str = error if error else ""
            print(
                f"{i:6d} | "
                f"{data:17d} | "
                f"0x{data:07X} | "
                f"{mean:10.2f} | "
                f"{stddev:10.2f} | "
                f"{time_ms:5.0f}ms | "
                f"{error_str}"
            )
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

    def take_samples(self, channel, n=10, delay=0.05):
        """Take n samples from channel, return list of raw readings"""
        samples = []
        for _ in range(n):
            samples.append(self.read_data(channel))
            time.sleep(delay)
        return samples

    def enter_sleep(self):
        """Put device in sleep mode"""
        config = self.read_register(self.REG_CONFIG)
        self.write_register(self.REG_CONFIG, config | self.CONFIG_SLEEP_MODE_EN)

    def exit_sleep(self):
        """Wake device from sleep mode"""
        config = self.read_register(self.REG_CONFIG)
        self.write_register(self.REG_CONFIG, config & ~self.CONFIG_SLEEP_MODE_EN)

    # STATUS register bit definitions (0x18) - per FDC2212 datasheet Table 7-36
    # Bit 14-13: ERR_CHAN - Channel that generated error
    # Bit 11: ERR_WD - Watchdog timeout error
    # Bit 10: ERR_AHW - Amplitude High Warning (drive current too high)
    # Bit 9: ERR_ALW - Amplitude Low Warning (drive current too low, or no oscillation)
    # Bit 6: DRDY - Data Ready (general flag, set when any channel has new data)
    # Bit 3: CH0_UNREADCONV - Unread conversion present for channel 0
    # Bit 2: CH1_UNREADCONV - Unread conversion present for channel 1
    # Bit 1: CH2_UNREADCONV - Unread conversion present for channel 2
    # Bit 0: CH3_UNREADCONV - Unread conversion present for channel 3
    STATUS_ERR_WD = 1 << 11
    STATUS_ERR_AHW = 1 << 10
    STATUS_ERR_ALW = 1 << 9
    STATUS_DRDY = 1 << 6
    STATUS_UNREADCONV_CH0 = 1 << 3
    STATUS_UNREADCONV_CH1 = 1 << 2
    STATUS_UNREADCONV_CH2 = 1 << 1
    STATUS_UNREADCONV_CH3 = 1 << 0

    def wait_for_drdy(self, channel=0, timeout_ms=500):
        """
        Poll STATUS register until DRDY bit is set for the specified channel.

        Args:
            channel: Channel to wait for (0-3)
            timeout_ms: Maximum time to wait in milliseconds

        Returns:
            (ready, error) tuple where:
                ready: True if DRDY was set, False if timeout
                error: None, 'AHW', or 'ALW' if amplitude error on this channel
        """
        unreadconv_bits = [self.STATUS_UNREADCONV_CH0, self.STATUS_UNREADCONV_CH1,
                           self.STATUS_UNREADCONV_CH2, self.STATUS_UNREADCONV_CH3]
        unreadconv_bit = unreadconv_bits[channel]

        start = time.time()
        timeout_s = timeout_ms / 1000.0
        error = None

        while (time.time() - start) < timeout_s:
            status = self.read_register(self.REG_STATUS)

            # Check for amplitude errors on this channel
            err_chan = (status >> 14) & 0x3
            if err_chan == channel:
                if status & self.STATUS_ERR_AHW:
                    error = 'AHW'
                elif status & self.STATUS_ERR_ALW:
                    error = 'ALW'

            if status & unreadconv_bit:
                return True, error
            time.sleep(0.001)  # 1ms poll interval

        if self.verbose:
            print(f"DRDY timeout, last status: 0x{status:04X}")
        return False, error

    def single_shot_read(self, channel, timeout_ms=500):
        """
        Single-shot measurement: wake -> wait for DRDY -> read -> sleep

        The FDC2x1x handles settle time and conversion internally via
        SETTLECOUNT and RCOUNT registers. We just poll DRDY to know when done.

        Args:
            channel: Channel to read
            timeout_ms: Maximum time to wait for conversion

        Returns:
            (data, error, time_ms) tuple where:
                data: Raw 28-bit reading, or None if timeout
                error: None, 'AHW', 'ALW', or 'TIMEOUT'
                time_ms: Time from wake to read complete in milliseconds
        """
        # Wake up (starts conversion with hardware-controlled settle + convert)
        start = time.time()
        self.exit_sleep()

        # Wait for hardware to signal conversion complete
        ready, error = self.wait_for_drdy(channel, timeout_ms)
        if not ready:
            elapsed_ms = (time.time() - start) * 1000
            self.enter_sleep()
            return None, 'TIMEOUT', elapsed_ms

        # Read data
        data = self.read_data(channel)
        elapsed_ms = (time.time() - start) * 1000

        # Return to sleep
        self.enter_sleep()

        return data, error, elapsed_ms

    def estimate_frequency(self, raw_reading, fref=40e6):
        """
        Estimate sensor oscillation frequency from raw reading

        From FDC2x1x datasheet equation 1:
        fSENSOR = (fREF × DATA) / 2^28

        Args:
            raw_reading: 28-bit raw data value
            fref: Reference frequency (default 40MHz internal)

        Returns:
            Estimated sensor frequency in Hz
        """
        return (raw_reading * fref) / (2**28)


def init_device(i2c_addr=None, verbose=False):
    """Initialize and verify FDC2212 device"""
    try:
        fdc = FDC2212(i2c_addr=i2c_addr, verbose=verbose)
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
    fdc = init_device(args.addr, verbose=args.verbose)
    if not fdc:
        return 1

    fdc.read_status()
    fdc.enter_sleep()
    return 0


def cmd_reset(args):
    """Reset the FDC2x1x device"""
    fdc = init_device(args.addr, verbose=args.verbose)
    if not fdc:
        return 1

    print("Resetting FDC2x1x device...")
    fdc.reset()

    if not args.no_verify:
        print("\nVerifying post-reset...")
        fdc.check_device_id()

    fdc.enter_sleep()
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


def cmd_config(args):
    """Configure device parameters"""
    fdc = init_device(args.addr, verbose=args.verbose)
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

    fdc.enter_sleep()
    return 0


def cmd_read(args):
    """Read capacitance data using single-shot mode (sleep between reads)"""
    fdc = init_device(args.addr, verbose=args.verbose)
    if not fdc:
        return 1

    if args.configure:
        print(f"Configuring channel {args.channel}...")
        fdc.configure_basic(channel=args.channel, rcount=args.rcount, settle=args.settle)
        print()

    fdc.continuous_read(channel=args.channel, samples=args.samples,
                        delay=args.delay)

    fdc.enter_sleep()
    return 0


def cmd_sweep(args):
    """Perform calibration sweep"""
    fdc = init_device(args.addr, verbose=args.verbose)
    if not fdc:
        return 1

    if args.rcount_values:
        # Parse hex values
        rcount_values = [int(v, 16) for v in args.rcount_values]
    else:
        # Default sweep values
        rcount_values = [0x1000, 0x4000, 0x8000, 0xC000, 0xFFFF]

    fdc.calibration_sweep(channel=args.channel, rcount_values=rcount_values)
    fdc.enter_sleep()
    return 0


def cmd_monitor(args):
    """Monitor multiple channels with live updates"""
    fdc = init_device(args.addr, verbose=args.verbose)
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

    fdc.enter_sleep()
    return 0


def cmd_characterize(args):
    """
    Characterize probe to find optimal settings for low-power, high-accuracy
    single-shot measurements.
    """
    fdc = init_device(args.addr, verbose=args.verbose)
    if not fdc:
        return 1

    channel = args.channel
    interactive = not args.non_interactive

    # Results storage for CSV output
    results = {
        'idrive': [],
        'rcount': [],
        'settle': [],
        'deglitch': []
    }

    print("=" * 60)
    print("=== FDC2x1x Probe Characterization ===")
    print("=" * 60)

    # =========================================================================
    # Phase 1: Baseline Discovery
    # =========================================================================
    print("\n--- Phase 1: Baseline Discovery ---")
    print("Configuring with safe defaults...")

    # Conservative defaults
    baseline_rcount = 0xFFFF
    baseline_settle = 0x0400
    baseline_idrive = 0x7800  # Mid-range

    # Use differential mode: fin_sel=1 for 0.01-8.75MHz range
    # Single-ended would use fin_sel=2
    fin_sel = 1  # Differential mode

    fdc.configure_basic(
        channel=channel,
        rcount=baseline_rcount,
        settle=baseline_settle,
        drive_current=baseline_idrive,
        fin_sel=fin_sel,
        fref_div=1,
        deglitch_mhz=10,
        sensor_activate_sel=True,
        intb_disable=True
    )

    # Wait for initial settling
    time.sleep(0.5)

    # Take baseline samples
    print("Taking baseline samples...")
    samples = fdc.take_samples(channel, n=20, delay=0.1)
    stats = compute_stats(samples)

    print(f"  Raw reading: {stats['mean']:.0f} +/- {stats['std']:.1f} (std dev over {stats['count']} samples)")
    print(f"  Range: {stats['min']} - {stats['max']}")

    # Estimate tank frequency
    freq = fdc.estimate_frequency(stats['mean'])
    print(f"  Tank frequency estimate: ~{freq/1e6:.2f} MHz")

    if interactive:
        print("\n  >>> OSCILLOSCOPE SETUP (Differential Mode):")
        print("  >>>")
        print("  >>> Your LC tank should be connected between IN0A and IN0B")
        print("  >>> Both pins oscillate 180 degrees out of phase")
        print("  >>>")
        print("  >>> Probe placement:")
        print("  >>>   - Probe IN0A (or IN0B) to GND")
        print("  >>>   - You'll measure half the differential amplitude")
        print("  >>>   - For true differential: use two probes and scope math (CH1-CH2)")
        print("  >>>")
        print("  >>> Scope settings:")
        print("  >>>   Timebase: ~1us/div (to see 2-5 cycles of MHz signal)")
        print("  >>>   Vertical: ~500mV/div initially, adjust as needed")
        print("  >>>   Trigger: Auto or Normal, edge trigger on signal")
        print("  >>>")
        print("  >>> Expected: Sinusoidal waveform at ~{:.2f} MHz".format(freq/1e6))
        print("  >>> If no oscillation: check LC tank connections and solder joints")
        print("  >>> If frequency is wrong: verify L and C values match your design")
        input("  >>> Press Enter when ready to continue...")

    # =========================================================================
    # Phase 2: Drive Current Sweep
    # =========================================================================
    print("\n--- Phase 2: Drive Current Sweep ---")
    print("Finding minimum IDRIVE for 1.2-1.8V oscillation amplitude...")
    print()
    print("  WHAT TO MEASURE ON OSCILLOSCOPE:")
    print("  - Measure peak-to-peak voltage (Vpp) of the sinusoidal oscillation")
    print("  - Target range: 1.2V to 1.8V peak-to-peak")
    print("  - Below 1.2V: Poor signal-to-noise, unreliable readings")
    print("  - Above 1.8V: Risk of long-term reliability issues")
    print("  - Goal: Find the LOWEST drive current that achieves >= 1.2V")
    print()

    # IDRIVE values to sweep (5-bit field in bits 15:11)
    # Finer granularity: step by 0x0800 (1 bit) for precise minimum finding
    idrive_values = [
        0x0800,  # 0x01 - minimum
        0x1000,  # 0x02
        0x1800,  # 0x03
        0x2000,  # 0x04
        0x2800,  # 0x05
        0x3000,  # 0x06
        0x3800,  # 0x07
        0x4000,  # 0x08
        0x4800,  # 0x09
        0x5000,  # 0x0A
        0x5800,  # 0x0B
        0x6000,  # 0x0C
        0x6800,  # 0x0D
        0x7000,  # 0x0E
        0x7800,  # 0x0F
        0x8000,  # 0x10
        0x8800,  # 0x11
        0x9000,  # 0x12
        0x9800,  # 0x13
        0xA000,  # 0x14
        0xA800,  # 0x15
        0xB000,  # 0x16
        0xB800,  # 0x17
        0xC000,  # 0x18
        0xC800,  # 0x19
        0xD000,  # 0x1A
        0xD800,  # 0x1B
        0xE000,  # 0x1C
        0xE800,  # 0x1D
        0xF000,  # 0x1E
        0xF800,  # 0x1F - maximum
    ]
    idrive_results = []
    optimal_idrive = None

    if interactive:
        # Interactive mode: use binary search to minimize user input
        print("  Using binary search to find minimum stable IDRIVE...")
        print("  (You'll measure Vpp on oscilloscope at each step)")
        print()

        def test_idrive_interactive(idrive):
            fdc.configure_basic(
                channel=channel,
                rcount=baseline_rcount,
                settle=baseline_settle,
                drive_current=idrive,
                fin_sel=fin_sel,
                fref_div=1,
                deglitch_mhz=10,
                sensor_activate_sel=True,
                intb_disable=True
            )

            time.sleep(0.3)
            samples = fdc.take_samples(channel, n=10, delay=0.05)
            stats = compute_stats(samples)

            print(f"      Mean: {stats['mean']:.0f}, Std Dev: {stats['std']:.1f}")

            vpp = None
            passed = False

            try:
                print("      >>> Measure Vpp on oscilloscope")
                vpp_input = input("      >>> Enter Vpp in volts (e.g., 1.4): ").strip()
                vpp = float(vpp_input)
                passed = 1.2 <= vpp <= 1.8
                if vpp < 1.2:
                    print(f"      Result: {vpp:.2f}V is below 1.2V - need more drive current")
                elif vpp > 1.8:
                    print(f"      Result: {vpp:.2f}V exceeds 1.8V - could use less current")
                    passed = True  # Still "works", just not optimal
                else:
                    print(f"      Result: {vpp:.2f}V is in valid range")
            except ValueError:
                print("      Invalid input, treating as unstable")

            return passed, {
                'idrive': idrive,
                'mean': stats['mean'],
                'std': stats['std'],
                'vpp': vpp,
                'status': "Stable" if passed else "Unstable"
            }

        # IDRIVE range: 0x0800 to 0xF800, step 0x0800 (hardware granularity)
        optimal_idrive, search_results = binary_search_min(
            lo=0x0800, hi=0xF800, test_fn=test_idrive_interactive, step=0x0800
        )

        for r in search_results:
            r['idrive'] = r.pop('value')
            idrive_results.append(r)
            results['idrive'].append(r)

        print(f"\n  Binary search tested {len(search_results)} values (of 31 possible)")

    else:
        # Non-interactive mode: linear sweep, then pick lowest IDRIVE with acceptable noise
        print("  Running linear sweep...")
        print()

        for idrive in idrive_values:
            fdc.configure_basic(
                channel=channel,
                rcount=baseline_rcount,
                settle=baseline_settle,
                drive_current=idrive,
                fin_sel=fin_sel,
                fref_div=1,
                deglitch_mhz=10,
                sensor_activate_sel=True,
                intb_disable=True
            )

            time.sleep(0.3)
            samples = fdc.take_samples(channel, n=20, delay=0.05)
            stats = compute_stats(samples)

            print(f"    0x{idrive:04X}: Mean={stats['mean']:.0f}, Std={stats['std']:.1f}")

            idrive_results.append({
                'idrive': idrive,
                'mean': stats['mean'],
                'std': stats['std'],
                'vpp': None,
                'status': 'Tested'
            })
            results['idrive'].append(idrive_results[-1])

        # Only consider results where sensor is actually oscillating (mean > 0)
        valid_results = [r for r in idrive_results if r['mean'] > 0]

        if not valid_results:
            print("\n  WARNING: No valid readings detected - sensor may not be oscillating")
            for r in idrive_results:
                r['status'] = 'No Signal'
        else:
            # Find min std dev among valid readings, then pick lowest IDRIVE within 1.5x of min
            min_std = min(r['std'] for r in valid_results)
            threshold = min_std * 1.5
            print(f"\n  Min std dev: {min_std:.1f}, threshold: {threshold:.1f} (1.5x min)")

            for r in idrive_results:
                if r['mean'] == 0:
                    r['status'] = 'No Signal'
                elif r['std'] <= threshold:
                    r['status'] = 'Stable'
                    if optimal_idrive is None:
                        optimal_idrive = r['idrive']
                        r['status'] = 'Optimal'
                else:
                    r['status'] = 'Unstable'

    # Print summary
    print("\n  IDRIVE Summary:")
    print("  IDRIVE   | Mean         | Std Dev | Vpp    | Status")
    print("  " + "-" * 55)
    for r in sorted(idrive_results, key=lambda x: x['idrive']):
        vpp_str = f"{r['vpp']:.1f}V" if r.get('vpp') else "N/A"
        marker = " <--" if r['status'] == "Optimal" else ""
        print(f"  0x{r['idrive']:04X}   | {r['mean']:12.0f} | {r['std']:7.1f} | {vpp_str:6} | {r['status']}{marker}")

    if optimal_idrive is None:
        optimal_idrive = 0x7800  # Fallback to mid-range
        print(f"\n  WARNING: Could not determine optimal IDRIVE, using default 0x{optimal_idrive:04X}")
    else:
        print(f"\n  Selected: 0x{optimal_idrive:04X}")

    # Validation: take many samples at optimal IDRIVE to confirm stability
    print("\n  Validating IDRIVE selection with extended sampling...")
    fdc.configure_basic(
        channel=channel,
        rcount=baseline_rcount,
        settle=baseline_settle,
        drive_current=optimal_idrive,
        fin_sel=fin_sel,
        fref_div=1,
        deglitch_mhz=10,
        sensor_activate_sel=True,
        intb_disable=True
    )
    time.sleep(0.5)
    validation_samples = fdc.take_samples(channel, n=50, delay=0.05)
    val_stats = compute_stats(validation_samples)
    noise_ppm = (val_stats['std'] / val_stats['mean']) * 1e6 if val_stats['mean'] > 0 else 0

    print(f"    Samples: {val_stats['count']}")
    print(f"    Mean: {val_stats['mean']:.1f}")
    print(f"    Std Dev: {val_stats['std']:.2f} ({noise_ppm:.0f} ppm)")
    print(f"    Range: {val_stats['min']} - {val_stats['max']} (span: {val_stats['max'] - val_stats['min']})")

    if val_stats['std'] > 100:
        print(f"    WARNING: Std dev > 100, readings may be unstable")

    # =========================================================================
    # Phase 3: RCOUNT Sweep
    # =========================================================================
    print("\n--- Phase 3: RCOUNT Sweep ---")
    print(f"Using IDRIVE=0x{optimal_idrive:04X}, sweeping RCOUNT...")

    # Finer RCOUNT sweep for resolution/noise analysis
    rcount_values = [0x2000, 0x4000, 0x6000, 0x8000, 0xA000, 0xC000, 0xE000, 0xFFFF]
    rcount_results = []

    for rcount in rcount_values:
        fdc.configure_basic(
            channel=channel,
            rcount=rcount,
            settle=baseline_settle,
            drive_current=optimal_idrive,
            fin_sel=fin_sel,
            fref_div=1,
            deglitch_mhz=10,
            sensor_activate_sel=True,
            intb_disable=True
        )

        time.sleep(0.5)
        samples = fdc.take_samples(channel, n=20, delay=0.05)
        stats = compute_stats(samples)

        rcount_results.append({
            'rcount': rcount,
            'mean': stats['mean'],
            'std': stats['std']
        })
        results['rcount'].append(rcount_results[-1])

    print("\n  RCOUNT   | Mean         | Std Dev")
    print("  " + "-" * 40)
    for r in rcount_results:
        marker = " <-- Max resolution" if r['rcount'] == 0xFFFF else ""
        print(f"  0x{r['rcount']:04X}   | {r['mean']:12.0f} | {r['std']:7.1f}{marker}")

    optimal_rcount = 0xFFFF  # For max accuracy
    print(f"\n  Selected: 0x{optimal_rcount:04X} (maximum resolution)")

    # =========================================================================
    # Phase 4: Settle Count Sweep
    # =========================================================================
    print("\n--- Phase 4: Settle Count Sweep ---")
    print("Simulating single-shot from sleep...")
    print()
    print("  WHAT TO OBSERVE ON OSCILLOSCOPE:")
    print("  - Watch for oscillation startup after each wake from sleep")
    print("  - Oscillation should reach stable amplitude before measurement")
    print("  - Too short settle time: amplitude still ramping up = unstable readings")
    print("  - Adequate settle time: amplitude stable before conversion starts")
    print()

    settle_values = [0x0020, 0x0040, 0x0080, 0x0100, 0x0200, 0x0400]
    settle_results = []
    optimal_settle = None

    # First get steady-state reference
    fdc.configure_basic(
        channel=channel,
        rcount=optimal_rcount,
        settle=0x0400,  # High settle for reference
        drive_current=optimal_idrive,
        fin_sel=fin_sel,
        fref_div=1,
        deglitch_mhz=10,
        sensor_activate_sel=True,
        intb_disable=True
    )
    time.sleep(1)
    steady_samples = fdc.take_samples(channel, n=10, delay=0.1)
    steady_stats = compute_stats(steady_samples)
    steady_mean = steady_stats['mean']

    print(f"  Steady-state reference: {steady_mean:.0f} +/- {steady_stats['std']:.1f}")
    print(f"  Stability threshold: wake std < {steady_stats['std'] * 2:.1f}")
    print()

    # Linear sweep - do multiple wake cycles per settle value to measure consistency
    num_trials = 10
    # Stable = wake-up std dev within 2x of steady-state std dev
    std_threshold = steady_stats['std'] * 2

    for settle in settle_values:
        fdc.configure_basic(
            channel=channel,
            rcount=optimal_rcount,
            settle=settle,
            drive_current=optimal_idrive,
            fin_sel=fin_sel,
            fref_div=1,
            deglitch_mhz=10,
            sensor_activate_sel=True,
            intb_disable=True
        )

        settle_time_s = settle / freq if freq > 0 else 0.1

        # Do multiple wake cycles and collect actual readings
        readings = []
        for _ in range(num_trials):
            fdc.enter_sleep()
            time.sleep(0.05)
            fdc.exit_sleep()
            time.sleep(max(settle_time_s, 0.05))
            reading = fdc.read_data(channel)
            readings.append(reading)

        # Calculate statistics on wake-up readings
        wake_mean = sum(readings) / len(readings)
        wake_std = (sum((r - wake_mean) ** 2 for r in readings) / len(readings)) ** 0.5

        # Stable if wake-up std dev is close to steady-state std dev
        if wake_std <= std_threshold:
            status = "Stable"
            if optimal_settle is None:
                optimal_settle = settle
                status = "Optimal"
        elif wake_std <= std_threshold * 2:
            status = "Marginal"
        else:
            status = "Unstable"

        print(f"    0x{settle:04X}: mean={wake_mean:.0f}, std={wake_std:.1f} (steady={steady_stats['std']:.1f}) -> {status}")

        settle_results.append({
            'settle': settle,
            'wake_mean': wake_mean,
            'wake_std': wake_std,
            'steady_std': steady_stats['std'],
            'status': status
        })
        results['settle'].append(settle_results[-1])

    print("\n  SETTLE   | Wake Mean    | Wake Std    | Steady Std | Status")
    print("  " + "-" * 60)
    for r in sorted(settle_results, key=lambda x: x['settle']):
        marker = " <--" if r['status'] == "Optimal" else ""
        print(f"  0x{r['settle']:04X}   | {r['wake_mean']:12.0f} | {r['wake_std']:11.1f} | {r['steady_std']:10.1f} | {r['status']}{marker}")

    if optimal_settle is None:
        optimal_settle = 0x0100  # Fallback
        print(f"\n  WARNING: Could not determine optimal settle, using 0x{optimal_settle:04X}")
    else:
        print(f"\n  Selected: 0x{optimal_settle:04X}")

    # Validation: do multiple wake-from-sleep cycles to confirm settle time
    print("\n  Validating SETTLE selection with multiple wake cycles...")
    fdc.configure_basic(
        channel=channel,
        rcount=optimal_rcount,
        settle=optimal_settle,
        drive_current=optimal_idrive,
        fin_sel=fin_sel,
        fref_div=1,
        deglitch_mhz=10,
        sensor_activate_sel=True,
        intb_disable=True
    )

    wake_deltas = []
    num_wake_cycles = 20
    for i in range(num_wake_cycles):
        fdc.enter_sleep()
        time.sleep(0.1)
        fdc.exit_sleep()
        settle_time_s = optimal_settle / freq if freq > 0 else 0.1
        time.sleep(max(settle_time_s, 0.05))
        first_read = fdc.read_data(channel)
        delta = abs(first_read - steady_mean)
        wake_deltas.append(delta)

    wake_stats = compute_stats(wake_deltas)
    max_delta = max(wake_deltas)
    failures = sum(1 for d in wake_deltas if d >= steady_stats['std'] * 2)

    print(f"    Wake cycles: {num_wake_cycles}")
    print(f"    Delta from steady-state:")
    print(f"      Mean: {wake_stats['mean']:.1f}")
    print(f"      Max: {max_delta:.1f} (threshold: {steady_stats['std'] * 2:.1f})")
    print(f"      Failures (delta >= threshold): {failures}/{num_wake_cycles}")

    if failures > 0:
        print(f"    WARNING: {failures} wake cycles exceeded threshold - consider increasing SETTLE")

    # =========================================================================
    # Phase 5: Deglitch Filter Selection
    # =========================================================================
    print("\n--- Phase 5: Deglitch Filter Selection ---")
    print()
    print("  DEGLITCH FILTER INFO:")
    print("  - Low-pass filter that rejects EMI above the sensor frequency")
    print("  - Must be set ABOVE your tank frequency to avoid attenuating signal")
    print("  - Lower setting = better EMI rejection (if above tank freq)")
    print()

    freq_mhz = freq / 1e6
    print(f"  Tank frequency: ~{freq_mhz:.2f} MHz")
    print()

    # All deglitch options - only test those above tank frequency
    all_deglitch = [1, 3.3, 10, 33]
    valid_deglitch = [d for d in all_deglitch if d > freq_mhz]

    if not valid_deglitch:
        # Tank freq is very high, must use 33 MHz
        valid_deglitch = [33]
        print("  WARNING: Tank frequency exceeds all filter options, using 33 MHz")

    print(f"  Testing valid options: {valid_deglitch} MHz")
    print()

    deglitch_results = []
    optimal_deglitch = None
    min_std = None

    for deglitch in valid_deglitch:
        fdc.configure_basic(
            channel=channel,
            rcount=optimal_rcount,
            settle=optimal_settle,
            drive_current=optimal_idrive,
            fin_sel=fin_sel,
            fref_div=1,
            deglitch_mhz=deglitch,
            sensor_activate_sel=True,
            intb_disable=True
        )
        time.sleep(0.3)
        samples = fdc.take_samples(channel, n=20, delay=0.05)
        stats = compute_stats(samples)

        deglitch_results.append({
            'deglitch': deglitch,
            'mean': stats['mean'],
            'std': stats['std'],
            'status': 'Pending'
        })
        results['deglitch'].append(deglitch_results[-1])

        print(f"    {deglitch:4} MHz: mean={stats['mean']:.0f}, std={stats['std']:.1f}")

    # Only consider results where sensor is actually oscillating
    valid_results = [r for r in deglitch_results if r['mean'] > 0]

    if not valid_results:
        print("\n  WARNING: No valid readings detected")
        for r in deglitch_results:
            r['status'] = 'No Signal'
        optimal_deglitch = valid_deglitch[0]  # Fallback to first valid option
    else:
        # Pick lowest std dev (best noise performance)
        min_std = min(r['std'] for r in valid_results)
        for r in deglitch_results:
            if r['mean'] == 0:
                r['status'] = 'No Signal'
            elif r['std'] == min_std and optimal_deglitch is None:
                optimal_deglitch = r['deglitch']
                r['status'] = 'Optimal'
            elif r['std'] <= min_std * 1.5:
                r['status'] = 'Good'
            else:
                r['status'] = 'Noisier'

    print()
    print("  DEGLITCH | Mean         | Std Dev     | Status")
    print("  " + "-" * 50)
    for r in deglitch_results:
        marker = " <--" if r['status'] == "Optimal" else ""
        print(f"  {r['deglitch']:4} MHz | {r['mean']:12.0f} | {r['std']:11.1f} | {r['status']}{marker}")

    print(f"\n  Selected: {optimal_deglitch} MHz (lowest noise)")

    # =========================================================================
    # Final Validation
    # =========================================================================
    print("\n--- Final Validation ---")
    print("Testing complete configuration with extended sampling...")
    print()

    # Configure with all optimal settings
    fdc.configure_basic(
        channel=channel,
        rcount=optimal_rcount,
        settle=optimal_settle,
        drive_current=optimal_idrive,
        fin_sel=fin_sel,
        fref_div=1,
        deglitch_mhz=optimal_deglitch,
        sensor_activate_sel=True,
        intb_disable=True
    )

    # Extended continuous sampling
    print("  Continuous mode (100 samples)...")
    time.sleep(0.5)
    continuous_samples = fdc.take_samples(channel, n=100, delay=0.05)
    cont_stats = compute_stats(continuous_samples)
    cont_noise_ppm = (cont_stats['std'] / cont_stats['mean']) * 1e6 if cont_stats['mean'] > 0 else 0

    print(f"    Mean: {cont_stats['mean']:.1f}")
    print(f"    Std Dev: {cont_stats['std']:.2f} ({cont_noise_ppm:.0f} ppm)")
    print(f"    Range: {cont_stats['min']} - {cont_stats['max']} (span: {cont_stats['max'] - cont_stats['min']})")

    # Simulated single-shot mode (wake from sleep each time)
    print("\n  Single-shot mode (20 wake cycles)...")
    single_shot_samples = []
    for _ in range(20):
        fdc.enter_sleep()
        time.sleep(0.05)
        fdc.exit_sleep()
        settle_time_s = optimal_settle / freq if freq > 0 else 0.1
        time.sleep(max(settle_time_s, 0.05))
        single_shot_samples.append(fdc.read_data(channel))

    ss_stats = compute_stats(single_shot_samples)
    ss_noise_ppm = (ss_stats['std'] / ss_stats['mean']) * 1e6 if ss_stats['mean'] > 0 else 0

    print(f"    Mean: {ss_stats['mean']:.1f}")
    print(f"    Std Dev: {ss_stats['std']:.2f} ({ss_noise_ppm:.0f} ppm)")
    print(f"    Range: {ss_stats['min']} - {ss_stats['max']} (span: {ss_stats['max'] - ss_stats['min']})")

    # Compare modes
    mode_delta = abs(cont_stats['mean'] - ss_stats['mean'])
    if cont_stats['mean'] > 0:
        print(f"\n  Continuous vs Single-shot delta: {mode_delta:.1f} ({mode_delta/cont_stats['mean']*1e6:.0f} ppm)")
    else:
        print(f"\n  Continuous vs Single-shot delta: {mode_delta:.1f}")

    if ss_stats['std'] > cont_stats['std'] * 2:
        print("  WARNING: Single-shot mode has significantly more noise than continuous")
        print("           Consider increasing SETTLE count")

    # =========================================================================
    # Final Recommendations
    # =========================================================================
    print("\n" + "=" * 60)
    print("=== RECOMMENDED CONFIGURATION ===")
    print("=" * 60)
    print(f"  IDRIVE:    0x{optimal_idrive:04X}")
    print(f"  RCOUNT:    0x{optimal_rcount:04X}")
    print(f"  SETTLE:    0x{optimal_settle:04X}")
    print(f"  DEGLITCH:  {optimal_deglitch} MHz")
    print(f"  Activation: Low power mode")
    print()
    print(f"  Expected noise floor (single-shot): {ss_stats['std']:.1f} counts ({ss_noise_ppm:.0f} ppm)")
    print()

    # Power estimation
    conversion_time_ms = (optimal_rcount * 16) / 40e6 * 1000
    settle_time_ms = optimal_settle / freq * 1000 if freq > 0 else 10
    total_time_ms = conversion_time_ms + settle_time_ms

    print(f"  Single-shot measurement time: ~{total_time_ms:.1f}ms")
    print(f"    Settling: ~{settle_time_ms:.1f}ms")
    print(f"    Conversion: ~{conversion_time_ms:.1f}ms")
    print()
    print(f"  Sleep current: ~0.4 uA")
    print(f"  Active current: ~300 uA (during {total_time_ms:.0f}ms measurement)")
    print()

    # Calculate for 5-minute interval
    interval_s = 300
    active_fraction = (total_time_ms / 1000) / interval_s
    avg_current_ua = 0.4 + 300 * active_fraction
    print(f"  At 1 measurement per 5 minutes:")
    print(f"    Average current: ~{avg_current_ua:.2f} uA")
    cr2032_mah = 220
    life_hours = cr2032_mah * 1000 / avg_current_ua
    life_years = life_hours / (24 * 365)
    print(f"    CR2032 ({cr2032_mah}mAh) life: ~{life_years:.0f} years (limited by self-discharge)")

    # Output CSV if requested
    if args.output:
        import csv
        with open(args.output, 'w', newline='') as f:
            writer = csv.writer(f)

            writer.writerow(['Phase', 'Parameter', 'Value', 'Mean', 'StdDev', 'Status'])

            for r in results['idrive']:
                writer.writerow(['IDRIVE', 'idrive', f"0x{r['idrive']:04X}",
                               r['mean'], r['std'], r['status']])

            for r in results['rcount']:
                writer.writerow(['RCOUNT', 'rcount', f"0x{r['rcount']:04X}",
                               r['mean'], r['std'], ''])

            for r in results['settle']:
                writer.writerow(['SETTLE', 'settle', f"0x{r['settle']:04X}",
                               r['wake_mean'], r['wake_std'], r['status']])

            # Final config
            writer.writerow(['FINAL', 'idrive', f"0x{optimal_idrive:04X}", '', '', ''])
            writer.writerow(['FINAL', 'rcount', f"0x{optimal_rcount:04X}", '', '', ''])
            writer.writerow(['FINAL', 'settle', f"0x{optimal_settle:04X}", '', '', ''])
            writer.writerow(['FINAL', 'deglitch', f"{optimal_deglitch}", '', '', ''])

            # Validation results
            writer.writerow(['VALIDATION', 'continuous_mean', cont_stats['mean'],
                           cont_stats['std'], cont_noise_ppm, ''])
            writer.writerow(['VALIDATION', 'single_shot_mean', ss_stats['mean'],
                           ss_stats['std'], ss_noise_ppm, ''])

        print(f"\n  Results saved to: {args.output}")

    fdc.enter_sleep()
    return 0


def main():
    """Main CLI entry point"""
    parser = argparse.ArgumentParser(
        description='FDC2x1x (FDC2112/2114/2212/2214) I2C Helper Script via FT232H',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s info                          # Show device info and status
  %(prog)s reset                         # Reset FDC2x1x device
  %(prog)s reset-ftdi                    # Reset FT232H USB adapter
  %(prog)s config -c 0 -r 0xFFFF        # Configure channel 0
  %(prog)s read -c 0 -n 10              # Read 10 samples (single-shot, sleeps between)
  %(prog)s monitor -C 0 1 2             # Monitor continuously (Ctrl+C to stop)
  %(prog)s sweep -c 0                   # Calibration sweep on channel 0
  %(prog)s sweep -c 0 -r 0x1000 0x8000 0xFFFF  # Custom sweep values
  %(prog)s characterize -c 0            # Characterize probe for optimal settings
  %(prog)s characterize -c 0 --output results.csv  # Save results to CSV
        """
    )
    
    parser.add_argument('-a', '--addr', type=lambda x: int(x, 0),
                       help='I2C address (default: 0x2A, alt: 0x2B)')
    parser.add_argument('-v', '--verbose', action='store_true',
                       help='Enable verbose output (show register configuration details)')

    subparsers = parser.add_subparsers(dest='command', help='Command to execute')
    
    # Info command
    parser_info = subparsers.add_parser('info', help='Display device information and status')
    
    # Reset command (FDC2x1x device)
    parser_reset = subparsers.add_parser('reset', help='Reset the FDC2x1x device')
    parser_reset.add_argument('--no-verify', action='store_true',
                             help='Skip post-reset verification')

    # Reset FTDI command (FT232H USB adapter)
    subparsers.add_parser('reset-ftdi', help='Reset the FT232H USB adapter')

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
    parser_read = subparsers.add_parser('read', help='Read capacitance data (single-shot mode)')
    parser_read.add_argument('-c', '--channel', type=int, default=0, choices=[0,1,2,3],
                            help='Channel to read (default: 0)')
    parser_read.add_argument('-n', '--samples', type=int, default=10,
                            help='Number of samples (default: 10)')
    parser_read.add_argument('-d', '--delay', type=float, default=0.5,
                            help='Delay between samples in seconds (default: 0.5)')
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

    # Characterize command
    parser_char = subparsers.add_parser('characterize',
                                        help='Characterize probe for optimal low-power settings')
    parser_char.add_argument('-c', '--channel', type=int, default=0, choices=[0,1,2,3],
                            help='Channel to characterize (default: 0)')
    parser_char.add_argument('--output', type=str, default=None,
                            help='Save results to CSV file')
    parser_char.add_argument('--non-interactive', action='store_true',
                            help='Skip oscilloscope prompts (use reading stability only)')

    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return 1

    # Route to appropriate command handler
    commands = {
        'info': cmd_info,
        'reset': cmd_reset,
        'reset-ftdi': cmd_reset_ftdi,
        'config': cmd_config,
        'read': cmd_read,
        'sweep': cmd_sweep,
        'monitor': cmd_monitor,
        'characterize': cmd_characterize,
    }

    return commands[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
