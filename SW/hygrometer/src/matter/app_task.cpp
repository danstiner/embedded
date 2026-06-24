#include "app_task.h"

#include "sensor/leak.h"

#include "app/matter_init.h"
#include "app/task_executor.h"
#include "board/board.h"
#include "clusters/identify.h"
#include "lib/core/CHIPError.h"

#include <app-common/zap-generated/attributes/Accessors.h>
#include <app/data-model/Nullable.h>
#include <app/server/AppDelegate.h>
#if defined(CONFIG_APP_MATTER_LEAK)
/* Boolean State has no ember Set accessor; it uses the code-driven cluster object. */
#include <app/clusters/boolean-state-server/CodegenIntegration.h>
#endif
#if defined(CONFIG_APP_MATTER_CO2)
#include "co2_mode_manager.h"
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

/* Pairing-mode LED: pulse while a commissioning window is open, off otherwise.
 * The board library default instead holds the LED solid on once provisioned,
 * which would drain the battery. Low duty cycle to limit draw during the
 * (up to 15 minute) window. */
constexpr uint32_t kPairingLedOnMs = 100;
constexpr uint32_t kPairingLedOffMs = 900;

bool commissioning_window_open;

void UpdateStatusLed()
{
	auto &led = Nrf::GetBoard().GetLED(Nrf::DeviceLeds::LED1);
	if (commissioning_window_open) {
		led.Blink(kPairingLedOnMs, kPairingLedOffMs);
	} else {
		led.Set(false);
	}
}

/* Callbacks run on the Matter thread; the LED state is owned by the app task
 * thread (the board library also calls UpdateStatusLed there), so hop over. */
class WindowLedDelegate : public AppDelegate
{
	void OnCommissioningWindowOpened() override
	{
		Nrf::PostTask([] {
			commissioning_window_open = true;
			UpdateStatusLed();
		});
	}

	void OnCommissioningWindowClosed() override
	{
		Nrf::PostTask([] {
			commissioning_window_open = false;
			UpdateStatusLed();
		});
	}
} window_led_delegate;
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
		K_HIGHEST_APPLICATION_THREAD_PRIO, 0, 0);
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

#if defined(CONFIG_APP_MATTER_CO2)
void AppTask::RequestCo2Recalibration()
{
	/* Pass current pressure for compensation when a BME688 is fitted; 0 lets
	 * the sensor keep its sea-level default. Read here (Matter thread) is safe:
	 * `sensors` is only ever written on this thread. */
	uint32_t pressure_pa = sensors.bme688.valid ? sensors.bme688.pressure_Pa : 0;

	LOG_INF("CO2 recalibration requested via Mode Select");
	sensor_recalibrate_stcc4_async(CONFIG_APP_CO2_RECAL_TARGET_PPM, pressure_pa,
				       AppTask::Co2RecalibrationDone);
}

void AppTask::Co2RecalibrationDone(int result)
{
	/* CurrentMode is driven by ReflectCo2Mode() from the sensor op state; just log. */
	LOG_INF("CO2 recalibration finished (result %d)", result);
}

void AppTask::RequestCo2FactoryReset()
{
	LOG_INF("CO2 factory reset requested via Mode Select");
	sensor_factory_reset_stcc4_async(AppTask::Co2FactoryResetDone);
}

void AppTask::Co2FactoryResetDone(int result)
{
	/* A successful factory reset hands off to the warm-up; CurrentMode stays Factory Reset
	 * (driven by ReflectCo2Mode()) until the warm-up ends. Just log the kick-off result. */
	LOG_INF("CO2 factory reset finished (result %d)", result);
}

bool AppTask::sCo2ModeReflecting;

void AppTask::ReflectCo2Mode()
{
	/* co2_state values are 1:1 with the Mode Select modes (Measure/Recalibrate/Factory
	 * Reset = 0/1/2), so the state maps straight onto CurrentMode. */
	uint8_t want = static_cast<uint8_t>(sensor_co2_state());
	uint8_t current = Co2Cal::kModeNormal;
	Clusters::ModeSelect::Attributes::CurrentMode::Get(kSensorEndpointId, &current);
	if (current == want) {
		return;
	}
	sCo2ModeReflecting = true;
	Clusters::ModeSelect::Attributes::CurrentMode::Set(kSensorEndpointId, want);
	sCo2ModeReflecting = false;
}
#endif /* CONFIG_APP_MATTER_CO2 */

void AppTask::SensorTimerCallback(k_timer *timer)
{
	if (!timer) {
		return;
	}

	/* Attribute writes must run on the Matter thread; the singleton is reached via
	 * Instance(), so no per-timer context is needed. */
	DeviceLayer::PlatformMgr().ScheduleWork(
		[](intptr_t) { AppTask::Instance().UpdateSensorAttributes(); }, 0);
}

