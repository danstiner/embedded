#include "app_task.h"

#include <app-common/zap-generated/ids/Attributes.h>
#include <app-common/zap-generated/ids/Clusters.h>
#include <app/ConcreteAttributePath.h>
#include <lib/support/CodeUtils.h>

using namespace ::chip;
using namespace ::chip::app::Clusters;

/* Global weak hook invoked by the ember attribute store after any attribute
 * write. HA's Mode Select select entity issues ChangeToMode, whose cluster-server
 * handler sets CurrentMode -> ember write -> this callback. */
void MatterPostAttributeChangeCallback(const chip::app::ConcreteAttributePath &attributePath, uint8_t type,
				       uint16_t size, uint8_t *value)
{
#if defined(CONFIG_APP_MATTER_CO2)
	if (attributePath.mClusterId == ModeSelect::Id &&
	    attributePath.mAttributeId == ModeSelect::Attributes::CurrentMode::Id) {
		/* Only "Recalibrate" (1) starts work; the firmware's own flip back to
		 * Normal (0) lands here too and is intentionally ignored. */
		if (value != nullptr && size >= 1 && *value == 1) {
			AppTask::Instance().RequestCo2Recalibration();
		}
	}
#endif
	ARG_UNUSED(attributePath);
	ARG_UNUSED(type);
	ARG_UNUSED(size);
	ARG_UNUSED(value);
}
