#include <stdlib.h>
#include <zephyr/kernel.h>
#include <zephyr/logging/log.h>
#include <zephyr/device.h>
#include <zephyr/devicetree.h>
#include <zephyr/drivers/sensor.h>
#include <zephyr/drivers/adc.h>
#include <zephyr/drivers/gpio.h>
#include <zephyr/bluetooth/bluetooth.h>
#include <zephyr/bluetooth/conn.h>

LOG_MODULE_REGISTER(app, LOG_LEVEL_INF);

/* Internal temperature sensor */
static const struct device *temp_sensor = DEVICE_DT_GET(DT_NODELABEL(temp));

/* ADC for battery voltage */
static const struct adc_dt_spec adc_battery = ADC_DT_SPEC_GET_BY_IDX(DT_PATH(zephyr_user), 0);

/* GPIO to enable battery voltage divider (active low = drive to GND) */
static const struct gpio_dt_spec battery_div_en =
	GPIO_DT_SPEC_GET(DT_PATH(zephyr_user), battery_div_gpios);

/* Battery voltage divider: VBAT -- R1 -- ADC -- R2 -- GPIO */
#define BATTERY_R1_KOHM  470
#define BATTERY_R2_KOHM  220

/* Minimum battery voltage (mV) to perform measurements */
#define BATTERY_MIN_MV  2000

/*
 * BTHome v2 Advertisement Format
 * https://bthome.io/format/
 *
 * Service UUID: 0xFCD2
 * Device Info byte: 0x40 = BTHome v2, no encryption, no trigger
 * Object IDs must be in ascending order:
 *   0x02 = Temperature (sint16, 0.01°C)
 *   0x03 = Humidity (uint16, 0.01%)
 *   0x14 = Moisture (uint16, 0.01%)
 */

#define BTHOME_SERVICE_UUID     0xFCD2
#define BTHOME_DEVICE_INFO      0x40  /* Version 2, no encryption */

#define BTHOME_ID_TEMPERATURE   0x02
#define BTHOME_ID_HUMIDITY      0x03
#define BTHOME_ID_MOISTURE      0x14

/* BTHome service data buffer */
static uint8_t bthome_svc_data[] = {
	/* UUID (little-endian) */
	BTHOME_SERVICE_UUID & 0xFF,
	BTHOME_SERVICE_UUID >> 8,
	/* Device info */
	BTHOME_DEVICE_INFO,
	/* Temperature: ID + sint16 (little-endian) */
	BTHOME_ID_TEMPERATURE, 0x00, 0x00,
	/* Humidity: ID + uint16 (little-endian) */
	BTHOME_ID_HUMIDITY, 0x00, 0x00,
	/* Moisture: ID + uint16 (little-endian) */
	BTHOME_ID_MOISTURE, 0x00, 0x00,
};

/* Offsets into bthome_svc_data for sensor values */
#define TEMP_OFFSET     4   /* After UUID(2) + DevInfo(1) + ID(1) */
#define HUMIDITY_OFFSET 7   /* After temp value(2) + ID(1) */
#define MOISTURE_OFFSET 10  /* After humidity value(2) + ID(1) */

static struct bt_data ad[] = {
	BT_DATA_BYTES(BT_DATA_FLAGS, (BT_LE_AD_GENERAL | BT_LE_AD_NO_BREDR)),
	BT_DATA(BT_DATA_SVC_DATA16, bthome_svc_data, sizeof(bthome_svc_data)),
};

/* Low-power connectable advertising: 10 second interval
 * 0x4000 = 16384 * 0.625ms = 10.24s (max allowed by BLE spec)
 * Uses BT_LE_ADV_OPT_CONN (not deprecated BT_LE_ADV_OPT_CONNECTABLE) */
static struct bt_le_adv_param adv_param = BT_LE_ADV_PARAM_INIT(
	BT_LE_ADV_OPT_CONN,
	0x4000, /* interval min: 10.24s */
	0x4000, /* interval max: 10.24s */
	NULL);

