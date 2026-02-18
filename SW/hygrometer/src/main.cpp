// Hygrometer firmware
//
// Supports both BL54L15u Hygrometer and BL54L15u DevKit boards.
// Reads SHT45 (temp/humidity), optional BME688 (pressure), optional STCC4 (CO2).
//
// Broadcasts via BTHome BLE advertisement.

#include <zephyr/device.h>
#include <zephyr/drivers/watchdog.h>
#include <zephyr/drivers/i2c.h>
#include <zephyr/drivers/sensor.h>
#include <zephyr/init.h>

#include <zephyr/bluetooth/bluetooth.h>
#include <zephyr/bluetooth/uuid.h>

#if DT_NODE_HAS_STATUS(DT_NODELABEL(npm1304_charger), okay)
#include <zephyr/drivers/sensor/npm13xx_charger.h>
#include <zephyr/drivers/mfd/npm13xx.h>
#endif

#include <zephyr/logging/log.h>

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

/* BTHome object IDs */
#define BTHOME_OBJ_TEMP     0x02  /* sint16, 0.01 °C */
#define BTHOME_OBJ_HUMIDITY 0x03  /* uint16, 0.01 % */
#define BTHOME_OBJ_PRESSURE 0x04  /* uint24, 0.01 hPa */
#define BTHOME_OBJ_VOLTAGE  0x0C  /* uint16, 0.001 V */
#define BTHOME_OBJ_CO2      0x12  /* uint16, 1 ppm */

/* Max service data: UUID(2) + info(1) + temp(3) + hum(3) + pressure(4) + co2(3) + voltage(3) = 19 */
#define SERVICE_DATA_MAX 19

static uint8_t service_data[SERVICE_DATA_MAX];
static size_t service_data_len;

/* Convert ms to BLE 0.625ms units */
#define ADV_INTERVAL_MIN  ((CONFIG_APP_BLE_ADV_INTERVAL_MS * 8) / 5)
#define ADV_INTERVAL_MAX  (ADV_INTERVAL_MIN + 0x0050)
#define ADV_PARAM BT_LE_ADV_PARAM(BT_LE_ADV_OPT_USE_IDENTITY, \
				  ADV_INTERVAL_MIN, \
				  ADV_INTERVAL_MAX, NULL)

static struct bt_data ad[] = {
	BT_DATA_BYTES(BT_DATA_FLAGS, BT_LE_AD_GENERAL | BT_LE_AD_NO_BREDR),
	BT_DATA(BT_DATA_NAME_COMPLETE, CONFIG_BT_DEVICE_NAME,
		sizeof(CONFIG_BT_DEVICE_NAME) - 1),
	BT_DATA(BT_DATA_SVC_DATA16, service_data, 0), /* len updated before adv */
};

/* ---- Sensor availability flags ---- */
static bool have_bme688;
static bool have_stcc4;

static uint32_t measurement_count;

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
 * Reads back the post-heater measurement for logging but the values
 * are not used — the heater elevates the sensor temperature, making
 * the reading unrepresentative of ambient conditions.
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

	/* Read back to clear the sensor's data-ready state.
	 * Sensor NACKs until measurement is ready; retry a few times. */
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

	/* Log post-heater values for diagnostics */
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

/* ---- Build service data ---- */
static void build_service_data(const struct sensor_value *temp,
			       const struct sensor_value *hum,
			       const struct sensor_value *pressure,
			       const uint16_t *co2_ppm,
			       const struct sensor_value *voltage)
{
	size_t idx = 0;

	/* UUID (little-endian) */
	service_data[idx++] = (uint8_t)(BTHOME_UUID & 0xFF);
	service_data[idx++] = (uint8_t)(BTHOME_UUID >> 8);
	/* Device info */
	service_data[idx++] = BTHOME_DEVICE_INFO;

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

/* ---- Read battery voltage ---- */
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

	return true;
#else
	return false;
#endif
}

int main()
{
	printk("\n\n=== Humid Zephyr ===\n");
#ifdef PMIC_NAME
	printk("Board: " PMIC_NAME "\n");
#endif
	printk("====================\n\n");

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

	/* Probe optional sensors */
	probe_optional_sensors();

	/* Initialize Bluetooth */
	int err = bt_enable(NULL);
	if (err) {
		LOG_ERR("Bluetooth init failed (err %d)", err);
		return 0;
	}
	LOG_INF("Bluetooth initialized");

	/* Build initial service data (empty readings) and start advertising */
	build_service_data(NULL, NULL, NULL, NULL, NULL);
	ad[2] = (struct bt_data)BT_DATA(BT_DATA_SVC_DATA16, service_data, service_data_len);

	err = bt_le_adv_start(ADV_PARAM, ad, ARRAY_SIZE(ad), NULL, 0);
	if (err) {
		LOG_ERR("Advertising failed to start (err %d)", err);
		return 0;
	}
	LOG_INF("BTHome advertising started");

#if IS_ENABLED(CONFIG_SHT4X_USE_HEATER)
	LOG_INF("SHT45 heater: power=%d duration=%s interval=%d",
		CONFIG_SHT4X_HEATER_PULSE_POWER,
		IS_ENABLED(CONFIG_SHT4X_HEATER_LONG_PULSE_DURATION) ? "long" : "short",
		CONFIG_APP_HEATER_INTERVAL);
#endif

	LOG_INF("Boot complete — measurement interval %ds",
		CONFIG_APP_MEASUREMENT_INTERVAL_SEC);

	/* ---- Main measurement loop ---- */
	while (1) {
		struct sensor_value temp, hum;
		struct sensor_value *temp_ptr = NULL;
		struct sensor_value *hum_ptr = NULL;
		struct sensor_value pressure;
		struct sensor_value *pressure_ptr = NULL;
		uint16_t co2_ppm;
		uint16_t *co2_ptr = NULL;
		struct sensor_value voltage;
		struct sensor_value *voltage_ptr = NULL;

		/* 1. Read SHT45 — temperature + humidity (always present) */
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
				if (measurement_count % CONFIG_APP_HEATER_INTERVAL == 0) {
					sht4x_heater_pulse();
				}
#endif
			} else {
				LOG_ERR("SHT45 fetch failed: %d", ret);
			}
		}
		measurement_count++;
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

		/* 4. Read battery voltage */
		if (read_battery_voltage(&voltage)) {
			voltage_ptr = &voltage;
			LOG_INF("Vbat: %d.%03dV",
				voltage.val1, voltage.val2 / 1000);
		}

		/* 5. Rebuild service data with current readings */
		build_service_data(temp_ptr, hum_ptr, pressure_ptr, co2_ptr,
				   voltage_ptr);

		/* 6. Update advertising data */
		ad[2] = (struct bt_data)BT_DATA(BT_DATA_SVC_DATA16, service_data,
						service_data_len);
		err = bt_le_adv_update_data(ad, ARRAY_SIZE(ad), NULL, 0);
		if (err) {
			LOG_ERR("Advertising update failed (err %d)", err);
		}

		k_sleep(K_SECONDS(CONFIG_APP_MEASUREMENT_INTERVAL_SEC));
	}

	return 0;
}
