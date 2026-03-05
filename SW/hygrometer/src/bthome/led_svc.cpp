#include "led_svc.h"

#include <zephyr/bluetooth/bluetooth.h>
#include <zephyr/bluetooth/gatt.h>
#include <zephyr/bluetooth/uuid.h>
#include <zephyr/drivers/gpio.h>
#include <zephyr/kernel.h>
#include <zephyr/logging/log.h>

LOG_MODULE_REGISTER(led_svc, LOG_LEVEL_INF);

/* Random 128-bit UUIDs (generated) */
/* Service:        a1b2c3d4-e5f6-7890-abcd-ef0123456789 */
/* Characteristic: a1b2c3d4-e5f6-7890-abcd-ef012345678a */
#define LED_SVC_UUID_VAL BT_UUID_128_ENCODE(0xa1b2c3d4, 0xe5f6, 0x7890, 0xabcd, 0xef0123456789)

#define LED_CHR_UUID_VAL BT_UUID_128_ENCODE(0xa1b2c3d4, 0xe5f6, 0x7890, 0xabcd, 0xef012345678a)

#define LED_SVC_UUID BT_UUID_DECLARE_128(LED_SVC_UUID_VAL)
#define LED_CHR_UUID BT_UUID_DECLARE_128(LED_CHR_UUID_VAL)

#define LED_ON_DURATION_SEC 30

static const struct gpio_dt_spec *led_gpio;

static void led_off_work_handler(struct k_work *work);
static K_WORK_DELAYABLE_DEFINE(led_off_work, led_off_work_handler);

static void led_off_work_handler(struct k_work *work)
{
	ARG_UNUSED(work);
	gpio_pin_set_dt(led_gpio, 0);
	LOG_INF("LED auto-off");
}

static ssize_t led_write_cb(struct bt_conn *conn, const struct bt_gatt_attr *attr, const void *buf,
			    uint16_t len, uint16_t offset, uint8_t flags)
{
	if (led_gpio == nullptr) {
		return BT_GATT_ERR(BT_ATT_ERR_UNLIKELY);
	}

	if (offset != 0 || len != 1) {
		return BT_GATT_ERR(BT_ATT_ERR_INVALID_OFFSET);
	}

	uint8_t val = ((const uint8_t *)buf)[0];

	if (val == 0x01) {
		gpio_pin_set_dt(led_gpio, 1);
		k_work_reschedule(&led_off_work, K_SECONDS(LED_ON_DURATION_SEC));
		LOG_INF("LED on (30s timer)");
	} else {
		k_work_cancel_delayable(&led_off_work);
		gpio_pin_set_dt(led_gpio, 0);
		LOG_INF("LED off");
	}

	return len;
}

BT_GATT_SERVICE_DEFINE(led_svc, BT_GATT_PRIMARY_SERVICE(LED_SVC_UUID),
		       BT_GATT_CHARACTERISTIC(LED_CHR_UUID,
					      BT_GATT_CHRC_WRITE | BT_GATT_CHRC_WRITE_WITHOUT_RESP,
					      BT_GATT_PERM_WRITE, nullptr, led_write_cb, nullptr), );

void led_svc_init(const struct gpio_dt_spec *led)
{
	led_gpio = led;
}
