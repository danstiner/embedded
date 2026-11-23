# Leak sensor 2026v5 firmware Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers-extended-cc:subagent-driven-development (recommended) or superpowers-extended-cc:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `SW/hygrometer` builds and runs on the 2026v5 leak board: a new board revision and a second leak driver that measures in both directions.

**Architecture:** A new devicetree binding and driver (`leak_bidir.cpp`) sit beside the existing one-way driver and implement the same `leak.h` interface. A Kconfig symbol derived from the devicetree picks which driver is compiled, so 2026v4 is untouched. The board revision is added the way 2026v4 was: board overlay, per-revision app config, CI matrix entry.

**Tech Stack:** Zephyr / nRF Connect SDK v3.3.0, C++17, devicetree, Kconfig, ztest with `gpio_emul` and `adc_emul`, twister.

**Spec:** `docs/superpowers/specs/2026-11-23-leak-sensor-2026v5-firmware-design.md`

## Global Constraints

- Do not edit `src/sensor/leak.cpp`, `src/sensor/leak.h`, `tests/leak/**`, `dts/bindings/sensor/local,leak-sensor.yaml`, or the 2026v3 / 2026v4 board overlays and app config. `leak_model.h` may only gain functions.
- Pins (hardware README 5.2): LEAK_A P1.12 = AIN5, LEAK_A_RET P1.09, LEAK_B P1.11 = AIN4, LEAK_B_RET P1.10. P1.05 (buzzer) stays unconfigured.
- Timing: `LEAK_DISCHARGE_US 10`, `LEAK_SETTLE_US 100`. SAADC leak channels: gain 1/4, internal reference, 40 µs acquisition, 12 bit, as 2026v4's.
- Threshold: the existing `CONFIG_APP_LEAK_THRESHOLD_MV` (default 1200). The decision uses the integer mean of the two directions, `(a + b) / 2`; a mean equal to the threshold is wet.
- Board default revision stays `2026v4`.
- Comments only for non-obvious logic or hardware quirks. American English. Format with `SW/lint.sh --fix` (clang-format 21, as CI).
- Commits end with `Co-Authored-By: Claude Fable 5.2 <noreply@anthropic.com>`. Never push; never `git add TODO.md`.
- No subagents unless Dan asks.

**User decisions (already made):**
- "Add a second driver." (approach A: a new driver beside the first, not one shared driver)
- "We can put off the buzzer for a later pr though"
- Crystal trim: "do it as a separate PR that also applies to the v4 hardware" (out of scope here; needs a measurement first)
- "we may want to split into multiple PRs if the new firmware diff gets to large": Tasks 2 to 4 form the first PR, Tasks 5 and 6 the second, if a split is wanted.

## Environment

```sh
T=/opt/nordic/ncs/toolchains/0c0f19d91c
export PATH=$T/bin:$T/usr/bin:$T/usr/local/bin:$T/opt/bin:$T/opt/nanopb/generator-bin:$T/opt/zephyr-sdk/arm-zephyr-eabi/bin:$PATH \
  ZEPHYR_TOOLCHAIN_VARIANT=zephyr ZEPHYR_SDK_INSTALL_DIR=$T/opt/zephyr-sdk
R=/Users/dan/git/danstiner/embedded/SW          # BOARD_ROOT; builds run from $R/hygrometer
```

- BTHome release build of revision `<rev>` into `<dir>`:
  `west build -p -d <dir> -b bl54l15u_hygrometer@<rev>/nrf54l15/cpuapp -- -DBOARD_ROOT=$R -DEXTRA_CONF_FILE=prj_extra_release.conf`
- Matter release build: the same with
  `-DEXTRA_CONF_FILE="prj_extra_release.conf;prj_extra_matter.conf" -DSB_EXTRA_CONF_FILE=sysbuild_extra_matter.conf -DEXTRA_DTC_OVERLAY_FILE=boards/matter.overlay`
