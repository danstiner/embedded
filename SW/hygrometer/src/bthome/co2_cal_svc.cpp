#include "co2_cal_svc.h"

#include <zephyr/bluetooth/bluetooth.h>
#include <zephyr/bluetooth/gatt.h>
#include <zephyr/bluetooth/uuid.h>
#include <zephyr/kernel.h>
#include <zephyr/logging/log.h>
#include <zephyr/sys/byteorder.h>

#include "sensor/sensor_reading.h"

LOG_MODULE_REGISTER(co2_cal_svc, LOG_LEVEL_INF);

/* Random 128-bit UUIDs (generated) */
/* Service:        a1b2c3d4-e5f6-7890-abcd-ef0123456780 */
/* Characteristic: a1b2c3d4-e5f6-7890-abcd-ef0123456781 */
#define CO2_CAL_SVC_UUID_VAL BT_UUID_128_ENCODE(0xa1b2c3d4, 0xe5f6, 0x7890, 0xabcd, 0xef0123456780)

#define CO2_CAL_CHR_UUID_VAL BT_UUID_128_ENCODE(0xa1b2c3d4, 0xe5f6, 0x7890, 0xabcd, 0xef0123456781)

#define CO2_CAL_SVC_UUID BT_UUID_DECLARE_128(CO2_CAL_SVC_UUID_VAL)
#define CO2_CAL_CHR_UUID BT_UUID_DECLARE_128(CO2_CAL_CHR_UUID_VAL)

static uint16_t frc_target_ppm;

static void frc_work_handler(struct k_work *work)
{
	ARG_UNUSED(work);

	LOG_INF("STCC4: forcing recalibration");

	int ret = sensor_force_recalibration_stcc4(frc_target_ppm);
	if (ret) {
		LOG_ERR("FRC work failed: %d", ret);
	}
}

static K_WORK_DEFINE(frc_work, frc_work_handler);

static ssize_t co2_cal_write_cb(struct bt_conn *conn, const struct bt_gatt_attr *attr,
				const void *buf, uint16_t len, uint16_t offset, uint8_t flags)
{
	if (offset != 0) {
		return BT_GATT_ERR(BT_ATT_ERR_INVALID_OFFSET);
	}

	uint16_t target;

	if (len == 0) {
		target = 420;
	} else if (len == 2) {
		target = sys_get_le16(static_cast<const uint8_t *>(buf));
	} else {
		return BT_GATT_ERR(BT_ATT_ERR_INVALID_ATTRIBUTE_LEN);
	}

	LOG_INF("CO2 FRC requested: target=%u ppm", target);

	frc_target_ppm = target;
	k_work_submit(&frc_work);

	return len;
}

BT_GATT_SERVICE_DEFINE(co2_cal_svc, BT_GATT_PRIMARY_SERVICE(CO2_CAL_SVC_UUID),
		       BT_GATT_CHARACTERISTIC(CO2_CAL_CHR_UUID,
					      BT_GATT_CHRC_WRITE | BT_GATT_CHRC_WRITE_WITHOUT_RESP,
					      BT_GATT_PERM_WRITE, nullptr, co2_cal_write_cb,
					      nullptr), );

void co2_cal_svc_init(void)
{
	/* Service auto-registers via BT_GATT_SERVICE_DEFINE */
}
