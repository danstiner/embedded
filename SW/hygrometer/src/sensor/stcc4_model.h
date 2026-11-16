#pragma once

/*
 * Pure (I2C-free) state machine for STCC4 maintenance, so the sequencing can be
 * unit-tested on the host. See tests/stcc4/ and sensor_read_stcc4().
 *
 * The measurement loop calls stcc4_next_step() once per CO2 cycle and performs the
 * returned step. A forced recalibration is therefore just the next
 * STCC4_RECAL_SHOTS CO2 cycles (after conditioning) with the sensor held in idle,
 * and nothing blocks longer than a single measurement.
 */

#include <stdint.h>

#include "sensor_reading.h"
#include "stcc4.h"

/* Datasheet §3.4.15: operate >=30 single-shots before forced recalibration. */
#define STCC4_RECAL_SHOTS 30

/* Single-shots to discard after (re)entering single-shot mode: the bypass phase emits
 * a fixed 390 ppm placeholder for the first 2 (datasheet §1.1.2). */
#define STCC4_BYPASS_DISCARDS 2

/* Maintenance request: none, factory reset, or (any other value) a forced
 * recalibration to that target in ppm. */
#define STCC4_REQ_NONE          0u
#define STCC4_REQ_FACTORY_RESET UINT32_MAX

/* RH/T compensation inputs (datasheet Table 11), from 0.01 degC / 0.01 %RH:
 *   T ticks  = (T[degC] + 45) * (2^16 - 1) / 175
 *   RH ticks = (RH[%RH] + 6) * (2^16 - 1) / 125 */
static inline uint16_t stcc4_temp_ticks(int16_t temperature_cC)
{
	int32_t ticks = (temperature_cC + 4500) * 65535LL / 17500;

	return (uint16_t)(ticks < 0 ? 0 : ticks > 65535 ? 65535 : ticks);
}

static inline uint16_t stcc4_hum_ticks(uint16_t humidity_cPct)
{
	int32_t ticks = (humidity_cPct + 600) * 65535LL / 12500;

	return (uint16_t)(ticks > 65535 ? 65535 : ticks);
}

struct stcc4_ctl {
	enum co2_state state;
	/* Uptime before which the sensor is conditioning: it must stay awake and
	 * unread (no completion signal). */
	int64_t cond_until;
	/* Uptime at which the post-factory-reset continuous warm-up ends; 0 until
	 * continuous mode has been started. */
	int64_t warmup_until;
	uint16_t recal_target_ppm;
	uint8_t recal_shots_remaining;
	uint8_t discards_remaining;
};

enum stcc4_step {
	STCC4_STEP_WAIT,                /* conditioning: leave the sensor alone */
	STCC4_STEP_MEASURE,             /* wake, single-shot, sleep */
	STCC4_STEP_BEGIN_RECAL,         /* wake, start conditioning */
	STCC4_STEP_RECAL_SHOT,          /* single-shot, stay in idle */
	STCC4_STEP_RECAL_FRC,           /* final single-shot, FRC to recal_target_ppm, sleep */
	STCC4_STEP_BEGIN_FACTORY_RESET, /* wake, factory reset, start conditioning */
	STCC4_STEP_BEGIN_WARMUP,        /* start continuous mode */
	STCC4_STEP_WARMUP_READ,         /* read the continuous-mode result */
	STCC4_STEP_END_WARMUP,          /* stop continuous mode, then as MEASURE */
};

/* A request is only started from idle; one arriving mid-operation or while the
 * sensor is conditioning is dropped (the caller sees a non-BEGIN step). */
static inline enum stcc4_step stcc4_next_step(struct stcc4_ctl *c, int64_t now, uint32_t request,
					      int64_t warmup_ms)
{
	if (now < c->cond_until) {
		return STCC4_STEP_WAIT;
	}

	switch (c->state) {
	case CO2_STATE_RECALIBRATE:
		if (--c->recal_shots_remaining > 0) {
			return STCC4_STEP_RECAL_SHOT;
		}
		c->state = CO2_STATE_MEASURE;
		return STCC4_STEP_RECAL_FRC;

	case CO2_STATE_FACTORY_RESET:
		if (c->warmup_until == 0 && warmup_ms > 0) {
			c->warmup_until = now + warmup_ms;
			return STCC4_STEP_BEGIN_WARMUP;
		}
		if (now < c->warmup_until) {
			return STCC4_STEP_WARMUP_READ;
		}
		c->state = CO2_STATE_MEASURE;
		c->discards_remaining = STCC4_BYPASS_DISCARDS;
		if (c->warmup_until == 0) {
			return STCC4_STEP_MEASURE;
		}
		c->warmup_until = 0;
		return STCC4_STEP_END_WARMUP;

	case CO2_STATE_MEASURE:
		break;
	}

	if (request == STCC4_REQ_NONE) {
		return STCC4_STEP_MEASURE;
	}

	c->cond_until = now + STCC4_CONDITIONING_MS;
	if (request == STCC4_REQ_FACTORY_RESET) {
		c->state = CO2_STATE_FACTORY_RESET;
		c->warmup_until = 0;
		return STCC4_STEP_BEGIN_FACTORY_RESET;
	}
	c->state = CO2_STATE_RECALIBRATE;
	c->recal_target_ppm = (uint16_t)request;
	c->recal_shots_remaining = STCC4_RECAL_SHOTS;
	return STCC4_STEP_BEGIN_RECAL;
}

/* An I2C step failed mid-operation: drop back to normal measurement. The caller
 * puts the sensor to sleep. */
static inline void stcc4_abort(struct stcc4_ctl *c)
{
	c->state = CO2_STATE_MEASURE;
	c->cond_until = 0;
	c->warmup_until = 0;
}
