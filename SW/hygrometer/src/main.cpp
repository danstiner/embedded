// Hygrometer firmware
//
// Supports both BL54L15u Hygrometer and BL54L15u DevKit boards.
// Reads SHT45 (temp/humidity), optional BME688 (pressure), optional STCC4 (CO2).
//
// Boot-cycle architecture for ultra-low power:
//   1. Measure sensors + broadcast BTHome for ADV_WINDOW_SEC
//   2. Schedule GRTC wakeup, enable GPIO (button) wakeup, call sys_poweroff()
//   3. GRTC fires after MEASUREMENT_INTERVAL_SEC → normal measurement boot
//   4. Button press (GPIO wakeup) → DFU mode stays running until timeout

#include <zephyr/device.h>
#include <zephyr/drivers/watchdog.h>
#include <zephyr/drivers/i2c.h>
#include <zephyr/drivers/sensor.h>
#include <zephyr/drivers/gpio.h>
#include <zephyr/drivers/hwinfo.h>
#include <zephyr/init.h>
#include <zephyr/input/input.h>
#include <zephyr/sys/poweroff.h>
#include <zephyr/drivers/timer/nrf_grtc_timer.h>
#include <zephyr/dfu/mcuboot.h>

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

#include "sht4x.h"
#include "stcc4.h"

LOG_MODULE_REGISTER(app, LOG_LEVEL_INF);

/* Select PMIC watchdog based on which board is active */
#if DT_NODE_HAS_STATUS(DT_NODELABEL(npm2100_wdt), okay)
#define PMIC_WDT_NODE DT_NODELABEL(npm2100_wdt)
#define PMIC_NAME "nPM2100"
#elif DT_NODE_HAS_STATUS(DT_NODELABEL(npm1304_wdt), okay)
#define PMIC_WDT_NODE DT_NODELABEL(npm1304_wdt)
#define PMIC_NAME "nPM1304"
#endif

/* ---- BTHome v2 constants ---- */
#define BTHOME_UUID        0xFCD2
#define BTHOME_DEVICE_INFO 0x40   /* Unencrypted, BTHome v2 */

/* BTHome object IDs — must appear in ascending order in payload */
#define BTHOME_OBJ_BATTERY 0x01  /* uint8, 1% */
#define BTHOME_OBJ_TEMP     0x02  /* sint16, 0.01 °C */
#define BTHOME_OBJ_HUMIDITY 0x03  /* uint16, 0.01 % */
#define BTHOME_OBJ_PRESSURE 0x04  /* uint24, 0.01 hPa */
#define BTHOME_OBJ_VOLTAGE  0x0C  /* uint16, 0.001 V */
#define BTHOME_OBJ_CO2      0x12  /* uint16, 1 ppm */

/* Max service data: UUID(2) + info(1) + battery%(2) + temp(3) + hum(3) + pressure(4) + co2(3) + voltage(3) = 21 */
#define SERVICE_DATA_MAX 21

/* DFU mode timeout */
#define DFU_TIMEOUT_SEC  300

/* SMP service UUID (8d53dc1d-1db7-4cd3-868b-8a527460aa84) in little-endian */
#define SMP_SVC_UUID_BYTES \
	0x84, 0xaa, 0x60, 0x74, 0x52, 0x8a, \
	0x8b, 0x86, 0xd3, 0x4c, 0xb7, 0x1d, \
	0x1d, 0xdc, 0x53, 0x8d

static uint8_t service_data[SERVICE_DATA_MAX];
static size_t service_data_len;

/* Convert ms to BLE 0.625ms units */
#define ADV_INTERVAL_MIN  ((CONFIG_APP_BLE_ADV_INTERVAL_MS * 8) / 5)
#define ADV_INTERVAL_MAX  (ADV_INTERVAL_MIN + 0x0050)

/* Non-connectable BTHome advertising parameters */
#define BTHOME_ADV_PARAM BT_LE_ADV_PARAM(BT_LE_ADV_OPT_USE_IDENTITY, \
					  ADV_INTERVAL_MIN, ADV_INTERVAL_MAX, NULL)

/* Connectable advertising parameters for DFU/SMP mode */
#define SMP_ADV_PARAM BT_LE_ADV_PARAM(BT_LE_ADV_OPT_CONN | \
				       BT_LE_ADV_OPT_USE_IDENTITY, \
				       BT_GAP_ADV_FAST_INT_MIN_2, \
				       BT_GAP_ADV_FAST_INT_MAX_2, NULL)

