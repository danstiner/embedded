/*
 * Shared sensor reading module
 *
 * Extracted from bthome/main.cpp — used by both BTHome and Matter builds.
 */

#include "sensor_reading.h"
#include "sht4x.h"
#include "stcc4.h"

#include <zephyr/device.h>
#include <zephyr/drivers/adc.h>
#include <zephyr/drivers/gpio.h>
#include <zephyr/drivers/i2c.h>
#include <zephyr/drivers/sensor.h>
#include <zephyr/drivers/regulator.h>
#include <zephyr/drivers/pinctrl.h>
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

/* Declare I2C20 pinctrl config as externally accessible (for "off" state) */
#if DT_NODE_HAS_STATUS(DT_NODELABEL(bme688), okay)
PINCTRL_DT_DEV_CONFIG_DECLARE(DT_NODELABEL(i2c20));
#endif

/* ---- Device pointers ---- */
#if DT_NODE_HAS_STATUS(DT_NODELABEL(sht4x), okay)
static const struct device *sht4x = DEVICE_DT_GET(DT_NODELABEL(sht4x));
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
static K_MUTEX_DEFINE(stcc4_mutex);
/* Uptime before which the STCC4 must not be read or slept: conditioning runs
 * inside the sensor for STCC4_CONDITIONING_MS after boot (no completion signal). */
static int64_t stcc4_cond_until;
/* While non-zero (an uptime deadline), the STCC4 is in a continuous-mode warm-up after a
 * factory reset; sensor_read_stcc4 reads it in continuous mode (no single-shot/sleep) and
 * reports the value as invalid until the deadline passes. */
static int64_t stcc4_warmup_until;
/* Number of single-shots to discard after (re)entering single-shot mode: the bypass phase
 * emits a fixed 390 ppm placeholder for the first 2 single-shots (datasheet §1.1.2). */
#define STCC4_BYPASS_DISCARDS 2
#else
#define HAVE_STCC4_BUS 0
#endif

/* Battery voltage sources.
 *
 * HAVE_BATT_PMIC: nPM2100/nPM1304 PMIC fuel gauge (Zephyr sensor driver).
 * HAVE_BATT_ADC:  raw CR2 coin cell measured via SAADC internal VDD (2026v4 —
 *                 no PMIC). The two are mutually exclusive in practice. */
#if DT_NODE_HAS_STATUS(DT_NODELABEL(npm2100_vbat), okay)
static const struct device *vbat_dev = DEVICE_DT_GET(DT_NODELABEL(npm2100_vbat));
#define HAVE_BATT_PMIC 1
#elif DT_NODE_HAS_STATUS(DT_NODELABEL(npm1304_charger), okay)
static const struct device *vbat_dev = DEVICE_DT_GET(DT_NODELABEL(npm1304_charger));
#define HAVE_BATT_PMIC 1
#endif

#if DT_NODE_EXISTS(DT_NODELABEL(vbatt)) && DT_NODE_HAS_STATUS(DT_NODELABEL(adc), okay)
static const struct adc_dt_spec vbatt_adc = ADC_DT_SPEC_GET(DT_NODELABEL(vbatt));
#define HAVE_BATT_ADC 1
#endif

#ifndef HAVE_BATT_PMIC
#define HAVE_BATT_PMIC 0
#endif
#ifndef HAVE_BATT_ADC
#define HAVE_BATT_ADC 0
#endif
#define HAVE_BATT (HAVE_BATT_PMIC || HAVE_BATT_ADC)

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

/* ---- Helper: CR2 (Li-MnO2) voltage → coarse battery health ---- */
#if HAVE_BATT_ADC
/* CR2 voltage → coarse health with hysteresis. Thresholds sit at the knee of the
 * Li-MnO2 curve: LOW ~2.80 V (~20% left), CRITICAL ~2.65 V (~7% left). The ~50 mV
 * gap between enter/clear keeps the state from flapping on the flat plateau. */
