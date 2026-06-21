/*
 * Minimal STCC4 CO2 sensor driver over raw I2C.
 *
 * Sensirion STCC4 — I2C address 0x64, Sensirion CRC-8 (poly 0x31, init 0xFF) per 2-byte word.
 * Datasheet: CD_DS_STCC4_D1 v1 (Jun 2025); the section refs below are to it.
 *
 * ── Measurement principle ──────────────────────────────────────────────────────────────
 * Thermal-conductivity sensor: CO2 is inferred from gas thermal conductivity, so the reading
 * is strongly affected by humidity, temperature and pressure. Accurate operation REQUIRES
 * feeding live RH/T (from the SHT4x) and, ideally, pressure compensation on every measurement
 * (set_rht_compensation / set_pressure_compensation; Table 11 conversions).
 *
 * ── Power / measurement states (Table 3) ───────────────────────────────────────────────
 *   sleep        ~1 µA    RH/T/pressure + ASC state retained. exit_sleep (0x00, 5 ms, not
 *                         ACKed) → idle; enter_sleep (0x3650) from idle.
 *   idle         ~55 µA   awake, not measuring. FRC must run from idle (NOT sleep).
 *   single-shot  ~100 µA  measure_single_shot (0x219D, 500 ms) then read_measurement; a 5–600 s
 *                @10 s    sampling interval is recommended (§3.4.6). Our steady state: wake →
 *                         compensate → single-shot → sleep, every measurement interval.
 *   continuous   ~950 µA  start_continuous_measurement (0x218B, 1 s internal cadence) → poll
 *                         read_measurement; stop_continuous (0x3F86, 1200 ms). Reaches accuracy
 *                         fastest (see warm-up) at a high, constant current cost.
 *
 * ── Initial operation, warm-up & ASC (§1.1.2–1.1.4) ────────────────────────────────────
 * The sensor needs sustained operation to become accurate. The timeline is specified in
 * continuous-mode terms and stretches at sparser single-shot intervals (footnote 3):
 *   • Bypass phase: a fixed 390 ppm output for the first 20 s continuous / first 2 single-shots
 *     after a (re)start.
 *   • First ASC save to NV: after 1 h continuous OR 360 single-shots (≈1 h @10 s).
 *   • Initial accuracy: after up to 12 h continuous, then exposure to fresh ~400 ppm air.
 *   • Warm-up after >3 h idle/power-off: 1 h continuous / 360 single-shots; perform_conditioning
 *     (0x29BC, 22 s) is recommended first.
 *   • RESTARTING continuous mode OR power-cycling within the first hour reinitializes the bypass
 *     phase and the ASC-save timer — i.e. it discards warm-up progress.
 *   • Automatic Self-Calibration (ASC): on by default, CANNOT be disabled (no command exists;
 *     only enable_testing_mode pauses it, and that emits the placeholder). Assumes exposure to
 *     ~400 ppm fresh air at least weekly; saves state every 2 h continuous / 720 single-shots.
 *
 * Consequence for our duty cycle: at a 5-min single-shot cadence the warm-up (360 shots ≈ 30 h)
 * and ASC save (720 shots ≈ 60 h) are very slow, and a power-cycle in the first hour restarts
 * the clock. So a freshly powered or factory-reset sensor stays inaccurate for a long time
 * unless run in continuous mode to clear initial operation. NOTE: the STCC4 is powered from the
 * PMIC rail across MCU resets, so a plain reflash/reboot does NOT restart the sensor's warm-up —
 * only a true power-cycle (battery) or perform_factory_reset does (distinguishable via the MCU
 * reset reason and the factory-reset command, respectively).
 *
 * ── Accuracy & output (Table 1) ────────────────────────────────────────────────────────
 *   ±(100 ppm + 10 % of reading), 400–5000 ppm, with SHT4x compensation at 10 s sampling.
 *   Output range 380–32000 ppm. 380 ppm is the FLOOR: a value pinned at 380 means the sensor is
 *   railed / not actually measuring (mid-bypass, or stuck), not a real reading.
 *
 * ── Measurement status word (read_measurement bytes 9–10, §3.4.3/§3.4.13) ───────────────
 *   testing mode = 2nd MSB of the status LSB byte = STCC4_STATUS_TESTING_MODE (0x0040). Treat
 *   ANY non-zero status word as "reading not trustworthy".
 *
 * ── Forced recalibration (FRC, §3.4.15) ────────────────────────────────────────────────
 *   Operate ≥30 single-shots / ~5 min (staying in idle, NOT sleep) with a stable reading, then
 *   perform_forced_recalibration(target). The read-back is the applied correction encoded as
 *   C_FRC = Output − 32768 ppm; 0xFFFF = command failed, a magnitude near ±32767 = railed (no
 *   valid reading to correct against). FRC is non-destructive: a new FRC replaces the previous
 *   correction; it does not wipe factory/ASC calibration.
 *
 * ── Factory reset (§3.4.11) ────────────────────────────────────────────────────────────
 *   perform_factory_reset wipes FRC + ASC history and re-enables the bypass phase. Destructive —
 *   use only to recover a sensor stuck at the floor; a full warm-up is then required.
 *
 * ── This firmware's state machine (sensor_reading.cpp) ──────────────────────────────────
 *   boot:        probe → self_test (logged) → disable_testing_mode → start conditioning (22 s
 *                window) → periodic single-shot (first 2 discarded; readings with a non-zero
 *                status word are discarded).
 *   measure:     every cycle — wake → push RH/T(+P) compensation → single-shot → sleep.
 *   recalibrate: wake → conditioning → refresh compensation → 32 single-shots @10 s (idle) →
 *                FRC → sleep; aborts if a warm-up reading has a non-zero status.
 *   factory rst: wake → perform_factory_reset → conditioning → start continuous warm-up
 *                (CONFIG_APP_CO2_WARMUP_MIN, §1.1.4) and return immediately; the measurement
 *                loop reads the sensor in continuous mode (CO2 reported invalid) until the
 *                warm-up window ends, then stops continuous and resumes single-shot.
 */

