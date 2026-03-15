/*
 * Shared sensor reading module
 *
 * Extracted from bthome/main.cpp — used by both BTHome and Matter builds.
 */

#include "sensor_reading.h"
#include "sht4x.h"
#include "stcc4.h"

#include <zephyr/device.h>
#include <zephyr/drivers/i2c.h>
#include <zephyr/drivers/sensor.h>
#include <zephyr/drivers/regulator.h>
#include <zephyr/pm/device.h>
#include <zephyr/kernel.h>

#if DT_NODE_HAS_STATUS(DT_NODELABEL(npm1304_charger), okay)
#include <zephyr/drivers/sensor/npm13xx_charger.h>
#include <zephyr/drivers/mfd/npm13xx.h>
#endif

#if IS_ENABLED(CONFIG_NRF_FUEL_GAUGE)
#include <nrf_fuel_gauge.h>
#endif

#include <zephyr/logging/log.h>
LOG_MODULE_REGISTER(sensor_reading, LOG_LEVEL_INF);

/* ---- Device pointers ---- */
#if DT_NODE_HAS_STATUS(DT_NODELABEL(sht45), okay)
static const struct device *sht45 = DEVICE_DT_GET(DT_NODELABEL(sht45));
#endif

/* BME688 (Zephyr sensor driver) */
#if DT_NODE_HAS_STATUS(DT_NODELABEL(bme688), okay)
#define HAVE_BME688 1
static const struct device *bme688_dev = DEVICE_DT_GET(DT_NODELABEL(bme688));
#else
#define HAVE_BME688 0
#endif

/* STCC4 shares the BME688 I2C bus (raw I2C, no DT node) */
#if DT_NODE_HAS_STATUS(DT_NODELABEL(bme688), okay)
#define HAVE_STCC4_BUS 1
static const struct device *sensor_bus = DEVICE_DT_GET(DT_BUS(DT_NODELABEL(bme688)));
#else
#define HAVE_STCC4_BUS 0
#endif

/* Battery voltage sources */
#if DT_NODE_HAS_STATUS(DT_NODELABEL(npm2100_vbat), okay)
static const struct device *vbat_dev = DEVICE_DT_GET(DT_NODELABEL(npm2100_vbat));
#define HAVE_BATT 1
#elif DT_NODE_HAS_STATUS(DT_NODELABEL(npm1304_charger), okay)
static const struct device *vbat_dev = DEVICE_DT_GET(DT_NODELABEL(npm1304_charger));
#define HAVE_BATT 1
#else
#define HAVE_BATT 0
#endif

/* ---- Fuel gauge state ---- */
#if IS_ENABLED(CONFIG_NRF_FUEL_GAUGE)

#if IS_ENABLED(CONFIG_NRF_FUEL_GAUGE_VARIANT_SECONDARY_CELL)
static const struct battery_model battery_model = {
#include "battery_model.inc"
};
#elif IS_ENABLED(CONFIG_NRF_FUEL_GAUGE_VARIANT_PRIMARY_CELL)
static const struct battery_model_primary battery_model_primary = {
#include <battery_models/primary_cell/2SAAA_Alkaline.inc>
};
#endif

static int64_t fg_ref_time;
static bool fg_initialized;
static float fg_last_soc;
static float fg_last_v = 3.0f;
static float fg_last_t = 25.0f;

#endif /* CONFIG_NRF_FUEL_GAUGE */

/* ---- Helper: convert sensor_value to raw SHT4x ticks ---- */
static uint16_t temp_to_raw_ticks(const struct sensor_value *val)
{
	int64_t micro = (int64_t)val->val1 * 1000000 + val->val2;
	return (uint16_t)(((micro + 45000000LL) * 65535LL) / 175000000LL);
}

static uint16_t hum_to_raw_ticks(const struct sensor_value *val)
{
	int64_t micro = (int64_t)val->val1 * 1000000 + val->val2;
	int64_t raw = ((micro + 6000000LL) * 65535LL) / 125000000LL;
	if (raw < 0) {
		raw = 0;
	}
	if (raw > 65535) {
		raw = 65535;
	}
	return (uint16_t)raw;
}

/* ---- Charge state update (nPM1304 / secondary cell only) ---- */
#if IS_ENABLED(CONFIG_NRF_FUEL_GAUGE_VARIANT_SECONDARY_CELL) &&                                    \
	DT_NODE_HAS_STATUS(DT_NODELABEL(npm1304_charger), okay)
