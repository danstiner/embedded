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

#if defined(CONFIG_APP_MATTER_CO2)
	/* Kick off a CO2 forced recalibration (Mode Select -> Recalibrate). Called on
	 * the Matter thread; the work itself runs off a dedicated work queue. */
	void RequestCo2Recalibration();
	/* Kick off a CO2 sensor factory reset (Mode Select -> Factory Reset). */
	void RequestCo2FactoryReset();
	/* True while the firmware is reflecting sensor state into CurrentMode; the Mode
	 * Select pre/post attribute callbacks ignore those self-writes. */
	static bool IsCo2ModeReflecting() { return sCo2ModeReflecting; }
#endif

      private:
	CHIP_ERROR Init();

#if defined(CONFIG_APP_MATTER_CO2)
	/* Recalibration completion callback (runs on the sensor work-queue thread).
	 * CurrentMode is driven by ReflectCo2Mode(); this just logs the result. */
	static void Co2RecalibrationDone(int result);
	/* Factory-reset completion callback; logs the result. */
	static void Co2FactoryResetDone(int result);
	/* Mirror the sensor's CO2 maintenance state into Mode Select CurrentMode. Runs on
	 * the Matter thread each measurement cycle; writes only on change. */
	void ReflectCo2Mode();
	static bool sCo2ModeReflecting;
#endif

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
