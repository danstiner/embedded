#include "app_task.h"
#include "co2_mode_manager.h"

#include <app-common/zap-generated/ids/Attributes.h>
#include <app-common/zap-generated/ids/Clusters.h>
#include <app/ConcreteAttributePath.h>
#include <lib/support/CodeUtils.h>
#include <protocols/interaction_model/StatusCode.h>

using namespace ::chip;
using namespace ::chip::app::Clusters;
using chip::Protocols::InteractionModel::Status;

/* Global weak hook invoked before an ember attribute write; a non-Success return aborts the
 * write (and the originating ChangeToMode command). Reject a Recalibrate/Factory Reset request
 * while a maintenance op is already running, so CurrentMode never moves and the controller sees
 * the failure — instead of the request silently doing nothing while the UI shows it "ran". */
chip::Protocols::InteractionModel::Status
MatterPreAttributeChangeCallback(const chip::app::ConcreteAttributePath &attributePath,
				 uint8_t type, uint16_t size, uint8_t *value)
{
#if defined(CONFIG_APP_MATTER_CO2)
	if (attributePath.mClusterId == ModeSelect::Id &&
	    attributePath.mAttributeId == ModeSelect::Attributes::CurrentMode::Id &&
	    !AppTask::IsCo2ModeReflecting() && value != nullptr && size >= 1) {
		if ((*value == Co2Cal::kModeRecalibrate || *value == Co2Cal::kModeFactoryReset) &&
		    sensor_co2_state() != CO2_STATE_MEASURE) {
			return Status::Busy;
		}
	}
#endif
	ARG_UNUSED(attributePath);
	ARG_UNUSED(type);
	ARG_UNUSED(size);
	ARG_UNUSED(value);
	return Status::Success;
}

/* Global weak hook invoked by the ember attribute store after any attribute
 * write. HA's Mode Select select entity issues ChangeToMode, whose cluster-server
 * handler sets CurrentMode -> ember write -> this callback. */
void MatterPostAttributeChangeCallback(const chip::app::ConcreteAttributePath &attributePath,
				       uint8_t type, uint16_t size, uint8_t *value)
{
#if defined(CONFIG_APP_MATTER_CO2)
	if (attributePath.mClusterId == ModeSelect::Id &&
	    attributePath.mAttributeId == ModeSelect::Attributes::CurrentMode::Id &&
	    !AppTask::IsCo2ModeReflecting()) {
		/* Controller-driven Recalibrate/Factory Reset start work. ReflectCo2Mode()'s own
		 * writes are skipped above; a controller write of Measure (0) is intentionally a
		 * no-op (you can't cancel a running op from the select). */
		if (value != nullptr && size >= 1) {
			if (*value == Co2Cal::kModeRecalibrate) {
				AppTask::Instance().RequestCo2Recalibration();
			} else if (*value == Co2Cal::kModeFactoryReset) {
				AppTask::Instance().RequestCo2FactoryReset();
			}
		}
	}
#endif
	ARG_UNUSED(attributePath);
	ARG_UNUSED(type);
	ARG_UNUSED(size);
	ARG_UNUSED(value);
}
