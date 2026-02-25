#include "app_task.h"

#include "app/matter_init.h"
#include "app/task_executor.h"
#include "board/board.h"
#include "clusters/identify.h"
#include "lib/core/CHIPError.h"

#include <app-common/zap-generated/attributes/Accessors.h>

#include <zephyr/logging/log.h>

LOG_MODULE_DECLARE(app, CONFIG_CHIP_APP_LOG_LEVEL);

using namespace ::chip;
using namespace ::chip::app;
using namespace ::chip::DeviceLayer;

namespace
{
constexpr chip::EndpointId kTemperatureSensorEndpointId = 1;

Nrf::Matter::IdentifyCluster sIdentifyCluster(kTemperatureSensorEndpointId);
} /* namespace */

void AppTask::ButtonEventHandler(Nrf::ButtonState state, Nrf::ButtonMask hasChanged)
{
	/* No physical buttons on hygrometer — placeholder for future SHPHLD button */
}

void AppTask::UpdateTemperatureTimeoutCallback(k_timer *timer)
{
	if (!timer || !timer->user_data) {
		return;
	}

	DeviceLayer::PlatformMgr().ScheduleWork(
		[](intptr_t p) {
			AppTask::Instance().UpdateTemperatureMeasurement();

			Protocols::InteractionModel::Status status =
				Clusters::TemperatureMeasurement::Attributes::MeasuredValue::Set(
					kTemperatureSensorEndpointId, AppTask::Instance().GetCurrentTemperature());

			if (status != Protocols::InteractionModel::Status::Success) {
				LOG_ERR("Updating temperature measurement failed %x", to_underlying(status));
			}
		},
		reinterpret_cast<intptr_t>(timer->user_data));
}

CHIP_ERROR AppTask::Init()
{
	/* Initialize Matter stack */
	ReturnErrorOnFailure(Nrf::Matter::PrepareServer());

	if (!Nrf::GetBoard().Init(ButtonEventHandler)) {
		LOG_ERR("User interface initialization failed.");
		return CHIP_ERROR_INCORRECT_STATE;
	}

	/* Register Matter event handler that controls the connectivity status LED based on the captured Matter network
	 * state. */
	ReturnErrorOnFailure(Nrf::Matter::RegisterEventHandler(Nrf::Board::DefaultMatterEventHandler, 0));

	ReturnErrorOnFailure(sIdentifyCluster.Init());

	return Nrf::Matter::StartServer();
}

CHIP_ERROR AppTask::StartApp()
{
	ReturnErrorOnFailure(Init());

	DataModel::Nullable<int16_t> val;
	Protocols::InteractionModel::Status status =
		Clusters::TemperatureMeasurement::Attributes::MinMeasuredValue::Get(kTemperatureSensorEndpointId, val);

	if (status != Protocols::InteractionModel::Status::Success || val.IsNull()) {
		LOG_ERR("Failed to get temperature measurement min value %x", to_underlying(status));
		return CHIP_ERROR_INCORRECT_STATE;
	}

	mTemperatureSensorMinValue = val.Value();

	status = Clusters::TemperatureMeasurement::Attributes::MaxMeasuredValue::Get(kTemperatureSensorEndpointId, val);

	if (status != Protocols::InteractionModel::Status::Success || val.IsNull()) {
		LOG_ERR("Failed to get temperature measurement max value %x", to_underlying(status));
		return CHIP_ERROR_INCORRECT_STATE;
	}

	mTemperatureSensorMaxValue = val.Value();

	k_timer_init(&mTimer, AppTask::UpdateTemperatureTimeoutCallback, nullptr);
	k_timer_user_data_set(&mTimer, this);
	k_timer_start(&mTimer, K_MSEC(kTemperatureMeasurementIntervalMs), K_MSEC(kTemperatureMeasurementIntervalMs));

	while (true) {
		Nrf::DispatchNextTask();
	}

	return CHIP_NO_ERROR;
}
