# Leak sensor 2026v5 firmware: board revision and two-way leak driver

Status: draft for Dan's approval, 2026-11-23. Branch `sw-leak-sensor-2026v5`.

## Intent

The 2026v5 leak board (`HW/BL54L15μ_LeakSensor/README.md`) moves the leak pins and makes
the front end symmetric: either contact can drive while the other senses, so the current
through the water can be reversed. `SW/hygrometer` has to run on it, in both the Matter
and the BTHome build.

No 2026v5 board exists yet. Everything here is proven by building and by tests on the
host until boards arrive.

## Goals

- `bl54l15u_hygrometer@2026v5` builds for BTHome and Matter, in CI.
- The leak is measured in both directions on every read and reported exactly as on
  2026v4: one wet/dry state, through Matter's Boolean State cluster or BTHome's
  moisture byte.
- A wet contact still wakes the board at once from a pin edge.
- No current through the contacts while dry; equal time each way while wet.
- The new driver is tested on the host against emulated pins, as 2026v4's is.

## Non-goals

- The buzzer. A later PR adds it (pattern, PWM on P1.05, timing against the radio).
  Here P1.05 is left unconfigured; R7 holds Q1 off while the pin floats.
- Renaming the board. It stays `bl54l15u_hygrometer`; the rename is already deferred.
- Any change to the Matter data model. 2026v5 uses 2026v4's.
- Trimming the crystal's load. The 0.5 pF of board stray is an estimate (README 7.1).

## Anti-goals

- Changing 2026v4's driver, overlay or behavior. It is the only leak hardware in hand,
  so it is the one thing this work could break for real.

## Constraints

- Pins (README 5.2): LEAK_A P1.12 (AIN5), LEAK_A_RET P1.09, LEAK_B P1.11 (AIN4),
  LEAK_B_RET P1.10. I2C is unchanged (SDA P1.14, SCL P1.04).
- AIN4 and AIN5 come from Ezurio's pin table and are unconfirmed on hardware. A wrong
  channel reads near VDD.
- 1 MΩ source: the SAADC needs the 40 µs acquisition time 2026v4 uses.
- Reversal timing: a contact that was driving sits at VDD. Left to fall through its
  1 MΩ it needs about 140 µs to settle; discharged through the pins first, the node
  rises from zero and settles in 71 µs at 10 MΩ (README 7.1).

## Approaches

**A. A second driver beside the first (chosen by Dan).** A new binding and source file
for the two-way front end with the same `leak_init` / `leak_read` interface; the build
picks the one the devicetree describes. 2026v4's code is untouched. Costs about 150
lines of similar plumbing.

**B. One driver for both boards.** Optional return pins and a second channel in the
existing binding. One code path, but it rewrites working code with no 2026v5 board to
prove the new path.

A was chosen because a 2026v4 regression is the failure that could ship today. The two
can merge once 2026v5 boards have run.

## Design

### Board revision

Everything here follows how 2026v4 was added.

- `SW/boards/local/bl54l15u_hygrometer/board.yml` and `revision.cmake`: add `2026v5`.
  The default stays `2026v4` until 2026v5 boards exist (my call).
- New `bl54l15u_hygrometer_nrf54l15_cpuapp_2026v5.overlay`:
  - the same removals as 2026v4's overlay (PMIC and its children, BME688, `i2c20`,
    LEDs), copied rather than shared, so 2026v4's file is not edited (my call);
  - SAADC channels: 0 for the cell (VDD, as 2026v4), 1 on AIN5 for LEAK_A, 2 on AIN4
    for LEAK_B; both leak channels as 2026v4's (gain 1/4, internal reference, 40 µs,
    12 bit);
  - the `vbatt` node, as 2026v4;
  - the leak node (below);
  - no buzzer node, and `gpio0` and `gpio2` stay disabled: every pin used is on port 1.
- New `SW/hygrometer/boards/bl54l15u_hygrometer_nrf54l15_cpuapp_2026v5.conf`, the same
  settings as 2026v4's (`CONFIG_ADC`, `CONFIG_APP_LEAK_SENSOR`, BME688 and STCC4 off).
- `.github/workflows/hygrometer.yml`: add `bl54l15u_hygrometer@2026v5` to the matrix.
- `SW/hygrometer/README.md`: list 2026v5.

### Binding