- Configure only (fast, enough for devicetree and `.config`): add `--cmake-only`.
- Unit tests, as CI runs them: `cd $R && west twister -p qemu_cortex_m3 -T hygrometer/tests --inline-logs -v`.
  This needs `qemu-system-arm`, which is **not installed** on this Mac (`native_sim` is Linux-only). Ask Dan before `brew install qemu`. Without it, run twister with `--build-only` and say plainly that the tests were built but not run; CI runs them on the PR.
- Put build directories in the session scratchpad, not in the repo.

## Review Focus

1. **Water arrives while a read has the edge interrupt disabled.** A person expects the alarm at once, not a measurement interval later. Arming must not lose it: the sensing node is discharged, the edge is enabled, and only then is the other side driven, so a wet contact produces its edge after the interrupt is on. The emulator offers no hook between those steps, so no host test can pin this: the reviewer checks the order in the arm routine, and the first board checks it with water held on across several reads. (Task 3, arm order in Interfaces)
2. **The SAADC fails on the second direction after the first succeeded.** The pins must not be left mid-measurement with one contact driven; the reading is invalid and the pins return to the previous idle state. (Task 3, `test_adc_error_second_direction`)
3. **Wet, then dry again.** The sensor must re-arm and wake on the next leak, not stay parked. (Task 3, `test_wet_then_dry_rearms`)
4. **Mean exactly at, and one count under, the threshold.** Integer rounding must not move the trip point. (Task 2, `test_mean_mv`; Task 3, `test_mean_decides`)
5. **`leak_read` on a sensor that never initialized.** It must return `-ENODEV` and touch no pin. (Task 3, `test_read_without_init`)

Not coverable on the host, for the first board (spec, "Left for hardware"): a wrong SAADC channel reads near VDD in both directions and looks exactly like water.

---

### Task 1: Baseline of the existing revisions

**Goal:** Record what 2026v3 and 2026v4 build to today, so later tasks can prove they did not change.

**Files:**
- Create (scratchpad only): `base/v3/`, `base/v4/` holding each revision's `zephyr.dts` and `.config`

**Acceptance Criteria:**
- [ ] `base/v4/zephyr.dts`, `base/v4/.config`, `base/v3/zephyr.dts` and `base/v3/.config` exist, taken from commit `main` (`f70767b`)
- [ ] Whether `qemu-system-arm` is available is known and stated

**Verify:** `ls base/v3 base/v4` → two files each; `which qemu-system-arm` → a path, or "not found" reported to Dan

**Steps:**

- [ ] **Step 1:** With the branch's firmware files still equal to `main` (`git diff main -- SW .github` is empty), configure both revisions with `--cmake-only` (BTHome release) and copy `<dir>/hygrometer/zephyr/zephyr.dts` and `<dir>/hygrometer/zephyr/.config` into `base/<rev>/`.
- [ ] **Step 2:** Check for `qemu-system-arm`. If missing, tell Dan and ask whether to install it; continue with `--build-only` meanwhile.

No commit: nothing in the repo changes.

---

### Task 2: Model functions and the test app

**Goal:** The two pure functions the driver needs, tested in a new test app that also carries the emulated two-way front end.

**Files:**
- Modify: `SW/hygrometer/src/sensor/leak_model.h` (append two functions)
- Create: `SW/hygrometer/dts/bindings/sensor/local,leak-sensor-bidir.yaml`
- Create: `SW/hygrometer/tests/leak_bidir/CMakeLists.txt`, `prj.conf`, `Kconfig`, `testcase.yaml`, `app.overlay`, `src/main.cpp`

**Acceptance Criteria:**
- [ ] `leak_mean_mv` and `leak_directions_disagree` exist with the signatures below
- [ ] The binding requires all six properties
- [ ] `hygrometer.sensor.leak_bidir` builds and its two model tests pass (or build, if qemu is missing)
- [ ] `hygrometer.sensor.leak` still passes

