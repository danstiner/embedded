/*
 * nRF54 Soil Moisture Sensor - Matter Application Task
 */

#pragma once

#include <lib/core/CHIPError.h>

class AppTask {
public:
	static AppTask &Instance()
	{
		static AppTask sAppTask;
		return sAppTask;
	}

	CHIP_ERROR StartApp();

private:
	CHIP_ERROR Init();
};
