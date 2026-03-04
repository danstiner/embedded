// Hygrometer firmware — BTHome BLE build
//
// Supports both BL54L15u Hygrometer and BL54L15u DevKit boards.
// Reads SHT45 (temp/humidity), optional BME688 (pressure), optional STCC4 (CO2).
//
// Simple loop architecture: always-on, always connectable, sleeps between readings.

#include <zephyr/device.h>
#include <zephyr/drivers/gpio.h>
#include <zephyr/drivers/watchdog.h>
#include <zephyr/drivers/i2c.h>
#include <zephyr/drivers/sensor.h>
#include <zephyr/init.h>

#include <zephyr/bluetooth/bluetooth.h>
#include <zephyr/bluetooth/conn.h>
#include <zephyr/bluetooth/uuid.h>

#include <zephyr/logging/log.h>

#include "bthome.h"
#include "led_svc.h"
#include "sensor/sht4x.h"
#include "sensor/sensor_reading.h"

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

/* Scan response — device name + SMP service UUID for DFU */
static struct bt_data sd[] = {
	BT_DATA(BT_DATA_NAME_COMPLETE, CONFIG_BT_DEVICE_NAME, sizeof(CONFIG_BT_DEVICE_NAME) - 1),
	BT_DATA_BYTES(BT_DATA_UUID128_ALL, SMP_SVC_UUID_BYTES),
};

/* SHT45 I2C bus for direct heater commands */
#if DT_NODE_HAS_STATUS(DT_NODELABEL(sht45), okay)
static const struct device *sht45_bus = DEVICE_DT_GET(DT_BUS(DT_NODELABEL(sht45)));
#endif

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

/* ---- Update BTHome advertisement data ---- */
static void update_advertisement(opt_i16 temperature_mC, opt_u16 humidity_mPct, opt_u32 pressure_Pa,
				 opt_u16 co2_ppm, opt_u16 iaq, opt_u8 bat_soc, opt_u16 bat_mV)
{
	bthome_update_service_data(temperature_mC, humidity_mPct, pressure_Pa, co2_ppm, iaq,
				   bat_soc, bat_mV);
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

int main()
{
	/* Boot LED flash for visual identification */
#if DT_NODE_HAS_STATUS(DT_ALIAS(boot_led), okay)
	if (gpio_is_ready_dt(&boot_led)) {
		gpio_pin_configure_dt(&boot_led, GPIO_OUTPUT_ACTIVE);
		k_sleep(K_MSEC(200));
		gpio_pin_set_dt(&boot_led, 0);
		led_svc_init(&boot_led);
	}
#endif

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

	struct sensor_state sensors;
	sensor_init(&sensors);
	sensor_fuel_gauge_init();

	/* Start BLE advertising */
	k_work_init(&advertise_work, advertise);
	update_advertisement(opt_i16_none(), opt_u16_none(), opt_u32_none(), opt_u16_none(),
			     opt_u16_none(), opt_u8_none(), opt_u16_none());
	int err = bt_enable(bt_ready);
	if (err) {
		LOG_ERR("Bluetooth init failed (err %d)", err);
		return -1;
	}

	uint32_t cycle = 0;

	while (true) {
		opt_i16 temperature_mC;
		opt_u16 humidity_mPct;
		opt_u32 pressure_Pa;
		opt_u16 co2_ppm;
		opt_u16 iaq;
		opt_u8 bat_soc;
		opt_u16 bat_mV;

		bool expensive_cycle = (cycle % CONFIG_APP_EXPENSIVE_SENSOR_DIVISOR) == 0;

		/* 1. Read SHT45 */
		if (sensor_read_sht45(&sensors) == 0) {
			temperature_mC = opt_i16_some(sensors.sht45.temperature_cC);
			humidity_mPct = opt_u16_some(sensors.sht45.humidity_cPct);

#if IS_ENABLED(CONFIG_SHT4X_USE_HEATER) && DT_NODE_HAS_STATUS(DT_NODELABEL(sht45), okay)
			sht4x_heater_pulse();
#endif
		}

		if (expensive_cycle) {
			/* 2. BME688: read pressure + gas/IAQ */
			if (sensor_read_bme688(&sensors) == 0) {
				pressure_Pa = opt_u32_some(sensors.bme688.pressure_Pa);
				if (sensors.bme688.have_iaq) {
					iaq = opt_u16_some(sensors.bme688.iaq);
				}
			}

			/* 3. STCC4: feed compensation + measure CO2 */
			if (sensor_read_stcc4(&sensors) == 0) {
				co2_ppm = opt_u16_some(sensors.stcc4.co2_ppm);
			}
		} else {
			/* Reuse last-known expensive sensor values */
			if (sensors.bme688.valid) {
				pressure_Pa = opt_u32_some(sensors.bme688.pressure_Pa);
				if (sensors.bme688.have_iaq) {
					iaq = opt_u16_some(sensors.bme688.iaq);
				}
			}
			if (sensors.stcc4.valid) {
				co2_ppm = opt_u16_some(sensors.stcc4.co2_ppm);
			}
		}

		/* 4. Read battery voltage (also updates fuel gauge SoC) */
		if (sensor_read_battery(&sensors) == 0) {
			bat_mV = opt_u16_some(sensors.battery.voltage_mV);
			if (sensors.battery.soc_pct > 0) {
				bat_soc = opt_u8_some(sensors.battery.soc_pct);
			}
		}

		/* 5. Update advertisement data */
		update_advertisement(temperature_mC, humidity_mPct, pressure_Pa, co2_ppm, iaq,
				     bat_soc, bat_mV);

		cycle++;
		k_sleep(K_SECONDS(CONFIG_APP_MEASUREMENT_INTERVAL_SEC));
	}

	return 0;
}
