#include "co2_mode_manager.h"

#include <app-common/zap-generated/cluster-objects.h>
#include <lib/support/Span.h>

using namespace chip;
using namespace chip::app::Clusters;
using namespace chip::app::Clusters::ModeSelect;
using chip::Protocols::InteractionModel::Status;

namespace
{
using ModeOptionStructType = Structs::ModeOptionStruct::Type;
using SemanticTag = Structs::SemanticTagStruct::Type;
template <typename T> using List = chip::app::DataModel::List<T>;

constexpr EndpointId kCo2Endpoint = 1;

ModeOptionStructType BuildOption(const char *label, uint8_t mode)
{
	ModeOptionStructType option;
	option.label = CharSpan::fromCharString(label);
	option.mode = mode;
	option.semanticTags = List<const SemanticTag>(); /* none */
	return option;
}

/* String literals have static storage duration, so the CharSpans stay valid for
 * the program lifetime — required because HA reads SupportedModes lazily. */
const ModeOptionStructType kOptions[] = {
	BuildOption("Normal", Co2Cal::kModeNormal),
	BuildOption("Recalibrate (outdoor air)", Co2Cal::kModeRecalibrate),
};

class Co2CalModesManager : public SupportedModesManager
{
	/* The base declares this alias privately; redeclare it so the overrides
	 * below can name the type (matches the SDK's static example). */
	using ModeOptionStructType = Structs::ModeOptionStruct::Type;

      public:
	ModeOptionsProvider getModeOptionsProvider(EndpointId endpointId) const override
	{
		/* The cluster only exists on endpoint 1. */
		if (endpointId != kCo2Endpoint) {
			return ModeOptionsProvider(nullptr, nullptr);
		}
		Span<const ModeOptionStructType> span(kOptions);
		return ModeOptionsProvider(span.data(), span.end());
	}

	Status getModeOptionByMode(EndpointId endpointId, uint8_t mode,
				   const ModeOptionStructType **dataPtr) const override
	{
		auto provider = getModeOptionsProvider(endpointId);
		if (provider.begin() == nullptr) {
			return Status::UnsupportedCluster;
		}
		for (auto *it = provider.begin(); it != provider.end(); ++it) {
			if (it->mode == mode) {
				*dataPtr = it;
				return Status::Success;
			}
		}
		return Status::InvalidCommand;
	}
};

Co2CalModesManager sManager;
} /* namespace */

namespace Co2Cal
{
SupportedModesManager *GetModeManager()
{
	return &sManager;
}
} /* namespace Co2Cal */
