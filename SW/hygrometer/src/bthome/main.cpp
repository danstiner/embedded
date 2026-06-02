// Hygrometer firmware — BTHome BLE build
//
// Supports both BL54L15u Hygrometer and BL54L15u DevKit boards.
// Reads SHT4x (temp/humidity), optional BME688 (pressure), optional STCC4 (CO2).
//
// Simple loop architecture: always-on, always connectable, sleeps between readings.

#include <zephyr/device.h>
#include <zephyr/drivers/gpio.h>
#include <zephyr/drivers/watchdog.h>
#include <zephyr/drivers/i2c.h>
#include <zephyr/drivers/sensor.h>
#include <ram_pwrdn.h>
#if DT_NODE_HAS_STATUS(DT_NODELABEL(npm1304_pmic), okay)
#include <zephyr/drivers/mfd/npm13xx.h>
#endif
#include <zephyr/bluetooth/bluetooth.h>
#include <zephyr/bluetooth/conn.h>
#include <zephyr/bluetooth/uuid.h>

#include <zephyr/logging/log.h>

#include "bthome.h"
#include "co2_cal_svc.h"
#include "led_svc.h"
#include "sensor/sht4x.h"
#include "sensor/sensor_reading.h"
#if IS_ENABLED(CONFIG_APP_LEAK_SENSOR)
#include "sensor/leak.h"
#endif

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

/* Connectable advertising parameters — ~4.0–4.5s interval to save power */
#define ADV_INT_MIN 0x1900 /* 4.0 s in 0.625 ms units */
#define ADV_INT_MAX 0x1C20 /* 4.5 s in 0.625 ms units */
#define ADV_PARAM_CONN                                                                             \
	BT_LE_ADV_PARAM(BT_LE_ADV_OPT_USE_IDENTITY | BT_LE_ADV_OPT_CONN, ADV_INT_MIN, ADV_INT_MAX, \
			NULL)

constexpr bt_data AD_FLAG_BYTES =
	BT_DATA_BYTES(BT_DATA_FLAGS, BT_LE_AD_GENERAL | BT_LE_AD_NO_BREDR);

/* Max service data: UUID(2) + info(1) + packet_id(2) + temp(3) + hum(3) + pressure(4)
 * + co2(3) + battery_low(2) + moisture(2). No single board populates every field
 * (pressure/CO2 are v3-only, moisture is v4-only), but size for the worst case. */
#define SERVICE_DATA_MAX 22

static uint8_t service_data[SERVICE_DATA_MAX];
static size_t service_data_len;

static struct bt_data ad[] = {
	AD_FLAG_BYTES,
	BT_DATA(BT_DATA_SVC_DATA16, NULL, 0),
};

constexpr size_t BT_DATA_HEADER_LEN = 1;

static_assert(BT_DATA_HEADER_LEN * 2 + AD_FLAG_BYTES.data_len + sizeof(service_data) <=
	      BT_GAP_ADV_MAX_ADV_DATA_LEN);

/* Scan response — device name + SMP service UUID for DFU */
static struct bt_data sd[] = {
	BT_DATA(BT_DATA_NAME_COMPLETE, CONFIG_BT_DEVICE_NAME, sizeof(CONFIG_BT_DEVICE_NAME) - 1),
	BT_DATA_BYTES(BT_DATA_UUID128_ALL, SMP_SVC_UUID_BYTES),
};

/* SHT4x I2C bus for direct heater commands */
#if DT_NODE_HAS_STATUS(DT_NODELABEL(sht4x), okay)
static const struct device *sht4x_bus = DEVICE_DT_GET(DT_BUS(DT_NODELABEL(sht4x)));
#endif

/*
 * Fire SHT4x heater via direct I2C for decontamination.
 */
