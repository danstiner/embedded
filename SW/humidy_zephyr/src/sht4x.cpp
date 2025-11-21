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

	sht = DEVICE_DT_GET_ANY(sensirion_sht4x);

    if (!device_is_ready(sht))
    {
        return CHIP_ERROR_INTERNAL;
    }

#if CONFIG_APP_SHT4X_HEATER
	struct sensor_value heater_p;
	struct sensor_value heater_d;

	heater_p.val1 = CONFIG_APP_HEATER_PULSE_POWER;
	heater_d.val1 = !!CONFIG_APP_HEATER_PULSE_DURATION_LONG;
	sensor_attr_set(sht, SENSOR_CHAN_ALL, SENSOR_ATTR_SHT4X_HEATER_POWER, &heater_p);
	sensor_attr_set(sht, SENSOR_CHAN_ALL, SENSOR_ATTR_SHT4X_HEATER_DURATION, &heater_d);
#endif

	return err;
}

void Sht4x::Read()
{
    struct sensor_value temp, hum;

    if (sensor_sample_fetch(sht)) {
        printf("Failed to fetch sample from SHT4X device\n");
        return;
    }

    sensor_channel_get(sht, SENSOR_CHAN_AMBIENT_TEMP, &temp);
    sensor_channel_get(sht, SENSOR_CHAN_HUMIDITY, &hum);

#if CONFIG_APP_USE_HEATER
    /*
     * Conditions in which it makes sense to activate the heater
     * are application/environment specific.
     *
     * The heater should not be used above SHT4X_HEATER_MAX_TEMP (65 °C)
     * as stated in the datasheet.
     *
     * The temperature data will not be updated here for obvious reasons.
     **/
    if (hum.val1 > CONFIG_APP_HEATER_HUMIDITY_THRESH &&
        temp.val1 < SHT4X_HEATER_MAX_TEMP) {
        printf("Activating heater.\n");

        if (sht4x_fetch_with_heater(sht)) {
            printf("Failed to fetch sample from SHT4X device\n");
            return 0;
        }

        sensor_channel_get(sht, SENSOR_CHAN_HUMIDITY, &hum);
    }
#endif

    LOG_INF("SHT4X: %.2f Temp. [C] ; %0.2f RH [%%]\n", sensor_value_to_double(&temp),
            sensor_value_to_double(&hum));
}
