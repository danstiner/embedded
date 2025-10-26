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
	chip::DeviceLayer::NetworkCommissioning::GenericThreadDriver> sThreadNetworkDriver(0);

const struct device *temp_dev;
struct k_work_delayable temp_work;

void LockOpenThreadTask()
{
	ThreadStackMgr().LockThreadStack();
}

void UnlockOpenThreadTask()
{
	ThreadStackMgr().UnlockThreadStack();
}

void ReadTemperatureSensor(struct k_work *work)
{
	struct sensor_value temp_value;

	if (sensor_sample_fetch(temp_dev) == 0) {
		if (sensor_channel_get(temp_dev, SENSOR_CHAN_DIE_TEMP, &temp_value) == 0) {
			int16_t temp_hundredths = (temp_value.val1 * 100) + (temp_value.val2 / 10000);
			temp_hundredths -= 300; // 3 degC offset for IC self-heating

			LOG_INF("Raw Temperature: %d.%02d C (Adjusted Matter: %d)",
				temp_value.val1, temp_value.val2 / 10000, temp_hundredths);

			chip::DeviceLayer::PlatformMgr().LockChipStack();
			chip::app::Clusters::TemperatureMeasurement::Attributes::MeasuredValue::Set(
				1, chip::app::DataModel::Nullable<int16_t>(temp_hundredths));
			chip::DeviceLayer::PlatformMgr().UnlockChipStack();
		} else {
			LOG_ERR("Failed to get temperature value");
		}
	} else {
		LOG_ERR("Failed to fetch temperature sample");
	}

	k_work_schedule(&temp_work, K_SECONDS(CONFIG_APP_MEASUREMENT_INTERVAL_SEC));
}
}

CHIP_ERROR AppTask::Init()
{
	ReturnErrorOnFailure(PlatformMgr().InitChipStack());

	ReturnErrorOnFailure(ThreadStackMgr().InitThreadStack());

	sThreadNetworkDriver.Init();

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

	temp_dev = DEVICE_DT_GET(DT_NODELABEL(temp));
	if (!device_is_ready(temp_dev)) {
		LOG_ERR("Temperature sensor not ready");
		return CHIP_ERROR_INTERNAL;
	}

	k_work_init_delayable(&temp_work, ReadTemperatureSensor);
	k_work_schedule(&temp_work, K_MSEC(1));

	return CHIP_NO_ERROR;
}

CHIP_ERROR AppTask::StartApp()
{
	ReturnErrorOnFailure(Init());

	LOG_INF("Matter server initialized");

	PlatformMgr().RunEventLoop();

	return CHIP_NO_ERROR;
}