static enum battery_health cr2_health(int32_t mv)
{
	static enum battery_health h = BATTERY_OK;
	switch (h) {
	case BATTERY_OK:
		if (mv <= 2650) {
			h = BATTERY_CRITICAL;
		} else if (mv <= 2800) {
			h = BATTERY_LOW;
		}
		break;
	case BATTERY_LOW:
		if (mv <= 2650) {
			h = BATTERY_CRITICAL;
		} else if (mv >= 2850) {
			h = BATTERY_OK;
		}
		break;
	case BATTERY_CRITICAL:
		if (mv >= 2850) {
			h = BATTERY_OK;
		} else if (mv >= 2700) {
			h = BATTERY_LOW;
		}
		break;
	}
	return h;
}

/* Coarse CR2 charge estimate from terminal voltage. The Li-MnO2 curve is flat, so
 * this is only a rough gauge: 0% at 2.50 V, 100% at 3.00 V, clamped, monotonic. */
static uint8_t cr2_percent(int32_t mv)
{
	int32_t pct = (mv - 2500) * 100 / 500;
	return (uint8_t)CLAMP(pct, 0, 100);
}
#endif /* HAVE_BATT_ADC */

#if HAVE_BATT_PMIC
/* Fuel-gauge SoC% → coarse health enum */
static enum battery_health soc_health(uint8_t soc)
{
	return soc <= 5 ? BATTERY_CRITICAL : soc <= 15 ? BATTERY_LOW : BATTERY_OK;
}
#endif /* HAVE_BATT_PMIC */

#if HAVE_STCC4_BUS && CONFIG_STCC4_ENABLE
/* ---- Helper: convert sensor_value to raw STCC4 compensation ticks ----
 * STCC4 datasheet Table 11 input conversions (2^16 - 1 = 65535):
 *   Temperature: Input = (T[degC] + 45) * (2^16 - 1) / 175
 *   Humidity:    Input = (RH[%RH] + 6) * (2^16 - 1) / 125
 * Values are computed in micro-units to keep integer precision. */
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

/* Fetch the SHT4x and push RH/T (+ pressure when pressure_pa != 0) compensation to the STCC4.
 * Shared by the periodic read and the FRC routine so both use identical Table 11 conversions;
 * logs the values applied so CO2 readings can be correlated with environment. The sensor must
 * be awake. On SHT4x failure the previous compensation (retained across sleep) is kept. */
