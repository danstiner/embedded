#include "co2_mode_manager.h"

#include <app-common/zap-generated/attribute-type.h>
#include <app-common/zap-generated/cluster-objects.h>
#include <app/util/attribute-table.h>
#include <lib/support/Span.h>

#include <cstdio>
#include <cstring>

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
	BuildOption("Measure", Co2Cal::kModeNormal),
	BuildOption("Recalibrate (requires ~30 min outdoor air)", Co2Cal::kModeRecalibrate),
	BuildOption("Factory Reset (requires 12hr outdoor air)", Co2Cal::kModeFactoryReset),
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

void ApplyDescription()
{
	/* "CO₂ sensor", char_string wire format = 1-byte length + UTF-8 bytes
	 * (₂ = U+2082 → E2 82 82). No typed Description::Set accessor is generated, so write
	 * via the local attribute API (bypasses external ACL; Description is RAM-backed). */
	uint8_t desc[] = {12, 'C', 'O', 0xE2, 0x82, 0x82, ' ', 's', 'e', 'n', 's', 'o', 'r'};
	emberAfWriteAttribute(kCo2Endpoint, ModeSelect::Id, ModeSelect::Attributes::Description::Id,
			      desc, ZCL_CHAR_STRING_ATTRIBUTE_TYPE);
}

void SetCalOffset(int offset_ppm)
{
	/* char_string wire format = 1-byte length + UTF-8 bytes (₂ = E2 82 82). HA surfaces the
	 * Description as the select entity's name, so this exposes the offset for diagnostics. */
	char text[52];
	int n = snprintf(text, sizeof(text), "CO\xE2\x82\x82 sensor: offset %d ppm", offset_ppm);
	if (n < 0) {
		return;
	}
	if (n > (int)sizeof(text)) {
		n = (int)sizeof(text);
	}
	uint8_t buf[1 + sizeof(text)];
	buf[0] = (uint8_t)n;
	memcpy(&buf[1], text, (size_t)n);
	emberAfWriteAttribute(kCo2Endpoint, ModeSelect::Id, ModeSelect::Attributes::Description::Id,
			      buf, ZCL_CHAR_STRING_ATTRIBUTE_TYPE);
}
} /* namespace Co2Cal */
