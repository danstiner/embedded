#include "sht4x.h"

#include <zephyr/drivers/sensor/sht4x.h>
#include <zephyr/drivers/sensor.h>
#include <zephyr/logging/log.h>

LOG_MODULE_REGISTER(sht4x, CONFIG_CHIP_APP_LOG_LEVEL);

#if !DT_HAS_COMPAT_STATUS_OKAY(sensirion_sht4x)
#error "No sensirion,sht4x compatible node found in the device tree"
#endif

CHIP_ERROR Sht4x::Init()
{
	CHIP_ERROR err = CHIP_NO_ERROR;

	LOG_DBG("Initialize sensirion_sht4x");
	
	sht = DEVICE_DT_GET_ANY(sensirion_sht4x);

    if (!device_is_ready(sht))
    {
		// TODO handle failure more gracefully
        return CHIP_NO_ERROR;
    }


#if APP_SHT4X_USE_HEATER
	struct sensor_value heater_p;
	struct sensor_value heater_d;

	heater_p.val1 = CONFIG_SHT4X_HEATER_PULSE_POWER;
	heater_d.val1 = !!CONFIG_SHT4X_HEATER_PULSE_DURATION_LONG;
	sensor_attr_set(sht, SENSOR_CHAN_ALL, SENSOR_ATTR_SHT4X_HEATER_POWER, &heater_p);
	sensor_attr_set(sht, SENSOR_CHAN_ALL, SENSOR_ATTR_SHT4X_HEATER_DURATION, &heater_d);
#endif

	return err;
}

bool Sht4x::Ready()
{
	return device_is_ready(sht);
}

bool Sht4x::Read(int16_t &temperature, uint16_t &humidity)
{
	struct sensor_value temp, hum;
	int rc;

	rc = sensor_sample_fetch(sht);
	if (rc != 0) {
		LOG_ERR("Failed to fetch sample from SHT4X: %d", rc);
		return false;
	}

	rc = sensor_channel_get(sht, SENSOR_CHAN_AMBIENT_TEMP, &temp);
	if (rc != 0) {
		LOG_ERR("Failed to read SHT4X temperature: %d", rc);
		return false;
	}

	rc = sensor_channel_get(sht, SENSOR_CHAN_HUMIDITY, &hum);
	if (rc != 0) {
		LOG_ERR("Failed to read SHT4X humidity: %d", rc);
		return false;
	}

#if CONFIG_SHT4X_USE_HEATER
		/*
		 * Conditions in which it makes sense to activate the heater
		 * are application/environment specific.
		 *
		 * The heater should not be used above SHT4X_HEATER_MAX_TEMP (65 °C)
		 * as stated in the datasheet.
		 *
		 * The temperature data will not be updated here for obvious reasons.
		 **/
		if (hum.val1 > CONFIG_SHT4X_HEATER_HUMIDITY_THRESH &&
		    temp.val1 < SHT4X_HEATER_MAX_TEMP_C) {
			LOG_INF("Activating heater");

			if (sht4x_fetch_with_heater(sht)) {
				LOG_ERR("Failed to fetch sample from SHT4X device");
				return false;
			}

			sensor_channel_get(sht, SENSOR_CHAN_HUMIDITY, &hum);
		}
#endif

	// Convert to Matter format
	// Temperature: 0.01°C units
	temperature = (temp.val1 * 100) + (temp.val2 / 10000);

	// Humidity: 0.01% units (0-10000 = 0-100%)
	humidity = (hum.val1 * 100) + (hum.val2 / 10000);

	LOG_INF("Read %d.%02d°C, %d.%02d%% RH",
		temp.val1, temp.val2 / 10000, hum.val1, hum.val2 / 10000);

	return true;
}
