#pragma once

/*
 * Pure (hardware-free) model + decision logic for the resistive leak sensor, so
 * the threshold math and the wet/dry state machine can be unit-tested on the
 * host without Zephyr, GPIO or ADC. See tests/leak/ and leak.cpp.
 *
 * Front-end divider (R1 = R2 = 10 kΩ in series, R3 = 1 MΩ pull-down):
 *
 *   V_sense = V_drive * R3 / (R1 + R2 + R_water + R3)
 *
 * Inverting for the leak resistance:
 *
 *   R_water = V_drive * R3 / V_sense - (R1 + R2 + R3)
 */

#include <stdbool.h>
#include <stdint.h>

#define LEAK_R3_OHM      1000000 /* R3, sense pull-down */
#define LEAK_R_FIXED_OHM 1020000 /* R1 + R2 + R3, the fixed divider legs */

/** True when the sampled sense voltage is at or above the trip threshold. */
static inline bool leak_is_wet(int32_t sense_mv, int32_t threshold_mv)
{
	return sense_mv >= threshold_mv;
}

/** Modelled sense voltage (mV) for a given water resistance and drive voltage.
 *  Monotonically decreasing in @p r_water_ohm: dry (open) → ~0 V. */
static inline int32_t leak_sense_mv(int32_t r_water_ohm, int32_t v_drive_mv)
{
	if (r_water_ohm < 0) {
		r_water_ohm = 0;
	}
	int64_t denom = (int64_t)LEAK_R_FIXED_OHM + r_water_ohm;
	return (int32_t)((int64_t)v_drive_mv * LEAK_R3_OHM / denom);
}

/** Estimated water resistance (Ω) for a measured sense voltage. Returns
 *  INT32_MAX for a dry/open reading (sense_mv <= 0) and clamps a near-short to
 *  0. Intended for a debug/calibration readout. */
static inline int32_t leak_water_ohm(int32_t sense_mv, int32_t v_drive_mv)
{
	if (sense_mv <= 0) {
		return INT32_MAX;
	}
	int64_t r = (int64_t)v_drive_mv * LEAK_R3_OHM / sense_mv - LEAK_R_FIXED_OHM;
	if (r < 0) {
		r = 0;
	}
	if (r > INT32_MAX) {
		r = INT32_MAX;
	}
	return (int32_t)r;
}

/** Outcome of one leak sample: the reported state plus whether it transitioned
 *  (so the caller logs only on change instead of every poll). */
struct leak_decision {
	bool wet;
	bool log_change;
};

/** Decide the new leak state from a sampled sense voltage and the prior state. */
static inline struct leak_decision leak_decide(int32_t sense_mv, int32_t threshold_mv,
					       bool prev_wet)
{
	struct leak_decision d;
	d.wet = leak_is_wet(sense_mv, threshold_mv);
	d.log_change = (d.wet != prev_wet);
	return d;
}
