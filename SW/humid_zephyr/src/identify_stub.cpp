/*
 * Identify Cluster Stub Implementations
 */

#include <app-common/zap-generated/callback.h>
#include <app-common/zap-generated/cluster-objects.h>
#include <app/CommandHandler.h>
#include <app/ConcreteAttributePath.h>
#include <app/ConcreteCommandPath.h>

using namespace chip;
using namespace chip::app::Clusters;

void __attribute__((weak)) emberAfIdentifyClusterServerInitCallback(EndpointId endpoint)
{
	(void)endpoint;
}

void __attribute__((weak)) MatterIdentifyClusterServerAttributeChangedCallback(const app::ConcreteAttributePath &attributePath)
{
	(void)attributePath;
}

bool __attribute__((weak)) emberAfIdentifyClusterIdentifyCallback(
	app::CommandHandler *commandObj,
	const app::ConcreteCommandPath &commandPath,
	const Identify::Commands::Identify::DecodableType &commandData)
{
	(void)commandObj;
	(void)commandPath;
	(void)commandData;
	return true;
}

bool __attribute__((weak)) emberAfIdentifyClusterTriggerEffectCallback(
	app::CommandHandler *commandObj,
	const app::ConcreteCommandPath &commandPath,
	const Identify::Commands::TriggerEffect::DecodableType &commandData)
{
	(void)commandObj;
	(void)commandPath;
	(void)commandData;
	return true;
}
