// AirHub firmware — BTHome BLE build
//
// Reads SHT4x (temp + humidity) and SCD40 (CO2).
// Advertises all values over BTHome BLE.
//
// Simple loop architecture: always-on, always connectable, sleeps between readings.

#include <zephyr/bluetooth/bluetooth.h>
#include <zephyr/bluetooth/conn.h>
#include <zephyr/bluetooth/uuid.h>
#include <zephyr/device.h>
#include <zephyr/drivers/sensor.h>
#include <zephyr/kernel.h>
#include <ram_pwrdn.h>

#include <zephyr/logging/log.h>

#include "bthome.h"
#include "sensor/sensor_reading.h"

LOG_MODULE_REGISTER(app, LOG_LEVEL_INF);

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

/* Max service data: UUID(2) + info(1) + packet_id(2) + temp(3) + hum(3) + co2(3) */
#define SERVICE_DATA_MAX 16

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

static void bthome_update_service_data(uint8_t packet_id, opt_i16 temperature_cC,
				       opt_u16 humidity_cPct, opt_u16 co2_ppm)
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
	if (temperature_cC.is_some) {
		service_data[idx++] = BTHOME_OBJ_TEMP;
		service_data[idx++] = (uint8_t)(temperature_cC.value & 0xFF);
		service_data[idx++] = (uint8_t)((temperature_cC.value >> 8) & 0xFF);
	}

	/* Humidity: uint16, factor 0.01 % */
	if (humidity_cPct.is_some) {
		service_data[idx++] = BTHOME_OBJ_HUMIDITY;
		service_data[idx++] = (uint8_t)(humidity_cPct.value & 0xFF);
		service_data[idx++] = (uint8_t)((humidity_cPct.value >> 8) & 0xFF);
	}

	/* CO2: uint16, factor 1 ppm */
	if (co2_ppm.is_some) {
		service_data[idx++] = BTHOME_OBJ_CO2;
		service_data[idx++] = (uint8_t)(co2_ppm.value & 0xFF);
		service_data[idx++] = (uint8_t)((co2_ppm.value >> 8) & 0xFF);
	}

	__ASSERT(idx <= SERVICE_DATA_MAX, "BTHome service data overflow");
	service_data_len = idx;
}

static void update_advertisement(uint8_t packet_id, opt_i16 temperature_cC,
				 opt_u16 humidity_cPct, opt_u16 co2_ppm)
{
	bthome_update_service_data(packet_id, temperature_cC, humidity_cPct, co2_ppm);
	ad[1] = (struct bt_data)BT_DATA(BT_DATA_SVC_DATA16, service_data,
					(uint8_t)service_data_len);
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

int main()
{
	power_down_unused_ram();

	LOG_INF("=== AirHub ===");

	sensor_state sensors;
	sensor_init(sensors);

	/* Start BLE advertising */
	k_work_init(&advertise_work, advertise);
	update_advertisement(0, opt_i16_none(), opt_u16_none(), opt_u16_none());
	int err = bt_enable(bt_ready);
	if (err) {
		LOG_ERR("Bluetooth init failed (err %d)", err);
		return -1;
	}

	uint32_t cycle = 0;

	while (true) {
		sensor_read_sht4x(sensors);
		sensor_read_scd40(sensors);

		update_advertisement(++cycle,
				     {sensors.sht4x.temperature_cC, sensors.sht4x.valid},
				     {sensors.sht4x.humidity_cPct, sensors.sht4x.valid},
				     {sensors.scd40.co2_ppm, sensors.scd40.valid});

		k_sleep(K_SECONDS(CONFIG_APP_MEASUREMENT_INTERVAL_SEC));
	}

	return 0;
}
