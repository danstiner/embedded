/*
 * nRF54 Soil Moisture Sensor - Matter Application Task
 */

#include "app_task.h"

#include <app/server/Server.h>
#include <app/clusters/network-commissioning/network-commissioning.h>
#include <credentials/DeviceAttestationCredsProvider.h>
#include <credentials/examples/DeviceAttestationCredsExample.h>
#include <data-model-providers/codegen/Instance.h>
#include <inet/EndPointStateOpenThread.h>
#include <lib/core/CHIPError.h>
#include <lib/support/CodeUtils.h>
#include <platform/CHIPDeviceLayer.h>
#include <platform/OpenThread/GenericNetworkCommissioningThreadDriver.h>
#include <platform/ThreadStackManager.h>

#include <zephyr/kernel.h>
#include <zephyr/logging/log.h>
#include <zephyr/sys/printk.h>

LOG_MODULE_REGISTER(app_task, CONFIG_CHIP_APP_LOG_LEVEL);

using namespace ::chip;
using namespace ::chip::DeviceLayer;

namespace {
chip::app::Clusters::NetworkCommissioning::InstanceAndDriver<
	chip::DeviceLayer::NetworkCommissioning::GenericThreadDriver> sThreadNetworkDriver(0);

void LockOpenThreadTask()
{
	ThreadStackMgr().LockThreadStack();
}

void UnlockOpenThreadTask()
{
	ThreadStackMgr().UnlockThreadStack();
}
}

CHIP_ERROR AppTask::Init()
{
	printk("AppTask::Init() starting\n");
	LOG_INF("Initializing Matter stack");

	printk("Calling PlatformMgr().InitChipStack()\n");
	ReturnErrorOnFailure(PlatformMgr().InitChipStack());
	printk("PlatformMgr init complete\n");

	printk("Initializing Thread stack\n");
	ReturnErrorOnFailure(ThreadStackMgr().InitThreadStack());
	printk("Thread stack init complete\n");

	printk("Initializing Thread network driver\n");
	sThreadNetworkDriver.Init();
	printk("Thread network driver init complete\n");

	printk("Setting DAC provider\n");
	chip::Credentials::SetDeviceAttestationCredentialsProvider(
		chip::Credentials::Examples::GetExampleDACProvider());

	printk("Initializing server params\n");
	static chip::CommonCaseDeviceServerInitParams initParams;

	chip::Inet::EndPointStateOpenThread::OpenThreadEndpointInitParam nativeParams;
	nativeParams.lockCb = LockOpenThreadTask;
	nativeParams.unlockCb = UnlockOpenThreadTask;
	nativeParams.openThreadInstancePtr = ThreadStackMgrImpl().OTInstance();
	initParams.endpointNativeParams = static_cast<void *>(&nativeParams);

	ReturnErrorOnFailure(initParams.InitializeStaticResourcesBeforeServerInit());

	initParams.dataModelProvider = chip::app::CodegenDataModelProviderInstance(initParams.persistentStorageDelegate);

	printk("Starting Matter server\n");
	ReturnErrorOnFailure(chip::Server::GetInstance().Init(initParams));

	printk("Logging device config\n");
	ConfigurationMgr().LogDeviceConfig();

	printk("AppTask::Init() complete\n");
	return CHIP_NO_ERROR;
}

CHIP_ERROR AppTask::StartApp()
{
	ReturnErrorOnFailure(Init());

	LOG_INF("Matter server initialized");

	PlatformMgr().RunEventLoop();

	return CHIP_NO_ERROR;
}
