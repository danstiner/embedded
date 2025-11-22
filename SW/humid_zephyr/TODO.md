# TODO - nRF54 Soil Moisture Sensor

This document tracks remaining tasks and future improvements for the nRF54 soil moisture sensor project.

---

## Current Status

**Matter integration complete:**
- ✅ Matter/CHIP SDK integrated (C++17)
- ✅ Thread networking (OpenThread)
- ✅ BLE commissioning support
- ✅ MCUboot bootloader with OTA capability
- ✅ Internal temperature sensor accessible
- ✅ Compressed OTA images fit in internal flash

**Flash/RAM Usage:**

| Build Type | Flash   | RAM    | Compressed | Notes |
|------------|---------|--------|------------|-------|
| Debug      | 690 KB  | 158 KB | 359 KB     | Full logging, shell enabled |
| Release    | 505 KB  | 147 KB | 310 KB     | Production optimized |

**Partitions (Internal Flash):**
- MCUboot: 56KB
- Primary slot: 858KB
- Secondary slot: 564KB (compressed OTA images)
- Factory data: 4KB
- Settings: 40KB

---

## Immediate TODO

### Test OTA Updates
- [ ] Create test OTA image
- [ ] Flash via Matter OTA
- [ ] Verify MCUboot decompression and upgrade
- [ ] Test rollback on failure

### Add Sensor Integration
- [ ] Add I2C sensor driver (FDC2x1x capacitive moisture sensor)
- [ ] Integrate with Matter Temperature Measurement cluster
- [ ] Add custom Matter cluster for soil moisture (if needed)
- [ ] Periodic measurement with proper sleep/wakeup

### Battery Monitoring (Future)
- [ ] Re-add battery.cpp when needed
- [ ] Enable `CONFIG_APP_BATTERY_MONITORING=y`
- [ ] Restore ADC configuration in device tree
- [ ] Integrate with Matter Power Source cluster
- [ ] Implement low-battery deep sleep

---

## Optimization Ideas

### Power Optimization
- [ ] Implement proper sleep modes between measurements
- [ ] Minimize active time during measurements
- [ ] Target: <500µA average current

### Code Cleanup
- [ ] Add .clang-format for consistent style
- [ ] Review retained RAM usage (currently unused)
- [ ] Clean up unused device tree entries
- [ ] Add proper error handling throughout

### Flash Size Reduction (If Needed)
Current release build (505KB) fits comfortably. If more space needed:
- [ ] Remove Matter shell from release build
- [ ] Reduce Thread buffers further
- [ ] Investigate unused Matter clusters

---

## Future Enhancements

### Advanced Matter Features
- [ ] Add commissioning window timeout
- [ ] Implement factory reset via button
- [ ] Add diagnostic logs cluster
- [ ] Support multiple endpoints (multiple sensors)

### Field Deployment
- [ ] Add NVS for calibration data persistence
- [ ] Implement crash logging with retained RAM
- [ ] Add watchdog timer for reliability
- [ ] Production test mode

### Developer Experience
- [ ] Add unit tests for sensor drivers
- [ ] Document commissioning flow
- [ ] Add development scripts
- [ ] Create user manual

---

## Build Commands Reference

```bash
# Debug build (full logging)
west build -b nrf54l15dk/nrf54l15/cpuapp

# Release build (optimized)
west build -b nrf54l15dk/nrf54l15/cpuapp -- -DEXTRA_CONF_FILE=prj_release.conf

# Internal flash build (compressed OTA)
west build -b nrf54l15dk/nrf54l15/cpuapp -- -DFILE_SUFFIX=internal

# Flash
west flash

# Monitor serial
screen /dev/tty.usbmodem* 115200
```

---

## Notes

- Target device: nRF54L15 (1.5MB flash, 256KB RAM)
- Commissioning PIN: 20202021
- Discriminator: 3840 (0xF00)
- Vendor ID: 65521 (0xFFF1)
- Product ID: 32781 (0x800D)