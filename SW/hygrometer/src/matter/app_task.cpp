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

Nrf::Matter::IdentifyCluster identify_cluster(kSensorEndpointId);
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
	sensor_read_cycle(&sensors, cycle++);

	if (sensors.sht4x.valid) {
		Clusters::TemperatureMeasurement::Attributes::MeasuredValue::Set(
			kSensorEndpointId, sensors.sht4x.temperature_cC);
		Clusters::RelativeHumidityMeasurement::Attributes::MeasuredValue::Set(
			kSensorEndpointId, sensors.sht4x.humidity_cPct);
	}

	if (sensors.bme688.valid) {
		Clusters::PressureMeasurement::Attributes::MeasuredValue::Set(
			kSensorEndpointId, sensors.bme688.pressure_kPa);
	}

	if (sensors.stcc4.valid) {
		co2_instance.SetMeasuredValue(
			DataModel::MakeNullable(static_cast<float>(sensors.stcc4.co2_ppm)));
	}

	/* Battery is read above by sensor_read_cycle().
	 * TODO (deferred Matter pass): expose battery via the Power Source cluster
	 * (0x002F). Map sensors.battery.health -> BatChargeLevel (OK/Warning/Critical)
	 * — the coarse health is the right fit for the flat CR2 curve — and optionally
	 * sensors.battery.millivolts -> BatVoltage. Requires adding the cluster to
	 * hygrometer.zap and regenerating the data model. The BTHome build already
	 * reports this as battery-low (0x15) + voltage (0x0C). */
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
	ReturnErrorOnFailure(identify_cluster.Init());

	/* Initialize CO2 concentration cluster instance */
	ReturnErrorOnFailure(co2_instance.Init());
	co2_instance.SetMinMeasuredValue(MakeNullable(0.0f));
	co2_instance.SetMaxMeasuredValue(MakeNullable(40000.0f));

	/* Initialize sensors */
	sensor_init(&sensors);
	sensor_fuel_gauge_init();

	return Nrf::Matter::StartServer();
}

CHIP_ERROR AppTask::StartApp()
{
	ReturnErrorOnFailure(Init());

	uint32_t intervalMs = CONFIG_APP_MEASUREMENT_INTERVAL_SEC * 1000;
	k_timer_init(&timer, AppTask::SensorTimerCallback, nullptr);
	k_timer_user_data_set(&timer, this);
	k_timer_start(&timer, K_MSEC(intervalMs), K_MSEC(intervalMs));

	while (true) {
		Nrf::DispatchNextTask();
	}

	return CHIP_NO_ERROR;
}
