#!/usr/bin/env python3
# /// script
# requires-python = ">=3.8"
# dependencies = [
#   "pyftdi",
# ]
# ///
"""
FDC1004 4-Channel Capacitance-to-Digital Converter I2C Helper Script via FT232H
For testing and calibration with oscilloscope
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
            print(f"    Binary search: testing {mid} (range {lo}-{hi})...")

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


class FDC1004:
    """FDC1004 4-Channel Capacitance-to-Digital Converter Driver"""

    # I2C Address (fixed)
    ADDR = 0x50

    # Register addresses
    REG_MEAS1_MSB = 0x00
    REG_MEAS1_LSB = 0x01
    REG_MEAS2_MSB = 0x02
    REG_MEAS2_LSB = 0x03
    REG_MEAS3_MSB = 0x04
    REG_MEAS3_LSB = 0x05
    REG_MEAS4_MSB = 0x06
    REG_MEAS4_LSB = 0x07

    REG_CONF_MEAS1 = 0x08
    REG_CONF_MEAS2 = 0x09
    REG_CONF_MEAS3 = 0x0A
    REG_CONF_MEAS4 = 0x0B

    REG_FDC_CONF = 0x0C

    REG_OFFSET_CAL_CIN1 = 0x0D
    REG_OFFSET_CAL_CIN2 = 0x0E
    REG_OFFSET_CAL_CIN3 = 0x0F
    REG_OFFSET_CAL_CIN4 = 0x10

    REG_GAIN_CAL_CIN1 = 0x11
    REG_GAIN_CAL_CIN2 = 0x12
    REG_GAIN_CAL_CIN3 = 0x13
    REG_GAIN_CAL_CIN4 = 0x14

    REG_MANUFACTURER_ID = 0xFE
    REG_DEVICE_ID = 0xFF

    # FDC_CONF register bit fields (0x0C)
    # Bit 15: RST - Software reset
    # Bits 11:10: RATE - Sample rate (0=100Hz, 1=200Hz, 2=reserved, 3=400Hz)
    # Bit 8: REPEAT - Repeat measurements
    # Bits 7:4: MEAS_x - Trigger measurement x (bit 7=MEAS1, bit 6=MEAS2, etc.)
    # Bits 3:0: DONE_x - Measurement x done flags (bit 3=MEAS1, bit 2=MEAS2, etc.)
    FDC_CONF_RST = 1 << 15
    FDC_CONF_RATE_MASK = 0x3 << 10
    FDC_CONF_REPEAT = 1 << 8
    FDC_CONF_MEAS1 = 1 << 7
    FDC_CONF_MEAS2 = 1 << 6
    FDC_CONF_MEAS3 = 1 << 5
    FDC_CONF_MEAS4 = 1 << 4
    FDC_CONF_DONE1 = 1 << 3
    FDC_CONF_DONE2 = 1 << 2
    FDC_CONF_DONE3 = 1 << 1
    FDC_CONF_DONE4 = 1 << 0

    # Sample rate values for RATE field
    RATE_100HZ = 0
    RATE_200HZ = 1
    RATE_400HZ = 3  # Note: 2 is reserved

    # CONF_MEASx bit fields
    # Bits 15:13: CHA - Positive channel (0=CIN1, 1=CIN2, 2=CIN3, 3=CIN4)
    # Bits 12:10: CHB - Negative channel (0=CIN1, 1=CIN2, 2=CIN3, 3=CIN4, 4=CAPDAC, 7=disabled)
    # Bits 9:5: CAPDAC - Capacitance offset (0-31, each step = 3.125pF)
    # Bits 4:0: Reserved

    # Channel constants
    CHA_CIN1 = 0
    CHA_CIN2 = 1
    CHA_CIN3 = 2
    CHA_CIN4 = 3

    CHB_CIN1 = 0
    CHB_CIN2 = 1
    CHB_CIN3 = 2
    CHB_CIN4 = 3
    CHB_CAPDAC = 4
    CHB_DISABLED = 7

    # CAPDAC constants
    CAPDAC_STEP_PF = 3.125  # pF per CAPDAC step
    CAPDAC_MAX = 31  # Maximum CAPDAC value
    CAPDAC_MAX_PF = 96.875  # Maximum offset in pF (31 * 3.125)

    @staticmethod
    def build_meas_config(cha, chb=7, capdac=0):
        """
        Build CONF_MEASx register value

        Args:
            cha: Positive channel input (0-3 for CIN1-CIN4)
            chb: Negative channel input (0-3 for CIN1-CIN4, 4=CAPDAC, 7=disabled)
            capdac: CAPDAC offset value (0-31, each step = 3.125pF)

        Returns:
            16-bit register value
        """
        if not (0 <= cha <= 3):
            raise ValueError("cha must be 0-3")
        if chb not in [0, 1, 2, 3, 4, 7]:
            raise ValueError("chb must be 0-3, 4 (CAPDAC), or 7 (disabled)")
        if not (0 <= capdac <= 31):
            raise ValueError("capdac must be 0-31")

        return (cha << 13) | (chb << 10) | (capdac << 5)

    @staticmethod
    def build_fdc_config(rate=0, repeat=False, trigger_meas=None):
        """
        Build FDC_CONF register value

        Args:
            rate: Sample rate (0=100Hz, 1=200Hz, 3=400Hz)
            repeat: Enable repeat measurements
            trigger_meas: List of measurement numbers to trigger (1-4)

        Returns:
            16-bit register value
        """
        if rate not in [0, 1, 3]:
            raise ValueError("rate must be 0 (100Hz), 1 (200Hz), or 3 (400Hz)")

        value = (rate << 10)
        if repeat:
            value |= FDC1004.FDC_CONF_REPEAT

        if trigger_meas:
            meas_bits = [FDC1004.FDC_CONF_MEAS1, FDC1004.FDC_CONF_MEAS2,
                        FDC1004.FDC_CONF_MEAS3, FDC1004.FDC_CONF_MEAS4]
            for m in trigger_meas:
                if 1 <= m <= 4:
                    value |= meas_bits[m - 1]

        return value

    def __init__(self, i2c_url='ftdi://ftdi:232h/1', i2c_addr=None, verbose=False):
        """Initialize FDC1004 with FT232H I2C bridge"""
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

    def check_device_id(self):
        """Verify device ID"""
        mfg_id = self.read_register(self.REG_MANUFACTURER_ID)
        dev_id = self.read_register(self.REG_DEVICE_ID)
        print(f"Manufacturer ID: 0x{mfg_id:04X} (expect 0x5449 for TI)")
        print(f"Device ID: 0x{dev_id:04X} (expect 0x1004 for FDC1004)")

        if mfg_id == 0x5449 and dev_id == 0x1004:
            return True
        else:
            print(f"Unexpected device ID!")
            return False

    def reset(self):
        """Software reset via RST bit"""
        self.write_register(self.REG_FDC_CONF, self.FDC_CONF_RST)
        time.sleep(0.1)

    def configure_measurement(self, meas_num, cha, chb=7, capdac=0):
        """
        Configure a measurement slot

        Args:
            meas_num: Measurement number (1-4)
            cha: Positive channel input (0-3 for CIN1-CIN4)
            chb: Negative channel input (0-3, 4=CAPDAC, 7=disabled)
            capdac: CAPDAC offset value (0-31)
        """
        if not (1 <= meas_num <= 4):
            raise ValueError("meas_num must be 1-4")

        reg = self.REG_CONF_MEAS1 + (meas_num - 1)
        value = self.build_meas_config(cha, chb, capdac)
        self.write_register(reg, value)

        if self.verbose:
            print(f"Configured MEAS{meas_num}: CHA={cha}, CHB={chb}, CAPDAC={capdac}")
            print(f"  Register 0x{reg:02X} = 0x{value:04X}")

    def configure_basic(self, channel, capdac=0, rate=0):
        """
        Simplified single-channel setup

        Args:
            channel: Input channel (0-3 for CIN1-CIN4)
            capdac: CAPDAC offset value (0-31)
            rate: Sample rate (0=100Hz, 1=200Hz, 3=400Hz)
        """
        # Configure MEAS1 with specified channel, CHB disabled
        self.configure_measurement(1, cha=channel, chb=self.CHB_DISABLED, capdac=capdac)

        if self.verbose:
            print(f"Configured channel {channel} with CAPDAC={capdac}, rate={rate}")

    def read_measurement_raw(self, meas_num):
        """
        Read 24-bit raw value from measurement slot

        Args:
            meas_num: Measurement number (1-4)

        Returns:
            24-bit raw measurement value
        """
        if not (1 <= meas_num <= 4):
            raise ValueError("meas_num must be 1-4")

        msb_reg = self.REG_MEAS1_MSB + (meas_num - 1) * 2
        lsb_reg = msb_reg + 1

        msb = self.read_register(msb_reg)
        lsb = self.read_register(lsb_reg)

        # Combine into 24-bit value (MSB bits 15:0 = data[23:8], LSB bits 15:8 = data[7:0])
        return (msb << 8) | (lsb >> 8)

    @staticmethod
    def raw_to_capacitance(raw_24bit, capdac):
        """
        Convert raw 24-bit reading to capacitance in pF

        Args:
            raw_24bit: 24-bit raw measurement value (two's complement)
            capdac: CAPDAC setting used for measurement

        Returns:
            Capacitance in pF
        """
        # Two's complement conversion for 24-bit value
        if raw_24bit >= 0x800000:
            signed = raw_24bit - 0x1000000
        else:
            signed = raw_24bit

        # C(pF) = value/2^19 + CAPDAC*3.125
        return (signed / 524288.0) + (capdac * 3.125)

    def trigger_measurement(self, meas_nums, rate=0):
        """
        Trigger one or more measurements

        Args:
            meas_nums: List of measurement numbers to trigger (1-4)
            rate: Sample rate (0=100Hz, 1=200Hz, 3=400Hz)
        """
        config = self.build_fdc_config(rate=rate, repeat=False, trigger_meas=meas_nums)
        self.write_register(self.REG_FDC_CONF, config)

    def wait_for_done(self, meas_num, timeout_ms=500):
        """
        Poll DONE flag until measurement is complete

        Args:
            meas_num: Measurement number (1-4)
            timeout_ms: Maximum time to wait in milliseconds

        Returns:
            (done, time_ms) tuple where:
                done: True if measurement completed, False if timeout
                time_ms: Time waited in milliseconds
        """
        done_bits = [self.FDC_CONF_DONE1, self.FDC_CONF_DONE2,
                     self.FDC_CONF_DONE3, self.FDC_CONF_DONE4]
        done_bit = done_bits[meas_num - 1]

        start = time.time()
        timeout_s = timeout_ms / 1000.0

        while (time.time() - start) < timeout_s:
            config = self.read_register(self.REG_FDC_CONF)
            if config & done_bit:
                elapsed_ms = (time.time() - start) * 1000
                return True, elapsed_ms
            time.sleep(0.001)  # 1ms poll interval

        elapsed_ms = (time.time() - start) * 1000
        return False, elapsed_ms

    def single_shot_read(self, meas_num, rate=0, capdac=None, timeout_ms=500):
        """
        Trigger, wait, and read a single measurement

        Args:
            meas_num: Measurement number (1-4)
            rate: Sample rate (0=100Hz, 1=200Hz, 3=400Hz)
            capdac: CAPDAC value for capacitance calculation (None to read from config)
            timeout_ms: Maximum time to wait

        Returns:
            (raw, capacitance, time_ms) tuple where:
                raw: 24-bit raw reading, or None if timeout
                capacitance: Capacitance in pF, or None if timeout
                time_ms: Time from trigger to read complete
        """
        # Read CAPDAC from measurement config if not provided
        if capdac is None:
            conf_reg = self.REG_CONF_MEAS1 + (meas_num - 1)
            conf = self.read_register(conf_reg)
            capdac = (conf >> 5) & 0x1F

        # Trigger measurement
        start = time.time()
        self.trigger_measurement([meas_num], rate=rate)

        # Wait for completion
        done, _ = self.wait_for_done(meas_num, timeout_ms)
        if not done:
            elapsed_ms = (time.time() - start) * 1000
            return None, None, elapsed_ms

        # Read result
        raw = self.read_measurement_raw(meas_num)
        elapsed_ms = (time.time() - start) * 1000

        capacitance = self.raw_to_capacitance(raw, capdac)

        return raw, capacitance, elapsed_ms

    def continuous_read(self, meas_num, samples=10, delay=0.1, rate=0, capdac=None):
        """
        Read multiple measurements with statistics

        Args:
            meas_num: Measurement number (1-4)
            samples: Number of samples to take
            delay: Delay between samples in seconds
            rate: Sample rate (0=100Hz, 1=200Hz, 3=400Hz)
            capdac: CAPDAC value (None to read from config)
        """
        # Read CAPDAC from measurement config if not provided
        if capdac is None:
            conf_reg = self.REG_CONF_MEAS1 + (meas_num - 1)
            conf = self.read_register(conf_reg)
            capdac = (conf >> 5) & 0x1F

        print(f"\nReading {samples} samples from MEAS{meas_num} (CAPDAC={capdac}):")
        print("Sample | Raw (24-bit)  | Capacitance (pF) |     Avg (pF) |  Std Dev |  Time")
        print("-" * 78)

        mean = 0.0
        m2 = 0.0  # Sum of squares of differences from the mean
        valid_count = 0
        cap_samples = []

        for i in range(samples):
            raw, capacitance, time_ms = self.single_shot_read(meas_num, rate=rate, capdac=capdac)

            if raw is None:
                print(f"{i:6d} | {'TIMEOUT':>13} |                  |              |          | {time_ms:5.0f}ms")
                time.sleep(delay)
                continue

            cap_samples.append(capacitance)

            # Update running statistics (Welford's algorithm)
            valid_count += 1
            delta = capacitance - mean
            mean += delta / valid_count
            delta2 = capacitance - mean
            m2 += delta * delta2

            variance = m2 / (valid_count - 1) if valid_count > 1 else 0.0
            stddev = math.sqrt(variance)

            print(
                f"{i:6d} | "
                f"0x{raw:06X} | "
                f"{capacitance:16.4f} | "
                f"{mean:12.4f} | "
                f"{stddev:8.4f} | "
                f"{time_ms:5.0f}ms"
            )
            time.sleep(delay)

        if cap_samples:
            stats = compute_stats(cap_samples)
            print("-" * 78)
            print(f"Summary: {stats['count']} samples, mean={stats['mean']:.4f} pF, "
                  f"std={stats['std']:.4f} pF, range=[{stats['min']:.4f}, {stats['max']:.4f}]")

    def take_samples(self, meas_num, n=10, delay=0.05, rate=0, capdac=None):
        """Take n samples, return list of capacitance readings"""
        # Read CAPDAC from measurement config if not provided
        if capdac is None:
            conf_reg = self.REG_CONF_MEAS1 + (meas_num - 1)
            conf = self.read_register(conf_reg)
            capdac = (conf >> 5) & 0x1F

        samples = []
        for _ in range(n):
            raw, capacitance, _ = self.single_shot_read(meas_num, rate=rate, capdac=capdac)
            if capacitance is not None:
                samples.append(capacitance)
            time.sleep(delay)
        return samples

    def read_config(self):
        """Read and display current device configuration"""
        print("\nCurrent Configuration:")
        print("-" * 50)

        # Read FDC_CONF
        fdc_conf = self.read_register(self.REG_FDC_CONF)
        rate_val = (fdc_conf >> 10) & 0x3
        rate_hz = {0: 100, 1: 200, 3: 400}.get(rate_val, "reserved")
        repeat = bool(fdc_conf & self.FDC_CONF_REPEAT)
        print(f"FDC_CONF (0x0C): 0x{fdc_conf:04X}")
        print(f"  Rate: {rate_hz} Hz")
        print(f"  Repeat: {repeat}")
        print(f"  DONE flags: MEAS1={bool(fdc_conf & 0x08)}, MEAS2={bool(fdc_conf & 0x04)}, "
              f"MEAS3={bool(fdc_conf & 0x02)}, MEAS4={bool(fdc_conf & 0x01)}")

        # Read CONF_MEASx registers
        for i in range(1, 5):
            reg = self.REG_CONF_MEAS1 + (i - 1)
            conf = self.read_register(reg)
            cha = (conf >> 13) & 0x7
            chb = (conf >> 10) & 0x7
            capdac = (conf >> 5) & 0x1F
            capdac_pf = capdac * 3.125

            chb_str = {0: "CIN1", 1: "CIN2", 2: "CIN3", 3: "CIN4", 4: "CAPDAC", 7: "disabled"}.get(chb, f"reserved({chb})")
            print(f"CONF_MEAS{i} (0x{reg:02X}): 0x{conf:04X}")
            print(f"  CHA=CIN{cha+1}, CHB={chb_str}, CAPDAC={capdac} ({capdac_pf:.3f}pF)")


def init_device(i2c_addr=None, verbose=False):
    """Initialize and verify FDC1004 device"""
    try:
        fdc = FDC1004(i2c_addr=i2c_addr, verbose=verbose)
        print("Connected to FT232H")
    except Exception as e:
        print(f"Error connecting to FT232H: {e}")
        print("\nMake sure:")
        print("  1. FT232H is connected via USB")
        print("  2. pyftdi is installed: pip install pyftdi")
        print("  3. FT232H is properly wired to FDC1004 (SDA, SCL, VCC, GND)")
        return None

    print("Verifying device...")
    if not fdc.check_device_id():
        print("Device ID mismatch! Check I2C connections.")
        return None

    return fdc


def cmd_info(args):
    """Display device information"""
    fdc = init_device(args.addr, verbose=args.verbose)
    if not fdc:
        return 1

    fdc.read_config()
    return 0


def cmd_reset(args):
    """Reset the FDC1004 device"""
    fdc = init_device(args.addr, verbose=args.verbose)
    if not fdc:
        return 1

    print("Resetting FDC1004 device...")
    fdc.reset()

    if not args.no_verify:
        print("\nVerifying post-reset...")
        fdc.check_device_id()

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
    """Configure measurement parameters"""
    fdc = init_device(args.addr, verbose=args.verbose)
    if not fdc:
        return 1

    print(f"Configuring MEAS{args.meas}...")
    fdc.configure_measurement(
        meas_num=args.meas,
        cha=args.cha,
        chb=args.chb,
        capdac=args.capdac
    )
    print("Configuration complete")

    fdc.read_config()
    return 0


def cmd_read(args):
    """Read capacitance measurements"""
    fdc = init_device(args.addr, verbose=args.verbose)
    if not fdc:
        return 1

    # Configure if requested
    if args.configure:
        print(f"Configuring MEAS{args.meas} with channel {args.cha}, CAPDAC={args.capdac}...")
        fdc.configure_measurement(
            meas_num=args.meas,
            cha=args.cha,
            chb=FDC1004.CHB_DISABLED,
            capdac=args.capdac
        )
        print()

    # Map rate string to value
    rate_map = {'100': 0, '200': 1, '400': 3}
    rate = rate_map.get(args.rate, 0)

    fdc.continuous_read(
        meas_num=args.meas,
        samples=args.samples,
        delay=args.delay,
        rate=rate,
        capdac=args.capdac if args.configure else None
    )

    return 0


def cmd_monitor(args):
    """Monitor multiple measurements continuously"""
    fdc = init_device(args.addr, verbose=args.verbose)
    if not fdc:
        return 1

    meas_nums = args.measurements if args.measurements else [1]

    # Configure all measurements if requested
    if args.configure:
        for i, m in enumerate(meas_nums):
            channel = i % 4  # Use different channels
            fdc.configure_measurement(m, cha=channel, chb=FDC1004.CHB_DISABLED, capdac=args.capdac)

    rate_map = {'100': 0, '200': 1, '400': 3}
    rate = rate_map.get(args.rate, 0)

    print(f"Monitoring MEAS{meas_nums} (Ctrl+C to stop)")
    print("=" * 60)

    try:
        sample = 0
        while True:
            print(f"\nSample {sample}:")
            for m in meas_nums:
                raw, capacitance, time_ms = fdc.single_shot_read(m, rate=rate)
                if raw is not None:
                    print(f"  MEAS{m}: {capacitance:12.4f} pF (0x{raw:06X}) [{time_ms:.0f}ms]")
                else:
                    print(f"  MEAS{m}: TIMEOUT")
            sample += 1
            time.sleep(args.delay)
    except KeyboardInterrupt:
        print("\n\nStopped")

    return 0


def cmd_characterize(args):
    """
    Characterize probe to find optimal CAPDAC and compare sample rates
    """
    fdc = init_device(args.addr, verbose=args.verbose)
    if not fdc:
        return 1

    meas_num = args.meas
    channel = args.channel

    print("=" * 60)
    print("=== FDC1004 Probe Characterization ===")
    print("=" * 60)

    # =========================================================================
    # Phase 1: Baseline Reading
    # =========================================================================
    print("\n--- Phase 1: Baseline Reading ---")
    print(f"Configuring MEAS{meas_num} with channel CIN{channel+1}, CAPDAC=0...")

    fdc.configure_measurement(meas_num, cha=channel, chb=FDC1004.CHB_DISABLED, capdac=0)

    # Take baseline samples at 100Hz (most stable)
    print("Taking baseline samples...")
    samples = fdc.take_samples(meas_num, n=20, delay=0.05, rate=FDC1004.RATE_100HZ, capdac=0)

    if not samples:
        print("ERROR: No valid readings - check connections")
        return 1

    stats = compute_stats(samples)
    print(f"  Capacitance: {stats['mean']:.4f} +/- {stats['std']:.4f} pF")
    print(f"  Range: [{stats['min']:.4f}, {stats['max']:.4f}] pF")

    baseline_cap = stats['mean']

    # Check if measurement is in range
    if baseline_cap < -15 or baseline_cap > 115:
        print(f"  WARNING: Measurement out of typical range (-15 to +115 pF)")
        print(f"  The FDC1004 measures -15pF to +115pF relative to CAPDAC offset")

    # =========================================================================
    # Phase 2: CAPDAC Sweep
    # =========================================================================
    print("\n--- Phase 2: CAPDAC Sweep ---")
    print("Finding optimal CAPDAC to center measurement range...")
    print()
    print("  CAPDAC adds offset: measured_cap = actual_cap - (CAPDAC * 3.125pF)")
    print("  Goal: Find CAPDAC that keeps raw reading near zero for best resolution")
    print()

    capdac_results = []
    optimal_capdac = None

    for capdac in range(32):
        fdc.configure_measurement(meas_num, cha=channel, chb=FDC1004.CHB_DISABLED, capdac=capdac)
        time.sleep(0.05)

        samples = fdc.take_samples(meas_num, n=5, delay=0.02, rate=FDC1004.RATE_100HZ, capdac=capdac)
        if not samples:
            continue

        stats = compute_stats(samples)
        offset_pf = capdac * 3.125

        # Raw reading (before adding CAPDAC offset back)
        raw_cap = stats['mean'] - offset_pf

        capdac_results.append({
            'capdac': capdac,
            'offset_pf': offset_pf,
            'capacitance': stats['mean'],
            'raw_cap': raw_cap,
            'std': stats['std']
        })

        print(f"    CAPDAC={capdac:2d} ({offset_pf:6.2f}pF): C={stats['mean']:8.4f}pF, raw={raw_cap:8.4f}pF, std={stats['std']:.4f}")

    # Find CAPDAC that gives raw reading closest to zero (best resolution)
    if capdac_results:
        best = min(capdac_results, key=lambda r: abs(r['raw_cap']))
        optimal_capdac = best['capdac']
        print(f"\n  Optimal CAPDAC: {optimal_capdac} ({optimal_capdac * 3.125:.2f}pF offset)")
        print(f"  Raw reading at optimal: {best['raw_cap']:.4f}pF")
    else:
        optimal_capdac = 0
        print("\n  WARNING: Could not determine optimal CAPDAC, using 0")

    # =========================================================================
    # Phase 3: Sample Rate Comparison
    # =========================================================================
    print("\n--- Phase 3: Sample Rate Comparison ---")
    print(f"Using CAPDAC={optimal_capdac}, comparing noise at different sample rates...")

    fdc.configure_measurement(meas_num, cha=channel, chb=FDC1004.CHB_DISABLED, capdac=optimal_capdac)

    rate_results = []
    rates = [
        (FDC1004.RATE_100HZ, "100Hz"),
        (FDC1004.RATE_200HZ, "200Hz"),
        (FDC1004.RATE_400HZ, "400Hz")
    ]

    for rate_val, rate_name in rates:
        samples = fdc.take_samples(meas_num, n=50, delay=0.02, rate=rate_val, capdac=optimal_capdac)
        if not samples:
            continue

        stats = compute_stats(samples)
        noise_ppm = (stats['std'] / stats['mean']) * 1e6 if stats['mean'] != 0 else 0

        rate_results.append({
            'rate': rate_name,
            'rate_val': rate_val,
            'mean': stats['mean'],
            'std': stats['std'],
            'noise_ppm': noise_ppm
        })

        print(f"    {rate_name}: mean={stats['mean']:.4f}pF, std={stats['std']:.6f}pF ({noise_ppm:.0f}ppm)")

    # Find best rate (lowest noise)
    if rate_results:
        best_rate = min(rate_results, key=lambda r: r['std'])
        print(f"\n  Best rate: {best_rate['rate']} (lowest noise)")

    # =========================================================================
    # Phase 4: Extended Validation
    # =========================================================================
    print("\n--- Phase 4: Extended Validation ---")
    print(f"Taking extended samples with optimal settings...")

    fdc.configure_measurement(meas_num, cha=channel, chb=FDC1004.CHB_DISABLED, capdac=optimal_capdac)

    # Use best rate or default to 100Hz
    best_rate_val = best_rate['rate_val'] if rate_results else FDC1004.RATE_100HZ

    samples = fdc.take_samples(meas_num, n=100, delay=0.02, rate=best_rate_val, capdac=optimal_capdac)
    stats = compute_stats(samples)
    noise_ppm = (stats['std'] / stats['mean']) * 1e6 if stats['mean'] != 0 else 0

    print(f"  Samples: {stats['count']}")
    print(f"  Mean: {stats['mean']:.4f} pF")
    print(f"  Std Dev: {stats['std']:.6f} pF ({noise_ppm:.0f} ppm)")
    print(f"  Range: [{stats['min']:.4f}, {stats['max']:.4f}] pF")
    print(f"  Span: {stats['max'] - stats['min']:.6f} pF")

    # =========================================================================
    # Final Recommendations
    # =========================================================================
    print("\n" + "=" * 60)
    print("=== RECOMMENDED CONFIGURATION ===")
    print("=" * 60)
    print(f"  Channel: CIN{channel+1}")
    print(f"  CAPDAC: {optimal_capdac} ({optimal_capdac * 3.125:.2f} pF offset)")
    if rate_results:
        print(f"  Rate: {best_rate['rate']}")
    print()
    print(f"  Expected capacitance: {stats['mean']:.4f} pF")
    print(f"  Expected noise: {stats['std']:.6f} pF ({noise_ppm:.0f} ppm)")
    print()

    # Command line for future use
    print("  Command to configure:")
    print(f"    python fdc1004_control.py config -m {meas_num} --cha {channel} --capdac {optimal_capdac}")
    print()
    print("  Command to read:")
    rate_str = best_rate['rate'].replace('Hz', '') if rate_results else '100'
    print(f"    python fdc1004_control.py read -m {meas_num} -n 10 --rate {rate_str}")

    # Output CSV if requested
    if args.output:
        import csv
        with open(args.output, 'w', newline='') as f:
            writer = csv.writer(f)

            writer.writerow(['Phase', 'Parameter', 'Value', 'Capacitance', 'StdDev'])

            for r in capdac_results:
                writer.writerow(['CAPDAC', r['capdac'], r['offset_pf'], r['capacitance'], r['std']])

            for r in rate_results:
                writer.writerow(['RATE', r['rate'], '', r['mean'], r['std']])

            writer.writerow(['FINAL', 'capdac', optimal_capdac, '', ''])
            writer.writerow(['FINAL', 'channel', channel, '', ''])
            writer.writerow(['VALIDATION', 'mean', stats['mean'], '', stats['std']])

        print(f"\n  Results saved to: {args.output}")

    return 0


def main():
    """Main CLI entry point"""
    parser = argparse.ArgumentParser(
        description='FDC1004 4-Channel Capacitance-to-Digital Converter I2C Helper Script via FT232H',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s info                          # Show device info and config
  %(prog)s reset                         # Reset FDC1004 device
  %(prog)s reset-ftdi                    # Reset FT232H USB adapter
  %(prog)s config -m 1 --cha 0 --capdac 10   # Configure MEAS1
  %(prog)s read -m 1 -n 10               # Read 10 samples from MEAS1
  %(prog)s read -m 1 -n 10 --configure   # Configure and read
  %(prog)s monitor -M 1 2                # Monitor MEAS1 and MEAS2
  %(prog)s characterize -c 0             # Characterize channel CIN1
  %(prog)s characterize -c 0 --output results.csv  # Save results to CSV
        """
    )

    parser.add_argument('-a', '--addr', type=lambda x: int(x, 0),
                       help='I2C address (default: 0x50)')
    parser.add_argument('-v', '--verbose', action='store_true',
                       help='Enable verbose output')

    subparsers = parser.add_subparsers(dest='command', help='Command to execute')

    # Info command
    subparsers.add_parser('info', help='Display device information and configuration')

    # Reset command
    parser_reset = subparsers.add_parser('reset', help='Reset the FDC1004 device')
    parser_reset.add_argument('--no-verify', action='store_true',
                             help='Skip post-reset verification')

    # Reset FTDI command
    subparsers.add_parser('reset-ftdi', help='Reset the FT232H USB adapter')

    # Config command
    parser_config = subparsers.add_parser('config', help='Configure measurement parameters')
    parser_config.add_argument('-m', '--meas', type=int, default=1, choices=[1, 2, 3, 4],
                              help='Measurement slot (1-4, default: 1)')
    parser_config.add_argument('--cha', type=int, default=0, choices=[0, 1, 2, 3],
                              help='Positive channel CINx (0-3, default: 0 for CIN1)')
    parser_config.add_argument('--chb', type=int, default=7, choices=[0, 1, 2, 3, 4, 7],
                              help='Negative channel (0-3=CINx, 4=CAPDAC, 7=disabled, default: 7)')
    parser_config.add_argument('--capdac', type=int, default=0,
                              help='CAPDAC offset 0-31 (each step = 3.125pF, default: 0)')

    # Read command
    parser_read = subparsers.add_parser('read', help='Read capacitance measurements')
    parser_read.add_argument('-m', '--meas', type=int, default=1, choices=[1, 2, 3, 4],
                            help='Measurement slot (1-4, default: 1)')
    parser_read.add_argument('-n', '--samples', type=int, default=10,
                            help='Number of samples (default: 10)')
    parser_read.add_argument('-d', '--delay', type=float, default=0.1,
                            help='Delay between samples in seconds (default: 0.1)')
    parser_read.add_argument('--rate', type=str, default='100', choices=['100', '200', '400'],
                            help='Sample rate in Hz (default: 100)')
    parser_read.add_argument('--configure', action='store_true',
                            help='Configure measurement before reading')
    parser_read.add_argument('--cha', type=int, default=0, choices=[0, 1, 2, 3],
                            help='Channel for configure (default: 0)')
    parser_read.add_argument('--capdac', type=int, default=0,
                            help='CAPDAC for configure (default: 0)')

    # Monitor command
    parser_monitor = subparsers.add_parser('monitor', help='Monitor multiple measurements')
    parser_monitor.add_argument('-M', '--measurements', type=int, nargs='+', choices=[1, 2, 3, 4],
                               help='Measurements to monitor (default: 1)')
    parser_monitor.add_argument('-d', '--delay', type=float, default=0.5,
                               help='Delay between readings in seconds (default: 0.5)')
    parser_monitor.add_argument('--rate', type=str, default='100', choices=['100', '200', '400'],
                               help='Sample rate in Hz (default: 100)')
    parser_monitor.add_argument('--configure', action='store_true',
                               help='Configure measurements before monitoring')
    parser_monitor.add_argument('--capdac', type=int, default=0,
                               help='CAPDAC for all measurements (default: 0)')

    # Characterize command
    parser_char = subparsers.add_parser('characterize',
                                        help='Characterize probe for optimal settings')
    parser_char.add_argument('-c', '--channel', type=int, default=0, choices=[0, 1, 2, 3],
                            help='Channel to characterize CINx (0-3, default: 0)')
    parser_char.add_argument('-m', '--meas', type=int, default=1, choices=[1, 2, 3, 4],
                            help='Measurement slot to use (default: 1)')
    parser_char.add_argument('--output', type=str, default=None,
                            help='Save results to CSV file')

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
        'monitor': cmd_monitor,
        'characterize': cmd_characterize,
    }

    return commands[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
