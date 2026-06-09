# nRF54 Humidity Sensor

Low power sensor for relative humidity, temperature, and water leaks utilizing the nRF54L15 microcontroller.

## Hardware Requirements

### Development Board
- BL54L15u Hygrometer or BL54L15u DevKit

### Hygrometer board revisions
The `bl54l15u_hygrometer` board has two hardware revisions.

- **2026v4** (default): CR2 coin cell (no PMIC — battery measured via SAADC),
  SHT4x only, adds a resistive water-leak sensor (reported as BTHome moisture
  `0x20`) and a buzzer pin (reserved, not yet driven).
- **2026v3**: nPM2100 PMIC + 2×AAA alkaline, SHT4x, optional BME688/STCC4. Build
  with `bl54l15u_hygrometer@2026v3/nrf54l15/cpuapp`.

> Note: the example commands below omit `@<revision>` and therefore build for the
> default **2026v4** hardware. Add `@2026v3` to target the older board.

## Build Instructions

### Builds

Base build advertising over BLE in the BTHome format, with RTT logging:
```sh
west build -b bl54l15u_hygrometer/nrf54l15/cpuapp -p -- -DBOARD_ROOT=.. -DEXTRA_CONF_FILE=prj_extra_rtt.conf -Dmcuboot_EXTRA_CONF_FILE=$(pwd)/sysbuild/mcuboot_extra_rtt.conf
```

Release mode with reduced power use:
```sh
west build -b bl54l15u_hygrometer/nrf54l15/cpuapp -p -- -DBOARD_ROOT=.. -DEXTRA_CONF_FILE=prj_extra_release.conf
```

2026v4 hardware (CR2 + leak sensing) over BTHome, with RTT logging:
```sh
west build -b bl54l15u_hygrometer@2026v4/nrf54l15/cpuapp -p -- -DBOARD_ROOT=.. -DEXTRA_CONF_FILE=prj_extra_rtt.conf -Dmcuboot_EXTRA_CONF_FILE=$(pwd)/sysbuild/mcuboot_extra_rtt.conf
```

Matter over Thread mode (instead of BTHome BLE advertising). Each board revision uses
its own data model (the v4 board has a leak sensor but no pressure/CO2; v3 is the
reverse). The model — product ID, name, and `.zap` — is selected **automatically from the
board revision** in Kconfig, so the same `prj_extra_matter.conf` works for both; just pick
the matching `@2026v3`/`@2026v4` board target:

2026v4 (temperature + humidity + **leak** + battery):
```sh
west build -b bl54l15u_hygrometer@2026v4/nrf54l15/cpuapp -p -- -DBOARD_ROOT=.. -DEXTRA_CONF_FILE="prj_extra_release.conf;prj_extra_matter.conf" -DSB_EXTRA_CONF_FILE=sysbuild_extra_matter.conf -DEXTRA_DTC_OVERLAY_FILE=boards/matter.overlay
```

2026v3 (temperature + humidity + **pressure** + **CO2** + battery):
```sh
west build -b bl54l15u_hygrometer@2026v3/nrf54l15/cpuapp -p -- -DBOARD_ROOT=.. -DEXTRA_CONF_FILE="prj_extra_release.conf;prj_extra_matter.conf" -DSB_EXTRA_CONF_FILE=sysbuild_extra_matter.conf -DEXTRA_DTC_OVERLAY_FILE=boards/matter.overlay
```

> The commands above use `prj_extra_release.conf`, which **disables logging** (and RTT)
> for low power. To see boot/commissioning/sensor logs over RTT, **drop**
> `prj_extra_release.conf` and **add** `prj_extra_rtt.conf` — e.g. for 2026v4:
> ```sh
> west build -b bl54l15u_hygrometer@2026v4/nrf54l15/cpuapp -p -- -DBOARD_ROOT=.. -DEXTRA_CONF_FILE="prj_extra_matter.conf;prj_extra_rtt.conf" -DSB_EXTRA_CONF_FILE=sysbuild_extra_matter.conf -DEXTRA_DTC_OVERLAY_FILE=boards/matter.overlay
> ```
> Then attach with `JLinkRTTViewer` (or `west rtt` if configured).