void AppTask::UpdateSensorAttributes()
{
	sensor_read_cycle(sensors, cycle++);

	/* Invalid readings are written as null so the controller sees "unknown"
	 * rather than a frozen last value. Unchanged writes (including repeated
	 * nulls) are deduped by the SDK and generate no reports. */
	if (sensors.sht4x.valid) {
		Clusters::TemperatureMeasurement::Attributes::MeasuredValue::Set(
			kSensorEndpointId, sensors.sht4x.temperature_cC);
		Clusters::RelativeHumidityMeasurement::Attributes::MeasuredValue::Set(
			kSensorEndpointId, sensors.sht4x.humidity_cPct);
	} else {
		Clusters::TemperatureMeasurement::Attributes::MeasuredValue::SetNull(
			kSensorEndpointId);
		Clusters::RelativeHumidityMeasurement::Attributes::MeasuredValue::SetNull(
			kSensorEndpointId);
	}

#if defined(CONFIG_APP_MATTER_PRESSURE)
	if (sensors.bme688.valid) {
		Clusters::PressureMeasurement::Attributes::MeasuredValue::Set(
			kSensorEndpointId, sensors.bme688.pressure_hPa);
	} else {
		Clusters::PressureMeasurement::Attributes::MeasuredValue::SetNull(
			kSensorEndpointId);
	}
#endif

#if defined(CONFIG_APP_MATTER_CO2)
	if (sensors.stcc4.valid) {
		co2_instance.SetMeasuredValue(
			DataModel::MakeNullable(static_cast<float>(sensors.stcc4.co2_ppm)));
	} else {
		co2_instance.SetMeasuredValue(DataModel::NullNullable);
	}
	ReflectCo2Mode();

	/* Diagnostic: surface the last FRC correction in the Mode Select Description (HA shows it
	 * as the entity name). Pushed only on change; INT32_MIN = no recal since boot. */
	int frc_offset = sensor_co2_last_frc_offset();
	static int pushed_frc_offset = INT32_MIN;
	if (frc_offset != INT32_MIN && frc_offset != pushed_frc_offset) {
		pushed_frc_offset = frc_offset;
		Co2Cal::SetCalOffset(frc_offset);
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
			uint8_t pct = sensors.battery.percent > 100 ? 100 : sensors.battery.percent;
			Clusters::PowerSource::Attributes::BatPercentRemaining::Set(
				0, DataModel::MakeNullable(static_cast<uint8_t>(pct * 2)));
		}
#endif
	} else {
		/* BatChargeLevel is non-nullable per spec, so it can't show "unknown". */
		Clusters::PowerSource::Attributes::BatVoltage::SetNull(0);
#if defined(CONFIG_APP_MATTER_BATTERY_PERCENT)
		Clusters::PowerSource::Attributes::BatPercentRemaining::SetNull(0);
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
	Nrf::Matter::InitData initData{};
	/* Drives the pairing-mode LED; registered via the server init params so it
	 * also sees the autostart commissioning window opened during Server::Init(). */
	initData.mServerInitParams->appDelegate = &window_led_delegate;
#if defined(CONFIG_APP_MATTER_CO2)
	/* The CO2 instance's Init() checks the ember endpoint table, which is only
	 * populated by Server::Init() on the Matter thread; defer it to the
	 * post-server-init callback (same pattern as the NCS thermostat sample). */
	initData.mPostServerInitClbk = [] {
		auto &co2 = Instance().co2_instance;
		ReturnLogErrorOnFailure(co2.Init());
		co2.SetMinMeasuredValue(MakeNullable(0.0f));
		co2.SetMaxMeasuredValue(MakeNullable(40000.0f));
		/* The Mode Select cluster serves SupportedModes via an
		 * AttributeAccessInterface, so it needs a registered manager or HA
		 * shows an empty dropdown and ChangeToMode fails. */
		Clusters::ModeSelect::setSupportedModesManager(Co2Cal::GetModeManager());
		Co2Cal::ApplyDescription();
		return CHIP_NO_ERROR;
	};
#endif
	ReturnErrorOnFailure(Nrf::Matter::PrepareServer(initData));

	if (!Nrf::GetBoard().Init(nullptr, UpdateStatusLed)) {
		LOG_ERR("User interface initialization failed.");
		return CHIP_ERROR_INCORRECT_STATE;
	}

	ReturnErrorOnFailure(
		Nrf::Matter::RegisterEventHandler(Nrf::Board::DefaultMatterEventHandler, 0));
	ReturnErrorOnFailure(identify_cluster.Init());

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
	k_timer_start(&timer, K_MSEC(intervalMs), K_MSEC(intervalMs));

	while (true) {
		Nrf::DispatchNextTask();
	}

	return CHIP_NO_ERROR;
}
