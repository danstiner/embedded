/* C++ side of the Zigbee sensor shim (see sensor_shim.h). */

#include "sensor_shim.h"

#include <zephyr/kernel.h> /* IS_ENABLED, ARG_UNUSED, struct k_sem */

#include "sensor/sensor_reading.h"
#if IS_ENABLED(CONFIG_APP_LEAK_SENSOR)
#include "sensor/leak.h"
#endif

static sensor_state sensors;

void zb_sensor_init(struct k_sem *leak_wake)
{
	sensor_init(sensors);
#if IS_ENABLED(CONFIG_APP_LEAK_SENSOR)
	leak_init(sensors, leak_wake);
#else
	ARG_UNUSED(leak_wake);
#endif
}

bool zb_sensor_read_sht4x(int16_t *temp_cC, uint16_t *hum_cPct)
{
	if (sensor_read_sht4x(sensors) == 0 && sensors.sht4x.valid) {
		*temp_cC = sensors.sht4x.temperature_cC;
		*hum_cPct = sensors.sht4x.humidity_cPct;
		return true;
	}
	return false;
}

bool zb_sensor_read_battery(uint16_t *millivolts, uint8_t *health)
{
	sensor_read_battery(sensors);
	if (sensors.battery.valid) {
		*millivolts = sensors.battery.millivolts;
		*health = static_cast<uint8_t>(sensors.battery.health);
		return true;
	}
	return false;
}

bool zb_sensor_read_leak(bool *wet)
{
#if IS_ENABLED(CONFIG_APP_LEAK_SENSOR)
	if (leak_read(sensors) == 0 && sensors.leak.valid) {
		*wet = sensors.leak.wet;
		return true;
	}
#else
	ARG_UNUSED(wet);
#endif
	return false;
}