static void stcc4_push_compensation(uint32_t pressure_pa)
{
	struct sensor_value temp, hum;

	if (sensor_sample_fetch(sht4x) == 0) {
		sensor_channel_get(sht4x, SENSOR_CHAN_AMBIENT_TEMP, &temp);
		sensor_channel_get(sht4x, SENSOR_CHAN_HUMIDITY, &hum);
		stcc4_set_rht_compensation(sensor_bus, temp_to_raw_ticks(&temp),
					   hum_to_raw_ticks(&hum));
		LOG_INF("STCC4 comp: T=%d.%02d°C RH=%d.%02d%%", temp.val1, temp.val2 / 10000,
			hum.val1, hum.val2 / 10000);
	} else {
		LOG_WRN("STCC4 comp: SHT4x fetch failed, keeping prior compensation");
	}

	if (pressure_pa != 0) {
		stcc4_set_pressure_compensation(sensor_bus, (uint16_t)(pressure_pa / 2));
		LOG_INF("STCC4 comp: P=%u Pa", pressure_pa);
	}
}
#endif /* HAVE_STCC4_BUS && CONFIG_STCC4_ENABLE */

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
void sensor_init(sensor_state &state)
{
	memset(&state, 0, sizeof(state));

#if DT_NODE_HAS_STATUS(DT_NODELABEL(sht4x), okay)
	if (device_is_ready(sht4x)) {
		state.have_sht4x = true;
		LOG_INF("SHT4x ready");
	}
#endif

	/* LDOSW is enabled via regulator-boot-on in DTS to power I2C20 sensors */

#if HAVE_BME688 && CONFIG_BME688_ENABLE
	/* Wait for sensor start-up */
	k_msleep(2);

	if (device_is_ready(bme688_dev)) {
		state.have_bme688 = true;
		LOG_INF("BME688 detected");
	} else {
		LOG_INF("BME688 not present — skipping");
	}
#endif

#if HAVE_STCC4_BUS && CONFIG_STCC4_ENABLE
	/* Wait for sensor start-up */
	k_msleep(10);
	if (device_is_ready(sensor_bus)) {
		k_mutex_lock(&stcc4_mutex, K_FOREVER);
		stcc4_exit_sleep(sensor_bus);
		bool present = stcc4_probe(sensor_bus);
		if (!present) {
			/* A reboot during a continuous-mode warm-up leaves the sensor in continuous
			 * mode, where get_product_id NACKs. Stop it and retry once. */
			stcc4_stop_continuous(sensor_bus);
			present = stcc4_probe(sensor_bus);
		}
		if (present) {
			state.have_stcc4 = true;
			state.stcc4_discards_remaining = STCC4_BYPASS_DISCARDS;
			LOG_INF("STCC4 detected");
			/* Clear any persisted testing mode (it freezes the sensor at the
			 * placeholder output) and log a one-shot self-test health verdict. */
			stcc4_disable_testing_mode(sensor_bus);
			uint16_t self_test = 0;
			if (stcc4_self_test(sensor_bus, &self_test) == 0) {
				/* 0x0000 and 0x0010 are both "pass" (§3.4.12); bit 4 (no SHT on the
				 * STCC4 controller pads) is expected here — we compensate in software. */
				if ((self_test & ~STCC4_SELF_TEST_SHT_NOT_CONNECTED) == 0) {
					LOG_INF("STCC4 self-test: pass (0x%04X)", self_test);
				} else {
					LOG_ERR("STCC4 self-test: FAIL (0x%04X)", self_test);
				}
			}
			/* Conditioning runs inside the sensor; don't block boot on it.
			 * The sensor must stay awake meanwhile — the first read after
			 * the window ends puts it back to sleep. */
			stcc4_start_conditioning(sensor_bus);
			stcc4_cond_until = k_uptime_get() + STCC4_CONDITIONING_MS;
		} else {
			LOG_INF("STCC4 not present — skipping");
		}
		k_mutex_unlock(&stcc4_mutex);
	}
#endif

	/* If no I2C20 sensors found, disable LDOSW and suspend I2C20 to save power */
#if DT_NODE_HAS_STATUS(DT_NODELABEL(npm2100_ldsw), okay)
	if (!state.have_bme688 && !state.have_stcc4) {
		const struct device *ldsw = DEVICE_DT_GET(DT_NODELABEL(npm2100_ldsw));
		if (device_is_ready(ldsw)) {
			regulator_disable(ldsw);
			LOG_INF("No I2C20 sensors — LDOSW disabled");
		}
#if DT_NODE_HAS_STATUS(DT_NODELABEL(bme688), okay)
		pm_device_action_run(DEVICE_DT_GET(DT_BUS(DT_NODELABEL(bme688))),
				     PM_DEVICE_ACTION_SUSPEND);
		/* Apply "off" pinctrl state — no pull-ups, avoids leaking
		 * current through unpowered sensor ESD diodes. */
		const struct pinctrl_dev_config *pcfg =
			PINCTRL_DT_DEV_CONFIG_GET(DT_NODELABEL(i2c20));
		pinctrl_apply_state(pcfg, PINCTRL_STATE_PRIV_START);
		LOG_INF("I2C20 suspended, pins set to off state");
#endif
	}
#endif

#if HAVE_BATT_PMIC
	if (device_is_ready(vbat_dev)) {
		state.have_battery = true;
		LOG_INF("Battery sensor ready");
	}
#elif HAVE_BATT_ADC
	if (adc_is_ready_dt(&vbatt_adc) && adc_channel_setup_dt(&vbatt_adc) == 0) {
		state.have_battery = true;
		LOG_INF("Battery ADC ready");
	} else {
		LOG_WRN("Battery ADC not ready");
	}
#endif
}

