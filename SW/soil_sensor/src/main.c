#include <zephyr/kernel.h>
#include <zephyr/device.h>
#include <zephyr/drivers/sensor.h>
#include <zephyr/bluetooth/bluetooth.h>
#include <zephyr/bluetooth/conn.h>
#include <zephyr/bluetooth/uuid.h>
#include <zephyr/logging/log.h>
#include <zephyr/drivers/mfd/npm13xx.h>
#include <ram_pwrdn.h>

#include "bthome.h"

/* FDC1004 custom channel */
#include "../drivers/sensor/fdc1004/fdc1004.h"

LOG_MODULE_REGISTER(soil_sensor, LOG_LEVEL_INF);

/* Calibration constants from Kconfig (in fF, convert to pF) */
#define CAP_DRY_PF (CONFIG_SOIL_CAP_DRY_FF / 1000.0)
#define CAP_WET_PF (CONFIG_SOIL_CAP_WET_FF / 1000.0)

/* SMP service UUID (8d53dc1d-1db7-4cd3-868b-8a527460aa84) in little-endian */
#define SMP_SVC_UUID_BYTES                                                                         \
	0x84, 0xaa, 0x60, 0x74, 0x52, 0x8a, 0x8b, 0x86, 0xd3, 0x4c, 0xb7, 0x1d, 0x1d, 0xdc, 0x53,  \
		0x8d

/* Advertising data */
static struct bt_data ad[] = {
	BT_DATA_BYTES(BT_DATA_FLAGS, BT_LE_AD_GENERAL | BT_LE_AD_NO_BREDR),
	BT_DATA(BT_DATA_NAME_COMPLETE, CONFIG_BT_DEVICE_NAME, sizeof(CONFIG_BT_DEVICE_NAME) - 1),
	BT_DATA(BT_DATA_SVC_DATA16, NULL, 0),
};

/* Scan response data — SMP service UUID for DFU */
static struct bt_data sd[] = {
	BT_DATA_BYTES(BT_DATA_UUID128_ALL, SMP_SVC_UUID_BYTES),
};

/* Connectable advertising */
#define ADV_PARAM_CONN                                                                             \
	BT_LE_ADV_PARAM(BT_LE_ADV_OPT_USE_IDENTITY | BT_LE_ADV_OPT_CONN | BT_LE_ADV_OPT_CODED,     \
			BT_GAP_PER_ADV_SLOW_INT_MIN, BT_GAP_PER_ADV_SLOW_INT_MAX, NULL)

static const struct device *fdc1004 = DEVICE_DT_GET_ANY(ti_fdc1004);
static const struct device *charger = DEVICE_DT_GET_ANY(nordic_npm1304_charger);

static void update_advertisement(opt_u16 moisture, opt_u16 voltage)
{
	bthome_update_service_data(moisture, voltage);
	ad[2] = (struct bt_data)BT_DATA(BT_DATA_SVC_DATA16, service_data,
					(uint8_t)service_data_len);

	/* Push updated data to the BLE stack */
	bt_le_adv_update_data(ad, ARRAY_SIZE(ad), sd, ARRAY_SIZE(sd));
}

static struct k_work advertise_work;

static void advertise(struct k_work *work)
{
	int rc = bt_le_adv_start(ADV_PARAM_CONN, ad, ARRAY_SIZE(ad), sd, ARRAY_SIZE(sd));
	if (rc) {
		LOG_ERR("Advertising failed to start (rc %d)", rc);
		return;
	}
	LOG_INF("Advertising successfully started");
}

static void bt_ready(int err)
{
	if (err) {
		LOG_ERR("Bluetooth init failed: %d", err);
		return;
	}
	k_work_submit(&advertise_work);
}

/* BLE connection callbacks */
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
	/* Restart advertising */
	k_work_submit(&advertise_work);
}

BT_CONN_CB_DEFINE(conn_callbacks) = {
	.connected = connected,
	.disconnected = disconnected,
	.recycled = recycled,
};

int main(void)
{
	power_down_unused_ram();

	int err;

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

	if (!device_is_ready(fdc1004)) {
		LOG_ERR("FDC1004 not ready");
	}

	if (!device_is_ready(charger)) {
		LOG_WRN("NPM1304 charger not ready");
	}

	/* Start BLE advertising */
	k_work_init(&advertise_work, advertise);
	update_advertisement(opt_u16_none(), opt_u16_none());
	err = bt_enable(bt_ready);
	if (err) {
		LOG_ERR("Bluetooth init failed: %d", err);
		return -1;
	}

	while (true) {
		/* Read sensors */
		opt_u16 moisture = opt_u16_none();
		opt_u16 voltage = opt_u16_none();

		if (device_is_ready(fdc1004)) {
			struct sensor_value cap_val;

			err = sensor_sample_fetch(fdc1004);
			if (err) {
				LOG_ERR("FDC1004 fetch failed: %d", err);
			} else {
				err = sensor_channel_get(
					fdc1004,
					(enum sensor_channel)SENSOR_CHAN_FDC1004_CAPACITANCE_CH0,
					&cap_val);
				if (err) {
					LOG_ERR("FDC1004 channel get failed: %d", err);
				} else {
					double cap_pf = sensor_value_to_double(&cap_val);
					double moisture_pct = (cap_pf - CAP_DRY_PF) /
							      (CAP_WET_PF - CAP_DRY_PF) * 100.0;

					if (moisture_pct < 0.0) {
						moisture_pct = 0.0;
					} else if (moisture_pct > 100.0) {
						moisture_pct = 100.0;
					}

					moisture = opt_u16_some(moisture_pct * 100.0);
					LOG_INF("Capacitance: %d.%06d pF -> Moisture: %u.%02u %%",
						cap_val.val1, cap_val.val2, moisture.value / 100,
						moisture.value % 100);
				}
			}
		}

		if (device_is_ready(charger)) {
			struct sensor_value volt_val;

			err = sensor_sample_fetch(charger);
			if (err == 0) {
				err = sensor_channel_get(charger, SENSOR_CHAN_GAUGE_VOLTAGE,
							 &volt_val);
				if (err == 0) {
					/* sensor_value is in V (val1) + uV (val2)
					 * BTHome voltage: uint16 with factor 0.001 V (mV) */
					voltage = opt_u16_some(volt_val.val1 * 1000 +
							       volt_val.val2 / 1000);
					LOG_INF("Battery: %d.%03d V", voltage.value / 1000,
						voltage.value % 1000);
				}
			}
		}

		/* Update advertised BTHome data */
		update_advertisement(moisture, voltage);

		/* Sleep main thread until next measurement */
		k_sleep(K_SECONDS(CONFIG_APP_MEASUREMENT_INTERVAL_SEC));
	}

	return 0;
}