static void charge_status_inform(int32_t chg_status)
{
	union nrf_fuel_gauge_ext_state_info_data info;

	if (chg_status & BIT(1)) {
		info.charge_state = NRF_FUEL_GAUGE_CHARGE_STATE_COMPLETE;
	} else if (chg_status & BIT(2)) {
		info.charge_state = NRF_FUEL_GAUGE_CHARGE_STATE_TRICKLE;
	} else if (chg_status & BIT(3)) {
		info.charge_state = NRF_FUEL_GAUGE_CHARGE_STATE_CC;
	} else if (chg_status & BIT(4)) {
		info.charge_state = NRF_FUEL_GAUGE_CHARGE_STATE_CV;
	} else {
		info.charge_state = NRF_FUEL_GAUGE_CHARGE_STATE_IDLE;
	}
	nrf_fuel_gauge_ext_state_update(NRF_FUEL_GAUGE_EXT_STATE_INFO_CHARGE_STATE_CHANGE, &info);
}
#endif

/* ---- Sensor init ---- */
void sensor_init(sensor_state *state)
{
	memset(state, 0, sizeof(*state));

#if DT_NODE_HAS_STATUS(DT_NODELABEL(sht45), okay)
	if (device_is_ready(sht45)) {
		state->have_sht45 = true;
		LOG_INF("SHT45 ready");
	}
#endif

	/* LDOSW is enabled via regulator-boot-on in DTS to power I2C20 sensors */

#if HAVE_BME688
	if (device_is_ready(bme688_dev)) {
		state->have_bme688 = true;
		LOG_INF("BME688 detected");
	} else {
		LOG_INF("BME688 not present — skipping");
	}
#endif

#if HAVE_STCC4_BUS
	if (device_is_ready(sensor_bus)) {
		stcc4_wake(sensor_bus);
		if (stcc4_probe(sensor_bus)) {
			state->have_stcc4 = true;
			stcc4_enter_sleep(sensor_bus);
			LOG_INF("STCC4 detected");
		} else {
			LOG_INF("STCC4 not present — skipping");
		}
	}
#endif

	/* If no I2C20 sensors found, disable LDOSW and suspend I2C20 to save power */
#if DT_NODE_HAS_STATUS(DT_NODELABEL(npm2100_ldsw), okay)
	if (!state->have_bme688 && !state->have_stcc4) {
		const struct device *ldsw = DEVICE_DT_GET(DT_NODELABEL(npm2100_ldsw));
		if (device_is_ready(ldsw)) {
			regulator_disable(ldsw);
			LOG_INF("No I2C20 sensors — LDOSW disabled");
		}
#if DT_NODE_HAS_STATUS(DT_NODELABEL(bme688), okay)
		pm_device_action_run(DEVICE_DT_GET(DT_BUS(DT_NODELABEL(bme688))),
				     PM_DEVICE_ACTION_SUSPEND);
		LOG_INF("I2C20 suspended");
#endif
	}
#endif

#if HAVE_BATT
	if (device_is_ready(vbat_dev)) {
		state->have_battery = true;
		LOG_INF("Battery sensor ready");
	}
#endif
}

/* ---- Fuel gauge init ---- */
void sensor_fuel_gauge_init(void)
{
#if IS_ENABLED(CONFIG_NRF_FUEL_GAUGE) && HAVE_BATT
	if (!device_is_ready(vbat_dev)) {
		LOG_WRN("VBAT device not ready — fuel gauge skipped");
		return;
	}

	struct sensor_value sv;
	struct nrf_fuel_gauge_init_parameters fg_params = {
		.opt_params = nullptr,
		.state = nullptr,
	};

	sensor_sample_fetch(vbat_dev);

	sensor_channel_get(vbat_dev, SENSOR_CHAN_GAUGE_VOLTAGE, &sv);
	fg_params.v0 = (float)sv.val1 + (float)sv.val2 / 1000000.f;
	fg_last_v = fg_params.v0;

#if IS_ENABLED(CONFIG_NRF_FUEL_GAUGE_VARIANT_SECONDARY_CELL)
	fg_params.model = &battery_model;

	sensor_channel_get(vbat_dev, SENSOR_CHAN_GAUGE_TEMP, &sv);
	fg_params.t0 = (float)sv.val1 + (float)sv.val2 / 1000000.f;
	fg_last_t = fg_params.t0;

	sensor_channel_get(vbat_dev, SENSOR_CHAN_GAUGE_AVG_CURRENT, &sv);
	fg_params.i0 = -((float)sv.val1 + (float)sv.val2 / 1000000.f);

	struct sensor_value sv_cc;
	sensor_channel_get(vbat_dev, SENSOR_CHAN_GAUGE_DESIRED_CHARGING_CURRENT, &sv_cc);
	float max_current = (float)sv_cc.val1 + (float)sv_cc.val2 / 1000000.f;
#elif IS_ENABLED(CONFIG_NRF_FUEL_GAUGE_VARIANT_PRIMARY_CELL)
	fg_params.model_primary = &battery_model_primary;

	sensor_channel_get(vbat_dev, SENSOR_CHAN_DIE_TEMP, &sv);
	fg_params.t0 = (float)sv.val1 + (float)sv.val2 / 1000000.f;
	fg_last_t = fg_params.t0;

	fg_params.i0 = 0.0f;
#endif

	int fg_ret = nrf_fuel_gauge_init(&fg_params, nullptr);
	if (fg_ret < 0) {
		LOG_ERR("Fuel gauge init failed: %d", fg_ret);
		return;
	}

#if IS_ENABLED(CONFIG_NRF_FUEL_GAUGE_VARIANT_SECONDARY_CELL)
	union nrf_fuel_gauge_ext_state_info_data fg_info;

	fg_info.charge_current_limit = max_current;
	nrf_fuel_gauge_ext_state_update(NRF_FUEL_GAUGE_EXT_STATE_INFO_CHARGE_CURRENT_LIMIT,
					&fg_info);

	fg_info.charge_term_current = max_current / 10.f;
	nrf_fuel_gauge_ext_state_update(NRF_FUEL_GAUGE_EXT_STATE_INFO_TERM_CURRENT, &fg_info);
#endif

	fg_initialized = true;
	LOG_INF("Fuel gauge initialized (%s)", nrf_fuel_gauge_version);
	fg_ref_time = k_uptime_get();
#endif /* CONFIG_NRF_FUEL_GAUGE && HAVE_BATT */
}