/* ---- Fuel gauge init ---- */
void sensor_fuel_gauge_init(void)
{
#if IS_ENABLED(CONFIG_NRF_FUEL_GAUGE) && HAVE_BATT_PMIC
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

/* ---- Read SHT4x ---- */
int sensor_read_sht4x(sensor_state &state)
{
#if DT_NODE_HAS_STATUS(DT_NODELABEL(sht4x), okay)
	if (!state.have_sht4x) {
		return -ENODEV;
	}

	int ret = sensor_sample_fetch(sht4x);
	if (ret) {
		LOG_ERR("SHT4x fetch failed: %d", ret);
		state.sht4x.valid = false;
		return ret;
	}

	struct sensor_value value;

	sensor_channel_get(sht4x, SENSOR_CHAN_AMBIENT_TEMP, &value);
	state.sht4x.temperature_cC = value.val1 * 100 + value.val2 / 10000;
	LOG_INF("SHT4x: T=%d.%02d°C", value.val1, value.val2 / 10000);

	sensor_channel_get(sht4x, SENSOR_CHAN_HUMIDITY, &value);
	state.sht4x.humidity_cPct = value.val1 * 100 + value.val2 / 10000;
	LOG_INF("SHT4x: RH=%d.%02d%%", value.val1, value.val2 / 10000);

	state.sht4x.timestamp = k_uptime_get();
	state.sht4x.valid = true;
	return 0;
#else
	return -ENOTSUP;
#endif
}

/* ---- Read BME688 ---- */
int sensor_read_bme688(sensor_state &state)
{
#if HAVE_BME688 && CONFIG_BME688_ENABLE
	if (!state.have_bme688) {
		return -ENODEV;
	}

	int ret = sensor_sample_fetch(bme688_dev);
	if (ret) {
		LOG_WRN("BME688 fetch failed: %d", ret);
		state.bme688.valid = false;
		return ret;
	}

	struct sensor_value value;

	sensor_channel_get(bme688_dev, SENSOR_CHAN_PRESS, &value);
	state.bme688.pressure_Pa = value.val1 * 1000 + value.val2 / 1000;
	state.bme688.pressure_hPa = (int16_t)(state.bme688.pressure_Pa / 100);
	LOG_INF("BME688: P=%d.%03d kPa", value.val1, value.val2 / 1000);

	state.bme688.timestamp = k_uptime_get();
	state.bme688.valid = true;
	return 0;
#else
	return -ENOTSUP;
#endif
}

/* ---- Read STCC4 ---- */
int sensor_read_stcc4(sensor_state &state)
{
#if HAVE_STCC4_BUS && CONFIG_STCC4_ENABLE
	if (!state.have_stcc4) {
		return -ENODEV;
	}

	if (k_uptime_get() < stcc4_cond_until) {
		LOG_INF("STCC4: skipping read, conditioning in progress");
		state.stcc4.valid = false;
		return -EBUSY;
	}

	/* Skip if FRC is in progress */
	if (k_mutex_lock(&stcc4_mutex, K_NO_WAIT) != 0) {
		LOG_INF("STCC4: skipping read, FRC in progress");
		return -EBUSY;
	}

	if (stcc4_warmup_until != 0) {
		if (k_uptime_get() < stcc4_warmup_until) {
			/* Post-factory-reset initial-operation warm-up: the sensor is in continuous
			 * mode, so read it without triggering a single-shot or sleeping it. Not yet
			 * accurate — log but report invalid. */
			stcc4_push_compensation(state.bme688.valid ? state.bme688.pressure_Pa : 0);

			int16_t wco2 = 0;
			uint16_t wstatus = 0;
			int wret = stcc4_read_continuous(sensor_bus, wco2, &wstatus);
			k_mutex_unlock(&stcc4_mutex);

			if (wret == 0) {
				LOG_INF("STCC4 warm-up: CO2=%d ppm (status 0x%04X)", wco2, wstatus);
			}
			state.stcc4.valid = false;
			return 0;
		}

		/* Warm-up window elapsed: stop continuous mode and fall through to single-shot.
		 * Re-arm the discard counter — restarting single-shot re-triggers the bypass phase. */
		stcc4_stop_continuous(sensor_bus);
		stcc4_enter_sleep(sensor_bus);
		stcc4_warmup_until = 0;
		state.stcc4_discards_remaining = STCC4_BYPASS_DISCARDS;
		LOG_INF("STCC4 warm-up complete, resuming single-shot");
	}

	/* Wake sensor from sleep before measurement */
	stcc4_exit_sleep(sensor_bus);

	stcc4_push_compensation(state.bme688.valid ? state.bme688.pressure_Pa : 0);

	int16_t co2;
	uint16_t status = 0;
	int ret = stcc4_measure(sensor_bus, co2, &status);

	/* Put sensor back to sleep even if measurement fails */
	stcc4_enter_sleep(sensor_bus);
	k_mutex_unlock(&stcc4_mutex);

	if (ret) {
		LOG_WRN("STCC4 measure failed: %d", ret);
		state.stcc4.valid = false;
		return ret;
	}

	/* Non-zero status (e.g. testing mode) means the reading is a placeholder/floor value,
	 * not a real measurement — never report it. */
	if (status != 0) {
		LOG_WRN("STCC4: discarding reading, status 0x%04X (CO2=%d)", status, co2);
		state.stcc4.valid = false;
		return -EIO;
	}

	if (co2 < 0) {
		LOG_WRN("STCC4 negative CO2: %d", co2);
		state.stcc4.valid = false;
		return -EINVAL;
	}

	LOG_INF("STCC4: CO2=%u ppm (status 0x%04X)", co2, status);

	if (state.stcc4_discards_remaining > 0) {
		state.stcc4_discards_remaining--;
		LOG_INF("STCC4: discarding warm-up reading (%u remaining)",
			state.stcc4_discards_remaining);
		state.stcc4.valid = false;
		return 0;
	}

	state.stcc4.co2_ppm = co2;
	state.stcc4.timestamp = k_uptime_get();
	state.stcc4.valid = true;

	return 0;
#else
	return -ENOTSUP;
#endif
}

/* ---- Read battery ---- */
int sensor_read_battery(sensor_state &state)
{
#if HAVE_BATT_ADC
	if (!state.have_battery) {
		return -ENODEV;
	}

	int16_t sample = 0;
	struct adc_sequence seq = {
		.buffer = &sample,
		.buffer_size = sizeof(sample),
	};
	adc_sequence_init_dt(&vbatt_adc, &seq);

	int ret = adc_read_dt(&vbatt_adc, &seq);
	if (ret) {
		LOG_WRN("Battery ADC read failed: %d", ret);
		state.battery.valid = false;
		return ret;
	}

	int32_t mv = sample;
	adc_raw_to_millivolts_dt(&vbatt_adc, &mv);
	if (mv < 0) {
		mv = 0;
	}

	state.battery.millivolts = (uint16_t)mv;
	state.battery.health = cr2_health(mv);
	state.battery.percent = cr2_percent(mv);
	state.battery.timestamp = k_uptime_get();
	state.battery.valid = true;
	LOG_INF("BAT_V: %d.%03dV (%s)", mv / 1000, mv % 1000,
		state.battery.health == BATTERY_OK    ? "ok"
		: state.battery.health == BATTERY_LOW ? "LOW"
						      : "CRITICAL");
	return 0;
#elif HAVE_BATT_PMIC
	if (!state.have_battery || !device_is_ready(vbat_dev)) {
		return -ENODEV;
	}

	int ret = sensor_sample_fetch(vbat_dev);
	if (ret) {
		LOG_WRN("Battery voltage fetch failed: %d", ret);
		state.battery.valid = false;
		return ret;
	}

	struct sensor_value voltage;
	ret = sensor_channel_get(vbat_dev, SENSOR_CHAN_GAUGE_VOLTAGE, &voltage);
	if (ret) {
		LOG_WRN("Battery voltage get failed: %d", ret);
		state.battery.valid = false;
		return ret;
	}

	LOG_INF("BAT_V: %d.%03dV", voltage.val1, voltage.val2 / 1000);
	state.battery.millivolts = (uint16_t)(voltage.val1 * 1000 + voltage.val2 / 1000);

	/* Default to unknown rather than the memset-zero OK/0% defaults */
	state.battery.percent = 0xFF;
	state.battery.timestamp = k_uptime_get();
	state.battery.valid = false;

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

		uint8_t soc = CLAMP((int)fg_last_soc, 0, 100);
		state.battery.health = soc_health(soc);
		state.battery.percent = soc;
		state.battery.valid = true;
		LOG_INF("BAT_%%: %u%%", soc);
	}
#endif /* CONFIG_NRF_FUEL_GAUGE */

	return 0;
#else
	return -ENOTSUP;
#endif
}

