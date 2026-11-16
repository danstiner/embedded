#pragma once

#include <stdbool.h>
#include <stdint.h>

/* Each reading's `valid` flag is true when the last *attempted* read of that
 * sensor succeeded. It persists across divisor skip cycles — a skip is not a
 * read — so the last value keeps being reported until the next attempt.
 * Consumers treat invalid as unknown: Matter writes null, BTHome omits the
 * field from the advertisement. */

struct sht4x_reading {
	int64_t timestamp;
	int16_t temperature_cC; /* 0.01 deg C units */
	uint16_t humidity_cPct; /* 0.01 % units */
	bool valid;
};

struct bme688_reading {
	int64_t timestamp;
	int16_t pressure_hPa; /* hPa = 0.1 kPa, the Matter PressureMeasurement encoding */
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
	uint8_t percent; /* coarse charge estimate, 0-100; 0xFF = unknown */
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
	struct battery_reading battery;
	struct leak_reading leak;
};

/** Probe all sensors, populate have_* flags. Call once at boot. */
void sensor_init(sensor_state &state);

/** Individual sensor read functions. Each updates its sub-struct + timestamp
 *  and sets `valid` to whether this attempt produced a usable value. */
int sensor_read_sht4x(sensor_state &state);
int sensor_read_bme688(sensor_state &state);
int sensor_read_stcc4(sensor_state &state);
int sensor_read_battery(sensor_state &state);

/** One measurement cycle: read SHT4x + battery every call, BME688 on a
 *  pressure-divisor cycle and STCC4 on a CO2-divisor cycle (see
 *  CONFIG_APP_*_INTERVAL_DIVISOR). Shared by the BTHome and Matter loops so the
 *  cadence stays identical. */
void sensor_read_cycle(sensor_state &state, uint32_t cycle);

/** Initialize fuel gauge. Call once after sensor_init. */
void sensor_fuel_gauge_init(void);

/** Inform fuel gauge of upcoming idle/sleep period.
 *  Call before entering low-power sleep so the library can account for
 *  discharge accurately during sleep when fuel-guage processing is
 * not being run by sensor_read_battery(). */
void sensor_fuel_gauge_idle_set(void);

/** Current STCC4 maintenance state. Values are 1:1 with the Matter Mode Select modes
 *  (Co2Cal::kModeNormal/kModeRecalibrate/kModeFactoryReset) so the Matter layer can
 *  reflect this straight into CurrentMode. FACTORY_RESET covers both the reset itself
 *  and the long warm-up that follows it. */
enum co2_state {
	CO2_STATE_MEASURE = 0,
	CO2_STATE_RECALIBRATE = 1,
	CO2_STATE_FACTORY_RESET = 2,
};

/** Current CO2 maintenance state, counting a request the loop has not picked up yet.
 *  Call from the measurement-loop thread. */
enum co2_state sensor_co2_state(void);

/** Request a forced recalibration of the STCC4 to target_ppm (datasheet §3.4.15).
 *  Non-destructive: a new FRC replaces the previous correction offset. Safe from any
 *  thread and returns immediately; the measurement loop picks the request up on its
 *  next CO2 cycle, conditions the sensor, then takes 30 readings at the CO2 interval
 *  (held in idle, CO2 reported unavailable) and applies the FRC after the last one.
 *  Dropped if another request is pending or an operation is already running. */
void sensor_request_stcc4_recal(uint16_t target_ppm);

/** Request an STCC4 factory reset (datasheet §3.4.11): wipes FRC + ASC history and
 *  re-enables the bypass phase. Destructive recovery for a unit stuck at the
 *  placeholder/floor; followed by conditioning and the CONFIG_APP_CO2_WARMUP_MIN
 *  continuous-mode warm-up, all driven by the measurement loop. Same hand-off and
 *  drop rules as sensor_request_stcc4_recal(). */
void sensor_request_stcc4_factory_reset(void);
