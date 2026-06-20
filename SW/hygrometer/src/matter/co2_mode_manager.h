#pragma once

#include <app/clusters/mode-select-server/supported-modes-manager.h>
#include <cstdint>

/* Mode Select cluster (0x0050) on endpoint 1, used as a HA-native trigger for
 * CO2 sensor recalibration:
 *   0 = Normal
 *   1 = Recalibrate (outdoor air)  -> runs the reset + forced-recalibration
 *
 * The firmware flips CurrentMode back to Normal once recalibration finishes. */
namespace Co2Cal
{
constexpr uint8_t kModeNormal = 0;
constexpr uint8_t kModeRecalibrate = 1;

/* Singleton SupportedModesManager providing the two modes above for endpoint 1.
 * Register it with ModeSelect::setSupportedModesManager() after Server::Init(). */
chip::app::Clusters::ModeSelect::SupportedModesManager *GetModeManager();
} /* namespace Co2Cal */