/* ---- One measurement cycle (shared cadence for BTHome + Matter) ---- */
void sensor_read_cycle(sensor_state &state, uint32_t cycle)
{
	sensor_read_sht4x(state);

	/* BME688 pressure on its own divisor; read before STCC4 so CO2 gets fresh
	 * pressure compensation. */
	if (cycle % CONFIG_APP_PRESSURE_INTERVAL_DIVISOR == 0) {
		sensor_read_bme688(state);
	}
	if (cycle % CONFIG_APP_CO2_INTERVAL_DIVISOR == 0) {
		sensor_read_stcc4(state);
	}

	sensor_read_battery(state);
}

void sensor_fuel_gauge_idle_set(void)
{
#if IS_ENABLED(CONFIG_NRF_FUEL_GAUGE) && HAVE_BATT_PMIC
	if (fg_initialized) {
		nrf_fuel_gauge_idle_set(fg_last_v, fg_last_t, 10e-6f);
	}
#endif
}

/* ---- Recalibrate STCC4 (forced recalibration) ---- */
#if HAVE_STCC4_BUS && CONFIG_STCC4_ENABLE
/* Core forced-recalibration sequence. The caller holds stcc4_mutex, has woken the
 * sensor, and sleeps it again afterward regardless of the result. */
static int recalibrate_stcc4_locked(uint16_t target_ppm, uint32_t pressure_pa)
{
	/* Condition the sensor: recommended after it has been idle/asleep (it sleeps
	 * between normal reads). Non-destructive. start_conditioning returns
	 * immediately; we must wait it out. */
	stcc4_start_conditioning(sensor_bus);
	k_sleep(K_MSEC(STCC4_CONDITIONING_MS));

	/* Refresh RH/T (+ pressure) compensation from a fresh SHT4x reading. */
	stcc4_push_compensation(pressure_pa);

	/* Datasheet §3.4.15: before FRC, operate the sensor for >=30 single-shot
	 * measurements at a ~10 s sampling interval (~5 min) with stable readings,
	 * staying in idle (stcc4_measure does not sleep the sensor). Faster/fewer
	 * samples don't give the FRC a stable enough signal to correct against. Log
	 * every reading so a stuck (non-varying) sensor is visible. */
	int16_t co2 = 0;

	for (int i = 0; i < 32; i++) {
		uint16_t meas_status = 0;
		int ret = stcc4_measure(sensor_bus, co2, &meas_status);

		if (ret) {
			LOG_ERR("STCC4 recal: warm-up measurement %d failed: %d", i + 1, ret);
			return ret;
		}

		LOG_INF("STCC4 recal: warm-up reading %d/32 = %d ppm (status 0x%04X)", i + 1, co2,
			meas_status);

		/* A non-zero status (e.g. testing mode) means the sensor is not producing real
		 * measurements; FRC would only rail against a placeholder. Abort instead. */
		if (meas_status != 0) {
			LOG_ERR("STCC4 recal: aborting, sensor not measuring (status 0x%04X)",
				meas_status);
			return -EIO;
		}

		k_sleep(K_SECONDS(10));
	}

	uint16_t correction = 0;
	int ret = stcc4_force_recalibration(sensor_bus, target_ppm, correction);

	if (ret == 0) {
		/* Datasheet Table 11: applied correction C_FRC = Output - 32768 (ppm).
		 * A magnitude near 32767 means the FRC railed (no valid reading to
		 * correct against). */
		LOG_INF("STCC4 recal: done, target=%u ppm, applied correction=%d ppm",
			target_ppm, correction - 32768);
	}
	return ret;
}
#endif /* HAVE_STCC4_BUS && CONFIG_STCC4_ENABLE */

