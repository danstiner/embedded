#pragma once

#include <stdbool.h>
#include <stdint.h>

struct sht45_reading {
	int64_t timestamp;
	int16_t temperature_cC;  /* 0.01 deg C units */
	uint16_t humidity_cPct;  /* 0.01 % units */
	uint16_t temp_raw_ticks; /* raw SHT4x ticks for STCC4 compensation */
	uint16_t hum_raw_ticks;  /* raw SHT4x ticks for STCC4 compensation */
	bool valid;
};

struct bme688_reading {
	int64_t timestamp;
	int16_t pressure_kPa; /* kPa (for Matter PressureMeasurement) */
	uint32_t pressure_Pa; /* Pa  (for BTHome, STCC4 compensation) */
	bool valid;
};

struct stcc4_reading {
	int64_t timestamp;
	uint16_t co2_ppm;
	bool valid;
};

struct battery_reading {
	int64_t timestamp;
	uint8_t soc_pct; /* state of charge 0-100% */
	bool valid;
};

struct sensor_state {
	bool have_sht45;
	bool have_bme688;
	bool have_stcc4;
	bool have_battery;

	struct sht45_reading sht45;
	struct bme688_reading bme688;
	struct stcc4_reading stcc4;
	struct battery_reading battery;
};

/** Probe all sensors, populate have_* flags. Call once at boot. */
void sensor_init(sensor_state *state);

/** Individual sensor read functions. Each updates its sub-struct + timestamp. */
int sensor_read_sht45(sensor_state *state);
int sensor_read_bme688(sensor_state *state);
int sensor_read_stcc4(sensor_state *state);
int sensor_read_battery(sensor_state *state);

/** Initialize fuel gauge. Call once after sensor_init. */
void sensor_fuel_gauge_init(void);
