#include <zephyr/kernel.h>
#include <zephyr/device.h>
#include <zephyr/drivers/sensor.h>
#include <zephyr/drivers/led.h>
#include <zephyr/input/input.h>
#include <zephyr/bluetooth/bluetooth.h>
#include <zephyr/bluetooth/conn.h>
#include <zephyr/bluetooth/uuid.h>
#include <zephyr/logging/log.h>
#include <zephyr/drivers/mfd/npm13xx.h>

/* FDC1004 custom channel */
#include "../drivers/sensor/fdc1004/fdc1004.h"

LOG_MODULE_REGISTER(soil_sensor, LOG_LEVEL_INF);

/* BTHome v2 service UUID */
#define BTHOME_SVC_UUID  0xFCD2

/* Calibration constants from Kconfig (in fF, convert to pF) */
#define CAP_DRY_PF   (CONFIG_SOIL_CAP_DRY_FF / 1000.0)
#define CAP_WET_PF   (CONFIG_SOIL_CAP_WET_FF / 1000.0)

/* BTHome object IDs */
#define BTHOME_OBJ_MOISTURE  0x14  /* uint16, factor 0.01 % */
#define BTHOME_OBJ_VOLTAGE   0x0C  /* uint16, factor 0.001 V */

/* DFU mode timeout */
#define DFU_TIMEOUT_SEC  300  /* 5 minutes */

/* SMP service UUID (8d53dc1d-1db7-4cd3-868b-8a527460aa84) in little-endian */
#define SMP_SVC_UUID_BYTES \
	0x84, 0xaa, 0x60, 0x74, 0x52, 0x8a, \
	0x8b, 0x86, 0xd3, 0x4c, 0xb7, 0x1d, \
	0x1d, 0xdc, 0x53, 0x8d

/* Service data layout (object IDs must be in ascending order per BTHome v2):
 * [0-1] UUID 0xFCD2 (little-endian)
 * [2]   Device info: 0x40 (BTHome v2, unencrypted)
 * [3]   Object ID: voltage (0x0C)
 * [4-5] Voltage value (uint16 LE, factor 0.001 V)
 * [6]   Object ID: moisture (0x14)
 * [7-8] Moisture value (uint16 LE, factor 0.01 %)
 */
#define SVC_DATA_LEN 9

static uint8_t svc_data[SVC_DATA_LEN] = {
	BT_UUID_16_ENCODE(BTHOME_SVC_UUID),
	0x40,                   /* BTHome v2, no encryption */
	BTHOME_OBJ_VOLTAGE,
	0x00, 0x00,             /* battery voltage mV */
	BTHOME_OBJ_MOISTURE,
	0x00, 0x00,             /* moisture % */
};

/* BTHome advertising data (used for both normal and DFU modes) */
static struct bt_data bthome_ad[] = {
	BT_DATA_BYTES(BT_DATA_FLAGS, BT_LE_AD_GENERAL | BT_LE_AD_NO_BREDR),
	BT_DATA(BT_DATA_NAME_COMPLETE, CONFIG_BT_DEVICE_NAME,
		sizeof(CONFIG_BT_DEVICE_NAME) - 1),
	BT_DATA(BT_DATA_SVC_DATA16, svc_data, ARRAY_SIZE(svc_data)),
};

/* Scan response for DFU mode — SMP service UUID */
static struct bt_data sd[] = {
	BT_DATA_BYTES(BT_DATA_UUID128_ALL, SMP_SVC_UUID_BYTES),
};

/* Non-connectable advertising parameters (BTHome) */
#define BTHOME_ADV_PARAM BT_LE_ADV_PARAM(BT_LE_ADV_OPT_USE_IDENTITY, \
					  BT_GAP_ADV_SLOW_INT_MIN, \
					  BT_GAP_ADV_SLOW_INT_MAX, NULL)

/* Connectable advertising parameters (SMP DFU) — fast interval for reliable
 * discovery and connection. DFU mode is brief and user-initiated, so the
 * extra power draw is acceptable. */
#define SMP_ADV_PARAM BT_LE_ADV_PARAM(BT_LE_ADV_OPT_CONN | \
				       BT_LE_ADV_OPT_USE_IDENTITY, \
				       BT_GAP_ADV_FAST_INT_MIN_2, \
				       BT_GAP_ADV_FAST_INT_MAX_2, NULL)