int sensor_recalibrate_stcc4(uint16_t target_ppm, uint32_t pressure_pa)
{
#if HAVE_STCC4_BUS && CONFIG_STCC4_ENABLE
	if (!device_is_ready(sensor_bus)) {
		return -ENODEV;
	}

	if (stcc4_warmup_until != 0) {
		LOG_WRN("STCC4 recal: warm-up in progress, ignoring request");
		return -EBUSY;
	}

	/* Wait for the main loop to finish any in-progress STCC4 read */
	if (k_mutex_lock(&stcc4_mutex, K_SECONDS(30)) != 0) {
		LOG_ERR("STCC4 recal: sensor busy, aborting");
		return -EBUSY;
	}

	LOG_INF("STCC4 recal: starting (target=%u ppm)", target_ppm);

	stcc4_exit_sleep(sensor_bus);
	int ret = recalibrate_stcc4_locked(target_ppm, pressure_pa);
	stcc4_enter_sleep(sensor_bus); /* always sleep, even on error */

	k_mutex_unlock(&stcc4_mutex);
	return ret;
#else
	ARG_UNUSED(target_ppm);
	ARG_UNUSED(pressure_pa);
	return -ENOTSUP;
#endif
}

int sensor_factory_reset_stcc4(void)
{
#if HAVE_STCC4_BUS && CONFIG_STCC4_ENABLE
	if (!device_is_ready(sensor_bus)) {
		return -ENODEV;
	}

	if (stcc4_warmup_until != 0) {
		LOG_WRN("STCC4 factory reset: warm-up in progress, ignoring request");
		return -EBUSY;
	}

	if (k_mutex_lock(&stcc4_mutex, K_SECONDS(30)) != 0) {
		LOG_ERR("STCC4 factory reset: sensor busy, aborting");
		return -EBUSY;
	}

	LOG_INF("STCC4 factory reset: starting (wipes learned calibration)");

	stcc4_exit_sleep(sensor_bus);
	int ret = stcc4_perform_factory_reset(sensor_bus);
	if (ret != 0) {
		LOG_ERR("STCC4 factory reset failed: %d", ret);
		stcc4_enter_sleep(sensor_bus);
		k_mutex_unlock(&stcc4_mutex);
		return ret;
	}

	/* Factory reset re-enabled the bypass phase; condition the sensor. */
	stcc4_start_conditioning(sensor_bus);
	k_sleep(K_MSEC(STCC4_CONDITIONING_MS));

	if (CONFIG_APP_CO2_WARMUP_MIN > 0) {
		/* Begin the initial-operation warm-up (datasheet §1.1.4): leave the sensor in
		 * continuous mode and return now (so the Mode Select snaps back to Measure); the
		 * measurement loop drives it and ends the warm-up after CONFIG_APP_CO2_WARMUP_MIN. */
		stcc4_start_continuous(sensor_bus);
		stcc4_warmup_until = k_uptime_get() + (int64_t)CONFIG_APP_CO2_WARMUP_MIN * 60 * 1000;
		LOG_INF("STCC4 factory reset: done, warming up %d min in continuous mode",
			CONFIG_APP_CO2_WARMUP_MIN);
	} else {
		stcc4_enter_sleep(sensor_bus);
		LOG_INF("STCC4 factory reset: done");
	}

	k_mutex_unlock(&stcc4_mutex);
	return ret;
#else
	return -ENOTSUP;
#endif
}

