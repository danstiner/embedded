/*
 * Shared sensor reading module
 *
 * Extracted from bthome/main.cpp — used by both BTHome and Matter builds.
 */

#include "sensor_reading.h"
#include "sht4x.h"
#include "stcc4.h"
#include "stcc4_model.h"

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
#else
#define HAVE_BME688 0
#endif

#if HAVE_BME688 && CONFIG_BME688_ENABLE
static const struct device *bme688_dev = DEVICE_DT_GET(DT_NODELABEL(bme688));
/* BME680/688 gas-heater control — we read pressure only, so keep the ~320 °C hotplate off
 * (see sensor_init). CTRL_GAS_0 bit 3 = heat_off (cuts heater current); CTRL_GAS_1 bit 4 =
 * run_gas (runs the gas conversion that drives the heater). The Zephyr driver re-asserts
 * run_gas on every power_up but NEVER writes CTRL_GAS_0, so heat_off is the durable disable. */
#define BME688_REG_CTRL_GAS_0      0x70
#define BME688_CTRL_GAS_0_HEAT_OFF 0x08
#define BME688_REG_CTRL_GAS_1      0x71
#endif

/* STCC4 shares the BME688 I2C bus (raw I2C, no DT node) */
#if DT_NODE_HAS_STATUS(DT_NODELABEL(bme688), okay)
#define HAVE_STCC4_BUS 1
static const struct device *sensor_bus = DEVICE_DT_GET(DT_BUS(DT_NODELABEL(bme688)));
/* Owned by the measurement loop: only sensor_init/sensor_read_stcc4 touch the sensor. */
static struct stcc4_ctl stcc4_ctl;
/* Pending STCC4_REQ_*: the one hand-off into the measurement loop, since the BTHome
 * request arrives on the Bluetooth thread. */
static atomic_t stcc4_request = ATOMIC_INIT(STCC4_REQ_NONE);
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
/* Push this cycle's SHT4x RH/T (and BME688 pressure, when valid) to the STCC4 as
 * compensation. The sensor must be awake. Without a valid reading the previous
 * compensation (retained across sleep) is kept. */
static void stcc4_push_compensation(const sensor_state &state)
{
	if (state.sht4x.valid) {
		stcc4_set_rht_compensation(sensor_bus, stcc4_temp_ticks(state.sht4x.temperature_cC),
					   stcc4_hum_ticks(state.sht4x.humidity_cPct));
	} else {
		LOG_WRN("STCC4 comp: no SHT4x reading, keeping prior compensation");
	}

	if (state.bme688.valid) {
		stcc4_set_pressure_compensation(sensor_bus,
						(uint16_t)(state.bme688.pressure_Pa / 2));
	}
}

