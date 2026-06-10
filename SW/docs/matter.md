# Matter over Thread

Shared, board-agnostic guide for commissioning, updating, and troubleshooting the Matter
firmware in this repo. Board-specific build commands, KMU provisioning, and per-device
factory-data provisioning live in each board's own README (e.g.
[`hygrometer/README.md`](../hygrometer/README.md)).

## Onboarding / pairing codes

- **Per device (required):** the app image bakes in no identity — factory data is built
  separately (`SB_CONFIG_MATTER_FACTORY_DATA_GENERATE=n`) so flashing firmware never overwrites it.
  Each unit must have unique factory data generated and flashed with
  `tools/provisioning/provision.py` (see the board README's "Per-device Matter provisioning");
  the QR `.png` / manual code for each unit is written to `tools/provisioning/history/`. Until
  a unit is provisioned it has no factory data and will not commission.
- **Print from a running device** over the RTT/UART shell:
  ```shell
  uart:~$ matter onboardingcodes none
  ```

## Commissioning

1. **Flash** the device (use an RTT/UART logging build to watch commissioning).
2. **Power on** and wait for it to advertise.
3. **Open your Matter controller**:
   - Apple Home: Add Accessory → More Options → scan the QR code
   - Google Home: Add Device → Matter → scan the QR code
   - Home Assistant: Settings → Devices → Add → Matter (see the HA note below)
   - chip-tool: see below
4. **Follow the prompts** to join your Thread network (~30 s).

### Home Assistant — enable Test Net DCL for development devices

HA's Matter Server rejects **test/development certificates by policy**, so a dev build
fails right after attestation with:

> Device uses a test/development certificate. Enable the "Test Net DCL" option
> (`--enable-test-net-dcl`) to commission test or development devices.

The device's credentials are valid — this is purely an HA policy. Fix: HA → Settings →
Add-ons → **Matter Server** → Configuration → enable **Test Net DCL**
(`--enable-test-net-dcl`), then **restart** the add-on and re-commission. These boards use
the CSA **test** vendor ID `0xFFF1` + development certificates until certification, which
Apple/Google accept (with an "uncertified device" prompt) but HA gates behind this option.

### chip-tool setup (macOS)

`chip-tool` needs a developer profile for Bluetooth access:

1. Download and install the **"Bluetooth Central Matter Client Developer Mode"** profile:
   - https://developer.apple.com/bug-reporting/profiles-and-logs/
   - Install via System Settings → Privacy & Security → Profiles
2. **Restart** your Mac for the profile to take effect.
3. Grant Bluetooth permission to Terminal: System Settings → Privacy & Security →
   Bluetooth.

Reference: [Matter Darwin guide](https://github.com/project-chip/connectedhomeip/blob/master/docs/guides/darwin.md#using-chip-tool-on-macos-or-chip-tool-on-ios)

### chip-tool commissioning (BLE-Thread)

```bash
# Thread dataset from an already-joined device's shell:
uart:~$ ot dataset active -x

# Commission (replace passcode/discriminator with the unit's actual values):
chip-tool pairing ble-thread 1 hex:<thread-dataset> 20202021 3840
```

## OTA update via Matter

### Build an OTA image

1. Make your code changes.
2. Bump `VERSION`, then do a **pristine** build (the generated
   `CONFIG_MCUBOOT_IMGTOOL_SIGN_VERSION` defaults to `VERSION` but is not refreshed on an
   incremental build).
3. The OTA image is at `build/matter.ota`.

### Method 1 — chip-ota-provider-app (recommended)

```bash
# 1. Start the provider on your machine
chip-ota-provider-app --filepath build/matter.ota

# 2. Commission the provider to the same fabric (node id 2)
chip-tool pairing onnetwork 2 20202021

# 3. Grant ACL so devices can reach the provider
chip-tool accesscontrol write acl \
  '[{"fabricIndex": 1, "privilege": 5, "authMode": 2, "subjects": [112233], "targets": null},
    {"fabricIndex": 1, "privilege": 3, "authMode": 2, "subjects": null, "targets": null}]' \
  2 0

# 4. Point the device (node 1) at the provider and announce it
chip-tool otasoftwareupdaterequestor write default-otaproviders \
  '[{"fabricIndex": 1, "providerNodeID": 2, "endpoint": 0}]' 1 0
chip-tool otasoftwareupdaterequestor announce-otaprovider 2 0 0 0 1 0

# 5. Verify after the device reboots
chip-tool basicinformation read software-version 1 0
chip-tool basicinformation read software-version-string 1 0
```

Monitor progress on the device console: `[OTA] QueryImage sent` → `Downloaded …` →
`[MCUboot] Swap successful` → `Rebooting...`.

### Method 2 — chip-tool directly

```bash
chip-tool otasoftwareupdaterequestor read update-state-progress 1 0
chip-tool otasoftwareupdaterequestor announce-ota-provider \
  <provider-node-id> 0 0 0 <device-node-id> 0
```

### What happens

Query → download to external flash (~1–5 min) → MCUboot verifies signature + checksum →
swap on reboot → new firmware confirms (marks permanent). MCUboot **auto-rolls back** if
the new image fails verification, crashes on boot, or doesn't confirm within the boot
cycle. Manual rollback: `uart:~$ mcuboot confirm 0`.

### OTA troubleshooting

- **Update not starting** — device commissioned/operational? provider on the same fabric
  (`chip-tool pairing onnetwork-long 2 20202021 0`)? ACL set? check device logs.
- **Download fails** — Thread up (`uart:~$ ot state`)? external flash OK (MX25R64 in
  logs)? room in the secondary slot?
- **Reboots but still old version** — MCUboot swap failed / signature invalid / firmware
  didn't confirm (boot crash). Check boot logs.

## Troubleshooting commissioning

### Joins Thread but commissioning times out

Symptoms: `[SVR]Operational advertising failed: 3`, `[BLE]ack recv timeout, closing ep`.

1. **Thread Border Router not reachable** — verify your BR (Google Nest, Apple HomePod,
   HA Thread BR, …) is online and on the same network as the controller;
   `uart:~$ ot state` should show `child` or `router`.
2. **IPv6 connectivity** — device gets an address but the controller can't reach it; check
   logs for `fd42:` addresses; `uart:~$ ot ipaddr` should list several.
3. **SRP registration timing** — look for `SRP update succeeded`; if missing, the Thread
   network may lack an SRP server.
4. **Factory reset and retry** — `uart:~$ matter factoryreset`, then reflash + recommission.
5. **Commissioner logs** — iOS/Home: Console.app; Android: `adb logcat | grep -i matter`;
   chip-tool: add `-v`.

### Commissions but not controllable

```shell
uart:~$ matter dns browse _matter._tcp   # should show the node advertising
uart:~$ ot ping <border-router-ip>
```

### Won't enter commissioning mode

```shell
uart:~$ matter ble adv start
uart:~$ matter factoryreset   # if needed
```

### Diagnostic commands

```shell
uart:~$ matter config          # fabric id (non-zero if commissioned), node id, CASE
uart:~$ ot state               # child / router / leader
uart:~$ ot ipaddr              # all IPv6 addresses
uart:~$ ot neighbor table      # Thread neighbors
uart:~$ ot netdata show        # network data
uart:~$ dns service            # registered SRP/DNS-SD services
uart:~$ matter dns resolve <node-id>
```

Full sequence: `ot state` → `ot ipaddr` → `matter config` → `ot ping <BR-ip>` →
`dns service` → (if all fails) `matter factoryreset`.