Commissioning, OTA-over-Matter, and Matter/Thread troubleshooting are board-agnostic and
documented in the shared guide: [`../docs/matter.md`](../docs/matter.md).

### KMU Provisioning

Provision signing keys to the hardware KMU before first boot. See [`keys/README.md`](../keys/README.md) for details.

```sh
(cd .. && west ncs-provision upload -i keys/provision-dev.yml)
```

### Per-device Matter provisioning (unique identity / QR)

Every Matter build bakes in the **same** default identity (serial, discriminator,
passcode, unique ID), so multiple units commission as — and get merged into — a single
device in controllers like Home Assistant. To give each unit its own identity and pairing
QR code, build the firmware once, then generate + flash a unique factory-data partition
per device with the shared tool [`../tools/provisioning/provision.py`](../tools/provisioning/provision.py):

```sh
python ../tools/provisioning/provision.py --build-dir build-matter-v4-dbg          # generate only
python ../tools/provisioning/provision.py --build-dir build-matter-v4-dbg --flash  # + flash this unit
```

It reads the product ID / names / partition offset from the build, assigns a sequential
serial (`BB-0001`, …), randomizes discriminator/passcode/salt/unique-ID, and writes the
hex, QR `.png`, onboarding `.txt`, and a `provisioning_log.csv` to the gitignored
`SW/tools/provisioning/history/`. Re-flashing a unit? Pass `--sn BB-0001` to keep its
identity/QR instead of minting a new serial. `--flash` programs only the `factory_data`
partition (firmware
untouched). The development DAC stays shared per product ID — only the identity changes
(production swaps in per-device DACs + a CSA CD).

Typical flow per board: `west flash --erase` (firmware) → `provision.py … --flash` →
power-cycle → commission. To re-identify an already-paired unit, re-provision it, run
`matter factoryreset`, and remove the stale device entry from the controller.

### Flash

```bash
west flash
```

### OTA update (BTHome build)

Build a new image, then flash it wirelessly using the SMP BLE transport:
```bash
uv run ../ota.py flash --confirm
```

## Development

### Modify Matter Clusters

There are two per-revision data models under `src/default_zap/`: `v3/` (temperature,
humidity, pressure, CO2, battery) and `v4/` (temperature, humidity, leak, battery). Edit
the one matching the board you are changing.

Open the ZAP GUI on that model's `.zap`:

```bash
west zap-gui src/default_zap/v4/hygrometer.zap    # or v3/hygrometer.zap
```

After saving changes in the GUI, regenerate that model's source files (the generated dir
must sit next to the `.zap`, as `<dir>/zap-generated`):

```bash
west zap-generate -z src/default_zap/v4/hygrometer.zap -o src/default_zap/v4/zap-generated
west zap-generate -z src/default_zap/v3/hygrometer.zap -o src/default_zap/v3/zap-generated
```

## Troubleshooting

Matter/Thread commissioning issues and diagnostic shell commands (`matter config`,
`ot state`, factory reset, etc.) are in the shared guide:
[`../docs/matter.md`](../docs/matter.md#troubleshooting-commissioning).

### No LED blinking
- Check if DK has led0 alias defined
- LED feature is optional, won't affect functionality
- Check DK schematic for LED GPIO

## References

- [nRF54L15 Product Specification](https://infocenter.nordicsemi.com/topic/ps_nrf54l15/index.html)
- [Zephyr ADC API](https://docs.zephyrproject.org/latest/hardware/peripherals/adc.html)
- [Zephyr Power Management](https://docs.zephyrproject.org/latest/services/pm/index.html)
