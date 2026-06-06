/*
 * Hygrometer firmware — Zigbee (ZBOSS / ncs-zigbee add-on) build.
 *
 * Sleepy end device that reports temperature, humidity, battery and water-leak
 * over Zigbee, reusing the shared sensor_reading / leak modules directly (same
 * sensors as the BTHome/Matter builds). Exposed as a custom endpoint with
 * Temperature/Relative Humidity Measurement, Power Configuration (battery) and
 * IAS Zone (water sensor) clusters.
 *
 * C++ like the other variants. The ZBOSS declaration macros parse fine as C++; the
 * only catch is that the ZBOSS public headers lack their own extern "C" guards, so
 * the includes below are wrapped to keep C linkage for the precompiled libzboss.a.
 */

/* Must precede every ZBOSS include. We hand-roll the endpoint, but still borrow
 * the Temperature Sensor device-ID/version constants from
 * ha/zb_ha_temperature_sensor.h, which only defines them when this is set. */
#define ZB_HA_DEFINE_DEVICE_TEMPERATURE_SENSOR

#include <string.h>

#include <zephyr/kernel.h>
#include <zephyr/logging/log.h>

/* ZBOSS / ncs-zigbee public headers have no extern "C" guards of their own. */
extern "C" {
#include <zboss_api.h>
#include <zboss_api_addons.h>
#include <zigbee/zigbee_error_handler.h>
#include <zigbee/zigbee_app_utils.h>
#include <zb_nrf_platform.h>
#include <ha/zb_ha_temperature_sensor.h>
}

#include <ram_pwrdn.h>

#include "sensor/sensor_reading.h"
#if IS_ENABLED(CONFIG_APP_LEAK_SENSOR)
#include "sensor/leak.h"
#endif

LOG_MODULE_REGISTER(app, LOG_LEVEL_INF);

/* Shared sensor state, owned by this app. */
static sensor_state sensors;

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

/* Device-driven attribute reporting to the coordinator (see configure_reporting()).
 * min: never report more often than this; max: heartbeat — report at least this
 * often even if unchanged, so HA never goes stale. Both are Kconfig-tunable. */
#define APP_REPORT_MIN_INTERVAL_SEC CONFIG_APP_ZIGBEE_REPORT_MIN_INTERVAL_SEC
#define APP_REPORT_MAX_INTERVAL_SEC CONFIG_APP_ZIGBEE_REPORT_MAX_INTERVAL_SEC

/* Temperature Measurement defaults (0.01 °C units). */
#define TEMP_MEASURE_MIN_VALUE (-4000) /* -40.00 °C */
#define TEMP_MEASURE_MAX_VALUE (12500) /* 125.00 °C */
#define TEMP_MEASURE_TOLERANCE (50)    /*   0.50 °C */

/* ZCL attribute storage. */
struct zb_device_ctx {
	zb_zcl_basic_attrs_ext_t basic_attr;
	zb_zcl_identify_attrs_t identify_attr;
	zb_zcl_temp_measurement_attrs_t temp_attr;

	/* Relative Humidity Measurement (ZBOSS has no bundled attrs struct). */
	zb_uint16_t humidity_value;
	zb_uint16_t humidity_min;
	zb_uint16_t humidity_max;

	/* Power Configuration (battery). Only Voltage + AlarmState carry real data;
	 * the other EXT attributes are kept "unknown". */
	struct {
		zb_uint8_t voltage; /* 100 mV units */
		zb_uint8_t size;
		zb_uint8_t quantity;
		zb_uint8_t rated_voltage;
		zb_uint8_t alarm_mask;
		zb_uint8_t voltage_min_threshold;
		zb_uint8_t remaining; /* 0xFF = unknown */
		zb_uint8_t threshold1;
		zb_uint8_t threshold2;
		zb_uint8_t threshold3;
		zb_uint8_t percentage_min_threshold;
		zb_uint8_t percentage_threshold1;
		zb_uint8_t percentage_threshold2;
		zb_uint8_t percentage_threshold3;
		zb_uint32_t alarm_state; /* bitmap, set on low battery */
	} battery_attr;

