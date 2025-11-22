#include "app_task.h"

#include <zephyr/kernel.h>
#include <zephyr/logging/log.h>
#include <zephyr/sys/printk.h>

LOG_MODULE_REGISTER(app, CONFIG_CHIP_APP_LOG_LEVEL);

int main()
{
	LOG_INF("Starting...");
	CHIP_ERROR err = AppTask::StartApp();
	LOG_ERR("Exited with code %" CHIP_ERROR_FORMAT, err.Format());
	return err == CHIP_NO_ERROR ? EXIT_SUCCESS : EXIT_FAILURE;
}
