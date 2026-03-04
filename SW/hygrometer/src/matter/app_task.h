#pragma once

#include "board/board.h"
#include "sensor/sensor_reading.h"

#include <platform/CHIPDeviceLayer.h>

struct Identify;

class AppTask {
public:
	static AppTask &Instance()
	{
		static AppTask sAppTask;
		return sAppTask;
	};

	CHIP_ERROR StartApp();

private:
	CHIP_ERROR Init();

	void UpdateSensorAttributes();

	static void SensorTimerCallback(k_timer *timer);
	static void ButtonEventHandler(Nrf::ButtonState state, Nrf::ButtonMask hasChanged);

	k_timer mTimer;
	struct sensor_state mSensors;
	uint32_t mCycle = 0;
};