	/* IAS Zone (water sensor). */
	zb_uint8_t zone_state;
	zb_uint16_t zone_type;
	zb_uint16_t zone_status;
	zb_ieee_addr_t ias_cie_address;
	zb_uint16_t cie_short_addr;
	zb_uint8_t cie_ep;
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

ZB_ZCL_DECLARE_REL_HUMIDITY_MEASUREMENT_ATTRIB_LIST(humidity_attr_list, &dev_ctx.humidity_value,
						    &dev_ctx.humidity_min, &dev_ctx.humidity_max);

/* Power Config: declare just BatteryVoltage + BatteryAlarmState by hand. The
 * ZBOSS ..._BATTERY_ATTRIB_LIST_EXT macro mis-pastes its battery-number token
 * (won't compile) and the non-EXT list lacks AlarmState; the per-attribute
 * descriptor macros take an empty battery-number suffix (= battery 1). */
ZB_ZCL_START_DECLARE_ATTRIB_LIST_CLUSTER_REVISION(power_attr_list, ZB_ZCL_POWER_CONFIG)
	ZB_SET_ATTR_DESCR_WITH_ZB_ZCL_ATTR_POWER_CONFIG_BATTERY_VOLTAGE_ID(
		&dev_ctx.battery_attr.voltage, ),
	ZB_SET_ATTR_DESCR_WITH_ZB_ZCL_ATTR_POWER_CONFIG_BATTERY_ALARM_STATE_ID(
		&dev_ctx.battery_attr.alarm_state, ),
ZB_ZCL_FINISH_DECLARE_ATTRIB_LIST;

ZB_ZCL_DECLARE_IAS_ZONE_ATTRIB_LIST(ias_zone_attr_list, &dev_ctx.zone_state, &dev_ctx.zone_type,
				    &dev_ctx.zone_status, &dev_ctx.ias_cie_address,
				    &dev_ctx.cie_short_addr, &dev_ctx.cie_ep);

/* Hand-rolled custom endpoint: no canned HA device bundles temperature +
 * humidity + power config + IAS zone, so declare the cluster list, simple
 * descriptor and endpoint directly. ZHA discovers entities per cluster. */
static zb_zcl_cluster_desc_t sensor_clusters[] = {
	ZB_ZCL_CLUSTER_DESC(ZB_ZCL_CLUSTER_ID_BASIC,
			    ZB_ZCL_ARRAY_SIZE(basic_attr_list, zb_zcl_attr_t), basic_attr_list,
			    ZB_ZCL_CLUSTER_SERVER_ROLE, ZB_ZCL_MANUF_CODE_INVALID),
	ZB_ZCL_CLUSTER_DESC(ZB_ZCL_CLUSTER_ID_IDENTIFY,
			    ZB_ZCL_ARRAY_SIZE(identify_attr_list, zb_zcl_attr_t), identify_attr_list,
			    ZB_ZCL_CLUSTER_SERVER_ROLE, ZB_ZCL_MANUF_CODE_INVALID),
	ZB_ZCL_CLUSTER_DESC(ZB_ZCL_CLUSTER_ID_TEMP_MEASUREMENT,
			    ZB_ZCL_ARRAY_SIZE(temp_attr_list, zb_zcl_attr_t), temp_attr_list,
			    ZB_ZCL_CLUSTER_SERVER_ROLE, ZB_ZCL_MANUF_CODE_INVALID),
	ZB_ZCL_CLUSTER_DESC(ZB_ZCL_CLUSTER_ID_REL_HUMIDITY_MEASUREMENT,
			    ZB_ZCL_ARRAY_SIZE(humidity_attr_list, zb_zcl_attr_t), humidity_attr_list,
			    ZB_ZCL_CLUSTER_SERVER_ROLE, ZB_ZCL_MANUF_CODE_INVALID),
	ZB_ZCL_CLUSTER_DESC(ZB_ZCL_CLUSTER_ID_POWER_CONFIG,
			    ZB_ZCL_ARRAY_SIZE(power_attr_list, zb_zcl_attr_t), power_attr_list,
			    ZB_ZCL_CLUSTER_SERVER_ROLE, ZB_ZCL_MANUF_CODE_INVALID),
	ZB_ZCL_CLUSTER_DESC(ZB_ZCL_CLUSTER_ID_IAS_ZONE,
			    ZB_ZCL_ARRAY_SIZE(ias_zone_attr_list, zb_zcl_attr_t), ias_zone_attr_list,
			    ZB_ZCL_CLUSTER_SERVER_ROLE, ZB_ZCL_MANUF_CODE_INVALID),
};

/* Reporting slots: temperature(1) + humidity(1) + battery voltage + alarm(2) = 4
 * self-configured, plus headroom for ZHA to add its own. (IAS Zone uses the
 * immediate Zone Status Change Notification, not attribute reporting.) */
#define SENSOR_REPORT_ATTR_COUNT 8

/* 6 server clusters, 0 client. The simple-desc macros token-paste their args, so
 * these must be literal numbers (a macro name would not expand into the type). */
ZB_DECLARE_SIMPLE_DESC(6, 0);
ZB_AF_SIMPLE_DESC_TYPE(6, 0) simple_desc_sensor_ep = {
	SENSOR_ENDPOINT,
	ZB_AF_HA_PROFILE_ID,
	ZB_HA_TEMPERATURE_SENSOR_DEVICE_ID,
	ZB_HA_DEVICE_VER_TEMPERATURE_SENSOR,
	0,
	6,
	0,
	{
		ZB_ZCL_CLUSTER_ID_BASIC,
		ZB_ZCL_CLUSTER_ID_IDENTIFY,
		ZB_ZCL_CLUSTER_ID_TEMP_MEASUREMENT,
		ZB_ZCL_CLUSTER_ID_REL_HUMIDITY_MEASUREMENT,
		ZB_ZCL_CLUSTER_ID_POWER_CONFIG,
		ZB_ZCL_CLUSTER_ID_IAS_ZONE,
	},
};

ZBOSS_DEVICE_DECLARE_REPORTING_CTX(reporting_info_sensor_ep, SENSOR_REPORT_ATTR_COUNT);

ZB_AF_DECLARE_ENDPOINT_DESC(sensor_ep, SENSOR_ENDPOINT, ZB_AF_HA_PROFILE_ID, 0, NULL,
			    ZB_ZCL_ARRAY_SIZE(sensor_clusters, zb_zcl_cluster_desc_t),
			    sensor_clusters, (zb_af_simple_desc_1_1_t *)&simple_desc_sensor_ep,
			    SENSOR_REPORT_ATTR_COUNT, reporting_info_sensor_ep, 0, NULL);

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

