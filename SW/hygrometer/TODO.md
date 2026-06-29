# TODO

## Matter (deferred parity work)
- [x] Power Source cluster (0x002F): `BatChargeLevel` ← `battery.health`, `BatVoltage` ←
      `battery.millivolts` (+ `BatPercentRemaining` on v3 only). Per-revision zap split.
- [x] Boolean State cluster (0x0045) for water leak ← `leak.wet` (v4, Water Leak
      Detector EP2, immediate ISR report via `BooleanState::FindClusterOnEndpoint`).
- [x] Home Assistant commissioning: **not a device issue.** The device's dev
      credentials are valid (DAC 0xFFF1/0x800D; built-in CD covers 0x8000-0x8063 incl.
      0x800D) — Google/Apple accept it. HA's matter.js server rejects test/development
      certificates **by policy**; fix is HA-side: enable **Test Net DCL**
      (`--enable-test-net-dcl`) in the Matter Server add-on config, then re-commission.
      Production swaps the test VID/dev-PAA/built-in-CD for a real CSA VID + DCL-registered
      PAA + per-device DAC (KMU) + CSA-signed CD — wiring unchanged.

## Debug / tooling
- [ ] **Resolve RTT channels for the Matter debug build.** `prj_extra_rtt.conf` puts the
      shell on RTT buffer 1 (`CONFIG_SHELL_BACKEND_RTT_BUFFER=1`) and logs on buffer 0,
      so VS Code / JLinkExe (channel 0) show logs but can't reach the shell prompt
      (`rtt:~$`). Want a Matter-friendly RTT overlay that puts shell+logs on channel 0
      (shell carries logs via `CONFIG_SHELL_LOG_BACKEND`, drop separate `RTT_CONSOLE`/
      `LOG_BACKEND_RTT`) so JLinkRTTViewer/RTTClient input works without disturbing the
      shared BTHome `prj_extra_rtt.conf`. Also `west rtt` errors `[Errno 22]` on macOS —
      use JLinkRTTViewer instead.

## Upstream (sdk-nrf)
- [ ] **`E: LED index out of the range` at boot (cosmetic).** The Matter samples-common
      board layer (`nrf/samples/matter/common/src/board/board.cpp:41,104,116,129`)
      initializes/iterates `mLED2` unconditionally; only LED3/LED4 have
      `#if NUMBER_OF_LEDS >= 3/4` guards. On our 1-LED board `dk_set_led(1, …)` fails its
      range check and logs the error at boot and during the factory-reset blink. Harmless
      (returns `-EINVAL`, LED2 is never used). Proper fix is an upstream PR adding
      `#if NUMBER_OF_LEDS >= 2` guards — not patching our NCS checkout locally.

## NCS 3.3.0 migration follow-ups
- [ ] Partition Manager is deprecated in 3.3.0 — migrate to Zephyr-native DT partitions eventually
- [ ] Confirm devkit + nrf54l15dk variants still green in CI on 3.3.0

## Hardware (2026v4)
- [ ] Drive the buzzer/siren (P2.05) on leak — currently reserved/stub (`CONFIG_APP_BUZZER`)
- [ ] Calibrate CR2 battery curve / health thresholds against a real discharge log
