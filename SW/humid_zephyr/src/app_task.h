#pragma once

#include <lib/core/CHIPError.h>

struct AppTask {
	static CHIP_ERROR StartApp();

private:
	static CHIP_ERROR Init();
	static void MeasureWorkPeriodic(struct k_work *work);
};
