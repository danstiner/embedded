/*
 * C-callable shim over the C++ sensor_reading module, so the (C) ZBOSS app can
 * reuse the shared sensors.
 */
#pragma once

#include <stdbool.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/** Probe sensors once at boot. */
void zb_sensor_init(void);

/** Read temperature in 0.01 °C units. Returns true on a valid reading. */
bool zb_sensor_read_temp(int16_t *temp_cC);

#ifdef __cplusplus
}
#endif
