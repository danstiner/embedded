/*
 * C-callable shim over the C++ sensor_reading / leak modules, so the (C) ZBOSS
 * app can reuse the shared sensors.
 */
#pragma once

#include <stdbool.h>
#include <stdint.h>

struct k_sem;

#ifdef __cplusplus
extern "C" {
#endif

/** Probe sensors once at boot. @p leak_wake is signalled by the leak ISR on a
 *  wet edge (may be NULL to disable wake-on-leak). */
void zb_sensor_init(struct k_sem *leak_wake);

/** Read SHT4x. Returns true on a valid reading and fills temperature (0.01 °C)
 *  and relative humidity (0.01 %). */
bool zb_sensor_read_sht4x(int16_t *temp_cC, uint16_t *hum_cPct);

/** Read the battery. Returns true on a valid reading and fills terminal voltage
 *  (mV) and coarse health (enum battery_health: 0 = OK). */
bool zb_sensor_read_battery(uint16_t *millivolts, uint8_t *health);

/** Sample the water-leak sensor. Returns true on a valid reading and sets @p wet. */
bool zb_sensor_read_leak(bool *wet);

#ifdef __cplusplus
}
#endif
