// Hygrometer firmware
//
// Supports both BL54L15u Hygrometer and BL54L15u DevKit boards.
// Reads SHT45 (temp/humidity), optional BME688 (pressure), optional STCC4 (CO2).
//
// Simple loop architecture: always-on, always connectable, sleeps between readings.

#include <zephyr/device.h>
#include <zephyr/drivers/watchdog.h>
#include <zephyr/drivers/i2c.h>
#include <zephyr/drivers/sensor.h>
#include <zephyr/init.h>

#include <zephyr/bluetooth/bluetooth.h>
#include <zephyr/bluetooth/conn.h>
#include <zephyr/bluetooth/uuid.h>

#if DT_NODE_HAS_STATUS(DT_NODELABEL(npm1304_charger), okay)
#include <zephyr/drivers/sensor/npm13xx_charger.h>
#include <zephyr/drivers/mfd/npm13xx.h>
#endif

#include <zephyr/logging/log.h>

#if IS_ENABLED(CONFIG_NRF_FUEL_GAUGE)
#include <nrf_fuel_gauge.h>
#endif

#include "bthome.h"
#include "sht4x.h"
#include "stcc4.h"

LOG_MODULE_REGISTER(app, LOG_LEVEL_INF);

/* Select PMIC watchdog based on which board is active */
#if DT_NODE_HAS_STATUS(DT_NODELABEL(npm2100_wdt), okay)
#define PMIC_WDT_NODE DT_NODELABEL(npm2100_wdt)
#define PMIC_NAME     "nPM2100"
#elif DT_NODE_HAS_STATUS(DT_NODELABEL(npm1304_wdt), okay)
#define PMIC_WDT_NODE DT_NODELABEL(npm1304_wdt)
#define PMIC_NAME     "nPM1304"
#endif

/* SMP service UUID (8d53dc1d-1db7-4cd3-868b-8a527460aa84) in little-endian */
#define SMP_SVC_UUID_BYTES                                                                         \
	0x84, 0xaa, 0x60, 0x74, 0x52, 0x8a, 0x8b, 0x86, 0xd3, 0x4c, 0xb7, 0x1d, 0x1d, 0xdc, 0x53,  \
		0x8d

/* Connectable advertising parameters — ~2.0–2.5s interval to save power */
#define ADV_INT_MIN 0x0C80 /* 2.0 s in 0.625 ms units */
#define ADV_INT_MAX 0x0FA0 /* 2.5 s in 0.625 ms units */
#define ADV_PARAM_CONN                                                                             \
	BT_LE_ADV_PARAM(BT_LE_ADV_OPT_USE_IDENTITY | BT_LE_ADV_OPT_CONN, ADV_INT_MIN,            \
			ADV_INT_MAX, NULL)

constexpr bt_data AD_FLAG_BYTES =
	BT_DATA_BYTES(BT_DATA_FLAGS, BT_LE_AD_GENERAL | BT_LE_AD_NO_BREDR);

static struct bt_data ad[] = {
	AD_FLAG_BYTES,
	BT_DATA(BT_DATA_SVC_DATA16, NULL, 0),
};

constexpr size_t BT_DATA_HEADER_LEN = 1;

static_assert(BT_DATA_HEADER_LEN * 2 + AD_FLAG_BYTES.data_len + sizeof(service_data) <=
	      BT_GAP_ADV_MAX_ADV_DATA_LEN);

/* Scan response — SMP service UUID for DFU */
static struct bt_data sd[] = {
	BT_DATA_BYTES(BT_DATA_UUID128_ALL, SMP_SVC_UUID_BYTES),
};

/* ---- Sensor availability flags ---- */
static bool have_bme688;
static bool have_stcc4;

/* ---- Device pointers ---- */
#if DT_NODE_HAS_STATUS(DT_NODELABEL(sht45), okay)
static const struct device *sht45 = DEVICE_DT_GET(DT_NODELABEL(sht45));
#endif

/* Optional sensor bus (i2c20 on hygrometer — carries BME688 + STCC4) */
#if DT_NODE_HAS_STATUS(DT_NODELABEL(bme688), okay)
#define HAVE_SENSOR_BUS 1
static const struct device *bme688_dev = DEVICE_DT_GET(DT_NODELABEL(bme688));
static const struct device *sensor_bus = DEVICE_DT_GET(DT_BUS(DT_NODELABEL(bme688)));
#else
#define HAVE_SENSOR_BUS 0
#endif