#if IS_ENABLED(CONFIG_SHT4X_USE_HEATER) && DT_NODE_HAS_STATUS(DT_NODELABEL(sht4x), okay)
static void sht4x_heater_pulse(void)
{
	int power = CONFIG_SHT4X_HEATER_PULSE_POWER;
	int duration = IS_ENABLED(CONFIG_SHT4X_HEATER_LONG_PULSE_DURATION) ? 0 : 1;

	uint8_t cmd = sht4x_heater_cmd[power][duration];
	int ret = i2c_write(sht4x_bus, &cmd, 1, SHT4X_I2C_ADDR);

	if (ret) {
		LOG_ERR("SHT4x heater cmd failed: %d", ret);
		return;
	}

	k_sleep(K_MSEC(sht4x_heater_total_wait_ms[duration]));

	uint8_t buf[6];

	for (int attempt = 0; attempt < 10; attempt++) {
		ret = i2c_read(sht4x_bus, buf, sizeof(buf), SHT4X_I2C_ADDR);
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

static void bthome_update_service_data(uint8_t packet_id, opt_i16 temperature_mC,
				       opt_u16 humidity_mPct, opt_u32 pressure_Pa, opt_u16 co2_ppm,
				       opt_u8 battery_low, opt_u8 moisture)
{
	size_t idx = 0;

	/* UUID (little-endian) */
	service_data[idx++] = (uint8_t)(BTHOME_UUID & 0xFF);
	service_data[idx++] = (uint8_t)(BTHOME_UUID >> 8);
	/* Device info */
	service_data[idx++] = BTHOME_DEVICE_INFO;

	/* Packet ID: uint8, rolling counter */
	service_data[idx++] = BTHOME_OBJ_PACKET_ID;
	service_data[idx++] = packet_id;

	/* Temperature: sint16, factor 0.01 °C */
	if (temperature_mC.is_some) {
		service_data[idx++] = BTHOME_OBJ_TEMP;
		service_data[idx++] = (uint8_t)(temperature_mC.value & 0xFF);
		service_data[idx++] = (uint8_t)((temperature_mC.value >> 8) & 0xFF);
	}

	/* Humidity: uint16, factor 0.01 % */
	if (humidity_mPct.is_some) {
		service_data[idx++] = BTHOME_OBJ_HUMIDITY;
		service_data[idx++] = (uint8_t)(humidity_mPct.value & 0xFF);
		service_data[idx++] = (uint8_t)((humidity_mPct.value >> 8) & 0xFF);
	}

	/* Pressure: uint24, factor 0.01 hPa */
	if (pressure_Pa.is_some) {
		service_data[idx++] = BTHOME_OBJ_PRESSURE;
		service_data[idx++] = (uint8_t)(pressure_Pa.value & 0xFF);
		service_data[idx++] = (uint8_t)((pressure_Pa.value >> 8) & 0xFF);
		service_data[idx++] = (uint8_t)((pressure_Pa.value >> 16) & 0xFF);
	}

	/* CO2: uint16, factor 1 ppm */
	if (co2_ppm.is_some) {
		service_data[idx++] = BTHOME_OBJ_CO2;
		service_data[idx++] = (uint8_t)(co2_ppm.value & 0xFF);
		service_data[idx++] = (uint8_t)((co2_ppm.value >> 8) & 0xFF);
	}

	/* Battery low: uint8 binary, 0 = normal, 1 = low (0x15 > 0x12, < 0x20) */
	if (battery_low.is_some) {
		service_data[idx++] = BTHOME_OBJ_BATTERY_LOW;
		service_data[idx++] = battery_low.value ? 1 : 0;
	}

	/* Moisture/water-leak: uint8 binary (0x20 keeps ascending order) */
	if (moisture.is_some) {
		service_data[idx++] = BTHOME_OBJ_MOISTURE;
		service_data[idx++] = moisture.value ? 1 : 0;
	}

	__ASSERT(idx <= SERVICE_DATA_MAX, "BTHome service data overflow");
	service_data_len = idx;
}

/* ---- Update BTHome advertisement data ---- */
static void update_advertisement(uint8_t packet_id, opt_i16 temperature_mC, opt_u16 humidity_mPct,
				 opt_u32 pressure_Pa, opt_u16 co2_ppm, opt_u8 battery_low,
				 opt_u8 moisture)
{
	bthome_update_service_data(packet_id, temperature_mC, humidity_mPct, pressure_Pa, co2_ppm,
				   battery_low, moisture);
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

#if DT_NODE_HAS_STATUS(DT_ALIAS(boot_led), okay)
static const struct gpio_dt_spec boot_led = GPIO_DT_SPEC_GET(DT_ALIAS(boot_led), gpios);
#endif

#if IS_ENABLED(CONFIG_APP_LEAK_SENSOR)
/* Signalled by the leak ISR so the main loop wakes immediately on a leak. */
static K_SEM_DEFINE(leak_wake_sem, 0, 1);
#endif

int main()
{
	/* LDOSW is managed by sensor_init() — enabled for probing,
	 * then disabled if no BME688/STCC4 are detected. */

	power_down_unused_ram();

	/* Boot LED flash for visual identification */
#if DT_NODE_HAS_STATUS(DT_ALIAS(boot_led), okay)
	if (gpio_is_ready_dt(&boot_led)) {
		gpio_pin_configure_dt(&boot_led, GPIO_OUTPUT_ACTIVE);
		k_sleep(K_MSEC(200));
		gpio_pin_set_dt(&boot_led, 0);
		led_svc_init(&boot_led);
	}
#endif

	LOG_INF("=== Hygrometer ===");
#ifdef PMIC_NAME
	LOG_INF("PMIC: " PMIC_NAME);
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
	}
#endif

	co2_cal_svc_init();

	sensor_state sensors;
	sensor_init(sensors);
	sensor_fuel_gauge_init();
#if IS_ENABLED(CONFIG_APP_LEAK_SENSOR)
	leak_init(sensors, &leak_wake_sem);
#endif

	uint32_t cycle = 0;

	/* Start BLE advertising */
	k_work_init(&advertise_work, advertise);
	update_advertisement(cycle, opt_i16_none(), opt_u16_none(), opt_u32_none(), opt_u16_none(),
			     opt_u8_none(), opt_u8_none());
	int err = bt_enable(bt_ready);
	if (err) {
		LOG_ERR("Bluetooth init failed (err %d)", err);
		return -1;
	}

	while (true) {
		bool co2_cycle = (cycle % CONFIG_APP_CO2_INTERVAL_DIVISOR) == 0;
		bool pressure_cycle = (cycle % CONFIG_APP_PRESSURE_INTERVAL_DIVISOR) == 0;

		sensor_read_sht4x(sensors);
#if IS_ENABLED(CONFIG_SHT4X_USE_HEATER) && DT_NODE_HAS_STATUS(DT_NODELABEL(sht4x), okay)
		if (sensors.sht4x.valid) {
			sht4x_heater_pulse();
		}
#endif

		if (pressure_cycle) {
			sensor_read_bme688(sensors);
		}

		if (co2_cycle) {
			sensor_read_stcc4(sensors);
		}

		sensor_read_battery(sensors);

		opt_u8 moisture = opt_u8_none();
#if IS_ENABLED(CONFIG_APP_LEAK_SENSOR)
		leak_read(sensors);
		if (sensors.leak.valid) {
			moisture = opt_u8_some(sensors.leak.wet ? 1 : 0);
		}
#endif

		opt_u8 battery_low = opt_u8_none();
		if (sensors.battery.valid) {
			battery_low = opt_u8_some(sensors.battery.health != BATTERY_OK ? 1 : 0);
		}

		update_advertisement(++cycle, {sensors.sht4x.temperature_cC, sensors.sht4x.valid},
				     {sensors.sht4x.humidity_cPct, sensors.sht4x.valid},
				     {sensors.bme688.pressure_Pa, sensors.bme688.valid},
				     {sensors.stcc4.co2_ppm, sensors.stcc4.valid}, battery_low,
				     moisture);
		sensor_fuel_gauge_idle_set();

#if IS_ENABLED(CONFIG_APP_LEAK_SENSOR)
		/* Wake early if the leak ISR fires, otherwise sleep the full interval. */
		k_sem_take(&leak_wake_sem, K_SECONDS(CONFIG_APP_MEASUREMENT_INTERVAL_SEC));
#else
		k_sleep(K_SECONDS(CONFIG_APP_MEASUREMENT_INTERVAL_SEC));
#endif
	}

	return 0;
}
