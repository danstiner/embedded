#pragma once

#include "board/board.h"
#include "sensor/sensor_reading.h"

#include <app/clusters/concentration-measurement-server/concentration-measurement-server.h>
#include <platform/CHIPDeviceLayer.h>

struct Identify;

class AppTask
{
      public:
	static AppTask &Instance()
	{
		static AppTask instance;
		return instance;
	};

	CHIP_ERROR StartApp();

#if defined(CONFIG_APP_MATTER_LEAK)
	/* Read the leak sensor and push Boolean State. Must run on the Matter thread
	 * (called both from the periodic update and, via ScheduleWork, the leak ISR). */
	void ReportLeak();
#endif

      private:
	CHIP_ERROR Init();

	void UpdateSensorAttributes();

	static void SensorTimerCallback(k_timer *timer);

	k_timer timer;
	sensor_state sensors;
	uint32_t cycle = 0;

#if defined(CONFIG_APP_MATTER_CO2)
	/* CO2 concentration measurement — NumericMeasurement only, no peak/average */
	chip::app::Clusters::ConcentrationMeasurement::Instance<true, false, false, false, false,
								false>
		co2_instance;

	AppTask()
		: co2_instance(
			  1, chip::app::Clusters::CarbonDioxideConcentrationMeasurement::Id,
			  chip::app::Clusters::ConcentrationMeasurement::MeasurementMediumEnum::
				  kAir,
			  chip::app::Clusters::ConcentrationMeasurement::MeasurementUnitEnum::kPpm)
	{
	}
#else
	AppTask() = default;
#endif
};