#ifndef STCC4_H_
#define STCC4_H_

#include <zephyr/device.h>
#include <stdbool.h>
#include <stdint.h>

#define STCC4_I2C_ADDR 0x64

/* Measurement status word (read_measurement bytes 9..10). Datasheet §3.4.13: the sensor is
 * in testing mode when the 2nd MSB of the status LSB byte is set. Any non-zero status word
 * means the CO2 reading is not trustworthy. */
#define STCC4_STATUS_TESTING_MODE 0x0040

/* Probe sensor: send get_product_id, return true if ACK */
bool stcc4_probe(const struct device *i2c);

/* Wake sensor from sleep mode */
int stcc4_exit_sleep(const struct device *i2c);

/* Enter sleep mode to minimize idle current (must be in idle mode) */
int stcc4_enter_sleep(const struct device *i2c);

/* Exit testing mode (command 0x3F3D). Harmless when not in testing mode; sent at boot so a
 * unit left in testing mode (status & STCC4_STATUS_TESTING_MODE) resumes normal measurement. */
int stcc4_disable_testing_mode(const struct device *i2c);

/* Self-test result bit (datasheet §3.4.12): SHT not connected through the STCC4's dedicated
 * I2C controller pads. Expected on this board — we push RH/T compensation in software — so a
 * result of 0x0000 OR 0x0010 is a PASS. Any other bit set (supply, debug, memory) is a fault. */
#define STCC4_SELF_TEST_SHT_NOT_CONNECTED 0x0010

/* On-chip self-test (command 0x278C). On success `result` holds the raw word: 0x0000/0x0010 =
 * pass (see mask above), other bits = fault per §3.4.12 (bit0 supply, bits3:1 debug, bits6:5
 * memory). Returns 0 if the command/read succeeded (inspect `result`), negative errno on I2C. */
int stcc4_self_test(const struct device *i2c, uint16_t *result);

/* Factory reset (command 0x3632): resets FRC + ASC history and re-enables the bypass phase
 * (datasheet §3.4.11). Destructive — wipes learned calibration; the sensor needs a fresh
 * warm-up afterwards. Returns 0 on success, -EIO if the sensor reports failure. */
int stcc4_perform_factory_reset(const struct device *i2c);

/* Set RH/T compensation using raw STCC4 tick values (datasheet Table 11 input
 * conversions; see temp_to_raw_ticks/hum_to_raw_ticks in sensor_reading.cpp). */
int stcc4_set_rht_compensation(const struct device *i2c, uint16_t raw_temp, uint16_t raw_humidity);

/* Set ambient pressure for CO2 compensation (command 0xE016).
 * Datasheet Table 11: Input = P[Pa] / 2, e.g. 50650 for standard atmosphere. */
int stcc4_set_pressure_compensation(const struct device *i2c, uint16_t pressure_pa_div2);

/* Trigger a single-shot measurement, wait, and read CO2. If status is non-null, the sensor
 * status word is returned in it (testing mode = STCC4_STATUS_TESTING_MODE; any non-zero value
 * means the reading is not trustworthy). */
int stcc4_measure(const struct device *i2c, int16_t &co2_ppm, uint16_t *status = nullptr);

/* Continuous measurement mode (datasheet §3.4.1/§3.4.2): the sensor self-measures every 1 s.
 * Used for the post-factory-reset initial-operation warm-up — start, then poll
 * stcc4_read_continuous (no per-read trigger; the sensor stays awake), then stop. */
int stcc4_start_continuous(const struct device *i2c);
int stcc4_stop_continuous(const struct device *i2c);

/* Read the latest result while in continuous mode (no single-shot trigger). Same decode and
 * status semantics as stcc4_measure. */
int stcc4_read_continuous(const struct device *i2c, int16_t &co2_ppm, uint16_t *status = nullptr);

/* The sensor conditions itself internally for up to 22s after the start command;
 * it must stay awake and unread for that long (no completion signal). */
#define STCC4_CONDITIONING_MS 22000

/* Start the conditioning sequence (needed after idle/power-off >3 hours).
 * Returns immediately; the caller must not sleep the sensor or read the sensor
 * for STCC4_CONDITIONING_MS afterwards. */
int stcc4_start_conditioning(const struct device *i2c);

/* Forced recalibration: tell sensor the current CO2 level is target_co2_ppm
 * (datasheet Table 11: target sent directly, in ppm). Sensor must be awake and,
 * per datasheet §3.4.15, must first have been operated for >=30 single-shot
 * measurements at ~10 s spacing (~5 min) with stable readings.
 * `correction` returns the RAW read-back word; decode per Table 11 as a signed
 * ppm value: C_FRC = correction - 32768 (0xFFFF = command failure -> -EIO).
 * Returns 0 on success, -EIO if the sensor reports failure. */
int stcc4_force_recalibration(const struct device *i2c, uint16_t target_co2_ppm,
			      uint16_t &correction);

#endif /* STCC4_H_ */
