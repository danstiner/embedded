# nRF54 Humidity Sensor

Low power sensor for relative humidity, temperature, and water leaks utilizing the nRF54L15 microcontroller.

## Hardware

The `bl54l15u_hygrometer` board has two hardware revisions:

- **2026v4** (default): Resistive water-leak sensor, SHT4x, buzzer, CR2 lithium battery
- **2026v3**: SHT4x, optional BME688/STCC4, nPM2100 PMIC + 2×AAA alkaline

This project also can be used with the BL54L15u DevKit.

## Build Instructions

Debug build advertising over BLE in the BTHome format, with RTT logging:
```sh
west build -b bl54l15u_hygrometer/nrf54l15/cpuapp -p -- -DBOARD_ROOT=.. -DEXTRA_CONF_FILE=prj_extra_rtt.conf -Dmcuboot_EXTRA_CONF_FILE="$(pwd)/sysbuild/mcuboot.conf;$(pwd)/sysbuild/mcuboot_extra_rtt.conf"
```

Release build with reduced power use:
```sh
west build -b bl54l15u_hygrometer/nrf54l15/cpuapp -p -- -DBOARD_ROOT=.. -DEXTRA_CONF_FILE=prj_extra_release.conf
```

Matter over Thread release build (instead of BTHome BLE advertising):

```sh
west build -b bl54l15u_hygrometer/nrf54l15/cpuapp -p -- -DBOARD_ROOT=.. -DEXTRA_CONF_FILE="prj_extra_release.conf;prj_extra_matter.conf" -DSB_EXTRA_CONF_FILE=sysbuild_extra_matter.conf -DEXTRA_DTC_OVERLAY_FILE=boards/matter.overlay
```

## Deployment

### KMU Provisioning

Provision signing keys to the hardware KMU before first boot. See [`keys/README.md`](../keys/README.md) for details.

```sh
(cd .. && west ncs-provision upload -i keys/provision-dev.yml)
```

### Flashing

```bash
west flash
```

## BTHome

### OTA update

Build a new image, then flash it wirelessly using the SMP BLE transport:
```bash
uv run ../ota.py flash --confirm
```

## Matter

### Provisioning

Per-device identity and other information must be flashed to the factory-data partition using the
provisioning tool [`../tools/matter/provisioning/provision.py`](../tools/matter/provisioning/provision.py):

```sh
python ../tools/matter/provisioning/provision.py --build-dir build --flash
```

It reads the product ID / names / partition offset from the build, assigns a sequential
serial (`SN-0001`, …), randomizes discriminator/passcode/salt/unique-ID, and writes the
hex, QR `.png`, onboarding `.txt`, and a `provisioning_log.csv` to the gitignored
`SW/tools/matter/provisioning/history/`. `--flash` programs the `factory_data` partition. To re-identify
an already-paired unit, re-provision it, run `matter factoryreset` on the device console, and
remove the stale device entry from the controller.

Commissioning, OTA-over-Matter, and Matter/Thread troubleshooting are board-agnostic and
documented in the shared guide: [`../docs/matter.md`](../docs/matter.md).

### Regenerating the Matter data model (ZAP)

The CO2 (2026v3) and leak (2026v4) builds use separate data models. After editing a
`.zap` (e.g. with `west zap-gui -z src/default_zap/v3/hygrometer.zap`), regenerate just
that revision so the other stays byte-identical:

```sh
west zap-generate -z src/default_zap/v3/hygrometer.zap
```

Omitting `-z` prompts interactively because both revisions ship a `.zap`. Commit the
regenerated `zap-generated/` files and `hygrometer.matter` alongside the `.zap`.

## Calibrating the CO2 sensor

The STCC4 (2026v3 only) self-calibrates given weekly fresh-air exposure; frequent
power-cycling or reflashing can leave it reading with a fixed offset. The Matter *CO₂ sensor*
select (Mode Select, endpoint 1) mirrors the live operation — it holds the in-progress state
until the operation (warm-up included) finishes, then returns to *Measure*, and rejects a
concurrent request. Recalibration is also triggerable over BTHome by writing the
CO2-calibration GATT characteristic (`a1b2c3d4-…-781`; empty for the default target, or a
2-byte little-endian ppm override):

- **Recalibrate (outdoor air)** — leave the device in stable outdoor shade (>~10 °C) for an
  hour, then select this. Non-destructive; forces the reading to
  `CONFIG_APP_CO2_RECAL_TARGET_PPM` (default 430 ppm) after 30 readings at the CO2 read
  interval (~60 min with the release overlay).
- **Factory Reset** — recovery for a unit stuck at the 380 ppm floor. Destructive: wipes
  calibration history and runs a ~12 h warm-up (`CONFIG_APP_CO2_WARMUP_MIN`), abandoned on reboot.

## References

- [nRF54L15 Product Specification](https://infocenter.nordicsemi.com/topic/ps_nrf54l15/index.html)
- [Zephyr ADC API](https://docs.zephyrproject.org/latest/hardware/peripherals/adc.html)
- [Zephyr Power Management](https://docs.zephyrproject.org/latest/services/pm/index.html)