/* ---- Read SHT45 ---- */
int sensor_read_sht45(sensor_state *state)
{
#if DT_NODE_HAS_STATUS(DT_NODELABEL(sht45), okay)
	if (!state->have_sht45) {
		return -ENODEV;
	}

	int ret = sensor_sample_fetch(sht45);
	if (ret) {
		LOG_ERR("SHT45 fetch failed: %d", ret);
		state->sht45.valid = false;
		return ret;
	}

	struct sensor_value value;

	sensor_channel_get(sht45, SENSOR_CHAN_AMBIENT_TEMP, &value);
	state->sht45.temperature_cC = value.val1 * 100 + value.val2 / 10000;
	state->sht45.temp_raw_ticks = temp_to_raw_ticks(&value);
	LOG_INF("SHT45: T=%d.%02d°C", value.val1, value.val2 / 10000);

	sensor_channel_get(sht45, SENSOR_CHAN_HUMIDITY, &value);
	state->sht45.humidity_cPct = value.val1 * 100 + value.val2 / 10000;
	state->sht45.hum_raw_ticks = hum_to_raw_ticks(&value);
	LOG_INF("SHT45: RH=%d.%02d%%", value.val1, value.val2 / 10000);

	state->sht45.timestamp = k_uptime_get();
	state->sht45.valid = true;
	return 0;
#else
	return -ENOTSUP;
#endif
}

/* ---- Read BME688 ---- */
int sensor_read_bme688(sensor_state *state)
{
#if HAVE_BME688
	if (!state->have_bme688) {
		return -ENODEV;
	}

	int ret = sensor_sample_fetch(bme688_dev);
	if (ret) {
		LOG_WRN("BME688 fetch failed: %d", ret);
		state->bme688.valid = false;
		return ret;
	}

	struct sensor_value value;

	sensor_channel_get(bme688_dev, SENSOR_CHAN_PRESS, &value);
	state->bme688.pressure_Pa = value.val1 * 1000 + value.val2 / 1000;
	state->bme688.pressure_kPa = (int16_t)value.val1;
	LOG_INF("BME688: P=%d.%03d kPa", value.val1, value.val2 / 1000);

	state->bme688.timestamp = k_uptime_get();
	state->bme688.valid = true;
	return 0;
#else
	return -ENOTSUP;
#endif
}

/* ---- Read STCC4 ---- */
int sensor_read_stcc4(sensor_state *state)
{
#if HAVE_STCC4_BUS
	if (!state->have_stcc4) {
		return -ENODEV;
	}

	/* Wake sensor from sleep before measurement */
	stcc4_wake(sensor_bus);

	/* Feed compensation from latest SHT45/BME688 readings */
	if (state->sht45.valid) {
		stcc4_set_rht_compensation(sensor_bus, state->sht45.temp_raw_ticks,
					   state->sht45.hum_raw_ticks);
	}
	if (state->bme688.valid) {
		uint16_t pressure_enc = (uint16_t)(state->bme688.pressure_Pa / 2);
		stcc4_set_pressure_compensation(sensor_bus, pressure_enc);
	}

	uint16_t co2;
	int ret = stcc4_measure(sensor_bus, &co2);
	if (ret) {
		LOG_WRN("STCC4 measure failed: %d", ret);
		state->stcc4.valid = false;
		return ret;
	}

	state->stcc4.co2_ppm = co2;
	state->stcc4.timestamp = k_uptime_get();
	state->stcc4.valid = true;
	LOG_INF("STCC4: CO2=%u ppm", co2);

	stcc4_enter_sleep(sensor_bus);
	return 0;
#else
	return -ENOTSUP;
#endif
}