/* Battery voltage sources */
#if DT_NODE_HAS_STATUS(DT_NODELABEL(npm2100_vbat), okay)
static const struct device *vbat_dev = DEVICE_DT_GET(DT_NODELABEL(npm2100_vbat));
#define HAVE_VBAT 1
#elif DT_NODE_HAS_STATUS(DT_NODELABEL(npm1304_charger), okay)
static const struct device *vbat_dev = DEVICE_DT_GET(DT_NODELABEL(npm1304_charger));
#define HAVE_VBAT 1
#else
#define HAVE_VBAT 0
#endif

/* SHT45 I2C bus for direct heater commands */
#if DT_NODE_HAS_STATUS(DT_NODELABEL(sht45), okay)
static const struct device *sht45_bus = DEVICE_DT_GET(DT_BUS(DT_NODELABEL(sht45)));
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
static float fg_last_v = 3.0f; /* safe defaults for idle_set before first measurement */
static float fg_last_t = 25.0f;

#endif /* CONFIG_NRF_FUEL_GAUGE */

/* ---- Helper: convert sensor_value to raw SHT4x ticks ---- */
static uint16_t temp_to_raw_ticks(const struct sensor_value *val)
{
	/* raw = (T + 45) * 65535 / 175, where T is in °C */
	int64_t micro = (int64_t)val->val1 * 1000000 + val->val2;
	return (uint16_t)(((micro + 45000000LL) * 65535LL) / 175000000LL);
}