New `SW/hygrometer/dts/bindings/sensor/local,leak-sensor-bidir.yaml`:

```dts
leak_sensor: leak-sensor {
	compatible = "local,leak-sensor-bidir";
	a-gpios        = <&gpio1 12 GPIO_ACTIVE_HIGH>;   /* LEAK_A */
	a-return-gpios = <&gpio1 9 GPIO_ACTIVE_HIGH>;    /* R3's return */
	b-gpios        = <&gpio1 11 GPIO_ACTIVE_HIGH>;   /* LEAK_B */
	b-return-gpios = <&gpio1 10 GPIO_ACTIVE_HIGH>;   /* R4's return */
	io-channels = <&adc 1>, <&adc 2>;
	io-channel-names = "a", "b";
};
```

The node keeps the label `leak_sensor`. All six properties are required.

### Driver

New `SW/hygrometer/src/sensor/leak_bidir.cpp`, implementing `leak.h` unchanged. The
build compiles it in place of `leak.cpp` when the devicetree has an enabled
`local,leak-sensor-bidir` node (a Kconfig symbol defaulted from
`dt_compat_enabled`, under `CONFIG_APP_LEAK_SENSOR`; my call).

Pin states, for "A drives" (swap A and B for the other direction):

| State        | A        | A return | B                | B return |
| ------------ | -------- | -------- | ---------------- | -------- |
| Armed        | out high | out high | input, rising edge | out low |
| Measuring    | out high | out high | SAADC            | out low  |
| Parked       | out low  | out low  | out low          | out low  |

`leak_init`: configure the pins, register one GPIO callback covering both sense pins
(same port), arm with A driving, set `state.have_leak`.

`leak_read`, every cycle and on a wake:

1. Disable the edge interrupt.
2. For each direction, A driving then B driving: park all four pins low for 10 µs to
   discharge both nodes, set the direction, wait 100 µs, take one SAADC sample of the
   sensing side.
3. Average the two readings and decide wet or dry with the existing `leak_decide` and
   `CONFIG_APP_LEAK_THRESHOLD_MV`.
4. Wet: park, interrupt left off. Dry: arm in the direction opposite to the one armed
   before this read, and enable the rising edge on the sensing pin. Alternating keeps
   either contact from always being the positive one.
5. Log as 2026v4 does (level and estimated resistance, wet/dry only on change), plus
   both directions' readings. If one direction is at or over the threshold and the
   other is under a quarter of it, log a warning: with water both read alike, so that
   pattern points at a wrong SAADC channel or a broken return.

An SAADC failure in either direction marks the reading invalid and leaves the pins in
the idle state the last good reading chose, as 2026v4's driver does.

Cost per read: two samples and about 220 µs of busy-wait, against one sample and
100 µs on 2026v4.

### Model

`leak_model.h` gains two pure functions, with tests: the average of two readings, and
the "directions disagree" check. Nothing in it changes for 2026v4.

### Tests

New `SW/hygrometer/tests/leak_bidir`, a copy of `tests/leak`'s arrangement: `native_sim`
with `gpio_emul` and a two-channel `adc_emul`, compiling the real `leak_bidir.cpp`. It
checks:

- dry: all four pins in the armed pattern, and the armed direction alternates from read
  to read;
- wet: all four pins low and no wake from an edge;
- a wake from a rising edge on the sensing pin while armed, in each direction;
- the decision uses the average (one direction over the threshold and one under, both
  sides of the threshold);
- each direction samples its own channel;
- the disagreement warning's condition, through the model function;
- an SAADC error leaves the reading invalid.

`tests/leak` is unchanged and must still pass.

### Checks before calling it done

- Twister: `tests/leak` and `tests/leak_bidir` pass on `native_sim`.
- Builds: `@2026v5` for BTHome and for Matter; `@2026v3` and `@2026v4` still build.
- `@2026v4`'s generated devicetree (`build/zephyr/zephyr.dts`) and `.config` are
  identical before and after, apart from the new Kconfig symbol reading `n`.

## Left for hardware

On the first 2026v5 board (README 7.2): that AIN5 and AIN4 read LEAK_A and LEAK_B; the
settle and discharge times; the wake threshold in both directions; sleep current armed
and parked.

## Left to the builder

File-internal structure, names of statics, log wording, and the exact Kconfig symbol
name.
