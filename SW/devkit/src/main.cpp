// Button-to-LED test for BL54L15u DevKit
// Press SW1 (P0.00) to light RED LED (P2.08)
// Uses GPIO interrupt to wake from sleep
#include <zephyr/kernel.h>
#include <zephyr/logging/log.h>
#include <zephyr/drivers/gpio.h>
#include <zephyr/drivers/led.h>
#include <zephyr/drivers/mfd/npm13xx.h>
#include <zephyr/drivers/sensor.h>
#include <zephyr/drivers/sensor/npm13xx_charger.h>
#include <zephyr/bluetooth/bluetooth.h>
#include <zephyr/bluetooth/conn.h>
#include <zephyr/bluetooth/hci.h>
#include <zephyr/mgmt/mcumgr/transport/smp_bt.h>
#include <nrf_fuel_gauge.h>
#include <ram_pwrdn.h>

LOG_MODULE_REGISTER(app, LOG_LEVEL_INF);

/* LED on P2.08 */
static const struct gpio_dt_spec led = GPIO_DT_SPEC_GET(DT_ALIAS(led0), gpios);

/* Button SW1 on P0.00 */
static const struct gpio_dt_spec button = GPIO_DT_SPEC_GET(DT_ALIAS(sw0), gpios);

static struct gpio_callback button_cb_data;

/* NPM1304 charger for battery monitoring */
static const struct device *charger = DEVICE_DT_GET(DT_NODELABEL(npm1304_charger));

/* ---- BTHome v2 ---- */
#define BTHOME_UUID        0xFCD2
#define BTHOME_DEVICE_INFO 0x40 /* Unencrypted, BTHome v2 */
#define BTHOME_OBJ_BATTERY 0x01 /* uint8, 1% */
#define BTHOME_OBJ_VOLTAGE 0x0C /* uint16, 0.001 V */

/* BTHome payload: UUID(2) + info(1) + battery%(1+1) + voltage(1+2) = 8 bytes */
static uint8_t bthome_data[8] = {
	(uint8_t)(BTHOME_UUID & 0xFF),
	(uint8_t)(BTHOME_UUID >> 8),
	BTHOME_DEVICE_INFO,
	BTHOME_OBJ_BATTERY,
	0,
	BTHOME_OBJ_VOLTAGE,
	0,
	0,
};

/* ---- Fuel gauge state ---- */
static const struct battery_model battery_model = {
#include "battery_model.inc"
};

static int64_t fg_ref_time;
static float fg_voltage_f;
static float fg_current_f;
static float fg_temp_f;
static int32_t fg_charge_status;

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

static void build_bthome_data(uint8_t soc_pct, uint16_t voltage_mv)
{
	bthome_data[3] = BTHOME_OBJ_BATTERY;
	bthome_data[4] = soc_pct;
	bthome_data[5] = BTHOME_OBJ_VOLTAGE;
	bthome_data[6] = (uint8_t)(voltage_mv & 0xFF);
	bthome_data[7] = (uint8_t)(voltage_mv >> 8);
}

