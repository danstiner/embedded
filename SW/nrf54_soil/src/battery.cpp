/*
 * Battery Monitoring Implementation
 */

#include "battery.h"
#include <zephyr/drivers/adc.h>
#include <zephyr/logging/log.h>

LOG_MODULE_REGISTER(battery, LOG_LEVEL_INF);

/* Device tree node for voltage divider */
#define VBATT DT_PATH(vbatt)

/* Get ADC spec and voltage divider properties from device tree */
static const struct adc_dt_spec adc_spec = ADC_DT_SPEC_GET(VBATT);
static const uint32_t full_ohms = DT_PROP(VBATT, full_ohms);
static const uint32_t output_ohms = DT_PROP(VBATT, output_ohms);

static int16_t adc_sample_buffer;
static struct adc_sequence sequence = {
	.buffer = &adc_sample_buffer,
	.buffer_size = sizeof(adc_sample_buffer),
	.calibrate = true,  /* Enable ADC calibration for accuracy */
};

static int32_t last_voltage_mv = 0;

int battery_init(void)
{
	int ret;

	if (!adc_is_ready_dt(&adc_spec)) {
		LOG_ERR("ADC device not ready");
		return -ENODEV;
	}

	ret = adc_channel_setup_dt(&adc_spec);
	if (ret < 0) {
		LOG_ERR("Failed to setup ADC channel: %d", ret);
		return ret;
	}

	/* Initialize ADC sequence from device tree */
	ret = adc_sequence_init_dt(&adc_spec, &sequence);
	if (ret < 0) {
		LOG_ERR("Failed to initialize ADC sequence: %d", ret);
		return ret;
	}

	LOG_INF("Battery monitoring initialized");
	LOG_INF("  ADC resolution: %d bits", sequence.resolution);
	LOG_INF("  Voltage divider: %u ohm / %u ohm", full_ohms, output_ohms);

	/* Perform initial reading */
	ret = battery_read_voltage(&last_voltage_mv);
	if (ret == 0) {
		LOG_INF("  Initial voltage: %d mV", last_voltage_mv);
	}

	return 0;
}

int battery_read_voltage(int32_t *voltage_mv)
{
	int ret;
	int32_t adc_value_mv;

	if (!voltage_mv) {
		return -EINVAL;
	}

	/* Read ADC */
	ret = adc_read_dt(&adc_spec, &sequence);
	if (ret < 0) {
		LOG_ERR("ADC read failed: %d", ret);
		return ret;
	}

	/* Convert raw ADC value to millivolts at ADC pin
	 * This accounts for gain and reference voltage automatically */
	adc_value_mv = (int32_t)adc_sample_buffer;
	ret = adc_raw_to_millivolts_dt(&adc_spec, &adc_value_mv);
	if (ret < 0) {
		LOG_ERR("ADC conversion failed: %d", ret);
		return ret;
	}

	/* Apply voltage divider ratio to get actual battery voltage
	 * Use 64-bit intermediate to prevent overflow */
	*voltage_mv = (int32_t)((int64_t)adc_value_mv * full_ohms / output_ohms);

	last_voltage_mv = *voltage_mv;

	LOG_DBG("ADC sample: %d, ADC voltage: %d mV, Battery voltage: %d mV",
		adc_sample_buffer, adc_value_mv, *voltage_mv);

	return 0;
}

enum battery_state battery_get_state(void)
{
	if (last_voltage_mv == 0) {
		/* No reading yet */
		return BATTERY_STATE_UNKNOWN;
	}

	if (last_voltage_mv < BATTERY_VOLTAGE_CRITICAL) {
		return BATTERY_STATE_CRITICAL;
	} else if (last_voltage_mv < BATTERY_VOLTAGE_LOW) {
		return BATTERY_STATE_LOW;
	} else if (last_voltage_mv < BATTERY_VOLTAGE_GOOD) {
		return BATTERY_STATE_GOOD;
	} else {
		return BATTERY_STATE_FULL;
	}
}

uint8_t battery_get_percentage(void)
{
	int32_t voltage = last_voltage_mv;

	/* Simple linear approximation for Li-ion battery:
	 * 4.2V = 100%
	 * 3.7V = 50%
	 * 3.0V = 5%
	 * 2.7V = 0%
	 */

	if (voltage >= BATTERY_VOLTAGE_FULL) {
		return 100;
	} else if (voltage <= BATTERY_VOLTAGE_CRITICAL) {
		return 0;
	}

	/* Linear interpolation between critical and full */
	int32_t range = BATTERY_VOLTAGE_FULL - BATTERY_VOLTAGE_CRITICAL;
	int32_t offset = voltage - BATTERY_VOLTAGE_CRITICAL;

	return (uint8_t)((offset * 100) / range);
}

bool battery_is_critical(void)
{
	return (battery_get_state() == BATTERY_STATE_CRITICAL);
}
