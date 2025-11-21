# nRF54 Soil Moisture Sensor

Low power humidity and water sensor utilizing the nRF54L15.

## Hardware Requirements

### Development Board
- nRF54L15 DK (PCA10156)

## Build Instructions

### Prerequisites
- nRF Connect SDK v2.6.0 or later installed

### Build

**Debug build** (with logging and console):
```bash
west build -b nrf54l15dk/nrf54l15/cpuapp
```

**Release build** (optimized for low power):
```bash
west build -b nrf54l15dk/nrf54l15/cpuapp -- -DEXTRA_CONF_FILE=prj_release.conf
```

**Internal build** (only uses internal storage)

For the nRF54L15, we can skip external storage and use the internal 1.5MB RRAM for both boot slots.

To enable this, set the ``FILE_SUFFIX`` CMake option to ``internal``.
```bash
west build -b nrf54l15dk/nrf54l15/cpuapp -- -DFILE_SUFFIX=internal
```

### Flash
```bash
west flash
```

### Monitor
```bash
# Linux
screen /dev/ttyACM0 115200

# macOS (find port with: ls /dev/tty.usbmodem*)
screen /dev/tty.usbmodem0010577860871 115200
```

## Matter Commissioning

### Setup Credentials

**QR Code**: `MT:W0GU2OTB00KA0648G00`
**Manual Pairing Code**: `34970112332`
**Setup PIN**: `20202021`
**Discriminator**: `3840`

### Commissioning Instructions

1. **Flash the device** with debug build to see commissioning logs
2. **Power on** and wait for device to start advertising
3. **Open your Matter controller app**:
   - Apple Home: Add Accessory → More Options → scan QR code
   - Google Home: Add Device → Matter → scan QR code
   - chip-tool: `chip-tool pairing ble-thread <node-id> hex:<thread-dataset> 20202021 3840`

4. **Follow the prompts** to join your Thread network
5. **Wait for commissioning to complete** (~30 seconds)

### Viewing Commissioning Info

Use the Matter CLI shell to print onboarding codes:
```shell
uart:~$ matter onboardingcodes none
QRCode:             MT:W0GU2OTB00KA0648G00
QRCodeUrl:          https://project-chip.github.io/connectedhomeip/qrcode.html?data=MT%3AW0GU2OTB00KA0648G00
ManualPairingCode:  34970112332
```

### Accessing Temperature Data

Once commissioned, the device exposes:
- **Temperature Measurement Cluster** (0x0402) on Endpoint 0
- **MeasuredValue** attribute: Temperature in 0.01°C units (e.g., 2534 = 25.34°C)
- Updates every 5 seconds (debug) or 5 minutes (release)

## Over-The-Air (OTA) Updates

The device supports Matter OTA updates using the external flash (MX25R64) for staging new firmware.

### Configuration

OTA is enabled by default with:
- **Secondary slot**: External flash (1.4 MB, same as primary)
- **No compression**: Simple swap-based update
- **Power consumption**: <1µA when idle, ~5-15mA during download (rare event)

### Building an OTA Update

1. **Make your code changes**

2. **Increment version** in `VERSION` file:
   ```bash
   echo "1.1.0" > VERSION
   ```

3. **Build with new version**:
   ```bash
   west build -b nrf54l15dk/nrf54l15/cpuapp -p -- \
     -DEXTRA_CONF_FILE=prj_release.conf \
     -DCONFIG_MCUBOOT_IMGTOOL_SIGN_VERSION='"1.1.0"'
   ```

4. **OTA image location**:
   ```
   build/zephyr/matter.ota
   ```

### Performing OTA Update via Matter

#### Prerequisites
- Device commissioned and operational on Thread network
- `chip-tool` or `chip-ota-provider-app` installed
- Matter OTA image file (`matter.ota`)

#### Method 1: Using chip-ota-provider-app (Recommended)

1. **Start the OTA provider** on your development machine:
   ```bash
   chip-ota-provider-app --filepath build/zephyr/matter.ota --port 5580
   ```

2. **Commission the OTA provider** to the same Matter fabric (use node ID 2):
   ```bash
   chip-tool pairing onnetwork 2 20202021
   ```

3. **Configure ACL** to allow devices to access the provider:
   ```bash
   chip-tool accesscontrol write acl \
     '[{"fabricIndex": 1, "privilege": 5, "authMode": 2, "subjects": [112233], "targets": null},
       {"fabricIndex": 1, "privilege": 3, "authMode": 2, "subjects": null, "targets": null}]' \
     2 0
   ```

4. **Announce the OTA provider** to your device (assuming device is node 1):
   ```bash
   chip-tool otasoftwareupdaterequestor announce-ota-provider 2 0 0 0 1 0
   ```

