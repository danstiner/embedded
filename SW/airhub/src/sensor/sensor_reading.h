#pragma once

#include <stdbool.h>
#include <stdint.h>

struct scd40_reading {
	int64_t timestamp;
	uint16_t co2_ppm;
	bool valid;
};

struct sht4x_reading {
	int64_t timestamp;
	int16_t temperature_cC;  /* 0.01 °C */
	uint16_t humidity_cPct;  /* 0.01 % */
	bool valid;
};

struct sensor_state {
	bool have_scd40;
	bool have_sht4x;

	struct scd40_reading scd40;
	struct sht4x_reading sht4x;
};

/** Probe all sensors, populate have_* flags. Call once at boot. */
void sensor_init(sensor_state &state);

/** Individual sensor read functions. Each updates its sub-struct + timestamp. */
int sensor_read_scd40(sensor_state &state);
int sensor_read_sht4x(sensor_state &state);
