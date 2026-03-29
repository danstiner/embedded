/*
 * AirHub sensor reading module
 *
 * SCD40 (CO2) and SHT4x (temp + humidity), both on I2C20.
 * Sensors use zephyr,deferred-init — sensor_init() waits for SCD40's
 * 1000 ms power-on requirement before calling device_init().
 */

#include "sensor_reading.h"

#include <zephyr/device.h>
#include <zephyr/drivers/sensor.h>
#include <zephyr/kernel.h>

#include <zephyr/logging/log.h>
LOG_MODULE_REGISTER(sensor_reading, LOG_LEVEL_INF);

/* ---- Device pointers ---- */
#if DT_NODE_HAS_STATUS(DT_NODELABEL(sht4x), okay)
static const struct device *sht4x_dev = DEVICE_DT_GET(DT_NODELABEL(sht4x));
#endif

#if DT_NODE_HAS_STATUS(DT_NODELABEL(scd40), okay)
static const struct device *scd40_dev = DEVICE_DT_GET(DT_NODELABEL(scd40));
#endif

/* ---- Sensor init ---- */
void sensor_init(sensor_state &state)
{
	memset(&state, 0, sizeof(state));

	/* SCD40 requires 1000 ms after power-on before accepting I2C commands.
	 * Both sensors use zephyr,deferred-init so we wait here first. */
	k_msleep(1200);

#if DT_NODE_HAS_STATUS(DT_NODELABEL(sht4x), okay)
	if (device_is_ready(sht4x_dev)) {
		state.have_sht4x = true;
		LOG_INF("SHT4x ready");
	} else {
		LOG_WRN("SHT4x not ready");
	}
#endif

#if DT_NODE_HAS_STATUS(DT_NODELABEL(scd40), okay)
	device_init(scd40_dev);
	if (device_is_ready(scd40_dev)) {
		state.have_scd40 = true;
		LOG_INF("SCD40 ready — periodic measurement started");
	} else {
		LOG_WRN("SCD40 not ready");
	}
#endif
}

/* ---- Read SHT4x ---- */
int sensor_read_sht4x(sensor_state &state)
{
#if DT_NODE_HAS_STATUS(DT_NODELABEL(sht4x), okay)
	if (!state.have_sht4x) {
		return -ENODEV;
	}

	int ret = sensor_sample_fetch(sht4x_dev);
	if (ret) {
		LOG_ERR("SHT4x fetch failed: %d", ret);
		state.sht4x.valid = false;
		return ret;
	}

	struct sensor_value value;

	sensor_channel_get(sht4x_dev, SENSOR_CHAN_AMBIENT_TEMP, &value);
	state.sht4x.temperature_cC = value.val1 * 100 + value.val2 / 10000;
	LOG_INF("SHT4x: T=%d.%02d°C", value.val1, value.val2 / 10000);

	sensor_channel_get(sht4x_dev, SENSOR_CHAN_HUMIDITY, &value);
	state.sht4x.humidity_cPct = value.val1 * 100 + value.val2 / 10000;
	LOG_INF("SHT4x: RH=%d.%02d%%", value.val1, value.val2 / 10000);

	state.sht4x.timestamp = k_uptime_get();
	state.sht4x.valid = true;
	return 0;
#else
	return -ENOTSUP;
#endif
}

/* ---- Read SCD40 ---- */
int sensor_read_scd40(sensor_state &state)
{
#if DT_NODE_HAS_STATUS(DT_NODELABEL(scd40), okay)
	if (!state.have_scd40) {
		return -ENODEV;
	}

	/* In periodic mode, returns 0 without updating data if not ready yet.
	 * This can happen on the very first call after boot (<5s after init). */
	int ret = sensor_sample_fetch(scd40_dev);
	if (ret) {
		LOG_ERR("SCD40 fetch failed: %d", ret);
		state.scd40.valid = false;
		return ret;
	}

	struct sensor_value co2_val;
	sensor_channel_get(scd40_dev, SENSOR_CHAN_CO2, &co2_val);

	/* CO2 == 0 means no measurement was ready yet (fresh boot) */
	if (co2_val.val1 == 0) {
		LOG_DBG("SCD40: no measurement ready yet");
		state.scd40.valid = false;
		return -EAGAIN;
	}

	state.scd40.co2_ppm = (uint16_t)co2_val.val1;
	LOG_INF("SCD40: CO2=%u ppm", state.scd40.co2_ppm);

	state.scd40.timestamp = k_uptime_get();
	state.scd40.valid = true;
	return 0;
#else
	return -ENOTSUP;
#endif
}