static struct bt_data ad[] = {
	BT_DATA_BYTES(BT_DATA_FLAGS, BT_LE_AD_GENERAL | BT_LE_AD_NO_BREDR),
	BT_DATA(BT_DATA_NAME_COMPLETE, CONFIG_BT_DEVICE_NAME,
		sizeof(CONFIG_BT_DEVICE_NAME) - 1),
	BT_DATA(BT_DATA_SVC_DATA16, service_data, 0), /* len updated before adv */
};

/* Scan response for DFU mode — SMP service UUID */
static struct bt_data sd[] = {
	BT_DATA_BYTES(BT_DATA_UUID128_ALL, SMP_SVC_UUID_BYTES),
};

/* ---- Sensor availability flags ---- */
static bool have_bme688;
static bool have_stcc4;

/* ---- DFU state ---- */
static bool dfu_mode;
static struct bt_conn *current_conn;

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

/* Button for GPIO wakeup and DFU trigger (devkit only) */
#if DT_HAS_ALIAS(sw0)
#define HAVE_BUTTON 1
static const struct gpio_dt_spec btn = GPIO_DT_SPEC_GET(DT_ALIAS(sw0), gpios);
#else
#define HAVE_BUTTON 0
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
static float fg_last_v = 3.0f;  /* safe defaults for idle_set before first measurement */
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
	if (raw < 0) raw = 0;
	if (raw > 65535) raw = 65535;
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

	if (sht4x_crc8(&buf[0], 2) == buf[2] &&
	    sht4x_crc8(&buf[3], 2) == buf[5]) {
		struct sensor_value t, h;
		uint16_t raw_t = ((uint16_t)buf[0] << 8) | buf[1];
		uint16_t raw_h = ((uint16_t)buf[3] << 8) | buf[4];

		sht4x_raw_to_temp(raw_t, &t);
		sht4x_raw_to_humidity(raw_h, &h);
		LOG_INF("SHT4x heater readback: T=%d.%02d°C RH=%d.%02d%%",
			t.val1, t.val2 / 10000, h.val1, h.val2 / 10000);
	}
}
#endif

/* ---- Fuel gauge charge state update (nPM1304 / secondary cell only) ---- */
#if IS_ENABLED(CONFIG_NRF_FUEL_GAUGE_VARIANT_SECONDARY_CELL) && \
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

/* ---- Build service data ---- */
static void build_service_data(const struct sensor_value *temp,
			       const struct sensor_value *hum,
			       const struct sensor_value *pressure,
			       const uint16_t *co2_ppm,
			       const uint8_t *soc_pct,
			       const struct sensor_value *voltage)
{
	size_t idx = 0;

	/* UUID (little-endian) */
	service_data[idx++] = (uint8_t)(BTHOME_UUID & 0xFF);
	service_data[idx++] = (uint8_t)(BTHOME_UUID >> 8);
	/* Device info */
	service_data[idx++] = BTHOME_DEVICE_INFO;

	/* Battery %: uint8, 1% — OBJ ID 0x01, must precede temp (0x02) */
	if (soc_pct) {
		service_data[idx++] = BTHOME_OBJ_BATTERY;
		service_data[idx++] = *soc_pct;
	}

	/* Temperature: sint16, factor 0.01 °C */
	if (temp) {
		int16_t t = (int16_t)(temp->val1 * 100 + temp->val2 / 10000);
		service_data[idx++] = BTHOME_OBJ_TEMP;
		service_data[idx++] = (uint8_t)(t & 0xFF);
		service_data[idx++] = (uint8_t)((t >> 8) & 0xFF);
	}

	/* Humidity: uint16, factor 0.01 % */
	if (hum) {
		uint16_t h = (uint16_t)(hum->val1 * 100 + hum->val2 / 10000);
		service_data[idx++] = BTHOME_OBJ_HUMIDITY;
		service_data[idx++] = (uint8_t)(h & 0xFF);
		service_data[idx++] = (uint8_t)((h >> 8) & 0xFF);
	}

	/* Pressure: uint24, factor 0.01 hPa */
	if (pressure) {
		/* sensor_value is in kPa; BTHome wants hPa * 100 */
		uint32_t p = (uint32_t)(pressure->val1 * 1000 + pressure->val2 / 1000);
		service_data[idx++] = BTHOME_OBJ_PRESSURE;
		service_data[idx++] = (uint8_t)(p & 0xFF);
		service_data[idx++] = (uint8_t)((p >> 8) & 0xFF);
		service_data[idx++] = (uint8_t)((p >> 16) & 0xFF);
	}

	/* CO2: uint16, factor 1 ppm */
	if (co2_ppm) {
		service_data[idx++] = BTHOME_OBJ_CO2;
		service_data[idx++] = (uint8_t)(*co2_ppm & 0xFF);
		service_data[idx++] = (uint8_t)((*co2_ppm >> 8) & 0xFF);
	}

	/* Battery voltage: uint16, factor 0.001 V */
	if (voltage) {
		uint16_t mv = (uint16_t)(voltage->val1 * 1000 + voltage->val2 / 1000);
		service_data[idx++] = BTHOME_OBJ_VOLTAGE;
		service_data[idx++] = (uint8_t)(mv & 0xFF);
		service_data[idx++] = (uint8_t)((mv >> 8) & 0xFF);
	}

	service_data_len = idx;
}

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
		stcc4_wake(sensor_bus);
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
		fg_last_soc = nrf_fuel_gauge_process(v, i, t, delta, NULL);
		fg_last_v = v;
		fg_last_t = t;
		LOG_INF("SoC: %d%%", (int)fg_last_soc);
	}
