/*
 * Unit tests for the STCC4 maintenance state machine (src/sensor/stcc4_model.h):
 * which action the measurement loop takes on each CO2 cycle while measuring,
 * recalibrating, and warming up after a factory reset.
 */

#include <zephyr/ztest.h>

#include "stcc4_model.h"

#define INTERVAL_MS 60000
#define WARMUP_MS   (10 * INTERVAL_MS)

static struct stcc4_ctl ctl;
static int64_t now;

static enum stcc4_step cycle(uint32_t request = STCC4_REQ_NONE, int64_t warmup_ms = WARMUP_MS)
{
	now += INTERVAL_MS;
	return stcc4_next_step(&ctl, now, request, warmup_ms);
}

static void before(void *)
{
	ctl = stcc4_ctl{};
	now = 0;
}

ZTEST_SUITE(stcc4_model, NULL, NULL, before, NULL, NULL);

/* Datasheet Table 11: T ticks = (T + 45) * 65535 / 175, RH ticks = (RH + 6) * 65535 / 125. */
ZTEST(stcc4_model, test_compensation_ticks)
{
	zassert_equal(stcc4_temp_ticks(2500), 26214);
	zassert_equal(stcc4_temp_ticks(-4500), 0);
	zassert_equal(stcc4_temp_ticks(13000), 65535);
	zassert_equal(stcc4_hum_ticks(5000), 29359);
	zassert_equal(stcc4_hum_ticks(0), 3145);
}

ZTEST(stcc4_model, test_compensation_ticks_clamp)
{
	zassert_equal(stcc4_temp_ticks(-5000), 0);
	zassert_equal(stcc4_temp_ticks(20000), 65535);
	zassert_equal(stcc4_hum_ticks(15000), 65535);
}

ZTEST(stcc4_model, test_idle_measures)
{
	zassert_equal(cycle(), STCC4_STEP_MEASURE);
	zassert_equal(ctl.state, CO2_STATE_MEASURE);
}

ZTEST(stcc4_model, test_conditioning_window_blocks_reads)
{
	ctl.cond_until = 1000;
	zassert_equal(stcc4_next_step(&ctl, 999, STCC4_REQ_NONE, WARMUP_MS), STCC4_STEP_WAIT);
	zassert_equal(stcc4_next_step(&ctl, 1000, STCC4_REQ_NONE, WARMUP_MS), STCC4_STEP_MEASURE);
}

ZTEST(stcc4_model, test_recal_runs_30_shots_then_frc)
{
	zassert_equal(cycle(430), STCC4_STEP_BEGIN_RECAL);
	zassert_equal(ctl.state, CO2_STATE_RECALIBRATE);
	zassert_equal(ctl.cond_until, now + STCC4_CONDITIONING_MS);

	for (int i = 0; i < STCC4_RECAL_SHOTS - 1; i++) {
		zassert_equal(cycle(), STCC4_STEP_RECAL_SHOT, "shot %d", i + 1);
		zassert_equal(ctl.state, CO2_STATE_RECALIBRATE);
	}

	zassert_equal(cycle(), STCC4_STEP_RECAL_FRC);
	zassert_equal(ctl.recal_target_ppm, 430);
	zassert_equal(ctl.state, CO2_STATE_MEASURE);
	zassert_equal(cycle(), STCC4_STEP_MEASURE);
}

ZTEST(stcc4_model, test_recal_waits_out_conditioning)
{
	zassert_equal(cycle(430), STCC4_STEP_BEGIN_RECAL);
	zassert_equal(
		stcc4_next_step(&ctl, now + STCC4_CONDITIONING_MS - 1, STCC4_REQ_NONE, WARMUP_MS),
		STCC4_STEP_WAIT);
	zassert_equal(ctl.recal_shots_remaining, STCC4_RECAL_SHOTS, "a skipped cycle is no shot");
}

ZTEST(stcc4_model, test_request_while_busy_is_dropped)
{
	zassert_equal(cycle(430), STCC4_STEP_BEGIN_RECAL);
	zassert_equal(cycle(STCC4_REQ_FACTORY_RESET), STCC4_STEP_RECAL_SHOT);
	zassert_equal(ctl.state, CO2_STATE_RECALIBRATE);
	zassert_equal(cycle(500), STCC4_STEP_RECAL_SHOT);
	zassert_equal(ctl.recal_target_ppm, 430);
	zassert_equal(ctl.recal_shots_remaining, STCC4_RECAL_SHOTS - 2);
}

ZTEST(stcc4_model, test_request_during_boot_conditioning_is_dropped)
{
	ctl.cond_until = now + 2 * INTERVAL_MS;
	zassert_equal(cycle(430), STCC4_STEP_WAIT);
	zassert_equal(ctl.state, CO2_STATE_MEASURE);
	zassert_equal(cycle(), STCC4_STEP_MEASURE);
}

ZTEST(stcc4_model, test_abort_returns_to_measure)
{
	zassert_equal(cycle(430), STCC4_STEP_BEGIN_RECAL);
	zassert_equal(cycle(), STCC4_STEP_RECAL_SHOT);
	stcc4_abort(&ctl);
	zassert_equal(ctl.state, CO2_STATE_MEASURE);
	zassert_equal(cycle(), STCC4_STEP_MEASURE);
}

ZTEST(stcc4_model, test_abort_cancels_conditioning_wait)
{
	zassert_equal(cycle(STCC4_REQ_FACTORY_RESET), STCC4_STEP_BEGIN_FACTORY_RESET);
	stcc4_abort(&ctl); /* reset command failed: nothing is conditioning */
	zassert_equal(stcc4_next_step(&ctl, now + 1, STCC4_REQ_NONE, WARMUP_MS),
		      STCC4_STEP_MEASURE);
}

ZTEST(stcc4_model, test_factory_reset_warms_up_then_measures)
{
	zassert_equal(cycle(STCC4_REQ_FACTORY_RESET), STCC4_STEP_BEGIN_FACTORY_RESET);
	zassert_equal(ctl.state, CO2_STATE_FACTORY_RESET);
	zassert_equal(ctl.cond_until, now + STCC4_CONDITIONING_MS);

	zassert_equal(cycle(), STCC4_STEP_BEGIN_WARMUP);
	const int64_t warmup_end = now + WARMUP_MS;

	while (now + INTERVAL_MS < warmup_end) {
		zassert_equal(cycle(), STCC4_STEP_WARMUP_READ);
		zassert_equal(ctl.state, CO2_STATE_FACTORY_RESET);
	}

	ctl.discards_remaining = 0;
	zassert_equal(cycle(), STCC4_STEP_END_WARMUP);
	zassert_equal(ctl.state, CO2_STATE_MEASURE);
	zassert_equal(ctl.discards_remaining, STCC4_BYPASS_DISCARDS,
		      "leaving continuous mode restarts the bypass phase");
	zassert_equal(cycle(), STCC4_STEP_MEASURE);
}

ZTEST(stcc4_model, test_factory_reset_without_warmup)
{
	zassert_equal(cycle(STCC4_REQ_FACTORY_RESET, 0), STCC4_STEP_BEGIN_FACTORY_RESET);
	ctl.discards_remaining = 0;
	zassert_equal(cycle(STCC4_REQ_NONE, 0), STCC4_STEP_MEASURE);
	zassert_equal(ctl.state, CO2_STATE_MEASURE);
	zassert_equal(ctl.discards_remaining, STCC4_BYPASS_DISCARDS);
}
