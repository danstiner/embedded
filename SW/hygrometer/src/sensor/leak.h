#pragma once

#include "sensor_reading.h"

#include <zephyr/kernel.h>

/** Configure the leak sensor GPIOs and a wake-on-leak interrupt.
 *
 *  Energises the drive electrode and watches the sense line. When water bridges
 *  the electrodes the sense line goes active and the interrupt gives @p wake_sem
 *  so the main loop can wake and report immediately. Sets state.have_leak.
 *
 *  @param wake_sem  Semaphore the ISR signals on a rising (wet) edge. May be
 *                   nullptr to disable the wake behaviour.
 */
void leak_init(sensor_state &state, struct k_sem *wake_sem);

/** Sample the leak sensor: settle the drive electrode, read the sense line,
 *  store the result in state.leak. Returns 0 on success, negative errno. */
int leak_read(sensor_state &state);
