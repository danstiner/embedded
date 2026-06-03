/* C++ side of the Zigbee sensor shim (see sensor_shim.h). */

#include "sensor_shim.h"
#include "sensor/sensor_reading.h"

static sensor_state sensors;

void zb_sensor_init(void)
{
	sensor_init(sensors);
}

bool zb_sensor_read_temp(int16_t *temp_cC)
{
	if (sensor_read_sht4x(sensors) == 0 && sensors.sht4x.valid) {
		*temp_cC = sensors.sht4x.temperature_cC;
		return true;
	}
	return false;
}
