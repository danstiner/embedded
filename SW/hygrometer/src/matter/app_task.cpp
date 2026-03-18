#include "app_task.h"

#include "app/matter_init.h"
#include "app/task_executor.h"
#include "board/board.h"
#include "clusters/identify.h"
#include "lib/core/CHIPError.h"

#include <app-common/zap-generated/attributes/Accessors.h>
#include <app/data-model/Nullable.h>

#include <zephyr/logging/log.h>

LOG_MODULE_DECLARE(app, CONFIG_CHIP_APP_LOG_LEVEL);

using namespace ::chip;
using namespace ::chip::app;
using namespace ::chip::app::DataModel;
using namespace ::chip::DeviceLayer;

namespace
{
constexpr chip::EndpointId kSensorEndpointId = 1;

Nrf::Matter::IdentifyCluster sIdentifyCluster(kSensorEndpointId);
} /* namespace */

void AppTask::ButtonEventHandler(Nrf::ButtonState state, Nrf::ButtonMask hasChanged)
{
	/* No physical buttons on hygrometer — placeholder for future SHPHLD button */
}

void AppTask::SensorTimerCallback(k_timer *timer)
{
	if (!timer || !timer->user_data) {
		return;
	}

	DeviceLayer::PlatformMgr().ScheduleWork(
		[](intptr_t p) { AppTask::Instance().UpdateSensorAttributes(); },
		reinterpret_cast<intptr_t>(timer->user_data));
}

void AppTask::UpdateSensorAttributes()
{
	/* 1. SHT45 — every cycle */
	if (sensor_read_sht45(&mSensors) == 0) {
		Clusters::TemperatureMeasurement::Attributes::MeasuredValue::Set(
			kSensorEndpointId, mSensors.sht45.temperature_cC);
		Clusters::RelativeHumidityMeasurement::Attributes::MeasuredValue::Set(
			kSensorEndpointId, mSensors.sht45.humidity_cPct);
	}

	/* 2. BME688 pressure — independent cadence */
	bool pressure_cycle = (mCycle % CONFIG_APP_PRESSURE_INTERVAL_DIVISOR) == 0;
	if (pressure_cycle) {
		sensor_read_bme688(&mSensors);
	}

	/* 3. STCC4 CO2 — expensive cycle cadence */
	bool co2_cycle = (mCycle++ % CONFIG_APP_CO2_INTERVAL_DIVISOR) == 0;
	if (co2_cycle) {
		if (sensor_read_stcc4(&mSensors) == 0) {
			mCo2Instance.SetMeasuredValue(DataModel::MakeNullable(
				static_cast<float>(mSensors.stcc4.co2_ppm)));
		}
	}

	if (mSensors.bme688.valid) {
		Clusters::PressureMeasurement::Attributes::MeasuredValue::Set(
			kSensorEndpointId, mSensors.bme688.pressure_kPa);
	}

	/* 4. Battery */
	sensor_read_battery(&mSensors);
}

CHIP_ERROR AppTask::Init()
{
	/* Initialize Matter stack */
	ReturnErrorOnFailure(Nrf::Matter::PrepareServer());

	if (!Nrf::GetBoard().Init(ButtonEventHandler)) {
		LOG_ERR("User interface initialization failed.");
		return CHIP_ERROR_INCORRECT_STATE;
	}

	ReturnErrorOnFailure(
		Nrf::Matter::RegisterEventHandler(Nrf::Board::DefaultMatterEventHandler, 0));
	ReturnErrorOnFailure(sIdentifyCluster.Init());

	/* Initialize CO2 concentration cluster instance */
	ReturnErrorOnFailure(mCo2Instance.Init());
	mCo2Instance.SetMinMeasuredValue(MakeNullable(0.0f));
	mCo2Instance.SetMaxMeasuredValue(MakeNullable(40000.0f));

	/* Initialize sensors */
	sensor_init(&mSensors);
	sensor_fuel_gauge_init();

	return Nrf::Matter::StartServer();
}

CHIP_ERROR AppTask::StartApp()
{
	ReturnErrorOnFailure(Init());

	uint32_t intervalMs = CONFIG_APP_MEASUREMENT_INTERVAL_SEC * 1000;
	k_timer_init(&mTimer, AppTask::SensorTimerCallback, nullptr);
	k_timer_user_data_set(&mTimer, this);
	k_timer_start(&mTimer, K_MSEC(intervalMs), K_MSEC(intervalMs));

	while (true) {
		Nrf::DispatchNextTask();
	}

	return CHIP_NO_ERROR;
}
