/*
 * SHT4x heater support via direct I2C
 *
 * The Zephyr SHT4x driver's fetch_with_heater() has a timing bug: it waits
 * only the heater-on duration but the measurement starts *after* the heater
 * timer expires. Total wait should be t_Heat + t_Measure.
 *
 * This header provides corrected constants and helpers for direct I2C heater
 * operations, bypassing the driver for heater cycles only.
 *
 * Reference: SHT4x datasheet, Table 4 (commands) and Table 5 (timing)
 */

#ifndef SHT4X_H_
#define SHT4X_H_

#include <zephyr/drivers/i2c.h>
#include <zephyr/drivers/sensor.h>
#include <stdint.h>

#define SHT4X_I2C_ADDR 0x44

/* High-repeatability measurement time: 8.3ms max, rounded up */
#define SHT4X_MEASURE_TIME_MS 9

// Above this temperature the heater should not be used
#define SHT4X_HEATER_MAX_TEMP_C 65

/*
 * Heater command bytes indexed by [power][duration]
 *   Power:    0=high (~200mW), 1=medium (~110mW), 2=low (~20mW)
 *   Duration: 0=long (1s), 1=short (100ms)
 */
static const uint8_t sht4x_heater_cmd[3][2] = {
	{0x39, 0x32}, /* high power:   long, short */
	{0x2F, 0x24}, /* medium power: long, short */
	{0x1E, 0x15}, /* low power:    long, short */
};

/*
 * Corrected total wait times: max heater duration + High repeatability measurement time
 *   Long:  1100 + 9 = 1109 ms
 *   Short:  110 + 9 =  119 ms
 */
static const uint32_t sht4x_heater_total_wait_ms[2] = {1100 + SHT4X_MEASURE_TIME_MS,
						       110 + SHT4X_MEASURE_TIME_MS};

/* Sensirion CRC-8: polynomial 0x31, init 0xFF */
static inline uint8_t sht4x_crc8(const uint8_t *data, size_t len)
{
	uint8_t crc = 0xFF;

	for (size_t i = 0; i < len; i++) {
		crc ^= data[i];
		for (int bit = 0; bit < 8; bit++) {
			if (crc & 0x80) {
				crc = (crc << 1) ^ 0x31;
			} else {
				crc <<= 1;
			}
		}
	}
	return crc;
}

/* Convert raw 16-bit temperature ticks to sensor_value (degrees C) */
static inline void sht4x_raw_to_temp(uint16_t raw, struct sensor_value *val)
{
	/* T [°C] = -45 + 175 * raw / 65535 */
	int64_t micro = -45000000LL + (175000000LL * (int64_t)raw) / 65535;

	val->val1 = (int32_t)(micro / 1000000);
	val->val2 = (int32_t)(micro % 1000000);
	if (val->val2 < 0) {
		val->val1--;
		val->val2 += 1000000;
	}
}

/* Convert raw 16-bit humidity ticks to sensor_value (percent RH) */
static inline void sht4x_raw_to_humidity(uint16_t raw, struct sensor_value *val)
{
	/* RH [%] = -6 + 125 * raw / 65535, clamped to [0, 100] */
	int64_t micro = -6000000LL + (125000000LL * (int64_t)raw) / 65535;

	if (micro < 0) {
		micro = 0;
	}
	if (micro > 100000000LL) {
		micro = 100000000LL;
	}
	val->val1 = (int32_t)(micro / 1000000);
	val->val2 = (int32_t)(micro % 1000000);
}

#endif /* SHT4X_H_ */
