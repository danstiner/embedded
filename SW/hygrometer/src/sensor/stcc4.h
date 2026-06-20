/*
 * Minimal STCC4 CO2 sensor driver over raw I2C
 *
 * Sensirion STCC4 - I2C address 0x64
 * Uses Sensirion CRC-8 (poly 0x31, init 0xFF) per 2-byte word
 */

#ifndef STCC4_H_
#define STCC4_H_

#include <zephyr/device.h>
#include <stdbool.h>
#include <stdint.h>

#define STCC4_I2C_ADDR 0x64

/* Probe sensor: send get_product_id, return true if ACK */
bool stcc4_probe(const struct device *i2c);

/* Wake sensor from sleep mode */
int stcc4_exit_sleep(const struct device *i2c);

/* Enter sleep mode to minimize idle current (must be in idle mode) */
int stcc4_enter_sleep(const struct device *i2c);

/* Set RH/T compensation using raw SHT4x tick values */
int stcc4_set_rht_compensation(const struct device *i2c, uint16_t raw_temp, uint16_t raw_humidity);

/* Set ambient pressure for CO2 compensation (command 0xE016).
 * pressure_pa_div2 is pressure in Pa / 2, e.g. 50650 for standard atmosphere. */
int stcc4_set_pressure_compensation(const struct device *i2c, uint16_t pressure_pa_div2);

/* Trigger single-shot measurement, wait, and read CO2 */
int stcc4_measure(const struct device *i2c, int16_t &co2_ppm);

/* The sensor conditions itself internally for up to 22s after the start command;
 * it must stay awake and unread for that long (no completion signal). */
#define STCC4_CONDITIONING_MS 22000

/* Start the conditioning sequence (needed after idle/power-off >3 hours).
 * Returns immediately; the caller must not sleep the sensor or read the sensor
 * for STCC4_CONDITIONING_MS afterwards. */
int stcc4_start_conditioning(const struct device *i2c);

/* Forced recalibration: tell sensor the current CO2 level is target_co2_ppm.
 * Sensor must be awake. Returns correction value via *correction (0xFFFF = failure).
 * Returns 0 on success, -EIO if sensor reports failure. */
int stcc4_force_recalibration(const struct device *i2c, uint16_t target_co2_ppm,
			      uint16_t &correction);

/* Factory reset (command 0x3632): wipe FRC + ASC history and re-arm the
 * 2-measurement bypass phase. Sensor must be awake.
 * Returns 0 on success, -EIO if sensor reports failure (status 0xFFFF). */
int stcc4_perform_factory_reset(const struct device *i2c);

#endif /* STCC4_H_ */
