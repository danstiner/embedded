#ifndef BTHOME_H_
#define BTHOME_H_

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

/* BTHome v2 constants */
#define BTHOME_UUID        0xFCD2
#define BTHOME_DEVICE_INFO 0x40 /* Unencrypted, BTHome v2 */

/* BTHome object IDs — must appear in ascending order in payload */
#define BTHOME_OBJ_BATTERY  0x01 /* uint8, 1% */
#define BTHOME_OBJ_TEMP     0x02 /* sint16, 0.01 °C */
#define BTHOME_OBJ_HUMIDITY 0x03 /* uint16, 0.01 % */
#define BTHOME_OBJ_PRESSURE 0x04 /* uint24, 0.01 hPa */
#define BTHOME_OBJ_VOLTAGE  0x0C /* uint16, 0.001 V */
#define BTHOME_OBJ_CO2      0x12 /* uint16, 1 ppm */

/* Max service data: UUID(2) + info(1) + battery%(2) + temp(3) + hum(3) + pressure(4) + co2(3) +
 * voltage(3) = 21 */
#define SERVICE_DATA_MAX 21

static uint8_t service_data[SERVICE_DATA_MAX];
static size_t service_data_len;

typedef struct {
	int16_t value;
	bool is_some;
} opt_i16;

static inline opt_i16 opt_i16_none()
{
	return (opt_i16){.value = 0, .is_some = false};
}

static inline opt_i16 opt_i16_some(int16_t value)
{
	return (opt_i16){.value = value, .is_some = true};
}

typedef struct {
	uint8_t value;
	bool is_some;
} opt_u8;

static inline opt_u8 opt_u8_none()
{
	return (opt_u8){.value = 0, .is_some = false};
}

static inline opt_u8 opt_u8_some(uint8_t value)
{
	return (opt_u8){.value = value, .is_some = true};
}

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

typedef struct {
	uint32_t value;
	bool is_some;
} opt_u32;

static inline opt_u32 opt_u32_none()
{
	return (opt_u32){.value = 0, .is_some = false};
}

static inline opt_u32 opt_u32_some(uint32_t value)
{
	return (opt_u32){.value = value, .is_some = true};
}

static void bthome_update_service_data(opt_i16 temperature_mC, opt_u16 humidity_mPct,
				       opt_u32 pressure_Pa, opt_u16 co2_ppm, opt_u8 bat_soc,
				       opt_u16 bat_mV)
{
	size_t idx = 0;

	/* UUID (little-endian) */
	service_data[idx++] = (uint8_t)(BTHOME_UUID & 0xFF);
	service_data[idx++] = (uint8_t)(BTHOME_UUID >> 8);
	/* Device info */
	service_data[idx++] = BTHOME_DEVICE_INFO;

	/* Battery state-of-charge %: uint8, 1% */
	if (bat_soc.is_some) {
		service_data[idx++] = BTHOME_OBJ_BATTERY;
		service_data[idx++] = bat_soc.value;
	}

	/* Temperature: sint16, factor 0.01 °C */
	if (temperature_mC.is_some) {
		service_data[idx++] = BTHOME_OBJ_TEMP;
		service_data[idx++] = (uint8_t)(temperature_mC.value & 0xFF);
		service_data[idx++] = (uint8_t)((temperature_mC.value >> 8) & 0xFF);
	}

	/* Humidity: uint16, factor 0.01 % */
	if (humidity_mPct.is_some) {
		service_data[idx++] = BTHOME_OBJ_HUMIDITY;
		service_data[idx++] = (uint8_t)(humidity_mPct.value & 0xFF);
		service_data[idx++] = (uint8_t)((humidity_mPct.value >> 8) & 0xFF);
	}

	/* Pressure: uint24, factor 0.01 hPa */
	if (pressure_Pa.is_some) {
		service_data[idx++] = BTHOME_OBJ_PRESSURE;
		service_data[idx++] = (uint8_t)(pressure_Pa.value & 0xFF);
		service_data[idx++] = (uint8_t)((pressure_Pa.value >> 8) & 0xFF);
		service_data[idx++] = (uint8_t)((pressure_Pa.value >> 16) & 0xFF);
	}

	/* Battery voltage: uint16, factor 0.001 V */
	if (bat_mV.is_some) {
		service_data[idx++] = BTHOME_OBJ_VOLTAGE;
		service_data[idx++] = (uint8_t)(bat_mV.value & 0xFF);
		service_data[idx++] = (uint8_t)((bat_mV.value >> 8) & 0xFF);
	}

	/* CO2: uint16, factor 1 ppm */
	if (co2_ppm.is_some) {
		service_data[idx++] = BTHOME_OBJ_CO2;
		service_data[idx++] = (uint8_t)(co2_ppm.value & 0xFF);
		service_data[idx++] = (uint8_t)((co2_ppm.value >> 8) & 0xFF);
	}

	service_data_len = idx;
}

#endif /* BTHOME_H_ */
