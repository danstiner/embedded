/*
 * Retained RAM structure for nRF54 Soil Moisture Sensor
 * Preserves state across System OFF sleep cycles
 */

#ifndef RETAINED_H
#define RETAINED_H

#include <zephyr/kernel.h>
#include <zephyr/retention/retention.h>

/* Retained state structure */
struct retained_data {
	uint32_t magic;           /* Magic number for validation */
	uint32_t measurement_count; /* Number of measurements taken */
	uint32_t boot_count;      /* Number of cold boots */
	int16_t last_temp_c;      /* Last temperature (°C * 100) */
	int32_t last_voltage_mv;  /* Last battery voltage (mV) */
	uint32_t checksum;        /* Simple checksum */
};

/* Magic number to validate retained data */
#define RETAINED_MAGIC 0x534F494C  /* "SOIL" in ASCII */

/* Global retained data instance */
extern struct retained_data retained;

/**
 * Validate retained data
 * @return true if valid, false if corrupted
 */
bool retained_validate(void);

/**
 * Update checksum in retained data
 */
void retained_update(void);

#endif /* RETAINED_H */
