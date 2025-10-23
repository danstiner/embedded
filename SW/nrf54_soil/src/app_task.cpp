/*
 * nRF54 Soil Moisture Sensor - Matter Application Task
 */

#include "app_task.h"

#include "lib/core/CHIPError.h"
#include "lib/support/CodeUtils.h"

#include <zephyr/kernel.h>
#include <zephyr/logging/log.h>

LOG_MODULE_REGISTER(app_task, CONFIG_CHIP_APP_LOG_LEVEL);

using namespace ::chip;

CHIP_ERROR AppTask::Init()
{
	LOG_INF("AppTask::Init");
	return CHIP_NO_ERROR;
}

CHIP_ERROR AppTask::StartApp()
{
	ReturnErrorOnFailure(Init());

	LOG_INF("Matter application started");

	while (true) {
		k_sleep(K_FOREVER);
	}

	return CHIP_NO_ERROR;
}
