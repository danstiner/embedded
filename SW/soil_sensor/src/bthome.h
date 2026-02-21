#ifndef BTHOME_H_
#define BTHOME_H_

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

/* BTHome v2 constants */
#define BTHOME_UUID        0xFCD2
#define BTHOME_DEVICE_INFO 0x40 /* Unencrypted, BTHome v2 */

/* BTHome object IDs */
#define BTHOME_OBJ_MOISTURE 0x14 /* uint16, factor 0.01 % */
#define BTHOME_OBJ_VOLTAGE  0x0C /* uint16, factor 0.001 V */

/* Full service data layout (object IDs must be in ascending order per BTHome v2):
 * [0-1] UUID 0xFCD2 (little-endian)
 * [2]   Device info: 0x40 (BTHome v2, unencrypted)
 * [3]   Object ID: voltage (0x0C)
 * [4-5] Voltage value (uint16 LE, factor 0.001 V)
 * [6]   Object ID: moisture (0x14)
 * [7-8] Moisture value (uint16 LE, factor 0.01 %)
 */
#define SERVICE_DATA_MAX 9

static uint8_t service_data[SERVICE_DATA_MAX];
static size_t service_data_len;

typedef struct {
	uint16_t value;
	bool is_some;
} opt_u16;

static inline opt_u16 opt_u16_none()
{
	return (opt_u16){.value = 0, .is_some = false};
}

static inline opt_u16 opt_u16_some(uint16_t value)
{
	return (opt_u16){.value = value, .is_some = true};
}

static void bthome_update_service_data(opt_u16 moisture, opt_u16 voltage)
{
	size_t idx = 0;

	/* UUID (little-endian) */
	service_data[idx++] = (uint8_t)(BTHOME_UUID & 0xFF);
	service_data[idx++] = (uint8_t)(BTHOME_UUID >> 8);
	/* Device info */
	service_data[idx++] = BTHOME_DEVICE_INFO;

	if (voltage.is_some) {
		service_data[idx++] = BTHOME_OBJ_VOLTAGE;
		service_data[idx++] = (uint8_t)(voltage.value & 0xFF);
		service_data[idx++] = (uint8_t)((voltage.value >> 8) & 0xFF);
	}

	if (moisture.is_some) {
		service_data[idx++] = BTHOME_OBJ_MOISTURE;
		service_data[idx++] = (uint8_t)(moisture.value & 0xFF);
		service_data[idx++] = (uint8_t)((moisture.value >> 8) & 0xFF);
	}

	service_data_len = idx;
}

#endif /* BTHOME_H_ */
