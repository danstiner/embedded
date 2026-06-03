/*
 * Hygrometer firmware — Zigbee (ZBOSS / ncs-zigbee add-on) build.
 *
 * Sleepy end device that reports temperature over Zigbee, reusing the shared
 * sensor_reading module via sensor_shim (same sensors as the BTHome/Matter
 * builds). First cut: Temperature Measurement only — humidity, battery
 * (Power Config) and water-leak (IAS Zone) clusters are follow-ups.
 *
 * Written in C because the ZBOSS device-declaration macros use C constructs
 * that do not parse as C++.
 */

/* Must precede every ZBOSS include: zboss_api.h pulls in the HA device headers
 * transitively, and ha/zb_ha_temperature_sensor.h only defines its DECLARE_*
 * macros when this is set. */
#define ZB_HA_DEFINE_DEVICE_TEMPERATURE_SENSOR

#include <zephyr/kernel.h>
#include <zephyr/logging/log.h>

#include <zboss_api.h>
#include <zboss_api_addons.h>
#include <zigbee/zigbee_error_handler.h>
#include <zigbee/zigbee_app_utils.h>
#include <zb_nrf_platform.h>
#include <ha/zb_ha_temperature_sensor.h>
#include <ram_pwrdn.h>

#include "sensor_shim.h"

LOG_MODULE_REGISTER(app, LOG_LEVEL_INF);

/* Application endpoint that hosts the ZCL clusters. */
#define SENSOR_ENDPOINT 10

/* Battery-powered coin cell. */
#define INIT_BASIC_POWER_SOURCE ZB_ZCL_BASIC_POWER_SOURCE_BATTERY

/* Basic cluster identity — shown as manufacturer/model in ZHA / zigbee2mqtt. */
#define INIT_BASIC_MANUF_NAME "Barry's Boards"
#define INIT_BASIC_MODEL_ID   "Hygrometer"

/* Sleepy end-device long-poll interval (ms): how often the device wakes its
 * radio to poll the parent for queued downlink. Longer = lower sleep current on
 * the coin cell, at the cost of downlink latency (coordinator attribute reads,
 * Identify, reporting reconfigure). Applied after join because the join
 * procedure resets it to the stack default. Deeper CR2 power-budget tuning is a
 * follow-up. */
#define APP_LONG_POLL_INTERVAL_MS 7680

/* Temperature Measurement defaults (0.01 °C units). */
#define TEMP_MEASURE_MIN_VALUE (-4000) /* -40.00 °C */
#define TEMP_MEASURE_MAX_VALUE (12500) /* 125.00 °C */
#define TEMP_MEASURE_TOLERANCE (50)    /*   0.50 °C */

/* ZCL attribute storage. */
struct zb_device_ctx {
	zb_zcl_basic_attrs_ext_t basic_attr;
	zb_zcl_identify_attrs_t identify_attr;
	zb_zcl_temp_measurement_attrs_t temp_attr;
};
static struct zb_device_ctx dev_ctx;

ZB_ZCL_DECLARE_IDENTIFY_ATTRIB_LIST(identify_attr_list, &dev_ctx.identify_attr.identify_time);

/* Extended Basic attribute list so we can advertise manufacturer/model names. */
ZB_ZCL_DECLARE_BASIC_ATTRIB_LIST_EXT(
	basic_attr_list, &dev_ctx.basic_attr.zcl_version, &dev_ctx.basic_attr.app_version,
	&dev_ctx.basic_attr.stack_version, &dev_ctx.basic_attr.hw_version,
	dev_ctx.basic_attr.mf_name, dev_ctx.basic_attr.model_id, dev_ctx.basic_attr.date_code,
	&dev_ctx.basic_attr.power_source, dev_ctx.basic_attr.location_id, &dev_ctx.basic_attr.ph_env,
	dev_ctx.basic_attr.sw_ver);

ZB_ZCL_DECLARE_TEMP_MEASUREMENT_ATTRIB_LIST(temp_attr_list, &dev_ctx.temp_attr.measure_value,
					    &dev_ctx.temp_attr.min_measure_value,
					    &dev_ctx.temp_attr.max_measure_value,
					    &dev_ctx.temp_attr.tolerance);

ZB_HA_DECLARE_TEMPERATURE_SENSOR_CLUSTER_LIST(sensor_clusters, basic_attr_list, identify_attr_list,
					      temp_attr_list);

ZB_HA_DECLARE_TEMPERATURE_SENSOR_EP(sensor_ep, SENSOR_ENDPOINT, sensor_clusters);

ZBOSS_DECLARE_DEVICE_CTX_1_EP(sensor_ctx, sensor_ep);

