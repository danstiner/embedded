#pragma once

#include "board/board.h"
#include "sensor/sensor_reading.h"

#include <app/clusters/concentration-measurement-server/concentration-measurement-server.h>
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

	/* CO2 concentration measurement — NumericMeasurement only, no peak/average */
	chip::app::Clusters::ConcentrationMeasurement::Instance<true, false, false, false, false, false>
		mCo2Instance;

	AppTask()
		: mCo2Instance(1, chip::app::Clusters::CarbonDioxideConcentrationMeasurement::Id,
			       chip::app::Clusters::ConcentrationMeasurement::MeasurementMediumEnum::kAir,
			       chip::app::Clusters::ConcentrationMeasurement::MeasurementUnitEnum::kPpm)
	{
	}
};