5. **Monitor the update** via device serial console:
   ```bash
   screen /dev/tty.usbmodem* 115200
   ```

   Expected output:
   ```
   [OTA] QueryImage sent to provider
   [OTA] Image available, starting download
   [OTA] Downloaded 1024/524288 bytes
   ...
   [OTA] Download complete
   [OTA] Applying update...
   [MCUboot] Starting swap using external flash
   [MCUboot] Swap successful
   Rebooting...
   ```

6. **Verify new version** after reboot:
   ```bash
   chip-tool basicinformation read software-version 1 0
   chip-tool basicinformation read software-version-string 1 0
   ```

#### Method 2: Using chip-tool directly

```bash
# Query current software version
chip-tool otasoftwareupdaterequestor read update-state-progress 1 0

# Trigger update check
chip-tool otasoftwareupdaterequestor announce-ota-provider \
  <provider-node-id> 0 0 0 <device-node-id> 0
```

### OTA Update Process

1. **Query**: Device queries OTA provider for available updates
2. **Download**: Device downloads image to external flash (~1-5 minutes)
3. **Verification**: MCUboot verifies signature and checksum
4. **Swap**: MCUboot swaps primary/secondary slots on reboot
5. **Confirm**: New firmware confirms update, marks image as permanent

### Troubleshooting OTA

#### Update not starting
- Check device is commissioned and operational
- Verify OTA provider is on same fabric: `chip-tool pairing onnetwork-long 2 20202021 0`
- Check ACL permissions are set correctly
- Monitor device logs for error messages

#### Download fails
- Check Thread network connectivity: `uart:~$ ot state`
- Verify external flash is working: Check MX25R64 status in logs
- Ensure sufficient space in secondary slot

#### Device reboots but still on old version
- MCUboot swap failed - check boot logs
- Image verification failed - check signature
- New firmware didn't confirm - possible boot crash

#### Rollback to previous version
MCUboot automatically rolls back if new firmware:
- Fails signature verification
- Crashes during boot
- Doesn't confirm the update within boot cycle

To manually trigger rollback (via serial console):
```bash
uart:~$ mcuboot confirm 0  # Reject current, revert to previous
```

### OTA Power Consumption

For battery-powered deployment:
- **Idle**: <1µA (external flash in deep power-down)
- **During OTA download**: ~5-15mA for 1-5 minutes (rare event)
- **Annual impact**: Negligible for 1-2 updates per year

## Power Management

### Normal Operation (Battery Good)

The device operates in a periodic measurement cycle:
1. **Boot/Wakeup**: Initialize peripherals and check retained RAM
2. **Measure**: Read temperature and battery voltage (~5-10ms active)
3. **Sleep**: Enter System OFF mode for 300 seconds (<5µA)
4. **Repeat**: GRTC timer wakes device for next measurement

## Configuration

### Measurement Interval

Edit `prj.conf` or `prj_release.conf`:
```
CONFIG_APP_MEASUREMENT_INTERVAL_SEC=300   # 5 minutes
```

Or override via Kconfig menuconfig.

### Voltage Divider

Edit `nrf54l15dk_nrf54l15_cpuapp.overlay`:
```dts
vbatt {
    output-ohms = <22000000>;  /* R (lower resistor) */
    full-ohms = <44000000>;    /* 2×R (total) */
};
```

### ADC Pin

Edit `nrf54l15dk_nrf54l15_cpuapp.overlay`:
```dts
&adc {
    channel@0 {
        zephyr,input-positive = <NRF_SAADC_AIN0>;  /* P0.00 - change as needed */
    };
};
```

## Project Structure

```
nrf54_soil/
├── CMakeLists.txt                         # Build configuration
├── Kconfig                                # Application Kconfig options
├── prj.conf                               # Debug config (full logging)
├── prj_release.conf                       # Release config (power optimized)
├── nrf54l15dk_nrf54l15_cpuapp.overlay    # Device tree (ADC, retention RAM)
├── src/
│   ├── main.c                            # Main app with System OFF loop
│   ├── battery.c                         # Battery monitoring
│   ├── battery.h                         # Battery API
│   ├── retained.c                        # Retained RAM management
│   └── retained.h                        # Retained data structure
├── VERSION                                # Version tracking
└── README.md                             # This file
```

## Troubleshooting

### Matter Commissioning Issues

#### Device joins Thread but commissioning times out

**Symptoms**:
```
[SVR]Operational advertising failed: 3
[BLE]ack recv timeout, closing ep
```

**Possible causes**:

