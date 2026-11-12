# TODO

## Upstream (sdk-nrf)
- [ ] **`E: LED index out of the range` at boot (cosmetic).** The Matter samples-common
      board layer (`nrf/samples/matter/common/src/board/board.cpp:41,104,116,129`)
      initializes/iterates `mLED2` unconditionally; only LED3/LED4 have
      `#if NUMBER_OF_LEDS >= 3/4` guards. On our 1-LED board `dk_set_led(1, …)` fails its
      range check and logs the error at boot and during the factory-reset blink. Harmless
      (returns `-EINVAL`, LED2 is never used). Proper fix is an upstream PR adding
      `#if NUMBER_OF_LEDS >= 2` guards — not patching our NCS checkout locally.
 - [ ] Check if we can use the stcc4 driver yet: https://github.com/zephyrproject-rtos/zephyr/commit/6011b07c5c05494dfe2b6fe1d2e7dd4e1e8a0de8#diff-3ab8bb22bb789f710ee793f63e5bd828eb3fb79aaa30a64c03c53fa0764d827b

## Hardware (2026v4)
- [ ] Drive the buzzer/siren (P2.05) on leak — currently reserved/stub (`CONFIG_APP_BUZZER`)
- [ ] Calibrate CR2 battery curve / health thresholds against a real discharge log
- [ ] Calibrate leak threshold (`CONFIG_APP_LEAK_THRESHOLD_MV`). Analog SAADC read + software
      threshold now implemented (default 1200 mV ≈ 1.5 MΩ reach). Remaining: bench-measure
      `V_sense` at known water resistances and confirm 1 MΩ trips; tune the default if needed.
- [x] Fix leak sensor continuously firing and logging while wet — edge interrupt disabled while
      wet (no storm) + log only on wet/dry transition

## Code review findings (verified against source 2026-11-11)

Correctness
- [ ] `src/sensor/leak.cpp` `leak_read()`: an ADC failure returns without `leak_park()`, so
      while wet the drive stays high (current through the water) until the next read.
- [ ] `src/sensor/sensor_reading.cpp` `sensor_read_battery()` (PMIC path): `battery.valid` is
      only set when the fuel gauge initialised, so a gauge init failure also hides the voltage.
- [ ] `sensor_reading.cpp` `stcc4_push_compensation()`: the recal thread and the main loop
      both fetch the SHT4x with no shared lock; the Zephyr sht4x driver has none of its own.
- [ ] `src/bthome/co2_cal_svc.cpp`: the write accepts any 16-bit FRC target on an
      unauthenticated characteristic; Kconfig limits the target to 350-600 ppm.
- [ ] `src/sensor/stcc4.cpp` `stcc4_force_recalibration()`: the ±3000 ppm check returns `-EIO`
      after the sensor has already applied the correction, and the offset is then never
      recorded. Datasheet "railed" is a magnitude near 32767.
- [ ] `sensor_reading.cpp` `sensor_read_stcc4()`: warm-up "ms remaining" operands are reversed
      (`uptime_ms - stcc4_warmup_until`), so the log is always negative.
- [ ] STCC4 non-zero status word: unclear what read status 0x0004 or 0x0104 means. The code
      now logs a warning and accepts the value (invalidation commented out), but `stcc4.h`
      still says such readings are discarded. Understand the status bits, then make the code
      and the header agree.
- [ ] `Kconfig` `APP_MATTER_BATTERY_PERCENT`: defaults on only for nPM2100, so the nPM1304
      devkit builds the v3 data model but never sets `BatPercentRemaining`.
- [ ] `sensor_reading.cpp` `stcc4_submit_op()`: lazy work-queue init and the busy check are
      unlocked. Latent: only one trigger thread exists per binary (Matter or BTHome).

Efficiency
- [ ] `sensor_reading.cpp`: every CO2 read fetches the SHT4x a second time in
      `stcc4_push_compensation()`; `sensor_read_cycle()` fetched it moments earlier.
- [ ] `sensor_reading.cpp`: the 12 h post-factory-reset warm-up re-fetches the SHT4x and
      rewrites compensation every cycle for a reading it discards.
- [ ] `sensor_reading.cpp`: a 2 KB stack is permanently reserved for the recal work queue.