	dev_ctx.humidity_value = ZB_ZCL_REL_HUMIDITY_MEASUREMENT_VALUE_DEFAULT_VALUE; /* unknown */
	dev_ctx.humidity_min = 0;     /*   0.00 % */
	dev_ctx.humidity_max = 10000; /* 100.00 % */

	dev_ctx.battery_attr.voltage = 0xFF;     /* unknown until first read */
	dev_ctx.battery_attr.size = 0xFF;        /* unknown */
	dev_ctx.battery_attr.quantity = 1;
	dev_ctx.battery_attr.rated_voltage = 30; /* 3.0 V CR2, 100 mV units */
	dev_ctx.battery_attr.remaining = 0xFF;   /* unknown — no percentage reported */
	dev_ctx.battery_attr.alarm_state = 0;

	dev_ctx.zone_state = ZB_ZCL_IAS_ZONE_ZONESTATE_NOT_ENROLLED;
	dev_ctx.zone_type = ZB_ZCL_IAS_ZONE_ZONETYPE_WATER_SENSOR;
	dev_ctx.zone_status = 0;
	memset(dev_ctx.ias_cie_address, 0xFF, sizeof(dev_ctx.ias_cie_address)); /* unset */
	dev_ctx.cie_short_addr = 0xFFFF;
	dev_ctx.cie_ep = 0;
}