1. **Thread Border Router not reachable**
   - Verify your Thread Border Router (Google Nest, Apple HomePod, etc.) is online
   - Check that the Border Router is on the same network as your controller
   - Try: `uart:~$ ot state` should show `child` or `router`

2. **IPv6 connectivity issue**
   - Device gets IPv6 address but controller can't reach it
   - Check logs for `fd42:` prefix addresses
   - Verify: `uart:~$ ot ipaddr` shows multiple IPv6 addresses

3. **SRP registration timing**
   - Device advertises before SRP registration completes
   - Look for `SRP update succeeded` in logs
   - If missing, Thread network may not have SRP server

4. **Factory reset and retry**
   ```shell
   uart:~$ matter factoryreset
   ```
   Then flash again and recommission

5. **Check commissioner logs**
   - iOS/Home app: Check Console app for errors
   - Android: Use `adb logcat | grep -i matter`
   - chip-tool: Add `-v` for verbose output

#### Commissioning succeeds but device not controllable

**Check operational discovery**:
```shell
uart:~$ matter dns browse _matter._tcp
```

Should show the device advertising with node ID.

**Verify network connectivity**:
```shell
uart:~$ ot ping <border-router-ip>
```

#### Device won't enter commissioning mode

**Check BLE advertising**:
```shell
uart:~$ matter ble adv start
```

**Factory reset if needed**:
```shell
uart:~$ matter factoryreset
```

### Commissioning Diagnostic Commands

**Check if device is commissioned**:
```shell
uart:~$ matter config
```
Look for:
- Fabric ID (should be non-zero if commissioned)
- Node ID
- Case Session Established

**Check Thread status**:
```shell
uart:~$ ot state          # Should show: child, router, or leader
uart:~$ ot ipaddr         # List all IPv6 addresses
uart:~$ ot neighbor table # Show Thread neighbors
uart:~$ ot netdata show   # Show network data
```

**Check SRP/DNS-SD status**:
```shell
uart:~$ dns service       # Show registered services
```

**Check operational advertising**:
```shell
uart:~$ matter dns resolve <node-id>
```

**Full diagnostic sequence**:
```shell
# 1. Check Thread attachment
uart:~$ ot state
uart:~$ ot ipaddr

# 2. Check Matter status
uart:~$ matter config

# 3. Ping Thread Border Router
uart:~$ ot ping fd42:77ca:5825::1

# 4. Check SRP
uart:~$ dns service

# 5. If all fails, factory reset
uart:~$ matter factoryreset
```

### ADC reads 0V or wrong voltage
- Check voltage divider resistors (should be 100K + 100K)
- Verify ADC pin connection (P0.00 = AIN0)
- Measure actual voltage at ADC pin (should be battery/2)
- Check battery is connected

### Immediate deep sleep on boot
- Battery voltage is below 2.7V
- ADC calibration issue
- Check voltage divider calculation in code

### No LED blinking
- Check if DK has led0 alias defined
- LED feature is optional, won't affect functionality
- Check DK schematic for LED GPIO

### Build errors
- Ensure nRF Connect SDK v2.6.0+ is installed
- Verify ZEPHYR_BASE environment variable
- Try clean build: `west build -p`

## Power Consumption

### System OFF Deep Sleep Mode

**Release build** (prj_release.conf) with 300 second measurement interval:
- **Sleep**: <5µA (System OFF mode)
- **Active**: ~1-2mA for ~10ms (CPU + ADC + temperature sensor)
- **Average**: ~5-10µA overall
- **Voltage divider leakage**: 95nA (22MΩ resistors)

**Debug build** (prj.conf):
- **Sleep**: <5µA (System OFF mode)
- **Active**: ~3mA for ~50ms (CPU + ADC + UART logging)
- **Average**: ~10-20µA overall

### Memory Usage

- **Debug build**: 61KB ROM, 14KB RAM
- **Release build**: 46KB ROM, 11KB RAM (25% smaller)

### Battery Life Estimates

With 2000mAh Li-ion battery and 300 second (5 minute) measurement interval:

**Release build**:
- Current draw: ~8µA average
- **Battery life: ~25 years** (limited by battery self-discharge, not system consumption)

**Debug build** (for development):
- Current draw: ~15µA average
- **Battery life: ~15 years**

Real-world battery life will be limited by battery self-discharge (~2-3% per month) rather than system power consumption.

## References

- [nRF54L15 Product Specification](https://infocenter.nordicsemi.com/topic/ps_nrf54l15/index.html)
- [Zephyr ADC API](https://docs.zephyrproject.org/latest/hardware/peripherals/adc.html)
- [Zephyr Power Management](https://docs.zephyrproject.org/latest/services/pm/index.html)
