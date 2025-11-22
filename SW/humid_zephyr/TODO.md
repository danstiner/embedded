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

---

## Immediate TODO

### Test OTA Updates
- [ ] Create test OTA image
- [ ] Flash via Matter OTA
- [ ] Verify MCUboot decompression and upgrade
- [ ] Test rollback on failure

### Humdity Sensor Integration
- [ ] Add I2C sensor driver (Some sensiron humdity sensor)
- [ ] Integrate with Matter Temperature/Humidity Measurement cluster

### Battery Monitoring
- [ ] Using nordic PMIC

---

## Further Ideas

### Power Optimization
- [ ] Implement deep sleep between measurements
- [ ] Minimize active time during measurements
- [ ] Add retained RAM
- [ ] Target: <500µA average current

### Code Cleanup
- [ ] Add .clang-format for consistent style
- [ ] Clean up unused device tree entries
- [ ] Add proper error handling throughout

### Advanced Matter Features
- [ ] Implement factory reset via button
- [ ] Status LED
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