/* IAS Zone status update — runs on the ZBOSS stack thread with an out buffer.
 * zb_zcl_ias_zone_set_status() updates the ZoneStatus attribute and, once the
 * device is enrolled, sends a Zone Status Change Notification to the CIE using
 * this buffer; it consumes the buffer on a scheduled send (ZB_TRUE), so we only
 * free it ourselves when nothing was sent. */
static void send_leak_status(zb_bufid_t bufid)
{
#if IS_ENABLED(CONFIG_APP_LEAK_SENSOR)
	if (leak_read(sensors) != 0 || !sensors.leak.valid) {
		if (bufid) {
			zb_buf_free(bufid);
		}
		return;
	}

	zb_uint16_t zone_status = sensors.leak.wet ? ZB_ZCL_IAS_ZONE_ZONE_STATUS_ALARM1 : 0;

	LOG_INF("Leak: %s", sensors.leak.wet ? "WET" : "dry");

	if (zb_zcl_ias_zone_set_status(SENSOR_ENDPOINT, zone_status, 0, bufid) != ZB_TRUE && bufid) {
		zb_buf_free(bufid);
	}
#else
	if (bufid) {
		zb_buf_free(bufid);
	}
#endif
}

#if IS_ENABLED(CONFIG_APP_LEAK_SENSOR)
/* Signalled by the leak ISR (in leak.cpp) on a wet edge. */
static K_SEM_DEFINE(leak_wake_sem, 0, 1);

static void schedule_leak_status(zb_uint8_t param)
{
	ZVUNUSED(param);
	zb_buf_get_out_delayed(send_leak_status);
}

/* The leak ISR can't touch the ZBOSS stack directly. It wakes this thread, which
 * bounces an immediate IAS Zone update onto the stack thread. */
static void leak_monitor(void *a, void *b, void *c)
{
	ARG_UNUSED(a);
	ARG_UNUSED(b);
	ARG_UNUSED(c);

	for (;;) {
		k_sem_take(&leak_wake_sem, K_FOREVER);
		zigbee_schedule_callback(schedule_leak_status, 0);
	}
}
K_THREAD_DEFINE(leak_monitor_tid, 1024, leak_monitor, NULL, NULL, NULL, K_PRIO_PREEMPT(10), 0, 0);
#endif /* CONFIG_APP_LEAK_SENSOR */