static const struct device *fdc1004 = DEVICE_DT_GET_ANY(ti_fdc1004);
static const struct device *charger = DEVICE_DT_GET_ANY(nordic_npm1304_charger);
static const struct device *led_dev = DEVICE_DT_GET(DT_COMPAT_GET_ANY_STATUS_OKAY(gpio_leds));

static bool dfu_mode;
static int64_t dfu_mode_start;
static struct bt_conn *current_conn;

static int start_bthome_adv(void)
{
	return bt_le_adv_start(BTHOME_ADV_PARAM, bthome_ad,
			       ARRAY_SIZE(bthome_ad), NULL, 0);
}

static int start_dfu_adv(void)
{
	return bt_le_adv_start(SMP_ADV_PARAM, bthome_ad,
			       ARRAY_SIZE(bthome_ad), sd,
			       ARRAY_SIZE(sd));
}

static void restart_smp_adv_work_handler(struct k_work *work)
{
	if (dfu_mode) {
		int err = start_dfu_adv();

		if (err) {
			LOG_ERR("Failed to restart DFU advertising: %d", err);
		}
	}
}

static K_WORK_DELAYABLE_DEFINE(restart_smp_adv_work, restart_smp_adv_work_handler);

static void enter_dfu_mode(void)
{
	int err;

	LOG_INF("Entering DFU mode");

	err = bt_le_adv_stop();
	if (err) {
		LOG_ERR("Failed to stop advertising: %d", err);
	}

	err = start_dfu_adv();
	if (err) {
		LOG_ERR("Failed to start DFU advertising: %d", err);
		start_bthome_adv();
		return;
	}

	dfu_mode = true;
	dfu_mode_start = k_uptime_get();
	led_on(led_dev, 0);

	LOG_INF("DFU advertising started (timeout %d s)", DFU_TIMEOUT_SEC);
}

static void exit_dfu_mode(void)
{
	int err;

	LOG_INF("Exiting DFU mode");

	/* Disconnect any active connection */
	if (current_conn) {
		bt_conn_disconnect(current_conn, BT_HCI_ERR_REMOTE_USER_TERM_CONN);
	}

	err = bt_le_adv_stop();
	if (err) {
		LOG_ERR("Failed to stop SMP advertising: %d", err);
	}

	err = start_bthome_adv();
	if (err) {
		LOG_ERR("Failed to restart BTHome advertising: %d", err);
	}

	dfu_mode = false;
	led_off(led_dev, 0);

	LOG_INF("BTHome advertising resumed");
}

/* Button callback (input subsystem) */
static void button_cb(struct input_event *evt, void *user_data)
{
	ARG_UNUSED(user_data);

	if (evt->code == INPUT_KEY_0 && evt->value) {
		if (dfu_mode) {
			exit_dfu_mode();
		} else {
			enter_dfu_mode();
		}
	}
}
INPUT_CALLBACK_DEFINE(NULL, button_cb, NULL);

