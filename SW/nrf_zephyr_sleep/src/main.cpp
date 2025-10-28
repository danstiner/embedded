#include <zephyr/kernel.h>
#include <zephyr/sys/printk.h>
#include <zephyr/drivers/hwinfo.h>
#include <zephyr/sys/poweroff.h>
#include <zephyr/device.h>
#include <zephyr/pm/device.h>
#include "retained.h"

#if defined(CONFIG_GRTC_WAKEUP_ENABLE)
#include <zephyr/drivers/timer/nrf_grtc_timer.h>
#define WAKEUP_INTERVAL_SEC CONFIG_APP_WAKEUP_INTERVAL_SEC
#endif

int main()
{
	uint32_t reset_cause;
	bool valid_retained;
	int err;
	const struct device *const cons = DEVICE_DT_GET(DT_CHOSEN(zephyr_console));

	/* Small delay for console to initialize */
	k_sleep(K_MSEC(10));

	/* Get reset cause */
	hwinfo_get_reset_cause(&reset_cause);

	/* Check if retained data is valid */
	valid_retained = retained_validate();

	if (valid_retained && (reset_cause & RESET_CLOCK)) {
		printk("=== Wakeup from deep sleep ===\n");
		retained.measurement_count++;
	} else {
		printk("=== Cold boot ===\n");
		/* Initialize retained data */
		memset(&retained, 0, sizeof(retained));
		retained.measurement_count = 0;
		retained.boot_count = 1;
	}

	/* Print the incrementing counter */
	printk("Counter: %u\n", retained.measurement_count);

	/* Update retained data */
	retained_update();

#if defined(CONFIG_GRTC_WAKEUP_ENABLE)
	/* Setup wakeup timer */
	err = z_nrf_grtc_wakeup_prepare(WAKEUP_INTERVAL_SEC * USEC_PER_SEC);
	if (err < 0) {
		printk("Failed to prepare GRTC wakeup (err = %d)\n", err);
		return err;
	}

	/* Enter System OFF (deep sleep) */
	printk("Entering deep sleep for %d seconds...\n", WAKEUP_INTERVAL_SEC);
#else
	printk("Entering deep sleep (no wakeup configured)...\n");
#endif

	/* Suspend console to allow deep sleep */
	err = pm_device_action_run(cons, PM_DEVICE_ACTION_SUSPEND);
	if (err < 0) {
		printk("Could not suspend console (%d)\n", err);
	}

	hwinfo_clear_reset_cause();
	sys_poweroff();

	/* Should never reach here */
	return 0;
}