static void log_battery_status(void)
{
	if (!device_is_ready(charger)) {
		LOG_WRN("Charger not ready");
		return;
	}

	struct sensor_value voltage, current, temp, status, error;

	sensor_sample_fetch(charger);

	sensor_channel_get(charger, SENSOR_CHAN_GAUGE_VOLTAGE, &voltage);
	sensor_channel_get(charger, SENSOR_CHAN_GAUGE_AVG_CURRENT, &current);
	if (sensor_channel_get(charger, SENSOR_CHAN_GAUGE_TEMP, &temp) < 0) {
		sensor_channel_get(charger, SENSOR_CHAN_DIE_TEMP, &temp);
	}
	sensor_channel_get(charger, (enum sensor_channel)SENSOR_CHAN_NPM13XX_CHARGER_STATUS,
			   &status);
	sensor_channel_get(charger, (enum sensor_channel)SENSOR_CHAN_NPM13XX_CHARGER_ERROR, &error);

	/* Save float values for fuel gauge */
	fg_voltage_f = (float)voltage.val1 + (float)voltage.val2 / 1000000.f;
	fg_current_f = (float)current.val1 + (float)current.val2 / 1000000.f;
	fg_temp_f = (float)temp.val1 + (float)temp.val2 / 1000000.f;
	fg_charge_status = status.val1;

	/* Convert current from uA to mA with sign */
	int current_ma = current.val1 * 1000 + current.val2 / 1000;

	LOG_INF("Vbat=%d.%03dV I=%d.%03dmA temp=%d.%03dC status=0x%02X err=0x%02X", voltage.val1,
		voltage.val2 / 1000, current_ma, abs(current.val2) % 1000, temp.val1,
		temp.val2 / 1000, status.val1, error.val1);

	/* BCHGCHARGESTATUS register (0x34):
	 *   Bit 0 = BATTERYDETECTED
	 *   Bit 1 = COMPLETED
	 *   Bit 2 = TRICKLECHARGE
	 *   Bit 3 = CONSTANTCURRENT
	 *   Bit 4 = CONSTANTVOLTAGE
	 *   Bit 5 = RECHARGE
	 *   Bit 6 = DIETEMPHIGHCHGPAUSED
	 *   Bit 7 = SUPPLEMENTACTIVE
	 */
	if (status.val1 & 0x01) {
		LOG_INF("Battery is connected.");
	}
	if (status.val1 & 0x02) {
		LOG_INF("Charging completed (Battery Full).");
	}
	if (status.val1 & 0x04) {
		LOG_INF("Trickle charge.");
	}
	if (status.val1 & 0x08) {
		LOG_INF("Constant current charging.");
	}
	if (status.val1 & 0x10) {
		LOG_INF("Constant voltage charging.");
	}
	if (status.val1 & 0x20) {
		LOG_INF("Battery re-charge is needed.");
	}
	if (status.val1 & 0x40) {
		LOG_INF("Charging stopped due Die Temp high.");
	}
	if (status.val1 & 0x80) {
		LOG_INF("Supplement Mode Active.");
	}
}

/* BLE SMP advertising for DFU, with BTHome service data in main ad */
static struct k_work advertise_work;

/* Main ad: FLAGS + BTHome service data + name (13 bytes used, 18 bytes free for 15-char name).
 * Scan response: SMP UUID for DFU discovery. */
static const struct bt_data ad[] = {
	BT_DATA_BYTES(BT_DATA_FLAGS, (BT_LE_AD_GENERAL | BT_LE_AD_NO_BREDR)),
	BT_DATA(BT_DATA_SVC_DATA16, bthome_data, sizeof(bthome_data)),
	BT_DATA(BT_DATA_NAME_COMPLETE, CONFIG_BT_DEVICE_NAME, sizeof(CONFIG_BT_DEVICE_NAME) - 1),
};

static const struct bt_data sd[] = {
	BT_DATA_BYTES(BT_DATA_UUID128_ALL, SMP_BT_SVC_UUID_VAL),
};

static void advertise(struct k_work *work)
{
	int rc = bt_le_adv_start(BT_LE_ADV_CONN_FAST_1, ad, ARRAY_SIZE(ad), sd, ARRAY_SIZE(sd));
	if (rc) {
		LOG_ERR("Advertising failed to start (rc %d)", rc);
		return;
	}
	LOG_INF("Advertising successfully started");
}

static void connected(struct bt_conn *conn, uint8_t err)
{
	if (err) {
		LOG_ERR("Connection failed, err 0x%02x %s", err, bt_hci_err_to_str(err));
		k_work_submit(&advertise_work);
	} else {
		LOG_INF("BLE connected");
	}
}

static void disconnected(struct bt_conn *conn, uint8_t reason)
{
	LOG_INF("BLE disconnected, reason 0x%02x %s", reason, bt_hci_err_to_str(reason));
}

