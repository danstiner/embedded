/*
 * Unit tests for the two-way leak sensor (src/sensor/leak_bidir.cpp) and the
 * model functions it adds to leak_model.h.
 */

#include <zephyr/ztest.h>

#include "leak_model.h"

ZTEST_SUITE(leak_bidir_model, NULL, NULL, NULL, NULL, NULL);

ZTEST(leak_bidir_model, test_mean_mv)
{
	zassert_equal(leak_mean_mv(1300, 1150), 1225);
	zassert_equal(leak_mean_mv(1199, 1200), 1199, "rounds down");
	zassert_equal(leak_mean_mv(1200, 1200), 1200);
	zassert_equal(leak_mean_mv(0, 0), 0);
}

ZTEST(leak_bidir_model, test_directions_disagree)
{
	zassert_true(leak_directions_disagree(1200, 299, 1200),
		     "wet one way, under a quarter the other");
	zassert_true(leak_directions_disagree(299, 1200, 1200), "symmetric");
	zassert_false(leak_directions_disagree(1200, 300, 1200),
		      "a quarter is not under a quarter");
	zassert_false(leak_directions_disagree(1199, 0, 1200), "neither reads wet");
	zassert_false(leak_directions_disagree(1490, 1490, 1200), "water reads alike both ways");
}