/* Scan response with name and SMP service UUID for OTA */
static const struct bt_data sd[] = {
	BT_DATA(BT_DATA_NAME_COMPLETE, CONFIG_BT_DEVICE_NAME, sizeof(CONFIG_BT_DEVICE_NAME) - 1),
	BT_DATA_BYTES(BT_DATA_UUID128_ALL,
		      /* SMP service UUID: 8d53dc1d-1db7-4cd3-868b-8a527460aa84 */
		      0x84, 0xaa, 0x60, 0x74, 0x52, 0x8a, 0x8b, 0x86,
		      0xd3, 0x4c, 0xb7, 0x1d, 0x1d, 0xdc, 0x53, 0x8d),
};

static struct bt_conn *current_conn;

static void connected(struct bt_conn *conn, uint8_t err)
{
	if (err) {
		LOG_ERR("Connection failed (err %u)", err);
		return;
	}
	LOG_INF("Connected");
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

BT_CONN_CB_DEFINE(conn_callbacks) = {
	.connected = connected,
	.disconnected = disconnected,
};

static void update_bthome_data(int16_t temp_centideg, uint16_t humidity_centipct,
			       uint16_t moisture_centipct)
{
	/* Temperature (sint16, little-endian) */
	bthome_svc_data[TEMP_OFFSET] = temp_centideg & 0xFF;
	bthome_svc_data[TEMP_OFFSET + 1] = (temp_centideg >> 8) & 0xFF;

	/* Humidity (uint16, little-endian) */
	bthome_svc_data[HUMIDITY_OFFSET] = humidity_centipct & 0xFF;
	bthome_svc_data[HUMIDITY_OFFSET + 1] = (humidity_centipct >> 8) & 0xFF;

	/* Moisture (uint16, little-endian) */
	bthome_svc_data[MOISTURE_OFFSET] = moisture_centipct & 0xFF;
	bthome_svc_data[MOISTURE_OFFSET + 1] = (moisture_centipct >> 8) & 0xFF;
}

static int start_advertising(void)
{
	int err = bt_le_adv_start(&adv_param, ad, ARRAY_SIZE(ad), sd, ARRAY_SIZE(sd));
	if (err) {
		LOG_ERR("Advertising failed to start (err %d)", err);
		return err;
	}
	LOG_INF("Advertising started (10s interval)");
	return 0;
}

static int update_advertising(void)
{
	int err = bt_le_adv_update_data(ad, ARRAY_SIZE(ad), sd, ARRAY_SIZE(sd));
	if (err) {
		LOG_ERR("Advertising update failed (err %d)", err);
		return err;
	}
	return 0;
}

/* Read internal temperature sensor, returns centidegrees (0.01°C units) */
static int16_t read_internal_temp(void)
{
	struct sensor_value val;
	int err;

	err = sensor_sample_fetch(temp_sensor);
	if (err) {
		LOG_ERR("Temp fetch failed: %d", err);
		return 0;
	}

	err = sensor_channel_get(temp_sensor, SENSOR_CHAN_DIE_TEMP, &val);
	if (err) {
		LOG_ERR("Temp get failed: %d", err);
		return 0;
	}

	/* Convert to centidegrees: val1 is integer part, val2 is fractional in 1/1000000 */
	return (int16_t)(val.val1 * 100 + val.val2 / 10000);
}

/* Read battery voltage via ADC with GPIO-switched divider, returns mV */
static uint16_t read_battery_voltage(void)
{
	int16_t buf;
	int32_t val_mv;
	int err;

	struct adc_sequence sequence = {
		.buffer = &buf,
		.buffer_size = sizeof(buf),
	};

	/* Enable voltage divider by driving GPIO low */
	gpio_pin_configure_dt(&battery_div_en, GPIO_OUTPUT_ACTIVE);

	/* Small delay for divider to settle */
	k_usleep(50);

	/* Read ADC */
	adc_sequence_init_dt(&adc_battery, &sequence);
	err = adc_read_dt(&adc_battery, &sequence);

	/* Disable divider by setting GPIO to high-Z */
	gpio_pin_configure_dt(&battery_div_en, GPIO_INPUT);

	if (err) {
		LOG_ERR("ADC read failed: %d", err);
		return 0;
	}

	val_mv = buf;
	err = adc_raw_to_millivolts_dt(&adc_battery, &val_mv);
	if (err) {
		LOG_ERR("ADC conversion failed: %d", err);
		return 0;
	}

	/* Scale by divider ratio: Vbat = Vadc * (R1 + R2) / R2 */
	val_mv = val_mv * (BATTERY_R1_KOHM + BATTERY_R2_KOHM) / BATTERY_R2_KOHM;

	return (uint16_t)val_mv;
}

/* Read sensors - uses internal temp, fake data for humidity/moisture */
static void read_sensors(int16_t *temp, uint16_t *humidity, uint16_t *moisture)
{
	/* Read real temperature from internal sensor */
	*temp = read_internal_temp();

	/* Fake data for humidity and moisture until external sensors added */
	static int cycle = 0;
	cycle++;
	*humidity = 5500 + (cycle % 8) * 25;    /* 55.00-56.75% */
	*moisture = 4500 + (cycle % 10) * 50;   /* 45.00-49.50% */
}

int main(void)
{
	int err;
	int16_t temperature;
	uint16_t humidity, moisture, voltage_mv;

	LOG_INF("Soil sensor starting (BTHome v2)...");

	/* Verify temperature sensor is ready */
	if (!device_is_ready(temp_sensor)) {
		LOG_ERR("Temperature sensor not ready");
		return EXIT_FAILURE;
	}
	LOG_INF("Temperature sensor ready");

	/* Initialize ADC for battery voltage */
	if (!adc_is_ready_dt(&adc_battery)) {
		LOG_ERR("ADC not ready");
		return EXIT_FAILURE;
	}
	err = adc_channel_setup_dt(&adc_battery);
	if (err) {
		LOG_ERR("ADC channel setup failed: %d", err);
		return EXIT_FAILURE;
	}
	LOG_INF("ADC ready");

	/* Initialize GPIO for battery divider (start in high-Z / disabled) */
	if (!gpio_is_ready_dt(&battery_div_en)) {
		LOG_ERR("Battery divider GPIO not ready");
		return EXIT_FAILURE;
	}
	gpio_pin_configure_dt(&battery_div_en, GPIO_INPUT);
	LOG_INF("Battery divider GPIO ready");

	/* Initialize Bluetooth */
	err = bt_enable(NULL);
	if (err) {
		LOG_ERR("Bluetooth init failed (err %d)", err);
		return EXIT_FAILURE;
	}
	LOG_INF("Bluetooth initialized");

	/* Initial sensor read */
	read_sensors(&temperature, &humidity, &moisture);
	update_bthome_data(temperature, humidity, moisture);

	/* Start advertising (SMP service is auto-registered) */
	err = start_advertising();
	if (err) {
		return EXIT_FAILURE;
	}

	/* Main loop - periodic sensor reads and advertisement updates */
	while (1) {
		k_sleep(K_SECONDS(CONFIG_APP_MEASUREMENT_INTERVAL_SEC));

		/* Check battery voltage before taking measurements */
		/*
		voltage_mv = read_battery_voltage();
		LOG_DBG("Battery: %d.%03d V", voltage_mv / 1000, voltage_mv % 1000);

		if (voltage_mv < BATTERY_MIN_MV) {
			LOG_WRN("Battery low (%d mV), skipping measurement", voltage_mv);
			continue;
		}
		*/

		read_sensors(&temperature, &humidity, &moisture);
		update_bthome_data(temperature, humidity, moisture);

		LOG_INF("Temp: %d.%02d C, RH: %d.%02d%%, Soil: %d.%02d%%",
			temperature / 100, abs(temperature % 100),
			humidity / 100, humidity % 100,
			moisture / 100, moisture % 100);

		/* Update advertisement if not connected */
		if (!current_conn) {
			update_advertising();
		}
	}

	return EXIT_SUCCESS;
}
