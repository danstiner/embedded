/*
 * Resistive water-leak sensor (2026v4 hardware).
 *
 * One electrode is driven high; the other is read back through a pull-down.
 * Water bridging the gap raises the sense line, which both flips the reported
 * state and (via a GPIO interrupt) wakes the main loop for an immediate report.
 */

#include "leak.h"

#include <zephyr/drivers/gpio.h>
#include <zephyr/kernel.h>

#include <zephyr/logging/log.h>
LOG_MODULE_REGISTER(leak, LOG_LEVEL_INF);

#if DT_NODE_HAS_STATUS(DT_NODELABEL(leak_sensor), okay)
#define HAVE_LEAK 1

static const struct gpio_dt_spec leak_drive =
	GPIO_DT_SPEC_GET(DT_NODELABEL(leak_sensor), drive_gpios);
static const struct gpio_dt_spec leak_sense =
	GPIO_DT_SPEC_GET(DT_NODELABEL(leak_sensor), sense_gpios);

static struct gpio_callback leak_cb;
static struct k_sem *leak_wake_sem;

static void leak_isr(const struct device *port, struct gpio_callback *cb, uint32_t pins)
{
	ARG_UNUSED(port);
	ARG_UNUSED(cb);
	ARG_UNUSED(pins);

	if (leak_wake_sem != nullptr) {
		k_sem_give(leak_wake_sem);
	}
}
#endif /* leak_sensor okay */

void leak_init(sensor_state &state, struct k_sem *wake_sem)
{
#if HAVE_LEAK
	if (!gpio_is_ready_dt(&leak_drive) || !gpio_is_ready_dt(&leak_sense)) {
		LOG_WRN("Leak sensor GPIOs not ready");
		return;
	}

	/* Hold the drive electrode active; current only flows when wet. */
	gpio_pin_configure_dt(&leak_drive, GPIO_OUTPUT_ACTIVE);
	gpio_pin_configure_dt(&leak_sense, GPIO_INPUT);

	leak_wake_sem = wake_sem;
	gpio_init_callback(&leak_cb, leak_isr, BIT(leak_sense.pin));
	if (gpio_add_callback(leak_sense.port, &leak_cb) == 0) {
		gpio_pin_interrupt_configure_dt(&leak_sense, GPIO_INT_EDGE_TO_ACTIVE);
	} else {
		LOG_WRN("Leak interrupt setup failed; polling only");
	}

	state.have_leak = true;
	LOG_INF("Leak sensor ready");
#else
	ARG_UNUSED(state);
	ARG_UNUSED(wake_sem);
#endif
}

int leak_read(sensor_state &state)
{
#if HAVE_LEAK
	if (!state.have_leak) {
		return -ENODEV;
	}

	/* Drive is held active; ensure it is set and let the line settle. */
	gpio_pin_set_dt(&leak_drive, 1);
	k_busy_wait(50);

	int v = gpio_pin_get_dt(&leak_sense);
	if (v < 0) {
		LOG_WRN("Leak sense read failed: %d", v);
		state.leak.valid = false;
		return v;
	}

	state.leak.wet = (v == 1);
	state.leak.timestamp = k_uptime_get();
	state.leak.valid = true;
	LOG_INF("Leak: %s", state.leak.wet ? "WET" : "dry");
	return 0;
#else
	ARG_UNUSED(state);
	return -ENOTSUP;
#endif
}
