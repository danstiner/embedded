#include "app_task.h"

#include "sensor/leak.h"

#include "app/matter_init.h"
#include "app/task_executor.h"
#include "board/board.h"
#include "clusters/identify.h"
#include "lib/core/CHIPError.h"

#include <app-common/zap-generated/attributes/Accessors.h>
#include <app/data-model/Nullable.h>
#if defined(CONFIG_APP_MATTER_LEAK)
/* Boolean State has no ember Set accessor; it uses the code-driven cluster object. */
#include <app/clusters/boolean-state-server/CodegenIntegration.h>
#endif

#include <zephyr/logging/log.h>

LOG_MODULE_DECLARE(app, CONFIG_CHIP_APP_LOG_LEVEL);

using namespace ::chip;
using namespace ::chip::app;
using namespace ::chip::app::DataModel;
using namespace ::chip::DeviceLayer;

namespace
{
constexpr chip::EndpointId kSensorEndpointId = 1;
#if defined(CONFIG_APP_MATTER_LEAK)
constexpr chip::EndpointId kLeakEndpointId = 2;
#endif

Nrf::Matter::IdentifyCluster identify_cluster(kSensorEndpointId);
} /* namespace */

#if defined(CONFIG_APP_MATTER_LEAK)
namespace
{
/* Given by the leak ISR; wakes the reporter thread for an immediate update. */
K_SEM_DEFINE(leak_wake_sem, 0, 1);

void ReportLeakWork(intptr_t)
{
	AppTask::Instance().ReportLeak();
}

void LeakReporterThread(void *, void *, void *)
{
	while (true) {
		k_sem_take(&leak_wake_sem, K_FOREVER);
		/* Matter attribute writes must happen on the Matter thread. */
		DeviceLayer::PlatformMgr().ScheduleWork(ReportLeakWork, 0);
	}
}

K_THREAD_DEFINE(leak_reporter_tid, 768, LeakReporterThread, nullptr, nullptr, nullptr,
		K_LOWEST_APPLICATION_THREAD_PRIO, 0, 0);
} /* namespace */

void AppTask::ReportLeak()
{
	leak_read(sensors);
	if (sensors.leak.valid) {
		auto *boolean_state =
			Clusters::BooleanState::FindClusterOnEndpoint(kLeakEndpointId);
		if (boolean_state != nullptr) {
			boolean_state->SetStateValue(sensors.leak.wet);
		}
	}
}
#endif /* CONFIG_APP_MATTER_LEAK */

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
	sensor_read_cycle(sensors, cycle++);

	if (sensors.sht4x.valid) {
		Clusters::TemperatureMeasurement::Attributes::MeasuredValue::Set(
			kSensorEndpointId, sensors.sht4x.temperature_cC);
		Clusters::RelativeHumidityMeasurement::Attributes::MeasuredValue::Set(
			kSensorEndpointId, sensors.sht4x.humidity_cPct);
	}

#if defined(CONFIG_APP_MATTER_PRESSURE)
	if (sensors.bme688.valid) {
		Clusters::PressureMeasurement::Attributes::MeasuredValue::Set(
			kSensorEndpointId, sensors.bme688.pressure_kPa);
	}
#endif

#if defined(CONFIG_APP_MATTER_CO2)
	if (sensors.stcc4.valid) {
		co2_instance.SetMeasuredValue(
			DataModel::MakeNullable(static_cast<float>(sensors.stcc4.co2_ppm)));
	}
#endif

	/* Battery (Power Source on endpoint 0) — present on every board revision.
	 * battery_health (OK/LOW/CRITICAL = 0/1/2) maps 1:1 onto BatChargeLevelEnum;
	 * the coarse health is the right fit for the flat CR2 curve. */
	if (sensors.battery.valid) {
		Clusters::PowerSource::Attributes::BatChargeLevel::Set(
			0, static_cast<Clusters::PowerSource::BatChargeLevelEnum>(
				   sensors.battery.health));
		Clusters::PowerSource::Attributes::BatVoltage::Set(
			0, static_cast<uint32_t>(sensors.battery.millivolts));
#if defined(CONFIG_APP_MATTER_BATTERY_PERCENT)
		/* BatPercentRemaining is in half-percent units (0-200); 0xFF = unknown. */
		if (sensors.battery.percent == 0xFF) {
			Clusters::PowerSource::Attributes::BatPercentRemaining::Set(
				0, DataModel::NullNullable);
		} else {
			uint8_t pct = sensors.battery.percent > 100 ? 100
								    : sensors.battery.percent;
			Clusters::PowerSource::Attributes::BatPercentRemaining::Set(
				0, DataModel::MakeNullable(static_cast<uint8_t>(pct * 2)));
		}
#endif
	}

#if defined(CONFIG_APP_MATTER_LEAK)
	/* Periodic refresh; the leak ISR path handles the immediate wet edge. */
	ReportLeak();
#endif
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

#if defined(CONFIG_APP_MATTER_CO2)
	/* Initialize CO2 concentration cluster instance */
	ReturnErrorOnFailure(co2_instance.Init());
	co2_instance.SetMinMeasuredValue(MakeNullable(0.0f));
	co2_instance.SetMaxMeasuredValue(MakeNullable(40000.0f));
#endif

	/* Initialize sensors */
	sensor_init(sensors);
	sensor_fuel_gauge_init();

#if defined(CONFIG_APP_MATTER_LEAK)
	/* Arm the leak sensor: its ISR gives leak_wake_sem, waking the reporter thread
	 * for an immediate Boolean State update. */
	leak_init(sensors, &leak_wake_sem);
#endif

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