static void on_conn_recycled(void)
{
	k_work_submit(&advertise_work);
}

BT_CONN_CB_DEFINE(conn_callbacks) = {
	.connected = connected,
	.disconnected = disconnected,
	.recycled = on_conn_recycled,
};

static void bt_ready(int err)
{
	if (err) {
		LOG_ERR("Bluetooth init failed: %d", err);
		return;
	}
	k_work_submit(&advertise_work);
}

static void button_pressed(const struct device *dev, struct gpio_callback *cb, uint32_t pins)
{
	int pressed = gpio_pin_get_dt(&button);
	gpio_pin_set_dt(&led, pressed);
	LOG_INF("Button %s", pressed ? "pressed" : "released");
}

int main(void)
{
	power_down_unused_ram();

	printk("\n\n=== BL54L15u DevKit ===\n");
	printk("Button-to-LED (interrupt-driven)\n");
	printk("================================\n\n");

	/* Configure red LED on P2.08 */
	if (!gpio_is_ready_dt(&led)) {
		LOG_ERR("LED GPIO not ready");
		return -1;
	}
	gpio_pin_configure_dt(&led, GPIO_OUTPUT_INACTIVE);

	/* Check USB CC status and flash LED accordingly
	 * USBCDETECTSTATUS register (0x0205):
	 *   Bits 1:0 = CC1 status: 00=none, 01=default(500mA), 10=1.5A, 11=3A
	 *   Bits 3:2 = CC2 status: 00=none, 01=default(500mA), 10=1.5A, 11=3A
	 *
	 * DAM (Debug Accessory Mode) - Table B-2 Rp/Rp values:
	 *   Default USB Power: CC1=3A, CC2=1.5A
	 *   1.5A Current:      CC1=1.5A, CC2=Default
	 *   3A Current:        CC1=3A, CC2=Default
	 */
	/* Flash duration encodes current: 200ms=default, 400ms=1.5A, 800ms=3A
	 * Flash count encodes type: 1=normal USB, 3=DAM */
	static const char *cc_names[] = {"none", "500mA", "1.5A", "3A"};
	static const int duration_ms[] = {100, 200, 400, 800}; /* indexed by CC level */
	const struct device *pmic = DEVICE_DT_GET(DT_NODELABEL(npm1304_pmic));
	const struct device *rgb = DEVICE_DT_GET(DT_NODELABEL(npm1304_leds));

	/* Configure POF (Power-Fail) threshold to 3.1V for battery protection
	 * When VSYS drops below this threshold, PMIC shuts down all outputs
	 * and enters ~0.5µA sleep until VSYS recovers above ~2.9V.
	 *
	 * POFCONFIG register (base 0x01, offset 0x06):
	 *   Bits 3:0 = Threshold: 0=2.6V, 1=2.7V, 2=2.8V(default), 3=2.9V,
	 *              4=3.0V, 5=3.1V, 6=3.2V, 7=3.3V
	 */
	if (device_is_ready(pmic)) {
		int ret = mfd_npm13xx_reg_write(pmic, 0x01, 0x06, 0x05);
		if (ret == 0) {
			LOG_INF("POF threshold set to 3.1V");
		} else {
			LOG_WRN("Failed to set POF threshold: %d", ret);
		}
	}

	int flash_count = 1;
	int flash_duration = 200;
	if (device_is_ready(pmic)) {
		uint8_t cc_status;
		int ret = mfd_npm13xx_reg_read(pmic, 0x02, 0x05, &cc_status);
		if (ret == 0) {
			uint8_t cc1 = cc_status & 0x03;
			uint8_t cc2 = (cc_status >> 2) & 0x03;

			LOG_INF("USB CC status: 0x%02X - CC1=%s, CC2=%s", cc_status, cc_names[cc1],
				cc_names[cc2]);

			/* Check for DAM modes (both CC active, either orientation) */
			if ((cc1 == 3 && cc2 == 2) || (cc1 == 2 && cc2 == 3)) {
				LOG_INF("USB DAM: Default USB Power");
				flash_count = 3;
				flash_duration = duration_ms[1];
			} else if ((cc1 == 2 && cc2 == 1) || (cc1 == 1 && cc2 == 2)) {
				LOG_INF("USB DAM: 1.5A Current");
				flash_count = 3;
				flash_duration = duration_ms[2];
			} else if ((cc1 == 3 && cc2 == 1) || (cc1 == 1 && cc2 == 3)) {
				LOG_INF("USB DAM: 3A Current");
				flash_count = 3;
				flash_duration = duration_ms[3];
			} else if (cc1 != 0 || cc2 != 0) {
				/* Normal USB - single CC active */
				uint8_t level = (cc1 > cc2) ? cc1 : cc2;
				LOG_INF("USB DFP %s", cc_names[level]);
				flash_count = 1;
				flash_duration = duration_ms[level];
			} else {
				LOG_INF("No USB connected");
				flash_count = 1;
				flash_duration = 200;
			}
		}
	}

	if (device_is_ready(rgb)) {
		LOG_INF("Flashing LED %dx @ %dms", flash_count, flash_duration);
		for (int i = 0; i < flash_count; i++) {
			led_on(rgb, 0); /* LED0 = Blue (host mode) */
			k_msleep(flash_duration);
			led_off(rgb, 0);
			k_msleep(100);
		}
	} else {
		LOG_WRN("NPM1304 LED driver not ready");
	}

	/* Configure button with interrupt on both edges */
	if (!gpio_is_ready_dt(&button)) {
		LOG_ERR("Button GPIO not ready");
		return -1;
	}
	gpio_pin_configure_dt(&button, GPIO_INPUT);
	gpio_pin_interrupt_configure_dt(&button, GPIO_INT_EDGE_BOTH);

	/* Set up callback */
	gpio_init_callback(&button_cb_data, button_pressed, BIT(button.pin));
	gpio_add_callback(button.port, &button_cb_data);

	LOG_INF("Press SW1 to toggle LED");

	/* ---- Fuel gauge init ---- */
	if (device_is_ready(charger)) {
		struct sensor_value sv;
		struct nrf_fuel_gauge_init_parameters fg_params = {
			.model = &battery_model,
			.opt_params = nullptr,
			.state = nullptr,
		};

		sensor_sample_fetch(charger);

		sensor_channel_get(charger, SENSOR_CHAN_GAUGE_VOLTAGE, &sv);
		fg_params.v0 = (float)sv.val1 + (float)sv.val2 / 1000000.f;
		fg_voltage_f = fg_params.v0;

		if (sensor_channel_get(charger, SENSOR_CHAN_GAUGE_TEMP, &sv) < 0) {
			sensor_channel_get(charger, SENSOR_CHAN_DIE_TEMP, &sv);
		}
		fg_params.t0 = (float)sv.val1 + (float)sv.val2 / 1000000.f;
		fg_temp_f = fg_params.t0;

		sensor_channel_get(charger, SENSOR_CHAN_GAUGE_AVG_CURRENT, &sv);
		fg_params.i0 = -((float)sv.val1 + (float)sv.val2 / 1000000.f);

		sensor_channel_get(charger, SENSOR_CHAN_GAUGE_DESIRED_CHARGING_CURRENT, &sv);
		float max_current = (float)sv.val1 + (float)sv.val2 / 1000000.f;

		int fg_ret = nrf_fuel_gauge_init(&fg_params, nullptr);
		if (fg_ret < 0) {
			LOG_ERR("Fuel gauge init failed: %d", fg_ret);
		} else {
			union nrf_fuel_gauge_ext_state_info_data fg_info;

			fg_info.charge_current_limit = max_current;
			nrf_fuel_gauge_ext_state_update(
				NRF_FUEL_GAUGE_EXT_STATE_INFO_CHARGE_CURRENT_LIMIT, &fg_info);

			fg_info.charge_term_current = max_current / 10.f;
			nrf_fuel_gauge_ext_state_update(NRF_FUEL_GAUGE_EXT_STATE_INFO_TERM_CURRENT,
							&fg_info);

			LOG_INF("Fuel gauge initialized (%s)", nrf_fuel_gauge_version);
		}
	} else {
		LOG_WRN("Charger not ready — fuel gauge skipped");
	}
	fg_ref_time = k_uptime_get();

	/* Start BLE SMP advertising for DFU */
	k_work_init(&advertise_work, advertise);
	int bt_rc = bt_enable(bt_ready);
	if (bt_rc) {
		LOG_ERR("Bluetooth enable failed: %d", bt_rc);
	}

	/* Pin test: cycle through all header-exposed GPIOs, driving each high for 5s */
	static const struct {
		const struct device *port;
		gpio_pin_t pin;
		const char *name;
	} test_pins[] = {
		{DEVICE_DT_GET(DT_NODELABEL(gpio1)), 2, "P1.02"},
		{DEVICE_DT_GET(DT_NODELABEL(gpio1)), 3, "P1.03"},
		{DEVICE_DT_GET(DT_NODELABEL(gpio1)), 6, "P1.06"},
		{DEVICE_DT_GET(DT_NODELABEL(gpio2)), 6, "P2.06"},
		{DEVICE_DT_GET(DT_NODELABEL(gpio2)), 4, "P2.04"},
		{DEVICE_DT_GET(DT_NODELABEL(gpio2)), 1, "P2.01"},
		{DEVICE_DT_GET(DT_NODELABEL(gpio2)), 0, "P2.00"},
		{DEVICE_DT_GET(DT_NODELABEL(gpio2)), 5, "P2.05"},
		{DEVICE_DT_GET(DT_NODELABEL(gpio1)), 15, "P1.15"},
		{DEVICE_DT_GET(DT_NODELABEL(gpio1)), 14, "P1.14"},
		{DEVICE_DT_GET(DT_NODELABEL(gpio1)), 13, "P1.13"},
	};

	for (int i = 0; i < ARRAY_SIZE(test_pins); i++) {
		gpio_pin_configure(test_pins[i].port, test_pins[i].pin, GPIO_OUTPUT_INACTIVE);
	}

	while (true) {
		for (int i = 0; i < ARRAY_SIZE(test_pins); i++) {
			LOG_INF("PIN TEST [%d/%d]: %s HIGH", i + 1, ARRAY_SIZE(test_pins),
				test_pins[i].name);
			gpio_pin_set(test_pins[i].port, test_pins[i].pin, 1);
			/* Inform fuel gauge of low-power sleep period */
			nrf_fuel_gauge_idle_set(fg_voltage_f, fg_temp_f, 10e-6f);
			k_sleep(K_SECONDS(5));
			gpio_pin_set(test_pins[i].port, test_pins[i].pin, 0);
		}

		log_battery_status();

		/* Update fuel gauge and BTHome advertising */
		static int32_t fg_prev_charge_status = -1;
		float fg_delta = (float)k_uptime_delta(&fg_ref_time) / 1000.f;

		if (fg_charge_status != fg_prev_charge_status) {
			fg_prev_charge_status = fg_charge_status;
			charge_status_inform(fg_charge_status);
		}

		float soc = nrf_fuel_gauge_process(fg_voltage_f, -fg_current_f, fg_temp_f, fg_delta,
						   nullptr);
		uint8_t soc_pct = (uint8_t)CLAMP((int)soc, 0, 100);
		uint16_t voltage_mv = (uint16_t)(fg_voltage_f * 1000.f);

		LOG_INF("SoC: %d%%", (int)soc_pct);

		build_bthome_data(soc_pct, voltage_mv);
		bt_le_adv_update_data(ad, ARRAY_SIZE(ad), sd, ARRAY_SIZE(sd));
	}

	return 0;
}
