#pragma once

#include "sensor_reading.h"

#include <zephyr/kernel.h>

/** Configure the leak sensor (drive GPIO, sense GPIO + SAADC channel) and a
 *  wake-on-leak interrupt.
 *
 *  Holds the drive electrode active while dry — the gap is open so no current
 *  flows — and arms a GPIO edge interrupt on the sense line: a strong
 *  (low-resistance) leak gives @p wake_sem so the main loop wakes and reports
 *  immediately. Weak (high-resistance) leaks are caught by leak_read()'s ADC
 *  sample instead. Sets state.have_leak.
 *
 *  @param wake_sem  Semaphore the ISR signals on a rising (wet) edge. May be
 *                   nullptr to disable the wake behaviour.
 */
void leak_init(sensor_state &state, struct k_sem *wake_sem);

/** Sample the leak sensor: pulse the drive, take one SAADC reading of the sense
 *  divider, and report WET when it is at/above CONFIG_APP_LEAK_THRESHOLD_MV.
 *  Updates state.leak. To limit electrode corrosion the drive is held active
 *  (edge interrupt armed) only while dry; once wet it is parked low between
 *  reads and re-armed when a later read comes back dry. Returns 0 on success,
 *  negative errno. */
int leak_read(sensor_state &state);
