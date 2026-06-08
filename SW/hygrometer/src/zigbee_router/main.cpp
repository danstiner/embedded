/*
 * Zigbee router / range-extender firmware (dev-board build).
 *
 * Minimal mains-powered ZBOSS router: it joins the existing Zigbee network and
 * relays traffic for sleepy end devices (the hygrometer) that can't reach the
 * coordinator directly. No sensors, never sleeps. Flash to a dev board placed
 * between the hygrometer and the coordinator; ZBOSS/ZHA handle the routing, so the
 * hygrometer firmware is unchanged.
 *
 * C++ like the other variants — the ZBOSS public headers lack their own extern "C"
 * guards, so the includes below are wrapped to keep C linkage for libzboss.a.
 */

#include <zephyr/kernel.h>
#include <zephyr/logging/log.h>

/* ZBOSS / ncs-zigbee public headers have no extern "C" guards of their own. */
extern "C" {
#include <zboss_api.h>
#include <zboss_api_addons.h>
#include <zigbee/zigbee_error_handler.h>
#include <zigbee/zigbee_app_utils.h>
#include <zb_nrf_platform.h>
#include "zb_range_extender.h"
}

LOG_MODULE_REGISTER(app, LOG_LEVEL_INF);

/* Endpoint hosting the Basic + Identify clusters of the range-extender device. */
#define ROUTER_ENDPOINT 10

/* Mains/USB powered. */
#define INIT_BASIC_POWER_SOURCE ZB_ZCL_BASIC_POWER_SOURCE_DC_SOURCE

/* Shown as manufacturer/model in ZHA so the extender is easy to spot. */
#define INIT_BASIC_MANUF_NAME "Barry's Boards"
#define INIT_BASIC_MODEL_ID   "Range Extender"

/* ZCL attribute storage. */
struct zb_device_ctx {
	zb_zcl_basic_attrs_ext_t basic_attr;
	zb_zcl_identify_attrs_t identify_attr;
};
static struct zb_device_ctx dev_ctx;

ZB_ZCL_DECLARE_IDENTIFY_ATTRIB_LIST(identify_attr_list, &dev_ctx.identify_attr.identify_time);

/* Extended Basic list so we can advertise manufacturer/model names. */
ZB_ZCL_DECLARE_BASIC_ATTRIB_LIST_EXT(
	basic_attr_list, &dev_ctx.basic_attr.zcl_version, &dev_ctx.basic_attr.app_version,
	&dev_ctx.basic_attr.stack_version, &dev_ctx.basic_attr.hw_version,
	dev_ctx.basic_attr.mf_name, dev_ctx.basic_attr.model_id, dev_ctx.basic_attr.date_code,
	&dev_ctx.basic_attr.power_source, dev_ctx.basic_attr.location_id, &dev_ctx.basic_attr.ph_env,
	dev_ctx.basic_attr.sw_ver);

/* ZBOSS Range Extender device (0x0008): Basic + Identify, router role. */
ZB_DECLARE_RANGE_EXTENDER_CLUSTER_LIST(router_clusters, basic_attr_list, identify_attr_list);
ZB_DECLARE_RANGE_EXTENDER_EP(router_ep, ROUTER_ENDPOINT, router_clusters);
ZBOSS_DECLARE_DEVICE_CTX_1_EP(router_ctx, router_ep);

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
}

/* ZBOSS stack signal handler — log join, then default behavior (which drives BDB
 * network steering to join an open network on first boot). */
void zboss_signal_handler(zb_bufid_t bufid)
{
	zb_zdo_app_signal_hdr_t *sig_hdr = NULL;
	zb_zdo_app_signal_type_t sig = zb_get_app_signal(bufid, &sig_hdr);
	zb_ret_t status = ZB_GET_APP_SIGNAL_STATUS(bufid);

	switch (sig) {
	case ZB_BDB_SIGNAL_DEVICE_REBOOT:
	case ZB_BDB_SIGNAL_STEERING:
		if (status == RET_OK) {
			LOG_INF("Router joined Zigbee network");
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
	LOG_INF("=== Zigbee Range Extender ===");

	ZB_AF_REGISTER_DEVICE_CTX(&router_ctx);
	app_clusters_attr_init();

	zigbee_enable();

	return 0;
}