static uint16_t hum_to_raw_ticks(const struct sensor_value *val)
{
	/* raw = (RH + 6) * 65535 / 125, where RH is in % */
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

/*
 * Fire SHT4x heater via direct I2C for decontamination.
 */
#if IS_ENABLED(CONFIG_SHT4X_USE_HEATER) && DT_NODE_HAS_STATUS(DT_NODELABEL(sht45), okay)
static void sht4x_heater_pulse(void)
{
	int power = CONFIG_SHT4X_HEATER_PULSE_POWER;
	int duration = IS_ENABLED(CONFIG_SHT4X_HEATER_LONG_PULSE_DURATION) ? 0 : 1;

	uint8_t cmd = sht4x_heater_cmd[power][duration];
	int ret = i2c_write(sht45_bus, &cmd, 1, SHT4X_I2C_ADDR);

	if (ret) {
		LOG_ERR("SHT4x heater cmd failed: %d", ret);
		return;
	}

	k_sleep(K_MSEC(sht4x_heater_total_wait_ms[duration]));

	uint8_t buf[6];

	for (int attempt = 0; attempt < 10; attempt++) {
		ret = i2c_read(sht45_bus, buf, sizeof(buf), SHT4X_I2C_ADDR);
		if (ret == 0) {
			break;
		}
		k_sleep(K_MSEC(10));
	}
	if (ret) {
		LOG_WRN("SHT4x heater readback failed: %d", ret);
		return;
	}

	if (sht4x_crc8(&buf[0], 2) == buf[2] && sht4x_crc8(&buf[3], 2) == buf[5]) {
		struct sensor_value t, h;
		uint16_t raw_t = ((uint16_t)buf[0] << 8) | buf[1];
		uint16_t raw_h = ((uint16_t)buf[3] << 8) | buf[4];

		sht4x_raw_to_temp(raw_t, &t);
		sht4x_raw_to_humidity(raw_h, &h);
		LOG_INF("SHT4x heater readback: T=%d.%02d°C RH=%d.%02d%%", t.val1, t.val2 / 10000,
			h.val1, h.val2 / 10000);
	}
}
#endif

/* ---- Fuel gauge charge state update (nPM1304 / secondary cell only) ---- */
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

/* ---- Probe optional sensors at boot ---- */
static void probe_optional_sensors(void)
{
#if HAVE_SENSOR_BUS
	if (device_is_ready(bme688_dev)) {
		have_bme688 = true;
		LOG_INF("BME688 detected");
	} else {
		LOG_INF("BME688 not present — skipping");
	}

	if (device_is_ready(sensor_bus)) {
		if (stcc4_probe(sensor_bus)) {
			have_stcc4 = true;
			LOG_INF("STCC4 detected");
		} else {
			LOG_INF("STCC4 not present — skipping");
		}
	}
#endif
}

/* ---- Read battery voltage and update fuel gauge ---- */
static bool read_battery_voltage(struct sensor_value *voltage)
{
#if HAVE_VBAT
	if (!device_is_ready(vbat_dev)) {
		return false;
	}

	int ret = sensor_sample_fetch(vbat_dev);
	if (ret) {
		LOG_WRN("Battery voltage fetch failed: %d", ret);
		return false;
	}

	ret = sensor_channel_get(vbat_dev, SENSOR_CHAN_GAUGE_VOLTAGE, voltage);
	if (ret) {
		LOG_WRN("Battery voltage get failed: %d", ret);
		return false;
	}

#if IS_ENABLED(CONFIG_NRF_FUEL_GAUGE)
	if (fg_initialized) {
		struct sensor_value sv_temp;
		float v = (float)voltage->val1 + (float)voltage->val2 / 1000000.f;
		float t, i;

#if IS_ENABLED(CONFIG_NRF_FUEL_GAUGE_VARIANT_SECONDARY_CELL)
		sensor_channel_get(vbat_dev, SENSOR_CHAN_GAUGE_TEMP, &sv_temp);
		t = (float)sv_temp.val1 + (float)sv_temp.val2 / 1000000.f;

		struct sensor_value sv_current;
		sensor_channel_get(vbat_dev, SENSOR_CHAN_GAUGE_AVG_CURRENT, &sv_current);
		/* Negate: Zephyr negative=discharging → library positive=discharging */
		i = -((float)sv_current.val1 + (float)sv_current.val2 / 1000000.f);

		/* Update charge state on change */
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
		/* No current measurement for primary cell; use fixed estimate */
		i = 5.0e-3f;
#endif

		float delta = (float)k_uptime_delta(&fg_ref_time) / 1000.f;
		fg_last_soc = nrf_fuel_gauge_process(v, i, t, delta, nullptr);
		fg_last_v = v;
		fg_last_t = t;
		LOG_INF("BAT_%: %d%%", (int)fg_last_soc);
	}
#endif /* CONFIG_NRF_FUEL_GAUGE */

	return true;
#else
	return false;
#endif
}

/* ---- Fuel gauge init ---- */
static void fuel_gauge_init(void)
{
#if IS_ENABLED(CONFIG_NRF_FUEL_GAUGE) && HAVE_VBAT
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
#endif /* CONFIG_NRF_FUEL_GAUGE && HAVE_VBAT */
}

/* ---- Update BTHome advertisement data ---- */
static void update_advertisement(opt_i16 temperature_mC, opt_u16 humidity_mPct, opt_u32 pressure_Pa,
				 opt_u16 co2_ppm, opt_u8 bat_soc, opt_u16 bat_mV)
{
	bthome_update_service_data(temperature_mC, humidity_mPct, pressure_Pa, co2_ppm, bat_soc,
				   bat_mV);
	ad[1] = (struct bt_data)BT_DATA(BT_DATA_SVC_DATA16, service_data,
					(uint8_t)service_data_len);

	/* Push updated data to the BLE stack */
	bt_le_adv_update_data(ad, ARRAY_SIZE(ad), sd, ARRAY_SIZE(sd));
}

/* ---- BLE advertising via work queue ---- */
static struct k_work advertise_work;

static void advertise(struct k_work *work)
{
	int rc = bt_le_adv_start(ADV_PARAM_CONN, ad, ARRAY_SIZE(ad), sd, ARRAY_SIZE(sd));
	if (rc) {
		LOG_ERR("Advertising failed to start (rc %d)", rc);
		return;
	}
	LOG_INF("Advertising started");
}

static void bt_ready(int err)
{
	if (err) {
		LOG_ERR("Bluetooth init failed: %d", err);
		return;
	}
	k_work_submit(&advertise_work);
}

/* ---- BLE connection callbacks ---- */
static void connected(struct bt_conn *conn, uint8_t err)
{
	LOG_DBG("Connected");
}

static void disconnected(struct bt_conn *conn, uint8_t reason)
{
	LOG_DBG("Disconnected (reason %u)", reason);
}

static void recycled(void)
{
	LOG_DBG("BLE connection recycled");
	k_work_submit(&advertise_work);
}

BT_CONN_CB_DEFINE(conn_cbs) = {
	.connected = connected,
	.disconnected = disconnected,
	.recycled = recycled,
};

int main()
{
	printk("\n\n=== Hygrometer ===\n");
#ifdef PMIC_NAME
	printk("PMIC: " PMIC_NAME "\n");
#endif

#if DT_NODE_HAS_STATUS(DT_NODELABEL(npm1304_pmic), okay)
	/* Set POF threshold to 3.1V for battery protection */
	const struct device *pmic = DEVICE_DT_GET(DT_NODELABEL(npm1304_pmic));
	if (device_is_ready(pmic)) {
		int ret = mfd_npm13xx_reg_write(pmic, 0x01, 0x06, 0x05);
		if (ret == 0) {
			LOG_INF("POF threshold set to 3.1V");
		} else {
			LOG_WRN("Failed to set POF threshold: %d", ret);
		}
	}
#endif

	/* Check PMIC watchdog */
#ifdef PMIC_WDT_NODE
	const struct device *wdt = DEVICE_DT_GET_OR_NULL(PMIC_WDT_NODE);
	if (wdt == nullptr) {
		LOG_ERR(PMIC_NAME " WDT not found in devicetree!");
	} else if (!device_is_ready(wdt)) {
		LOG_ERR(PMIC_NAME " WDT not ready — I2C issue?");
	} else {
		LOG_INF(PMIC_NAME " WDT ready");
	}
#endif

	probe_optional_sensors();
	fuel_gauge_init();

	/* Start BLE advertising */
	k_work_init(&advertise_work, advertise);
	update_advertisement(opt_i16_none(), opt_u16_none(), opt_u32_none(), opt_u16_none(),
			     opt_u8_none(), opt_u16_none());
	int err = bt_enable(bt_ready);
	if (err) {
		LOG_ERR("Bluetooth init failed (err %d)", err);
		return -1;
	}

	while (true) {
		opt_i16 temperature_mC;
		opt_u16 temperature_ticks;
		opt_u16 humidity_mPct;
		opt_u16 humidity_ticks;
		opt_u32 pressure_Pa;
		opt_u16 co2_ppm;
		opt_u8 bat_soc;
		opt_u16 bat_mV;
		struct sensor_value value;

		/* 1. Read SHT45 */
#if DT_NODE_HAS_STATUS(DT_NODELABEL(sht45), okay)
		if (device_is_ready(sht45)) {
			int ret = sensor_sample_fetch(sht45);

			if (ret == 0) {
				// Convert Celsius result to millicelsius
				sensor_channel_get(sht45, SENSOR_CHAN_AMBIENT_TEMP, &value);
				temperature_mC =
					opt_i16_some(value.val1 * 100 + value.val2 / 10000);
				temperature_ticks = opt_u16_some(temp_to_raw_ticks(&value));
				LOG_INF("SHT45: T=%d.%02d°C ", value.val1, value.val2 / 10000);

				// Convert relative humidity percentage to milliprecent
				sensor_channel_get(sht45, SENSOR_CHAN_HUMIDITY, &value);
				humidity_mPct = opt_u16_some(value.val1 * 100 + value.val2 / 10000);
				humidity_ticks = opt_u16_some(hum_to_raw_ticks(&value));
				LOG_INF("SHT45: RH=%d.%02d%%", value.val1, value.val2 / 10000);

#if IS_ENABLED(CONFIG_SHT4X_USE_HEATER)
				sht4x_heater_pulse();
#endif
			} else {
				LOG_ERR("SHT45 fetch failed: %d", ret);
			}
		}
#endif

		/* 2. STCC4: feed compensation + measure CO2 */
#if HAVE_SENSOR_BUS
		if (have_stcc4) {
			if (temperature_ticks.is_some && humidity_ticks.is_some) {
				stcc4_set_rht_compensation(sensor_bus, temperature_ticks.value,
							   humidity_ticks.value);
			}
			int ret = stcc4_measure(sensor_bus, &co2_ppm.value);
			if (ret == 0) {
				co2_ppm.is_some = true;
				LOG_INF("STCC4: CO2=%u ppm", co2_ppm.value);
			} else {
				LOG_WRN("STCC4 measure failed: %d", ret);
			}
		}
#endif

		/* 3. BME688: read pressure */
#if HAVE_SENSOR_BUS
		if (have_bme688) {
			int ret = sensor_sample_fetch(bme688_dev);
			if (ret == 0) {
				sensor_channel_get(bme688_dev, SENSOR_CHAN_PRESS, &value);
				pressure_Pa = opt_u32_some(value.val1 * 1000 + value.val2 / 1000);
				LOG_INF("BME688: P=%d.%03d kPa", value.val1, value.val2 / 1000);
			} else {
				LOG_WRN("BME688 fetch failed: %d", ret);
			}
		}
#endif

		/* 4. Read battery voltage (also updates fuel gauge SoC) */
		if (read_battery_voltage(&value)) {
			// Convert from micro volts to mV
			bat_mV = opt_u16_some(value.val1 * 1000 + value.val2 / 1000);
			LOG_INF("BAT_V: %d.%03dV", value.val1, value.val2 / 1000);
		}

		/* 5. Compute SoC for BTHome payload */
#if IS_ENABLED(CONFIG_NRF_FUEL_GAUGE)
		if (fg_initialized) {
			bat_soc = opt_u8_some(CLAMP((int)fg_last_soc, 0, 100));
		}
#endif

		/* 6. Update advertisement data */
		update_advertisement(temperature_mC, humidity_mPct, pressure_Pa, co2_ppm, bat_soc,
				     bat_mV);

		k_sleep(K_SECONDS(CONFIG_APP_MEASUREMENT_INTERVAL_SEC));
	}

	return 0;
}
