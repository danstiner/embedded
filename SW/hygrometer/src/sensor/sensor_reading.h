#pragma once

#include <stdbool.h>
#include <stdint.h>

struct sht4x_reading {
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

/* Coarse battery health. For a flat-curve coin cell this is more meaningful than
 * a percentage; values mirror Matter's Power Source BatChargeLevel enum. */
enum battery_health {
	BATTERY_OK = 0,
	BATTERY_LOW = 1,
	BATTERY_CRITICAL = 2,
};

struct battery_reading {
	int64_t timestamp;
	uint16_t millivolts; /* measured terminal voltage (mV) */
	enum battery_health health;
	bool valid;
};

struct leak_reading {
	int64_t timestamp;
	bool wet; /* true when water bridges the leak electrodes */
	bool valid;
};

struct sensor_state {
	bool have_sht4x;
	bool have_bme688;
	bool have_stcc4;
	bool have_battery;
	bool have_leak;

	struct sht4x_reading sht4x;
	struct bme688_reading bme688;
	struct stcc4_reading stcc4;
	uint8_t stcc4_discards_remaining;
	struct battery_reading battery;
	struct leak_reading leak;
};

/* Pointer-based, C-linkage API so the (C) Zigbee app can call it directly without
 * a shim — the BTHome/Matter C++ builds use the same functions. */
#ifdef __cplusplus
extern "C" {
#endif

/** Probe all sensors, populate have_* flags. Call once at boot. */
void sensor_init(struct sensor_state *state);

/** Individual sensor read functions. Each updates its sub-struct + timestamp. */
int sensor_read_sht4x(struct sensor_state *state);
int sensor_read_bme688(struct sensor_state *state);
int sensor_read_stcc4(struct sensor_state *state);
int sensor_read_battery(struct sensor_state *state);

/** One measurement cycle: read SHT4x + battery every call, BME688 on a
 *  pressure-divisor cycle and STCC4 on a CO2-divisor cycle (see
 *  CONFIG_APP_*_INTERVAL_DIVISOR). Shared by the BTHome and Matter loops so the
 *  cadence stays identical. */
void sensor_read_cycle(struct sensor_state *state, uint32_t cycle);

/** Initialize fuel gauge. Call once after sensor_init. */
void sensor_fuel_gauge_init(void);

/** Inform fuel gauge of upcoming idle/sleep period.
 *  Call before entering low-power sleep so the library can account for
 *  discharge accurately during sleep when fuel-guage processing is
 * not being run by sensor_read_battery(). */
void sensor_fuel_gauge_idle_set(void);

/** Force recalibration of STCC4 CO2 sensor.
 *  Wakes sensor, runs FRC at target_co2_ppm, puts sensor back to sleep.
 *  Returns 0 on success, negative errno on failure. */
int sensor_force_recalibration_stcc4(uint16_t target_co2_ppm);

#ifdef __cplusplus
}
#endif
