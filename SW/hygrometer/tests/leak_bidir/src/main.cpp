/*
 * Unit tests for the two-way leak sensor (src/sensor/leak_bidir.cpp) and the
 * model functions it adds to leak_model.h.
 */

#include <zephyr/ztest.h>
#include <zephyr/device.h>
#include <zephyr/drivers/adc.h>
#include <zephyr/drivers/adc/adc_emul.h>
#include <zephyr/drivers/gpio.h>
#include <zephyr/drivers/gpio/gpio_emul.h>
#include <zephyr/kernel.h>

#include "leak.h"
#include "leak_model.h"

ZTEST_SUITE(leak_bidir_model, NULL, NULL, NULL, NULL, NULL);

ZTEST(leak_bidir_model, test_mean_mv)
{
	zassert_equal(leak_mean_mv(1300, 1150), 1225);
	zassert_equal(leak_mean_mv(1199, 1200), 1199, "rounds down");
	zassert_equal(leak_mean_mv(1200, 1200), 1200);
	zassert_equal(leak_mean_mv(0, 0), 0);
}

ZTEST(leak_bidir_model, test_mean_at_threshold)
{
	zassert_true(leak_decide(leak_mean_mv(1200, 1200), 1200, false).wet,
		     "a mean at the threshold is wet");
	zassert_false(leak_decide(leak_mean_mv(1199, 1200), 1200, false).wet,
		      "a mean one count under is dry");
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

/* ---- Real driver via emulated ADC/GPIO ---- */

#define LEAK_NODE DT_NODELABEL(leak_sensor)

static const struct gpio_dt_spec t_a = GPIO_DT_SPEC_GET(LEAK_NODE, a_gpios);
static const struct gpio_dt_spec t_a_ret = GPIO_DT_SPEC_GET(LEAK_NODE, a_return_gpios);
static const struct gpio_dt_spec t_b = GPIO_DT_SPEC_GET(LEAK_NODE, b_gpios);
static const struct gpio_dt_spec t_b_ret = GPIO_DT_SPEC_GET(LEAK_NODE, b_return_gpios);
static const struct adc_dt_spec t_adc_a = ADC_DT_SPEC_GET_BY_NAME(LEAK_NODE, a);
static const struct adc_dt_spec t_adc_b = ADC_DT_SPEC_GET_BY_NAME(LEAK_NODE, b);

static K_SEM_DEFINE(wake_sem, 0, 1);
static sensor_state state;

enum pin_role {
	OUT_LOW,
	OUT_HIGH,
	INPUT,
	UNKNOWN
};

static pin_role role(const struct gpio_dt_spec &p)
{
	gpio_flags_t flags = 0;

	if (gpio_emul_flags_get(p.port, p.pin, &flags) != 0) {
		return UNKNOWN;
	}
	if ((flags & GPIO_OUTPUT) == 0) {
		return (flags & GPIO_INPUT) != 0 ? INPUT : UNKNOWN;
	}
	return gpio_emul_output_get(p.port, p.pin) != 0 ? OUT_HIGH : OUT_LOW;
}

static bool is_armed(bool a_drives)
{
	const struct gpio_dt_spec &drv = a_drives ? t_a : t_b;
	const struct gpio_dt_spec &drv_ret = a_drives ? t_a_ret : t_b_ret;
	const struct gpio_dt_spec &sns = a_drives ? t_b : t_a;
	const struct gpio_dt_spec &sns_ret = a_drives ? t_b_ret : t_a_ret;

	return role(drv) == OUT_HIGH && role(drv_ret) == OUT_HIGH && role(sns) == INPUT &&
	       role(sns_ret) == OUT_LOW;
}

static void expect_armed(bool a_drives)
{
	zassert_true(is_armed(a_drives),
		     "expected armed with %s driving: A %d, A ret %d, B %d, B ret %d",
		     a_drives ? "A" : "B", role(t_a), role(t_a_ret), role(t_b), role(t_b_ret));
}

static void expect_parked(void)
{
	zassert_true(role(t_a) == OUT_LOW && role(t_a_ret) == OUT_LOW && role(t_b) == OUT_LOW &&
			     role(t_b_ret) == OUT_LOW,
		     "expected parked: A %d, A ret %d, B %d, B ret %d", role(t_a), role(t_a_ret),
		     role(t_b), role(t_b_ret));
}

/* a_mv is the voltage on LEAK_A's channel, which the driver samples while B drives. */
static int read_at(int a_mv, int b_mv)
{
	zassert_ok(adc_emul_const_value_set(t_adc_a.dev, t_adc_a.channel_id, a_mv));
	zassert_ok(adc_emul_const_value_set(t_adc_b.dev, t_adc_b.channel_id, b_mv));
	return leak_read(state);
}

/* The emulator refuses to set the input of a pin configured as an output (parked): ignored. */
static bool wakes_on_rising(const struct gpio_dt_spec &p)
{
	(void)gpio_emul_input_set(p.port, p.pin, 0);
	k_sem_reset(&wake_sem);
	(void)gpio_emul_input_set(p.port, p.pin, 1);
	bool woke = k_sem_take(&wake_sem, K_NO_WAIT) == 0;
	(void)gpio_emul_input_set(p.port, p.pin, 0);
	return woke;
}

static void *leak_setup(void)
{
	state = sensor_state{};
	leak_init(state, &wake_sem);
	zassert_true(state.have_leak, "leak_init should mark the sensor present");
	return NULL;
}

/* Every test starts dry and armed with A driving. */
static void leak_before(void *fixture)
{
	ARG_UNUSED(fixture);
	for (int i = 0; i < 2 && !is_armed(true); i++) {
		zassert_ok(read_at(100, 100));
	}
	expect_armed(true);
	k_sem_reset(&wake_sem);
}

ZTEST_SUITE(leak_bidir, NULL, leak_setup, leak_before, NULL, NULL);

ZTEST(leak_bidir, test_dry_alternates_direction)
{
	expect_armed(true);
	zassert_ok(read_at(100, 100));
	zassert_true(state.leak.valid);
	zassert_false(state.leak.wet);
	expect_armed(false);
	zassert_ok(read_at(100, 100));
	expect_armed(true);
}

ZTEST(leak_bidir, test_wet_parks_and_does_not_wake)
{
	zassert_ok(read_at(1490, 1490));
	zassert_true(state.leak.wet);
	expect_parked();
	zassert_false(wakes_on_rising(t_a));
	zassert_false(wakes_on_rising(t_b));
}

ZTEST(leak_bidir, test_wake_each_direction)
{
	zassert_true(wakes_on_rising(t_b), "A drives: B senses");
	zassert_ok(read_at(100, 100));
	zassert_true(wakes_on_rising(t_a), "B drives: A senses");
}

ZTEST(leak_bidir, test_mean_decides)
{
	zassert_ok(read_at(1300, 1150));
	zassert_true(state.leak.wet, "mean 1225");
	zassert_ok(read_at(1250, 1100));
	zassert_false(state.leak.wet, "mean 1175");
	/* The emulated 12-bit ADC returns up to 1 mV less than it is given, so the
	 * exact trip point is pinned in test_mean_at_threshold, on the model. */
	zassert_ok(read_at(1205, 1205));
	zassert_true(state.leak.wet, "both just over the threshold");
	zassert_ok(read_at(1195, 1195));
	zassert_false(state.leak.wet, "both just under the threshold");
}

ZTEST(leak_bidir, test_wet_then_dry_rearms)
{
	zassert_ok(read_at(1490, 1490));
	zassert_ok(read_at(100, 100));
	zassert_false(state.leak.wet);
	expect_armed(false);
	zassert_true(wakes_on_rising(t_a));
}

ZTEST(leak_bidir, test_read_without_init)
{
	sensor_state fresh{};
	zassert_equal(leak_read(fresh), -ENODEV);
	expect_armed(true);
}

/* What the four pins were doing when a channel was sampled, and how often it was. */
struct sample_snapshot {
	int calls;
	pin_role a, a_ret, b, b_ret;
};

static int snapshot_value(const struct device *dev, unsigned int chan, void *data, uint32_t *result)
{
	ARG_UNUSED(dev);
	ARG_UNUSED(chan);
	struct sample_snapshot *s = static_cast<struct sample_snapshot *>(data);

	s->calls++;
	s->a = role(t_a);
	s->a_ret = role(t_a_ret);
	s->b = role(t_b);
	s->b_ret = role(t_b_ret);
	*result = 100;
	return 0;
}

ZTEST(leak_bidir, test_each_direction_samples_its_channel)
{
	struct sample_snapshot on_a = {}, on_b = {};

	zassert_ok(adc_emul_value_func_set(t_adc_a.dev, t_adc_a.channel_id, snapshot_value, &on_a));
	zassert_ok(adc_emul_value_func_set(t_adc_b.dev, t_adc_b.channel_id, snapshot_value, &on_b));
	zassert_ok(leak_read(state));

	zassert_equal(on_b.calls, 1, "channel b is sampled once, while A drives");
	zassert_true(on_b.a == OUT_HIGH && on_b.a_ret == OUT_HIGH && on_b.b == INPUT &&
			     on_b.b_ret == OUT_LOW,
		     "channel b sampled with A %d, A ret %d, B %d, B ret %d", on_b.a, on_b.a_ret,
		     on_b.b, on_b.b_ret);
	zassert_equal(on_a.calls, 1, "channel a is sampled once, while B drives");
	zassert_true(on_a.b == OUT_HIGH && on_a.b_ret == OUT_HIGH && on_a.a == INPUT &&
			     on_a.a_ret == OUT_LOW,
		     "channel a sampled with A %d, A ret %d, B %d, B ret %d", on_a.a, on_a.a_ret,
		     on_a.b, on_a.b_ret);
}

static int failing_value(const struct device *dev, unsigned int chan, void *data, uint32_t *result)
{
	ARG_UNUSED(dev);
	ARG_UNUSED(chan);
	ARG_UNUSED(data);
	ARG_UNUSED(result);
	return -EIO;
}

ZTEST(leak_bidir, test_adc_error_first_direction)
{
	zassert_ok(adc_emul_const_value_set(t_adc_a.dev, t_adc_a.channel_id, 100));
	zassert_ok(adc_emul_value_func_set(t_adc_b.dev, t_adc_b.channel_id, failing_value, NULL));

	zassert_not_equal(leak_read(state), 0);
	zassert_false(state.leak.valid);
	expect_armed(true);
	zassert_true(wakes_on_rising(t_b), "re-armed, not left as the measurement had it");
}

ZTEST(leak_bidir, test_adc_error_second_direction)
{
	zassert_ok(adc_emul_const_value_set(t_adc_b.dev, t_adc_b.channel_id, 100));
	zassert_ok(adc_emul_value_func_set(t_adc_a.dev, t_adc_a.channel_id, failing_value, NULL));

	zassert_not_equal(leak_read(state), 0);
	zassert_false(state.leak.valid);
	expect_armed(true);
	zassert_true(wakes_on_rising(t_b));

	/* The same failure after a wet reading leaves the pins parked. */
	zassert_ok(read_at(1490, 1490));
	zassert_ok(adc_emul_value_func_set(t_adc_a.dev, t_adc_a.channel_id, failing_value, NULL));
	zassert_not_equal(leak_read(state), 0);
	zassert_false(state.leak.valid);
	expect_parked();
}
