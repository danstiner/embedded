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
int stcc4_wake(const struct device *i2c);

/* Set RH/T compensation using raw SHT4x tick values */
int stcc4_set_rht_compensation(const struct device *i2c,
			       uint16_t raw_temp, uint16_t raw_humidity);

/* Trigger single-shot measurement, wait, and read CO2 */
int stcc4_measure(const struct device *i2c, uint16_t *co2_ppm);

#endif /* STCC4_H_ */