/* ---- Read battery ---- */
int sensor_read_battery(sensor_state *state)
{
#if HAVE_BATT
	if (!state->have_battery || !device_is_ready(vbat_dev)) {
		return -ENODEV;
	}

	int ret = sensor_sample_fetch(vbat_dev);
	if (ret) {
		LOG_WRN("Battery voltage fetch failed: %d", ret);
		state->battery.valid = false;
		return ret;
	}

	struct sensor_value voltage;
	ret = sensor_channel_get(vbat_dev, SENSOR_CHAN_GAUGE_VOLTAGE, &voltage);
	if (ret) {
		LOG_WRN("Battery voltage get failed: %d", ret);
		state->battery.valid = false;
		return ret;
	}

	LOG_INF("BAT_V: %d.%03dV", voltage.val1, voltage.val2 / 1000);

#if IS_ENABLED(CONFIG_NRF_FUEL_GAUGE)
	if (fg_initialized) {
		struct sensor_value sv_temp;
		float v = (float)voltage.val1 + (float)voltage.val2 / 1000000.f;
		float t, i;

#if IS_ENABLED(CONFIG_NRF_FUEL_GAUGE_VARIANT_SECONDARY_CELL) &&                                    \
	DT_NODE_HAS_STATUS(DT_NODELABEL(npm1304_charger), okay)
		sensor_channel_get(vbat_dev, SENSOR_CHAN_GAUGE_TEMP, &sv_temp);
		t = (float)sv_temp.val1 + (float)sv_temp.val2 / 1000000.f;

		struct sensor_value sv_current;
		sensor_channel_get(vbat_dev, SENSOR_CHAN_GAUGE_AVG_CURRENT, &sv_current);
		i = -((float)sv_current.val1 + (float)sv_current.val2 / 1000000.f);

		static int32_t prev_chg = -1;
		struct sensor_value sv_status;
		sensor_channel_get(vbat_dev,
				   (enum sensor_channel)SENSOR_CHAN_NPM13XX_CHARGER_STATUS,
				   &sv_status);
		if (sv_status.val1 != prev_chg) {
			prev_chg = sv_status.val1;
			charge_status_inform(sv_status.val1);
		}
#elif IS_ENABLED(CONFIG_NRF_FUEL_GAUGE_VARIANT_PRIMARY_CELL)
		sensor_channel_get(vbat_dev, SENSOR_CHAN_DIE_TEMP, &sv_temp);
		t = (float)sv_temp.val1 + (float)sv_temp.val2 / 1000000.f;
		i = 1.0e-3f;
#endif

		float delta = (float)k_uptime_delta(&fg_ref_time) / 1000.f;
		fg_last_soc = nrf_fuel_gauge_process(v, i, t, delta, nullptr);
		fg_last_v = v;
		fg_last_t = t;

		state->battery.soc_pct = CLAMP((int)fg_last_soc, 0, 100);
		LOG_INF("BAT_%%: %d%%", (int)fg_last_soc);
	}
#endif /* CONFIG_NRF_FUEL_GAUGE */

	state->battery.timestamp = k_uptime_get();
	state->battery.valid = true;
	return 0;
#else
	return -ENOTSUP;
#endif
}

/* ---- Force recalibration STCC4 ---- */
int sensor_force_recalibration_stcc4(uint16_t target_co2_ppm)
{
#if HAVE_STCC4_BUS
	if (!device_is_ready(sensor_bus)) {
		return -ENODEV;
	}

	stcc4_wake(sensor_bus);

	uint16_t correction;
	int ret = stcc4_force_recalibration(sensor_bus, target_co2_ppm, &correction);

	stcc4_enter_sleep(sensor_bus);

	if (ret) {
		LOG_ERR("STCC4 FRC failed: %d", ret);
	} else {
		LOG_INF("STCC4 FRC done: target=%u ppm, correction=0x%04X", target_co2_ppm,
			correction);
	}

	return ret;
#else
	return -ENOTSUP;
#endif
}
