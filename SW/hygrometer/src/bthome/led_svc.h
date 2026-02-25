#pragma once

#include <zephyr/drivers/gpio.h>

/**
 * Initialize the LED GATT service.
 * @param led GPIO spec for the LED to control.
 */
void led_svc_init(const struct gpio_dt_spec *led);
