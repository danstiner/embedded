/*
 * Unit tests for the resistive leak sensor driver (src/sensor/leak.cpp).
 *
 * Runs on native_sim with the emulated ADC (adc_emul) and GPIO (gpio_emul)
 * drivers, so the real leak_init()/leak_read() are exercised end to end: a
 * sensed voltage is injected on the ADC, then the wet/dry decision, the
 * drive-pin state (held active when dry vs parked low when wet) and the
 * wake-interrupt behaviour are checked against the actual driver. A handful of
 * cheaper asserts cover the pure model in leak_model.h directly.
 */

#include <zephyr/ztest.h>
#include <zephyr/device.h>
#include <zephyr/drivers/adc.h>
#include <zephyr/drivers/adc/adc_emul.h>
#include <zephyr/drivers/gpio.h>
#include <zephyr/drivers/gpio/gpio_emul.h>
#include <zephyr/kernel.h>
#include <zephyr/sys/util.h>

#include "leak.h"
#include "leak_model.h"

#define LEAK_NODE DT_NODELABEL(leak_sensor)

static const struct gpio_dt_spec t_drive = GPIO_DT_SPEC_GET(LEAK_NODE, drive_gpios);
static const struct gpio_dt_spec t_sense = GPIO_DT_SPEC_GET(LEAK_NODE, sense_gpios);
static const struct adc_dt_spec t_adc = ADC_DT_SPEC_GET(LEAK_NODE);

static K_SEM_DEFINE(wake_sem, 0, 1);
static sensor_state state;

/* Inject a sensed voltage (mV) on the emulated ADC and run one read cycle. */
static int sample_at(int mv)
{
	zassert_ok(adc_emul_const_value_set(t_adc.dev, t_adc.channel_id, mv),
		   "adc_emul set %d mV", mv);
	return leak_read(state);
}

/* Physical level driven onto the drive electrode (active-high). */
static int drive_level(void)
{
	return gpio_emul_output_get(t_drive.port, t_drive.pin);
}

/* Produce a clean rising edge on the sense line. */
static void pulse_sense(void)
{
	gpio_emul_input_set(t_sense.port, t_sense.pin, 0);
	k_sem_reset(&wake_sem);
	gpio_emul_input_set(t_sense.port, t_sense.pin, 1);
}

static void *leak_setup(void)
{
	state = sensor_state{};
	leak_init(state, &wake_sem);
	zassert_true(state.have_leak, "leak_init should mark the sensor present");
	return NULL;
}

ZTEST_SUITE(leak, NULL, leak_setup, NULL, NULL, NULL);

/* ---- Real driver via emulated ADC/GPIO ---- */

ZTEST(leak, test_wet_sample_parks_drive)
{
	zassert_ok(sample_at(1490));
	zassert_true(state.leak.valid);
	zassert_true(state.leak.wet, "1490 mV is above the 1200 mV threshold");
	zassert_equal(drive_level(), 0, "drive must be parked low while wet");
}

ZTEST(leak, test_dry_sample_holds_drive)
{
	zassert_ok(sample_at(100));
	zassert_true(state.leak.valid);
	zassert_false(state.leak.wet, "100 mV is well below threshold");
	zassert_equal(drive_level(), 1, "drive must be held active while dry");
}

ZTEST(leak, test_threshold_decision)
{
	zassert_ok(sample_at(1250));
	zassert_true(state.leak.wet, "just above threshold -> wet");

	zassert_ok(sample_at(1150));
	zassert_false(state.leak.wet, "just below threshold -> dry");
}

ZTEST(leak, test_wake_fires_when_dry)
{
	/* A dry read leaves the drive active and the edge interrupt armed. */
	zassert_ok(sample_at(100));

	pulse_sense();
	zassert_ok(k_sem_take(&wake_sem, K_NO_WAIT), "armed sense edge should wake");
}

ZTEST(leak, test_wake_suppressed_when_wet)
{
	/* A wet read parks the drive and disables the edge interrupt. */
	zassert_ok(sample_at(1490));

	pulse_sense();
	zassert_not_equal(k_sem_take(&wake_sem, K_NO_WAIT), 0,
			  "wet/parked state must not wake on a sense edge");
}

/* ---- Pure model (leak_model.h), no hardware ---- */

ZTEST(leak, test_divider_math)
{
	zassert_within(leak_sense_mv(1000000, 3000), 1485, 5,
		       "1 Mohm at 3.0 V should be ~1.49 V");
	zassert_equal(leak_water_ohm(0, 3000), INT32_MAX, "0 mV reads as open");

	const int32_t rs[] = {200000, 500000, 1000000, 1500000};
	for (size_t i = 0; i < ARRAY_SIZE(rs); i++) {
		int32_t v = leak_sense_mv(rs[i], 3000);
		int32_t r = leak_water_ohm(v, 3000);
		zassert_within(r, rs[i], rs[i] / 100 + 1000,
			       "round-trip R=%d -> %d mV -> %d ohm", rs[i], v, r);
	}
}

ZTEST(leak, test_one_megaohm_trips_default)
{
	int32_t v = leak_sense_mv(1000000, 3000);
	zassert_true(leak_is_wet(v, 1200), "1 Mohm (=%d mV) must trip the 1200 mV default", v);
}

ZTEST(leak, test_log_on_change_only)
{
	zassert_true(leak_decide(1490, 1200, false).log_change, "dry->wet logs");
	zassert_false(leak_decide(1490, 1200, true).log_change, "wet->wet silent");
	zassert_true(leak_decide(100, 1200, true).log_change, "wet->dry logs");
	zassert_false(leak_decide(100, 1200, false).log_change, "dry->dry silent");
	zassert_true(leak_decide(1490, 1200, false).wet);
	zassert_false(leak_decide(100, 1200, false).wet);
}