**Verify:** `cd $R && west twister -p qemu_cortex_m3 -T hygrometer/tests --inline-logs -v` → both suites pass, 0 failed

**Steps:**

- [ ] **Step 1: Binding.** `compatible: "local,leak-sensor-bidir"`; required `phandle-array` properties `a-gpios`, `a-return-gpios`, `b-gpios`, `b-return-gpios`, `io-channels`; required `string-array` `io-channel-names` (values `"a"`, `"b"`: the channel on LEAK_A, then on LEAK_B). Description: two identical contacts, each with a series resistor to its GPIO/SAADC pin and a 1 MΩ to its own return GPIO; either side can drive while the other senses.

- [ ] **Step 2: Test app.** Copy `tests/leak`'s arrangement. Differences:
  - `testcase.yaml`: test id `hygrometer.sensor.leak_bidir`, same platforms and tags.
  - `app.overlay`: `adc_emul` with `nchannels = <2>` and `channel@0`, `channel@1` (same settings as `tests/leak`'s channel); the node

    ```dts
    leak_sensor: leak-sensor {
    	compatible = "local,leak-sensor-bidir";
    	a-gpios        = <&test_gpio 0 GPIO_ACTIVE_HIGH>;
    	a-return-gpios = <&test_gpio 1 GPIO_ACTIVE_HIGH>;
    	b-gpios        = <&test_gpio 2 GPIO_ACTIVE_HIGH>;
    	b-return-gpios = <&test_gpio 3 GPIO_ACTIVE_HIGH>;
    	io-channels = <&test_adc 0>, <&test_adc 1>;
    	io-channel-names = "a", "b";
    };
    ```
  - `CMakeLists.txt`: sources `src/main.cpp` only for now (Task 3 adds the driver).

- [ ] **Step 3: Failing tests** in `src/main.cpp`, suite `leak_bidir_model`:

  ```cpp
  ZTEST(leak_bidir_model, test_mean_mv)
  {
  	zassert_equal(leak_mean_mv(1300, 1150), 1225);
  	zassert_equal(leak_mean_mv(1199, 1200), 1199, "rounds down");
  	zassert_equal(leak_mean_mv(1200, 1200), 1200);
  	zassert_equal(leak_mean_mv(0, 0), 0);
  }

  ZTEST(leak_bidir_model, test_directions_disagree)
  {
  	zassert_true(leak_directions_disagree(1200, 299, 1200), "wet one way, under a quarter the other");
  	zassert_true(leak_directions_disagree(299, 1200, 1200), "symmetric");
  	zassert_false(leak_directions_disagree(1200, 300, 1200), "a quarter is not under a quarter");
  	zassert_false(leak_directions_disagree(1199, 0, 1200), "neither reads wet");
  	zassert_false(leak_directions_disagree(1490, 1490, 1200), "water reads alike both ways");
  }
  ```

- [ ] **Step 4:** Run twister: the new suite fails to build (functions undefined).

- [ ] **Step 5: Implement** in `leak_model.h`:

  ```c
  /** Mean of the two directions' sense voltages (mV), rounded down. */
  static inline int32_t leak_mean_mv(int32_t a_mv, int32_t b_mv);

  /** True when one direction reads at or over @p threshold_mv and the other under a
   *  quarter of it: water reads alike both ways, so this points at a wrong SAADC
   *  channel or a broken return. */
  static inline bool leak_directions_disagree(int32_t a_mv, int32_t b_mv, int32_t threshold_mv);
  ```

- [ ] **Step 6:** Run twister: both suites pass. Run `SW/lint.sh`.

- [ ] **Step 7: Commit** `hygrometer: model functions and test app for the two-way leak sensor`.

---

### Task 3: The two-way driver

**Goal:** `leak_bidir.cpp` implements `leak.h` for the four-pin front end and passes its tests against emulated pins.

**Files:**
- Create: `SW/hygrometer/src/sensor/leak_bidir.cpp`
- Modify: `SW/hygrometer/tests/leak_bidir/CMakeLists.txt` (add the driver source), `SW/hygrometer/tests/leak_bidir/src/main.cpp` (suite `leak_bidir`)

**Acceptance Criteria:**
- [ ] Every test below passes
- [ ] `leak.cpp`, `leak.h` and `tests/leak` are unchanged (`git diff main --stat` shows none of them)
- [ ] `hygrometer.sensor.leak` still passes

**Verify:** `cd $R && west twister -p qemu_cortex_m3 -T hygrometer/tests --inline-logs -v` → both test apps pass, 0 failed

**Interfaces (what the driver must do; the spec's "Driver" section is the reference):**

- Devicetree: `GPIO_DT_SPEC_GET(DT_NODELABEL(leak_sensor), a_gpios)` and the three like it; `ADC_DT_SPEC_GET_BY_NAME(DT_NODELABEL(leak_sensor), a)` and `b`. `BUILD_ASSERT` that the node is okay and that `a-gpios` and `b-gpios` share a port (one callback covers both).
- "X drives" means: X out high, X return out high, the other side's pin an input, the other side's return out low. The sample is taken on the **other** side's channel ("A drives" samples channel `b`).
- `leak_init`: check readiness (as `leak.cpp`), set up both ADC channels, register one callback for both sense pins, arm with A driving, set `state.have_leak`.
- Arm (X drives), in this order, which is what makes a wet contact wake the board (Review Focus 1): all four pins out low for `LEAK_DISCHARGE_US`; sensing pin to input; enable `GPIO_INT_EDGE_TO_ACTIVE` on it; only then drive X and X return high. Say why in a comment at the arm routine.
- Park: both edge interrupts disabled, all four pins out low.
- `leak_read`: `-ENODEV` if `!state.have_leak`. Disable both edge interrupts. For A drives, then B drives: all four low for `LEAK_DISCHARGE_US`, set the direction, `k_busy_wait(LEAK_SETTLE_US)`, one sample of the sensing side, negative readings clamped to 0. Decide with `leak_decide(leak_mean_mv(a, b), CONFIG_APP_LEAK_THRESHOLD_MV, prev_wet)`. Wet: park. Dry: arm in the direction opposite to the one armed most recently (a wet spell in between does not reset it). Log as `leak.cpp` does, with both readings, and `LOG_WRN` when `leak_directions_disagree`.
- SAADC error in either direction: return the error, `state.leak.valid = false`, and restore the idle state the last good reading chose (parked if it was wet, otherwise armed in the direction that was armed before this read: no alternation).

**Steps:**

- [ ] **Step 1: Test helpers** in `src/main.cpp`:

  ```cpp
  enum pin_role { OUT_LOW, OUT_HIGH, INPUT };
  static pin_role role(const struct gpio_dt_spec &p);   // gpio_emul_flags_get + gpio_emul_output_get
  static void expect_armed(bool a_drives);              // the four roles of the "X drives" pattern
  static void expect_parked(void);                      // all four OUT_LOW
  static int read_at(int a_mv, int b_mv);               // adc_emul_const_value_set on channels a and b, then leak_read(state)
  static bool wakes_on_rising(const struct gpio_dt_spec &p);   // 0 then 1 on the pin's emulated input; true if wake_sem was given
  ```

  The four specs are `t_a`, `t_a_ret`, `t_b`, `t_b_ret`, read from the node as the driver reads them. `wakes_on_rising` ignores the emulator's error when the pin is an output (parked).

  `a_mv` is the voltage on LEAK_A's channel, which the driver samples while **B** drives. The suite's setup runs `leak_init` once, as `tests/leak` does; add a `before` hook that brings the driver to a known state for each test with `read_at(100, 100)` repeated until `expect_armed(true)` would hold (at most two reads).

- [ ] **Step 2: Failing tests**, suite `leak_bidir`:

  ```cpp
  ZTEST(leak_bidir, test_dry_alternates_direction)
  {
  	expect_armed(true);
  	zassert_ok(read_at(100, 100));
  	zassert_true(state.leak.valid);
  	zassert_false(state.leak.wet);
  	expect_armed(false);
  	zassert_ok(read_at(100, 100));
  	expect_armed(true);
  }

  ZTEST(leak_bidir, test_wet_parks_and_does_not_wake)
  {
  	zassert_ok(read_at(1490, 1490));
  	zassert_true(state.leak.wet);
  	expect_parked();
  	zassert_false(wakes_on_rising(t_a));
  	zassert_false(wakes_on_rising(t_b));
  }

  ZTEST(leak_bidir, test_wake_each_direction)
  {
  	zassert_true(wakes_on_rising(t_b), "A drives: B senses");
  	zassert_ok(read_at(100, 100));
  	zassert_true(wakes_on_rising(t_a), "B drives: A senses");
  }

  ZTEST(leak_bidir, test_mean_decides)
  {
  	zassert_ok(read_at(1300, 1150));
  	zassert_true(state.leak.wet, "mean 1225");
  	zassert_ok(read_at(1250, 1100));
  	zassert_false(state.leak.wet, "mean 1175");
  	zassert_ok(read_at(1200, 1200));
  	zassert_true(state.leak.wet, "mean at the threshold is wet");
  	zassert_ok(read_at(1199, 1200));
  	zassert_false(state.leak.wet, "mean 1199");
  }

  ZTEST(leak_bidir, test_wet_then_dry_rearms)
  {
  	zassert_ok(read_at(1490, 1490));
  	zassert_ok(read_at(100, 100));
  	zassert_false(state.leak.wet);
  	expect_armed(false);
  	zassert_true(wakes_on_rising(t_a));
  }

  ZTEST(leak_bidir, test_read_without_init)
  {
  	sensor_state fresh{};
  	zassert_equal(leak_read(fresh), -ENODEV);
  	expect_armed(true);
  }
  ```

  Two more kinds use `adc_emul_value_func_set` on one or both channels (restore constant values afterwards):

  - `test_each_direction_samples_its_channel`: a value function on each channel records the four pin roles at the moment it is sampled and counts calls. After one `read_at`-style read: channel `b` was sampled once with A `OUT_HIGH`, A return `OUT_HIGH`, B `INPUT`, B return `OUT_LOW`; channel `a` once with the mirror image.
  - `test_adc_error_first_direction` and `test_adc_error_second_direction`: the value function on channel `b` (first) or `a` (second) returns `-EIO`. `leak_read` returns non-zero, `state.leak.valid` is false, and `expect_armed(true)` still holds (no alternation). Repeat the second-direction case after a wet read: `expect_parked()` holds.

- [ ] **Step 3:** Add `../../src/sensor/leak_bidir.cpp` to the test's `CMakeLists.txt`; run twister: the suite fails to build (file missing).

- [ ] **Step 4: Implement** `leak_bidir.cpp` to the Interfaces block. Open it with a short header comment: the front end's diagram for both sides and the three pin states; do not repeat `leak.cpp`'s divider math, point to `leak_model.h`.

- [ ] **Step 5:** Run twister: every test in both apps passes. Run `SW/lint.sh`.

- [ ] **Step 6: Commit** `hygrometer: two-way leak driver for the four-pin front end`.

---

### Task 4: Build selection

**Goal:** The app compiles `leak_bidir.cpp` when the devicetree has a `local,leak-sensor-bidir` node and `leak.cpp` otherwise, with 2026v3 and 2026v4 unchanged.

**Files:**
- Modify: `SW/hygrometer/Kconfig` (after `APP_LEAK_THRESHOLD_MV`), `SW/hygrometer/CMakeLists.txt:29-32`

**Acceptance Criteria:**
- [ ] `CONFIG_APP_LEAK_SENSOR_BIDIR` exists: a promptless `bool`, `depends on APP_LEAK_SENSOR`, `default $(dt_compat_enabled,$(DT_COMPAT_LOCAL_LEAK_SENSOR_BIDIR))` with `DT_COMPAT_LOCAL_LEAK_SENSOR_BIDIR := local,leak-sensor-bidir`
- [ ] 2026v4: `zephyr.dts` identical to `base/v4`; `.config` differs only by the line `# CONFIG_APP_LEAK_SENSOR_BIDIR is not set`
- [ ] 2026v3: `zephyr.dts` and `.config` identical to `base/v3`
- [ ] 2026v4 builds completely (BTHome release)

**Verify:** `diff base/v4/zephyr.dts <dir>/hygrometer/zephyr/zephyr.dts` → empty; `diff <(grep -v '^#\|^$' base/v4/.config | sort) <(grep -v '^#\|^$' <dir>/hygrometer/zephyr/.config | sort)` → empty; the same two for v3 → empty

**Steps:**

- [ ] **Step 1:** Add the Kconfig symbol. Help text: selects the two-way driver for boards whose devicetree describes the four-pin front end (2026v5).
- [ ] **Step 2:** In `CMakeLists.txt`, under `CONFIG_APP_LEAK_SENSOR`, compile `src/sensor/leak_bidir.cpp` if `CONFIG_APP_LEAK_SENSOR_BIDIR`, else `src/sensor/leak.cpp`. Update the comment above it to name both revisions.
- [ ] **Step 3:** Configure 2026v3 and 2026v4 (`--cmake-only`) and run the Verify diffs. Then build 2026v4 completely.
- [ ] **Step 4: Commit** `hygrometer: pick the leak driver from the devicetree`.

**If the work is split, the first PR ends here.**

---

### Task 5: Board revision 2026v5

**Goal:** `bl54l15u_hygrometer@2026v5` configures and builds for BTHome and Matter.

**Files:**
- Modify: `SW/boards/local/bl54l15u_hygrometer/board.yml` (add `- name: 2026v5`; default stays `2026v4`), `SW/boards/local/bl54l15u_hygrometer/revision.cmake` (`VALID_BOARD_REVISIONS`)
- Create: `SW/boards/local/bl54l15u_hygrometer/bl54l15u_hygrometer_nrf54l15_cpuapp_2026v5.overlay`
- Create: `SW/hygrometer/boards/bl54l15u_hygrometer_nrf54l15_cpuapp_2026v5.conf`

**Acceptance Criteria:**
- [ ] 2026v5 `.config` has `CONFIG_APP_LEAK_SENSOR=y` and `CONFIG_APP_LEAK_SENSOR_BIDIR=y`
- [ ] 2026v5 `zephyr.dts`: `leak-sensor` is `local,leak-sensor-bidir` on gpio1 pins 12, 9, 11, 10; SAADC channel 1 on AIN5 and channel 2 on AIN4; `gpio0` and `gpio2` not okay; no `buzzer` node; `leds`, the PMIC nodes, `bme688` and `i2c20` disabled
- [ ] 2026v5 builds completely for BTHome release and for Matter release
- [ ] 2026v3 and 2026v4 still match `base/` as in Task 4, and still build

**Verify:** the two 2026v5 builds end with `dfu_application.zip` written and no warnings from `hygrometer/src`; `grep -c 'CONFIG_APP_LEAK_SENSOR_BIDIR=y' <v5 dir>/hygrometer/zephyr/.config` → 1; Task 4's diffs → empty

**Steps:**

- [ ] **Step 1: Overlay.** Start from the 2026v4 overlay's text. Keep, unchanged: the includes, every node disabled under "Remove 2026v3-only hardware", `&adc`'s `channel@0` and the `vbatt` node. Drop: the `&gpio0` and `&gpio2` blocks, the `buzzer` node. Change:
  - header comment: 2026v5's differences (two-way leak front end on P1.12/P1.09 and P1.11/P1.10; buzzer on P1.05, not driven yet; SHT40; see `HW/BL54L15μ_LeakSensor/README.md`);
  - `channel@1`: `zephyr,input-positive = <NRF_SAADC_AIN5>;  /* P1.12 = AIN5 LEAK_A */`, other properties as 2026v4's `channel@1`;
  - new `channel@2`: the same with `reg = <2>` and `NRF_SAADC_AIN4` (`/* P1.11 = AIN4 LEAK_B */`);
  - the leak node, exactly:

    ```dts
    leak_sensor: leak-sensor {
    	compatible = "local,leak-sensor-bidir";
    	a-gpios        = <&gpio1 12 GPIO_ACTIVE_HIGH>;  /* P1.12 LEAK_A */
    	a-return-gpios = <&gpio1 9 GPIO_ACTIVE_HIGH>;   /* P1.09 R3's return */
    	b-gpios        = <&gpio1 11 GPIO_ACTIVE_HIGH>;  /* P1.11 LEAK_B */
    	b-return-gpios = <&gpio1 10 GPIO_ACTIVE_HIGH>;  /* P1.10 R4's return */
    	io-channels = <&adc 1>, <&adc 2>;
    	io-channel-names = "a", "b";
    };
    ```
  - one comment by the leak channels: AIN4 and AIN5 are from Ezurio's pin table and unconfirmed on hardware; a wrong channel reads near VDD.
- [ ] **Step 2: App config.** The same four settings as the 2026v4 file (`CONFIG_ADC=y`, `CONFIG_APP_LEAK_SENSOR=y`, `CONFIG_BME688_ENABLE=n`, `CONFIG_STCC4_ENABLE=n`), with its comments adapted to 2026v5.
- [ ] **Step 3:** `board.yml` and `revision.cmake`.
- [ ] **Step 4:** Configure 2026v5 and check the acceptance criteria in its `zephyr.dts` and `.config`. Build it for BTHome release and for Matter release. Re-run Task 4's checks for 2026v3 and 2026v4.
- [ ] **Step 5: Commit** `hygrometer: board revision 2026v5`.

---

### Task 6: CI and README

**Goal:** CI builds 2026v5, and the README lists it.

**Files:**
- Modify: `.github/workflows/hygrometer.yml` (build matrix), `SW/hygrometer/README.md` (hardware list)

**Acceptance Criteria:**
- [ ] The matrix has `board: bl54l15u_hygrometer@2026v5/nrf54l15/cpuapp`, `name: bl54l15u_hygrometer_2026v5`
- [ ] The README's revision list has a 2026v5 line: two-way resistive leak sensor, SHT40, buzzer (not driven yet), CR2, built with `-b bl54l15u_hygrometer@2026v5/nrf54l15/cpuapp`; 2026v4 is still marked default
- [ ] `SW/lint.sh` passes; twister passes (or builds, if qemu is missing); `git diff main --stat` lists no file under Global Constraints' "do not edit"

**Verify:** `cd $R && ./lint.sh` → exit 0; `git diff main --stat -- SW/hygrometer/src/sensor/leak.cpp SW/hygrometer/src/sensor/leak.h SW/hygrometer/tests/leak` → empty

**Steps:**

- [ ] **Step 1:** Add the matrix entry after 2026v4's. The unit-test job needs no change: it runs everything under `hygrometer/tests`.
- [ ] **Step 2:** README line.
- [ ] **Step 3:** Run the Verify commands and the full twister run once more.
- [ ] **Step 4: Commit** `hygrometer: build 2026v5 in CI, list it in the README`.

Pushing and opening the PR (one, or two split after Task 4) waits for Dan.