/* Report a maintenance-phase reading instead of unavailable (debug builds only). */
static void stcc4_report_debug(sensor_state &state, int16_t co2)
{
	if (IS_ENABLED(CONFIG_APP_CO2_REPORT_DURING_CALIBRATION) && co2 >= 0) {
		state.stcc4.co2_ppm = (uint16_t)co2;
		state.stcc4.timestamp = k_uptime_get();
		state.stcc4.valid = true;
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
		/* Disable the gas hotplate: we read only pressure, but the driver enables run_gas
		 * so each forced measurement would heat to ~320 °C/197 ms — wasted power and a heat
		 * source beside the STCC4/SHT4x. Set heat_off (CTRL_GAS_0 bit 3): the driver never
		 * writes 0x70, so it survives a PM resume that re-asserts run_gas. Also clear
		 * run_gas so the gas step (and its ~197 ms wait) is skipped in normal operation.
		 * T/P/H unaffected. */
		const uint16_t bme_addr = DT_REG_ADDR(DT_NODELABEL(bme688));
		int g0 = i2c_reg_write_byte(sensor_bus, bme_addr, BME688_REG_CTRL_GAS_0,
					    BME688_CTRL_GAS_0_HEAT_OFF);
		int g1 = i2c_reg_write_byte(sensor_bus, bme_addr, BME688_REG_CTRL_GAS_1, 0x00);
		if (g0 || g1) {
			LOG_WRN("BME688: failed to disable gas heater (%d, %d)", g0, g1);
		}
		LOG_INF("BME688 detected");
	} else {
		LOG_INF("BME688 not present — skipping");
	}
#endif

#if HAVE_STCC4_BUS && CONFIG_STCC4_ENABLE
	/* Wait for sensor start-up */
	k_msleep(10);
	if (device_is_ready(sensor_bus)) {
		stcc4_exit_sleep(sensor_bus);
		bool present = stcc4_probe(sensor_bus);
		if (!present) {
			/* A reboot during a continuous-mode warm-up leaves the sensor in continuous
			 * mode, where get_product_id NACKs. Stop it and retry once — every boot
			 * therefore lands in the same single-shot state. A reboot mid warm-up thus
			 * abandons it (rare: needs a battery pull/crash in the window); re-run the
			 * factory reset if needed. */
			stcc4_stop_continuous(sensor_bus);
			present = stcc4_probe(sensor_bus);
		}
		if (present) {
			state.have_stcc4 = true;
			stcc4_ctl.discards_remaining = STCC4_BYPASS_DISCARDS;
			LOG_INF("STCC4 detected");
			/* Clear any persisted testing mode (it freezes the sensor at the
			 * placeholder output) and log a one-shot self-test health verdict. */
			stcc4_disable_testing_mode(sensor_bus);
			uint16_t self_test = 0;
			if (stcc4_self_test(sensor_bus, &self_test) == 0) {
				/* 0x0000 and 0x0010 are both "pass" (§3.4.12); bit 4 (no SHT on the
				 * STCC4 controller pads) is expected here — we compensate in
				 * software. */
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
			stcc4_ctl.cond_until = k_uptime_get() + STCC4_CONDITIONING_MS;
		} else {
			LOG_INF("STCC4 not present — skipping");
		}
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
	/* Consume the request even with no sensor, so it can't stay pending forever. */
	const uint32_t request = (uint32_t)atomic_clear(&stcc4_request);

	if (!state.have_stcc4) {
		return -ENODEV;
	}

	const int64_t uptime_ms = k_uptime_get();
	const enum stcc4_step step = stcc4_next_step(
		&stcc4_ctl, uptime_ms, request, (int64_t)CONFIG_APP_CO2_WARMUP_MIN * 60 * 1000);

	if (request != STCC4_REQ_NONE && step != STCC4_STEP_BEGIN_RECAL &&
	    step != STCC4_STEP_BEGIN_FACTORY_RESET) {
		LOG_WRN("STCC4 busy, dropping maintenance request");
	}

	int16_t co2 = 0;
	uint16_t status = 0;
	int ret;

	/* Every maintenance step reports CO2 unavailable; only MEASURE sets it valid. */
	state.stcc4.valid = false;

	switch (step) {
	case STCC4_STEP_WAIT:
		LOG_INF("STCC4: skipping read, conditioning in progress");
		return -EBUSY;

	case STCC4_STEP_BEGIN_RECAL:
		/* Conditioning is recommended after the sensor has been asleep (it sleeps
		 * between normal reads). The shots that follow hold it in idle, as FRC
		 * requires (datasheet §3.4.15). */
		LOG_INF("STCC4 recal: starting (target=%u ppm)", stcc4_ctl.recal_target_ppm);
		stcc4_exit_sleep(sensor_bus);
		stcc4_start_conditioning(sensor_bus);
		return 0;

	case STCC4_STEP_RECAL_SHOT:
	case STCC4_STEP_RECAL_FRC: {
		const int shot = STCC4_RECAL_SHOTS - stcc4_ctl.recal_shots_remaining;

		stcc4_push_compensation(state);
		ret = stcc4_measure(sensor_bus, co2, &status);
		if (ret) {
			LOG_ERR("STCC4 recal: reading %d failed (%d), aborting", shot, ret);
			stcc4_enter_sleep(sensor_bus);
			stcc4_abort(&stcc4_ctl);
			return ret;
		}

		/* Log every reading so a stuck (non-varying) sensor is visible. */
		LOG_INF("STCC4 recal: reading %d/%d = %d ppm (status 0x%04X)", shot,
			STCC4_RECAL_SHOTS, co2, status);
		/* A non-zero status (e.g. testing mode) means the sensor is not producing real
		 * measurements; FRC would only rail against a placeholder. */
		if (status != 0) {
			LOG_ERR("STCC4 recal: sensor not measuring (status 0x%04X)", status);
		}
		stcc4_report_debug(state, co2);

		if (step == STCC4_STEP_RECAL_FRC) {
			uint16_t correction = 0;

			ret = stcc4_force_recalibration(sensor_bus, stcc4_ctl.recal_target_ppm,
							correction);
			stcc4_enter_sleep(sensor_bus);
			if (ret) {
				LOG_ERR("STCC4 recal: failed (%d)", ret);
			} else {
				LOG_INF("STCC4 recal: done, target=%u ppm, applied correction=%d "
					"ppm",
					stcc4_ctl.recal_target_ppm, correction - 32768);
			}
		}
		return ret;
	}

	case STCC4_STEP_BEGIN_FACTORY_RESET:
		LOG_INF("STCC4 factory reset: starting (wipes learned calibration)");
		stcc4_exit_sleep(sensor_bus);
		ret = stcc4_perform_factory_reset(sensor_bus);
		if (ret) {
			LOG_ERR("STCC4 factory reset failed: %d", ret);
			stcc4_enter_sleep(sensor_bus);
			stcc4_abort(&stcc4_ctl);
			return ret;
		}
		/* Factory reset re-enabled the bypass phase; condition the sensor. */
		stcc4_start_conditioning(sensor_bus);
		return 0;

	case STCC4_STEP_BEGIN_WARMUP:
		/* Initial-operation warm-up (datasheet §1.1.4): leave the sensor in
		 * continuous mode until the window ends. */
		LOG_INF("STCC4 factory reset: warming up %d min in continuous mode",
			CONFIG_APP_CO2_WARMUP_MIN);
		return stcc4_start_continuous(sensor_bus);

	case STCC4_STEP_WARMUP_READ:
		/* The sensor is in continuous mode: read it without triggering a
		 * single-shot or sleeping it. Not yet accurate. */
		stcc4_push_compensation(state);
		ret = stcc4_read_continuous(sensor_bus, co2, &status);
		if (ret == 0) {
			LOG_INF("STCC4 warm-up: CO2=%d ppm (status 0x%04X), %lld ms remaining", co2,
				status, stcc4_ctl.warmup_until - uptime_ms);
			stcc4_report_debug(state, co2);
		}
		return 0;

	case STCC4_STEP_END_WARMUP:
		stcc4_stop_continuous(sensor_bus);
		LOG_INF("STCC4 warm-up complete, resuming single-shot");
		break;

	case STCC4_STEP_MEASURE:
		break;
	}

	/* Wake sensor from sleep before measurement */
	stcc4_exit_sleep(sensor_bus);

	stcc4_push_compensation(state);

	ret = stcc4_measure(sensor_bus, co2, &status);

	/* Put sensor back to sleep even if measurement fails */
	stcc4_enter_sleep(sensor_bus);

	if (ret) {
		LOG_WRN("STCC4 measure failed: %d", ret);
		return ret;
	}

	/* Non-zero status could mean testing mode, or other undocumented failure case. Unsure if
	 * measurement is real. */
	if (status != 0) {
		LOG_WRN("STCC4: potentially invalid reading, status 0x%04X (CO2=%d)", status, co2);
		// state.stcc4.valid = false;
		// return -EIO;
	}

	if (co2 < 0) {
		LOG_WRN("STCC4 negative CO2: %d", co2);
		return -EINVAL;
	}

	LOG_INF("STCC4: CO2=%u ppm (status 0x%04X)", co2, status);

	if (stcc4_ctl.discards_remaining > 0) {
		stcc4_ctl.discards_remaining--;
		LOG_INF("STCC4: discarding warm-up reading (%u remaining)",
			stcc4_ctl.discards_remaining);
		return 0;
	}

	state.stcc4.co2_ppm = co2;
	state.stcc4.timestamp = uptime_ms;
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
	/* Read temperature first to limit any heating cross-contamination. */
	sensor_read_sht4x(state);

	/* Read after SHT4 to get fresh tempature/humidity compensation. */
	if (cycle % CONFIG_APP_CO2_INTERVAL_DIVISOR == 0) {
		sensor_read_stcc4(state);
	}

	/* Read last to limit heating cross-contamination from gas sensing. */
	if (cycle % CONFIG_APP_PRESSURE_INTERVAL_DIVISOR == 0) {
		sensor_read_bme688(state);
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

/* ---- STCC4 maintenance requests ---- */
#if HAVE_STCC4_BUS && CONFIG_STCC4_ENABLE
static void stcc4_submit_request(uint32_t request)
{
	if (!atomic_cas(&stcc4_request, STCC4_REQ_NONE, (atomic_val_t)request)) {
		LOG_WRN("STCC4 maintenance request already pending, ignoring");
	}
}
#endif

void sensor_request_stcc4_recal(uint16_t target_ppm)
{
#if HAVE_STCC4_BUS && CONFIG_STCC4_ENABLE
	stcc4_submit_request(target_ppm);
#else
	ARG_UNUSED(target_ppm);
#endif
}

void sensor_request_stcc4_factory_reset(void)
{
#if HAVE_STCC4_BUS && CONFIG_STCC4_ENABLE
	stcc4_submit_request(STCC4_REQ_FACTORY_RESET);
#endif
}

enum co2_state sensor_co2_state(void)
{
#if HAVE_STCC4_BUS && CONFIG_STCC4_ENABLE
	/* A request not yet picked up already counts, so a second one is refused. */
	const uint32_t request = (uint32_t)atomic_get(&stcc4_request);

	if (request == STCC4_REQ_FACTORY_RESET) {
		return CO2_STATE_FACTORY_RESET;
	}
	if (request != STCC4_REQ_NONE) {
		return CO2_STATE_RECALIBRATE;
	}
	return stcc4_ctl.state;
#else
	return CO2_STATE_MEASURE;
#endif
}
