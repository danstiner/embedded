#include "app_task.h"
#include "sht4x.h"

#include <app/server/Server.h>
#include <app/clusters/network-commissioning/network-commissioning.h>
#include <app/clusters/ota-requestor/BDXDownloader.h>
#include <app/clusters/ota-requestor/DefaultOTARequestor.h>
#include <app/clusters/ota-requestor/DefaultOTARequestorDriver.h>
#include <app/clusters/ota-requestor/DefaultOTARequestorStorage.h>
#include <app/clusters/ota-requestor/OTARequestorInterface.h>
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
#include <platform/nrfconnect/OTAImageProcessorImpl.h>
#include <platform/OpenThread/GenericNetworkCommissioningThreadDriver.h>
#include <platform/ThreadStackManager.h>
#include <platform/ConnectivityManager.h>

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
	chip::DeviceLayer::NetworkCommissioning::GenericThreadDriver> THREAD_NETWORK_DRIVER(0);

// OTA Requestor
chip::DefaultOTARequestorStorage sOTARequestorStorage;
chip::DeviceLayer::DefaultOTARequestorDriver sOTARequestorDriver;
chip::BDXDownloader sBDXDownloader;
chip::DefaultOTARequestor sOTARequestor;

struct k_work_delayable measure_work;
Sht4x sht4x;

void LockOpenThreadTask()
{
	ThreadStackMgr().LockThreadStack();
}

void UnlockOpenThreadTask()
{
	ThreadStackMgr().UnlockThreadStack();
}

CHIP_ERROR ConfigureThreadRole()
{
#if CHIP_DEVICE_CONFIG_THREAD_FTD
	return ConnectivityMgr().SetThreadDeviceType(ConnectivityManager::kThreadDeviceType_Router);
#elif CONFIG_CHIP_THREAD_SSED
    return ConnectivityMgr().SetThreadDeviceType(ConnectivityManager::kThreadDeviceType_SynchronizedSleepyEndDevice);
#elif CONFIG_OPENTHREAD_MTD_SED
    return ConnectivityMgr().SetThreadDeviceType(ConnectivityManager::kThreadDeviceType_SleepyEndDevice);
#else
    return ConnectivityMgr().SetThreadDeviceType(ConnectivityManager::kThreadDeviceType_MinimalEndDevice);
#endif
}

} // namespace

void AppTask::MeasureWorkPeriodic(struct k_work *work)
{
	int16_t temperature;
	uint16_t humidity;
	bool success = false;
	if (sht4x.Ready()) {

		// Read SHT4x sensor
		success = sht4x.Read(temperature, humidity);
	} else {
		LOG_DBG("Sht4x not ready");
	}

	// Update Matter attributes
	PlatformMgr().LockChipStack();
	if (success) {
		chip::app::Clusters::TemperatureMeasurement::Attributes::MeasuredValue::Set(
			1, chip::app::DataModel::Nullable<int16_t>(temperature));
		chip::app::Clusters::RelativeHumidityMeasurement::Attributes::MeasuredValue::Set(
			1, chip::app::DataModel::Nullable<uint16_t>(humidity));
	} else {
		// Set to null on error to indicate sensor unavailable
		chip::app::Clusters::TemperatureMeasurement::Attributes::MeasuredValue::Set(
			1, chip::app::DataModel::Nullable<int16_t>());
		chip::app::Clusters::RelativeHumidityMeasurement::Attributes::MeasuredValue::Set(
			1, chip::app::DataModel::Nullable<uint16_t>());
	}
	PlatformMgr().UnlockChipStack();

	k_work_schedule(&measure_work, K_SECONDS(CONFIG_APP_MEASUREMENT_INTERVAL_SEC));
}

CHIP_ERROR AppTask::Init()
{
	ReturnErrorOnFailure(PlatformMgr().InitChipStack());

	ReturnErrorOnFailure(ThreadStackMgr().InitThreadStack());

	ReturnErrorOnFailure(ConfigureThreadRole());

	THREAD_NETWORK_DRIVER.Init();

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

	// Initialize OTA Requestor
	static chip::DeviceLayer::OTAImageProcessorImpl sOTAImageProcessor;
	sOTAImageProcessor.SetOTADownloader(&sBDXDownloader);
	sBDXDownloader.SetImageProcessorDelegate(&sOTAImageProcessor);
	sOTARequestorStorage.Init(chip::Server::GetInstance().GetPersistentStorage());
	sOTARequestor.Init(chip::Server::GetInstance(), sOTARequestorStorage, sOTARequestorDriver, sBDXDownloader);
	sOTARequestorDriver.Init(&sOTARequestor, &sOTAImageProcessor);
	chip::SetRequestorInstance(&sOTARequestor);

	// Initialize SHT4x driver
	ReturnErrorOnFailure(sht4x.Init());

	// Start measurement periodic after short delay
	// TODO only start once commissioned
	k_work_init_delayable(&measure_work, AppTask::MeasureWorkPeriodic);
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