#endif /* CONFIG_NRF_FUEL_GAUGE */

	return true;
#else
	return false;
#endif
}

/* ---- Fuel gauge init (called every boot — state lost over poweroff) ---- */
static void fuel_gauge_init(void)
{
#if IS_ENABLED(CONFIG_NRF_FUEL_GAUGE) && HAVE_VBAT
	if (!device_is_ready(vbat_dev)) {
		LOG_WRN("VBAT device not ready — fuel gauge skipped");
		return;
	}

	struct sensor_value sv;
	struct nrf_fuel_gauge_init_parameters fg_params = {
		.opt_params = NULL,
		.state = NULL,
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

	int fg_ret = nrf_fuel_gauge_init(&fg_params, NULL);
	if (fg_ret < 0) {
		LOG_ERR("Fuel gauge init failed: %d", fg_ret);
		return;
	}

#if IS_ENABLED(CONFIG_NRF_FUEL_GAUGE_VARIANT_SECONDARY_CELL)
	union nrf_fuel_gauge_ext_state_info_data fg_info;

	fg_info.charge_current_limit = max_current;
	nrf_fuel_gauge_ext_state_update(
		NRF_FUEL_GAUGE_EXT_STATE_INFO_CHARGE_CURRENT_LIMIT, &fg_info);

	fg_info.charge_term_current = max_current / 10.f;
	nrf_fuel_gauge_ext_state_update(
		NRF_FUEL_GAUGE_EXT_STATE_INFO_TERM_CURRENT, &fg_info);
#endif

	fg_initialized = true;
	LOG_INF("Fuel gauge initialized (%s)", nrf_fuel_gauge_version);
	fg_ref_time = k_uptime_get();
#endif /* CONFIG_NRF_FUEL_GAUGE && HAVE_VBAT */
}

/* ---- Configure wakeup sources and enter System OFF ---- */
static FUNC_NORETURN void enter_system_off(void)
{
	LOG_INF("Scheduling GRTC wakeup in %ds", CONFIG_APP_MEASUREMENT_INTERVAL_SEC);

	/* Give the log backend time to flush before poweroff (no-op in release) */
	if (IS_ENABLED(CONFIG_LOG)) {
		k_sleep(K_MSEC(50));
	}

	int err = z_nrf_grtc_wakeup_prepare(
		(uint64_t)CONFIG_APP_MEASUREMENT_INTERVAL_SEC * USEC_PER_SEC);
	if (err < 0) {
		LOG_ERR("GRTC wakeup prepare failed: %d", err);
	}

#if HAVE_BUTTON
	/* Configure button as sense wakeup source. The GPIO sense mechanism
	 * survives System OFF — a low level on the active-low button triggers
	 * wakeup and sets RESETREAS OFF bit (→ RESET_LOW_POWER_WAKE). */
	gpio_pin_configure_dt(&btn, GPIO_INPUT);
	gpio_pin_interrupt_configure_dt(&btn, GPIO_INT_LEVEL_ACTIVE);
#endif

	sys_poweroff();
}

/* ---- BLE connection callbacks (DFU mode) ---- */
static void connected(struct bt_conn *conn, uint8_t err)
{
	if (err) {
		LOG_ERR("Connection failed: %d", err);
		return;
	}
	LOG_INF("DFU client connected");
	current_conn = bt_conn_ref(conn);
}

static void disconnected(struct bt_conn *conn, uint8_t reason)
{
	LOG_INF("Disconnected (reason %u)", reason);
	if (current_conn) {
		bt_conn_unref(current_conn);
		current_conn = NULL;
	}
}

BT_CONN_CB_DEFINE(conn_cbs) = {
	.connected = connected,
	.disconnected = disconnected,
};

/* ---- DFU mode ---- */
static void run_dfu_mode(void)
{
	LOG_INF("DFU mode — SMP advertising for %ds", DFU_TIMEOUT_SEC);

	int err = bt_le_adv_start(SMP_ADV_PARAM, ad, ARRAY_SIZE(ad), sd, ARRAY_SIZE(sd));
	if (err) {
		LOG_ERR("DFU advertising failed to start: %d", err);
		enter_system_off();
	}

#if DT_HAS_ALIAS(led0)
	const struct gpio_dt_spec led = GPIO_DT_SPEC_GET(DT_ALIAS(led0), gpios);
	if (gpio_is_ready_dt(&led)) {
		gpio_pin_configure_dt(&led, GPIO_OUTPUT_ACTIVE);
	}
#endif

	int64_t deadline = k_uptime_get() + (int64_t)DFU_TIMEOUT_SEC * 1000;

	while (k_uptime_get() < deadline) {
		k_sleep(K_SECONDS(1));
	}

	LOG_INF("DFU timeout — entering System OFF");
#if DT_HAS_ALIAS(led0)
	if (gpio_is_ready_dt(&led)) {
		gpio_pin_configure_dt(&led, GPIO_OUTPUT_INACTIVE);
	}
#endif
	bt_le_adv_stop();
	bt_disable();
	enter_system_off();
}

/* ---- Normal measurement + BTHome broadcast ---- */
static void run_measurement(void)
{
	struct sensor_value temp, hum;
	struct sensor_value *temp_ptr = NULL;
	struct sensor_value *hum_ptr = NULL;
	struct sensor_value pressure;
	struct sensor_value *pressure_ptr = NULL;
	uint16_t co2_ppm;
	uint16_t *co2_ptr = NULL;
	struct sensor_value voltage;
	struct sensor_value *voltage_ptr = NULL;

	/* 1. Read SHT45 */
#if DT_NODE_HAS_STATUS(DT_NODELABEL(sht45), okay)
	if (device_is_ready(sht45)) {
		int ret = sensor_sample_fetch(sht45);

		if (ret == 0) {
			sensor_channel_get(sht45, SENSOR_CHAN_AMBIENT_TEMP, &temp);
			sensor_channel_get(sht45, SENSOR_CHAN_HUMIDITY, &hum);
			temp_ptr = &temp;
			hum_ptr = &hum;

			LOG_INF("SHT45: T=%d.%02d°C RH=%d.%02d%%",
				temp.val1, temp.val2 / 10000,
				hum.val1, hum.val2 / 10000);

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
	if (have_stcc4 && temp_ptr && hum_ptr) {
		uint16_t raw_t = temp_to_raw_ticks(&temp);
		uint16_t raw_h = hum_to_raw_ticks(&hum);
		stcc4_set_rht_compensation(sensor_bus, raw_t, raw_h);
	}
	if (have_stcc4) {
		int ret = stcc4_measure(sensor_bus, &co2_ppm);
		if (ret == 0) {
			co2_ptr = &co2_ppm;
			LOG_INF("STCC4: CO2=%u ppm", co2_ppm);
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
			sensor_channel_get(bme688_dev, SENSOR_CHAN_PRESS, &pressure);
			pressure_ptr = &pressure;
			LOG_INF("BME688: P=%d.%03d kPa",
				pressure.val1, pressure.val2 / 1000);
		} else {
			LOG_WRN("BME688 fetch failed: %d", ret);
		}
	}
#endif

	/* 4. Read battery voltage (also updates fuel gauge SoC) */
	if (read_battery_voltage(&voltage)) {
		voltage_ptr = &voltage;
		LOG_INF("Vbat: %d.%03dV", voltage.val1, voltage.val2 / 1000);
	}

	/* 5. Compute SoC for BTHome payload */
#if IS_ENABLED(CONFIG_NRF_FUEL_GAUGE)
	uint8_t soc_u8 = fg_initialized ?
		(uint8_t)CLAMP((int)fg_last_soc, 0, 100) : 0;
	uint8_t *soc_ptr = fg_initialized ? &soc_u8 : NULL;
#else
	uint8_t *soc_ptr = NULL;
#endif

	/* 6. Build and start BTHome advertising */
	build_service_data(temp_ptr, hum_ptr, pressure_ptr, co2_ptr,
			   soc_ptr, voltage_ptr);
	ad[2] = (struct bt_data)BT_DATA(BT_DATA_SVC_DATA16, service_data, (uint8_t)service_data_len);

	int err = bt_le_adv_start(BTHOME_ADV_PARAM, ad, ARRAY_SIZE(ad), NULL, 0);
	if (err) {
		LOG_ERR("BTHome advertising failed to start (err %d)", err);
	} else {
		LOG_INF("BTHome advertising started");
	}

	/* 7. Broadcast for the advertising window, then stop */
	LOG_INF("Sleeping for %ds then powering off", CONFIG_APP_BLE_ADV_WINDOW_SEC);
	k_sleep(K_SECONDS(CONFIG_APP_BLE_ADV_WINDOW_SEC));

	bt_le_adv_stop();
	bt_disable();

	/* 8. Enter System OFF with GRTC (+ optional GPIO) wakeup */
	enter_system_off();
}

int main()
{
	printk("\n\n=== Humid Zephyr ===\n");
#ifdef PMIC_NAME
	printk("Board: " PMIC_NAME "\n");
#endif
	printk("====================\n\n");

	/* ---- [A] Determine boot reason ---- */
	uint32_t cause = 0;

	hwinfo_get_reset_cause(&cause);
	/* Clear immediately so a subsequent soft reset (OTA, watchdog) doesn't
	 * inherit stale bits — RESETREAS accumulates across soft resets on nRF. */
	hwinfo_clear_reset_cause();
	/* Note: RESET_LOW_POWER_WAKE = GPIO wakeup from System OFF (button press)
	 *       RESET_CLOCK          = GRTC wakeup from System OFF (timer)
	 *       All other values     = cold boot / debugger / watchdog */
	bool is_gpio_wakeup = (cause & RESET_LOW_POWER_WAKE) != 0;

	LOG_INF("Reset cause: 0x%08x %s", cause,
		is_gpio_wakeup ? "(GPIO wakeup → DFU mode)" :
		(cause & RESET_CLOCK) ? "(GRTC wakeup → measure)" : "(cold boot)");

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
	if (wdt == NULL) {
		LOG_ERR(PMIC_NAME " WDT not found in devicetree!");
	} else if (!device_is_ready(wdt)) {
		LOG_ERR(PMIC_NAME " WDT not ready — I2C issue?");
	} else {
		LOG_INF(PMIC_NAME " WDT ready");
	}
#endif

	/* ---- [C] DFU mode path ---- */
	if (is_gpio_wakeup || !boot_is_img_confirmed()) {
		if (!is_gpio_wakeup) {
			LOG_INF("Unconfirmed OTA image — auto-entering DFU mode for client verification");
		}
		int err = bt_enable(NULL);
		if (err) {
			LOG_ERR("Bluetooth init failed (err %d)", err);
			enter_system_off();
		}
		run_dfu_mode();
		/* run_dfu_mode() does not return */
	}

	/* ---- [B] Normal measurement path ---- */
	probe_optional_sensors();
	fuel_gauge_init();

	int err = bt_enable(NULL);
	if (err) {
		LOG_ERR("Bluetooth init failed (err %d)", err);
		enter_system_off();
	}
	LOG_INF("Bluetooth initialized");

	run_measurement();
	/* run_measurement() → enter_system_off() — does not return */

	return 0;
}
