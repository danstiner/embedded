#pragma once

#include <app/clusters/mode-select-server/supported-modes-manager.h>
#include <cstdint>

/* Mode Select cluster (0x0050) on endpoint 1, a HA-native trigger for CO2 sensor
 * maintenance:
 *   0 = Measure (normal operation, the resting state)
 *   1 = Recalibrate (outdoor air)  -> forced recalibration to the outdoor target
 *   2 = Factory Reset              -> wipes learned calibration (recovery)
 *
 * The firmware flips CurrentMode back to Measure (0) once the op finishes. */
namespace Co2Cal
{
constexpr uint8_t kModeNormal = 0;
constexpr uint8_t kModeRecalibrate = 1;
constexpr uint8_t kModeFactoryReset = 2;

/* Singleton SupportedModesManager providing the two modes above for endpoint 1.
 * Register it with ModeSelect::setSupportedModesManager() after Server::Init(). */
chip::app::Clusters::ModeSelect::SupportedModesManager *GetModeManager();

/* Set the Mode Select Description to "CO₂ sensor" — Home Assistant uses it as the
 * select entity's name. Call after Server::Init(). */
void ApplyDescription();

/* Diagnostic: rewrite the Mode Select Description to include the last applied FRC correction
 * (e.g. "CO₂ sensor: offset -250 ppm"), which HA surfaces as the select entity's name. Must be
 * called from the Matter thread. */
void SetCalOffset(int offset_ppm);
} /* namespace Co2Cal */