/* BLE connection callbacks */
static void connected(struct bt_conn *conn, uint8_t err)
{
	if (err) {
		LOG_ERR("Connection failed: %d", err);
		if (dfu_mode) {
			start_dfu_adv();
		}
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

	/* Restart SMP advertising if still in DFU mode. Deferred to the system
	 * work queue — calling bt_le_adv_start directly from the disconnect
	 * callback fails with -ENOMEM because resources aren't freed yet. */
	if (dfu_mode) {
		k_work_schedule(&restart_smp_adv_work, K_MSEC(100));
	}
}

BT_CONN_CB_DEFINE(conn_cbs) = {
	.connected = connected,
	.disconnected = disconnected,
};

int main(void)
{
	int err;

	LOG_INF("Soil Sensor starting");

	if (!device_is_ready(led_dev)) {
		LOG_WRN("LED device not ready");
	}

	/* Initialize Bluetooth (before sensor checks so DFU works without sensor) */
	err = bt_enable(NULL);
	if (err) {
		LOG_ERR("Bluetooth init failed: %d", err);
		return 0;
	}

	/* Start non-connectable advertising */
	err = start_bthome_adv();
	if (err) {
		LOG_ERR("Advertising failed to start: %d", err);
		return 0;
	}

	LOG_INF("BTHome advertising started");

	/* Set POF threshold to 3.1V (register base=0x01, offset=0x06, value=0x05) */
	const struct device *pmic = DEVICE_DT_GET_ANY(nordic_npm1304);

	if (pmic && device_is_ready(pmic)) {
		int ret = mfd_npm13xx_reg_write(pmic, 0x01, 0x06, 0x05);

		if (ret == 0) {
			LOG_INF("POF threshold set to 3.1V");
		} else {
			LOG_WRN("Failed to set POF threshold: %d", ret);
		}
	}

	/* Check sensors — non-fatal, DFU and advertising continue without them */
	if (!device_is_ready(fdc1004)) {
		LOG_ERR("FDC1004 not ready");
	}

	if (!device_is_ready(charger)) {
		LOG_WRN("NPM1304 charger not ready, voltage will be 0");
	}

	while (1) {
		struct sensor_value cap_val, volt_val;
		double cap_pf, moisture_pct;
		uint16_t moisture_raw, voltage_raw;

		/* DFU timeout check */
		if (dfu_mode &&
		    k_uptime_get() - dfu_mode_start > DFU_TIMEOUT_SEC * 1000LL) {
			LOG_INF("DFU timeout, returning to BTHome");
			exit_dfu_mode();
		}

		/* Skip sensor reads if sensor unavailable */
		if (!device_is_ready(fdc1004)) {
			goto sleep;
		}

		/* Read capacitance from FDC1004 channel 0 */
		err = sensor_sample_fetch(fdc1004);
		if (err) {
			LOG_ERR("FDC1004 fetch failed: %d", err);
			goto sleep;
		}

		err = sensor_channel_get(fdc1004, (enum sensor_channel)SENSOR_CHAN_FDC1004_CAPACITANCE_CH0, &cap_val);
		if (err) {
			LOG_ERR("FDC1004 channel get failed: %d", err);
			goto sleep;
		}

		cap_pf = sensor_value_to_double(&cap_val);

		/* Linear map to moisture % */
		moisture_pct = (cap_pf - CAP_DRY_PF) / (CAP_WET_PF - CAP_DRY_PF) * 100.0;
		if (moisture_pct < 0.0) {
			moisture_pct = 0.0;
		} else if (moisture_pct > 100.0) {
			moisture_pct = 100.0;
		}

		/* BTHome moisture: uint16 with factor 0.01 */
		moisture_raw = (uint16_t)(moisture_pct * 100.0);

		LOG_INF("Capacitance: %d.%06d pF -> Moisture: %u.%02u %%",
			cap_val.val1, cap_val.val2,
			moisture_raw / 100, moisture_raw % 100);

		/* Read battery voltage from NPM1304 */
		voltage_raw = 0;
		if (device_is_ready(charger)) {
			err = sensor_sample_fetch(charger);
			if (err == 0) {
				err = sensor_channel_get(charger,
					SENSOR_CHAN_GAUGE_VOLTAGE, &volt_val);
				if (err == 0) {
					/* sensor_value is in V (val1) + uV (val2)
					 * BTHome voltage: uint16 with factor 0.001 V (mV) */
					voltage_raw = (uint16_t)(volt_val.val1 * 1000 +
								volt_val.val2 / 1000);
					LOG_INF("Battery: %d.%03d V",
						voltage_raw / 1000, voltage_raw % 1000);
				}
			}
		}

		/* Update BTHome service data */
		svc_data[4] = voltage_raw & 0xFF;
		svc_data[5] = voltage_raw >> 8;
		svc_data[7] = moisture_raw & 0xFF;
		svc_data[8] = moisture_raw >> 8;

		if (dfu_mode) {
			err = bt_le_adv_update_data(bthome_ad, ARRAY_SIZE(bthome_ad),
						    sd, ARRAY_SIZE(sd));
		} else {
			err = bt_le_adv_update_data(bthome_ad, ARRAY_SIZE(bthome_ad),
						    NULL, 0);
		}
		if (err) {
			LOG_ERR("Failed to update advertising data: %d", err);
		}

sleep:
		k_sleep(K_SECONDS(11));
	}

	return 0;
}