static void app_clusters_attr_init(void)
{
	dev_ctx.basic_attr.zcl_version = ZB_ZCL_VERSION;
	dev_ctx.basic_attr.power_source = INIT_BASIC_POWER_SOURCE;

	/* ZCL strings are Pascal-style (length byte first) — use the helper. */
	ZB_ZCL_SET_STRING_VAL(dev_ctx.basic_attr.mf_name, INIT_BASIC_MANUF_NAME,
			      ZB_ZCL_STRING_CONST_SIZE(INIT_BASIC_MANUF_NAME));
	ZB_ZCL_SET_STRING_VAL(dev_ctx.basic_attr.model_id, INIT_BASIC_MODEL_ID,
			      ZB_ZCL_STRING_CONST_SIZE(INIT_BASIC_MODEL_ID));

	dev_ctx.identify_attr.identify_time = ZB_ZCL_IDENTIFY_IDENTIFY_TIME_DEFAULT_VALUE;

	dev_ctx.temp_attr.measure_value = ZB_ZCL_ATTR_TEMP_MEASUREMENT_VALUE_UNKNOWN;
	dev_ctx.temp_attr.min_measure_value = TEMP_MEASURE_MIN_VALUE;
	dev_ctx.temp_attr.max_measure_value = TEMP_MEASURE_MAX_VALUE;
	dev_ctx.temp_attr.tolerance = TEMP_MEASURE_TOLERANCE;
}

/* Periodic sensor sample → ZCL attribute update (ZBOSS scheduler callback). */
static void measure(zb_bufid_t bufid)
{
	int16_t t;

	ZVUNUSED(bufid);

	if (zb_sensor_read_temp(&t)) {
		zb_zcl_status_t status = zb_zcl_set_attr_val(
			SENSOR_ENDPOINT, ZB_ZCL_CLUSTER_ID_TEMP_MEASUREMENT,
			ZB_ZCL_CLUSTER_SERVER_ROLE, ZB_ZCL_ATTR_TEMP_MEASUREMENT_VALUE_ID,
			(zb_uint8_t *)&t, ZB_FALSE);
		if (status != ZB_ZCL_STATUS_SUCCESS) {
			LOG_WRN("Set temp attr failed: %d", status);
		} else {
			LOG_INF("Temp: %d.%02d C", t / 100, t % 100);
		}
	}

	ZB_SCHEDULE_APP_ALARM(measure, 0,
			      ZB_MILLISECONDS_TO_BEACON_INTERVAL(
				      CONFIG_APP_MEASUREMENT_INTERVAL_SEC * 1000));
}

/* ZBOSS stack signal handler — handle join/steering, then default behavior. */
void zboss_signal_handler(zb_bufid_t bufid)
{
	zb_zdo_app_signal_hdr_t *sig_hdr = NULL;
	zb_zdo_app_signal_type_t sig = zb_get_app_signal(bufid, &sig_hdr);
	zb_ret_t status = ZB_GET_APP_SIGNAL_STATUS(bufid);

	switch (sig) {
	case ZB_BDB_SIGNAL_DEVICE_REBOOT:
	case ZB_BDB_SIGNAL_STEERING:
		if (status == RET_OK) {
			LOG_INF("Joined Zigbee network");
			/* Must be set after join — join resets it to the default. */
			zb_zdo_pim_set_long_poll_interval(APP_LONG_POLL_INTERVAL_MS);
			ZB_SCHEDULE_APP_ALARM(measure, 0,
					      ZB_MILLISECONDS_TO_BEACON_INTERVAL(1000));
		}
		break;
	default:
		break;
	}

	ZB_ERROR_CHECK(zigbee_default_signal_handler(bufid));

	if (bufid) {
		zb_buf_free(bufid);
	}
}

int main(void)
{
	LOG_INF("=== Hygrometer (Zigbee) ===");

	zb_sensor_init();

	/* Sleepy end device: radio off when idle to save the coin cell. Age out
	 * slowly (parent keeps us as a child for up to 64 min between contacts)
	 * and keep the parent link alive every 30 s. */
	zb_set_ed_timeout(ED_AGING_TIMEOUT_64MIN);
	zb_set_keepalive_timeout(ZB_MILLISECONDS_TO_BEACON_INTERVAL(30000));
	zigbee_configure_sleepy_behavior(true);

	/* Power down unused RAM banks to cut sleep current on the coin cell. */
	if (IS_ENABLED(CONFIG_RAM_POWER_DOWN_LIBRARY)) {
		power_down_unused_ram();
	}

	ZB_AF_REGISTER_DEVICE_CTX(&sensor_ctx);
	app_clusters_attr_init();

	zigbee_enable();

	return 0;
}