/* ---- Async wrapper: run recalibration/factory reset off a dedicated work queue ---- */
#if HAVE_STCC4_BUS && CONFIG_STCC4_ENABLE
/* The recalibration sequence blocks for ~6 min — far too long for the system
 * work queue, which BLE/Thread share. Give it its own thread + stack. */
#define STCC4_RECAL_STACK_SIZE 2048
static K_THREAD_STACK_DEFINE(stcc4_recal_stack, STCC4_RECAL_STACK_SIZE);
static struct k_work_q stcc4_recal_wq;
static bool stcc4_recal_wq_started;

enum stcc4_op {
	STCC4_OP_RECAL,
	STCC4_OP_FACTORY_RESET,
};

static struct {
	struct k_work work;
	enum stcc4_op op;
	uint16_t target_ppm;
	uint32_t pressure_pa;
	void (*done)(int result);
} stcc4_recal_ctx;

static void stcc4_recal_work_handler(struct k_work *work)
{
	ARG_UNUSED(work);

	int ret = (stcc4_recal_ctx.op == STCC4_OP_FACTORY_RESET)
			  ? sensor_factory_reset_stcc4()
			  : sensor_recalibrate_stcc4(stcc4_recal_ctx.target_ppm,
						     stcc4_recal_ctx.pressure_pa);
	if (stcc4_recal_ctx.done) {
		stcc4_recal_ctx.done(ret);
	}
}

