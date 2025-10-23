/*
 * Battery Monitoring Module
 * ADC-based voltage measurement with low battery detection
 */

#ifndef BATTERY_H
#define BATTERY_H

#include <zephyr/kernel.h>
#include <stdint.h>

/* Battery voltage thresholds (in millivolts) */
#define BATTERY_VOLTAGE_CRITICAL    2700    /* Enter deep sleep immediately */
#define BATTERY_VOLTAGE_LOW         3000    /* Warning threshold */
#define BATTERY_VOLTAGE_GOOD        3300    /* Normal operation */
#define BATTERY_VOLTAGE_FULL        4200    /* Fully charged (Li-ion) */

/* Battery state */
enum battery_state {
	BATTERY_STATE_CRITICAL,    /* < 2.7V - shut down */
	BATTERY_STATE_LOW,         /* 2.7V - 3.0V - conserve power */
	BATTERY_STATE_GOOD,        /* 3.0V - 3.3V - normal operation */
	BATTERY_STATE_FULL,        /* > 3.3V - fully charged */
	BATTERY_STATE_UNKNOWN,     /* Not yet measured */
};

/**
 * Initialize battery monitoring subsystem
 * @return 0 on success, negative errno on failure
 */
int battery_init(void);

/**
 * Read current battery voltage in millivolts
 * @param voltage_mv Pointer to store voltage reading
 * @return 0 on success, negative errno on failure
 */
int battery_read_voltage(int32_t *voltage_mv);

/**
 * Get current battery state based on voltage
 * @return Battery state enum
 */
enum battery_state battery_get_state(void);

/**
 * Get battery percentage (0-100%)
 * Based on voltage curve for Li-ion battery
 * @return Battery percentage
 */
uint8_t battery_get_percentage(void);

/**
 * Check if battery is critically low and needs shutdown
 * @return true if critical, false otherwise
 */
bool battery_is_critical(void);

#endif /* BATTERY_H */