/* Periodic sensor sample → ZCL attribute update (ZBOSS scheduler callback). */
static void measure(zb_bufid_t bufid)
{
	ZVUNUSED(bufid);

	if (sensor_read_sht4x(sensors) == 0 && sensors.sht4x.valid) {
		int16_t t = sensors.sht4x.temperature_cC;
		uint16_t rh = sensors.sht4x.humidity_cPct;

		zb_zcl_set_attr_val(SENSOR_ENDPOINT, ZB_ZCL_CLUSTER_ID_TEMP_MEASUREMENT,
				    ZB_ZCL_CLUSTER_SERVER_ROLE, ZB_ZCL_ATTR_TEMP_MEASUREMENT_VALUE_ID,
				    (zb_uint8_t *)&t, ZB_FALSE);
		zb_zcl_set_attr_val(SENSOR_ENDPOINT, ZB_ZCL_CLUSTER_ID_REL_HUMIDITY_MEASUREMENT,
				    ZB_ZCL_CLUSTER_SERVER_ROLE,
				    ZB_ZCL_ATTR_REL_HUMIDITY_MEASUREMENT_VALUE_ID, (zb_uint8_t *)&rh,
				    ZB_FALSE);
		LOG_INF("T=%d.%02d C  RH=%u.%02u%%", t / 100, t % 100, rh / 100, rh % 100);
	}

	if (sensor_read_battery(sensors) == 0 && sensors.battery.valid) {
		uint16_t mv = sensors.battery.millivolts;
		/* health: 0 = OK; anything else (low/critical) trips the alarm. */
		uint8_t health = (uint8_t)sensors.battery.health;
		zb_uint8_t voltage_dV = (zb_uint8_t)(mv / 100); /* 100 mV units */
		zb_uint32_t alarm =
			health ? ZB_ZCL_POWER_CONFIG_BATTERY_ALARM_STATE_SOURCE1_MIN_THRESHOLD : 0;

		zb_zcl_set_attr_val(SENSOR_ENDPOINT, ZB_ZCL_CLUSTER_ID_POWER_CONFIG,
				    ZB_ZCL_CLUSTER_SERVER_ROLE,
				    ZB_ZCL_ATTR_POWER_CONFIG_BATTERY_VOLTAGE_ID, &voltage_dV,
				    ZB_FALSE);
		zb_zcl_set_attr_val(SENSOR_ENDPOINT, ZB_ZCL_CLUSTER_ID_POWER_CONFIG,
				    ZB_ZCL_CLUSTER_SERVER_ROLE,
				    ZB_ZCL_ATTR_POWER_CONFIG_BATTERY_ALARM_STATE_ID,
				    (zb_uint8_t *)&alarm, ZB_FALSE);
		LOG_INF("Battery: %u mV (%s)", mv, health ? "low" : "ok");
	}

	/* Re-sample the leak line each cycle so a dry transition is caught — the ISR
	 * only fires on the wet edge. */
	zb_buf_get_out_delayed(send_leak_status);

	ZB_SCHEDULE_APP_ALARM(measure, 0,
			      ZB_MILLISECONDS_TO_BEACON_INTERVAL(
				      CONFIG_APP_MEASUREMENT_INTERVAL_SEC * 1000));
}

/* Register one device-side reporting slot that sends Report Attributes straight to
 * the coordinator (0x0000) — no binding required, the destination is carried in the
 * reporting info. */
static void report_cfg(zb_uint16_t cluster_id, zb_uint16_t attr_id,
		       union zb_zcl_attr_var_u delta)
{
	zb_zcl_reporting_info_t rep = {0};

	rep.direction = ZB_ZCL_CONFIGURE_REPORTING_SEND_REPORT;
	rep.ep = SENSOR_ENDPOINT;
	rep.cluster_id = cluster_id;
	rep.cluster_role = ZB_ZCL_CLUSTER_SERVER_ROLE;
	rep.attr_id = attr_id;
	/* Must be 0xFFFF for standard (non-manufacturer) attributes, else the attr
	 * lookup in zb_zcl_put_reporting_info fails with RET_NOT_FOUND. */
	rep.manuf_code = ZB_ZCL_NON_MANUFACTURER_SPECIFIC;
	rep.dst.short_addr = 0x0000; /* coordinator */
	rep.dst.endpoint = 1;        /* ZHA coordinator endpoint */
	rep.dst.profile_id = ZB_AF_HA_PROFILE_ID;
	rep.u.send_info.min_interval = APP_REPORT_MIN_INTERVAL_SEC;
	rep.u.send_info.max_interval = APP_REPORT_MAX_INTERVAL_SEC;
	rep.u.send_info.delta = delta;

	zb_ret_t ret = zb_zcl_put_reporting_info(&rep, ZB_TRUE);

	if (ret != RET_OK) {
		LOG_WRN("Reporting cfg cl=0x%04x attr=0x%04x failed: %d", cluster_id, attr_id, ret);
	}
}