/* Queue an op on the dedicated STCC4 work queue (started lazily). Recal and factory reset
 * share one work item, so only one runs at a time. */
static void stcc4_submit_op(enum stcc4_op op, uint16_t target_ppm, uint32_t pressure_pa,
			    void (*done)(int result))
{
	if (!stcc4_recal_wq_started) {
		k_work_queue_start(&stcc4_recal_wq, stcc4_recal_stack,
				   K_THREAD_STACK_SIZEOF(stcc4_recal_stack),
				   K_LOWEST_APPLICATION_THREAD_PRIO, NULL);
		k_work_init(&stcc4_recal_ctx.work, stcc4_recal_work_handler);
		stcc4_recal_wq_started = true;
	}

	if (k_work_busy_get(&stcc4_recal_ctx.work) != 0) {
		LOG_WRN("STCC4 op already in progress, ignoring request");
		return;
	}

	stcc4_recal_ctx.op = op;
	stcc4_recal_ctx.target_ppm = target_ppm;
	stcc4_recal_ctx.pressure_pa = pressure_pa;
	stcc4_recal_ctx.done = done;
	k_work_submit_to_queue(&stcc4_recal_wq, &stcc4_recal_ctx.work);
}
#endif

void sensor_recalibrate_stcc4_async(uint16_t target_ppm, uint32_t pressure_pa,
				    void (*done)(int result))
{
#if HAVE_STCC4_BUS && CONFIG_STCC4_ENABLE
	stcc4_submit_op(STCC4_OP_RECAL, target_ppm, pressure_pa, done);
#else
	ARG_UNUSED(target_ppm);
	ARG_UNUSED(pressure_pa);
	ARG_UNUSED(done);
#endif
}

void sensor_factory_reset_stcc4_async(void (*done)(int result))
{
#if HAVE_STCC4_BUS && CONFIG_STCC4_ENABLE
	stcc4_submit_op(STCC4_OP_FACTORY_RESET, 0, 0, done);
#else
	ARG_UNUSED(done);
#endif
}
