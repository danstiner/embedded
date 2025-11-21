/*
 * nRF54 Soil Moisture Sensor - Matter Application Task
 */

#include "app_task.h"

#include <app/server/Server.h>
#include <app/clusters/network-commissioning/network-commissioning.h>
#include <app/reporting/reporting.h>
#include <app/util/attribute-storage.h>
#include <app-common/zap-generated/attributes/Accessors.h>
#include <credentials/DeviceAttestationCredsProvider.h>
#include <credentials/examples/DeviceAttestationCredsExample.h>
#include <data-model-providers/codegen/Instance.h>
#include <inet/EndPointStateOpenThread.h>
#include <lib/core/CHIPError.h>
#include <lib/support/CodeUtils.h>
#include <platform/CHIPDeviceLayer.h>
#include <platform/OpenThread/GenericNetworkCommissioningThreadDriver.h>
#include <platform/ThreadStackManager.h>

#include "zap-generated/endpoint_config.h"

#include <zephyr/drivers/sensor.h>
#include <zephyr/kernel.h>
#include <zephyr/logging/log.h>
#include <zephyr/sys/printk.h>

LOG_MODULE_REGISTER(app_task, CONFIG_CHIP_APP_LOG_LEVEL);

using namespace ::chip;
using namespace ::chip::DeviceLayer;

namespace {

chip::app::Clusters::NetworkCommissioning::InstanceAndDriver<
	chip::DeviceLayer::NetworkCommissioning::GenericThreadDriver> thread_network_driver(0);

const struct device *temperature_device;
struct k_work_delayable measure_work;

void LockOpenThreadTask()
{
	ThreadStackMgr().LockThreadStack();
}

void UnlockOpenThreadTask()
{
	ThreadStackMgr().UnlockThreadStack();
}

bool ReadInternalTemperature(int16_t &matter_temperature)
{
	struct sensor_value temperature;
	int rc;

	rc = sensor_sample_fetch(temperature_device);
	if (rc != 0) {
		LOG_ERR("Failed to fetch temperature sample: %d", rc);
		return false;
	}

	rc = sensor_channel_get(temperature_device, SENSOR_CHAN_DIE_TEMP, &temperature);
	if (rc != 0) {
		LOG_ERR("Failed to read temperature channel: %d", rc);
		return false;
	}

	// Convert to Matter format (0.01°C units) and apply calibration offset
	matter_temperature = (temperature.val1 * 100) + (temperature.val2 / 10000) - 300;
	// 3°C offset for IC self-heating

	LOG_INF("Temperature: %d.%02d°C (Matter: %d)",
		temperature.val1, temperature.val2 / 10000, matter_temperature);
	return true;
}

void OnMeasureTimer(struct k_work *work)
{
	int16_t internal_temperature;
	bool new_internal_temperature = ReadInternalTemperature(internal_temperature);

	// Update Matter attribute
	PlatformMgr().LockChipStack();
	if (new_internal_temperature)
	{
		chip::app::Clusters::TemperatureMeasurement::Attributes::MeasuredValue::Set(
			1, chip::app::DataModel::Nullable<int16_t>(internal_temperature));
	}
	PlatformMgr().UnlockChipStack();

	k_work_schedule(&measure_work, K_SECONDS(CONFIG_APP_MEASUREMENT_INTERVAL_SEC));
}

} // namespace

CHIP_ERROR AppTask::Init()
{
	ReturnErrorOnFailure(PlatformMgr().InitChipStack());

	ReturnErrorOnFailure(ThreadStackMgr().InitThreadStack());

	thread_network_driver.Init();

	chip::Credentials::SetDeviceAttestationCredentialsProvider(
		chip::Credentials::Examples::GetExampleDACProvider());

	static chip::CommonCaseDeviceServerInitParams initParams;

	chip::Inet::EndPointStateOpenThread::OpenThreadEndpointInitParam nativeParams;
	nativeParams.lockCb = LockOpenThreadTask;
	nativeParams.unlockCb = UnlockOpenThreadTask;
	nativeParams.openThreadInstancePtr = ThreadStackMgrImpl().OTInstance();
	initParams.endpointNativeParams = static_cast<void *>(&nativeParams);

	ReturnErrorOnFailure(initParams.InitializeStaticResourcesBeforeServerInit());

	initParams.dataModelProvider = chip::app::CodegenDataModelProviderInstance(initParams.persistentStorageDelegate);

	ReturnErrorOnFailure(chip::Server::GetInstance().Init(initParams));

	ConfigurationMgr().LogDeviceConfig();

	// Initialize temperature sensor
	temperature_device = DEVICE_DT_GET(DT_NODELABEL(temp));
	if (!device_is_ready(temperature_device)) {
		LOG_ERR("Temperature sensor device not ready");
		return CHIP_ERROR_INTERNAL;
	}

	k_work_init_delayable(&measure_work, OnMeasureTimer);
	k_work_schedule(&measure_work, K_MSEC(500));

	return CHIP_NO_ERROR;
}

CHIP_ERROR AppTask::StartApp()
{
	ReturnErrorOnFailure(Init());

	LOG_INF("Matter server initialized");

	// Use current thread to drive CHIP event loop
	PlatformMgr().RunEventLoop();

	return CHIP_NO_ERROR;
}