/* Configure device-driven reporting so temperature/humidity/battery updates flow to
 * HA without relying on ZHA's Configure Reporting (which is unreliable over a sleepy
 * link). ZHA may still override these. Leak is intentionally excluded — it uses the
 * immediate IAS Zone Zone Status Change Notification. */
static void configure_reporting(void)
{
	/* Reportable-change deltas. One union, set the matching field before each call
	 * (C++ has no C99 compound literals). */
	union zb_zcl_attr_var_u delta;

	delta.s16 = 10; /* 0.1 °C */
	report_cfg(ZB_ZCL_CLUSTER_ID_TEMP_MEASUREMENT, ZB_ZCL_ATTR_TEMP_MEASUREMENT_VALUE_ID, delta);
	delta.u16 = 50; /* 0.5 %RH */
	report_cfg(ZB_ZCL_CLUSTER_ID_REL_HUMIDITY_MEASUREMENT,
		   ZB_ZCL_ATTR_REL_HUMIDITY_MEASUREMENT_VALUE_ID, delta);
	delta.u8 = 1; /* 0.1 V */
	report_cfg(ZB_ZCL_CLUSTER_ID_POWER_CONFIG, ZB_ZCL_ATTR_POWER_CONFIG_BATTERY_VOLTAGE_ID, delta);
	delta.u32 = 0; /* any change */
	report_cfg(ZB_ZCL_CLUSTER_ID_POWER_CONFIG, ZB_ZCL_ATTR_POWER_CONFIG_BATTERY_ALARM_STATE_ID,
		   delta);
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
			/* Commissioned now → switch to sleepy operation (radio off when
			 * idle). Doing this only post-join keeps the join handshake
			 * reliable. */
			zigbee_configure_sleepy_behavior(true);
			/* Must be set after join — join resets it to the default. */
			zb_zdo_pim_set_long_poll_interval(APP_LONG_POLL_INTERVAL_MS);
			/* Drive our own reporting so HA updates without ZHA config. */
			configure_reporting();
			/* Keep a single measurement chain across re-joins: cancel any
			 * stale one before re-arming (else they accumulate). */
			ZB_SCHEDULE_APP_ALARM_CANCEL(measure, ZB_ALARM_ANY_PARAM);
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

int main()
{
	LOG_INF("=== Hygrometer (Zigbee) ===");
	LOG_INF("Reporting: min %us / max %us; measure every %us", APP_REPORT_MIN_INTERVAL_SEC,
		APP_REPORT_MAX_INTERVAL_SEC, CONFIG_APP_MEASUREMENT_INTERVAL_SEC);

	sensor_init(sensors);
#if IS_ENABLED(CONFIG_APP_LEAK_SENSOR)
	leak_init(sensors, &leak_wake_sem);
#endif

	/* End-device aging: ask the parent to keep us as a child for up to 64 min
	 * between contacts. We deliberately do NOT call zb_set_keepalive_timeout():
	 * per the Zigbee R23 add-on known issue KRKNWK-20726, when the parent supports
	 * the keepalive method a SED that sets it floods End-Device Timeout Requests
	 * and churns the link. Instead we rely solely on MAC data polls (long-poll
	 * interval, set post-join in zboss_signal_handler) to refresh our slot in the
	 * parent's child table — 7.68 s poll << 64 min aging. Sleepy behaviour itself
	 * is enabled only *after* we join (see zboss_signal_handler) — commissioning is
	 * far more reliable with the radio on, especially over a weak link. */
	zb_set_ed_timeout(ED_AGING_TIMEOUT_64MIN);

	/* Power down unused RAM banks to cut sleep current on the coin cell. */
	if (IS_ENABLED(CONFIG_RAM_POWER_DOWN_LIBRARY)) {
		power_down_unused_ram();
	}

	ZB_AF_REGISTER_DEVICE_CTX(&sensor_ctx);
	app_clusters_attr_init();

	zigbee_enable();

	return 0;
}
