/*
 * Two-way resistive water-leak sensor (2026v5 hardware).
 *
 * Both contacts have the same front end, so either can drive while the other
 * senses and the current through the water can be reversed:
 *
 *   A ---R1(10k)--[ contact A ]~~ water (R_water) ~~[ contact B ]--R2(10k)--- B
 *   |   (AIN, edge)                                             (AIN, edge)   |
 *  R3(1M)                                                                  R4(1M)
 *   |                                                                         |
 *  A_RET                                                                    B_RET
 *
 * "A drives": A and A_RET high, B an input, B_RET low. R3 then has no voltage
 * across it and carries nothing; B sees the one-way board's divider (see
 * leak_model.h) with R4 as the pull-down. "B drives" is the mirror image.
 *
 * Pin states:
 *   - Armed (dry idle): one side drives. The gap is open, so no current flows;
 *     a rising edge on the sensing pin wakes the device on a strong leak. The
 *     driving side alternates from read to read, so neither contact is always
 *     the positive one.
 *   - Measuring: each read samples the sensing side with the SAADC in both
 *     directions, equal time each way, and decides on the mean of the two.
 *   - Parked (wet idle): all four pins low, edge interrupt off. No current
 *     flows through the water between reads.
 */

#include "leak.h"
#include "leak_model.h"

#include <zephyr/drivers/adc.h>
#include <zephyr/drivers/gpio.h>
#include <zephyr/kernel.h>
#include <zephyr/sys/util.h>

#include <zephyr/logging/log.h>
LOG_MODULE_REGISTER(leak, LOG_LEVEL_INF);

#define LEAK_NODE DT_NODELABEL(leak_sensor)

BUILD_ASSERT(DT_NODE_HAS_STATUS(LEAK_NODE, okay),
	     "The two-way leak driver is selected but the leak_sensor devicetree node is missing");
BUILD_ASSERT(DT_SAME_NODE(DT_GPIO_CTLR(LEAK_NODE, a_gpios), DT_GPIO_CTLR(LEAK_NODE, b_gpios)),
	     "a-gpios and b-gpios must be on one port: one callback covers both sensing pins");

struct leak_side {
	struct gpio_dt_spec pin;
	struct gpio_dt_spec ret;
	struct adc_dt_spec adc;
};

static const struct leak_side side_a = {
	GPIO_DT_SPEC_GET(LEAK_NODE, a_gpios),
	GPIO_DT_SPEC_GET(LEAK_NODE, a_return_gpios),
	ADC_DT_SPEC_GET_BY_NAME(LEAK_NODE, a),
};
static const struct leak_side side_b = {
	GPIO_DT_SPEC_GET(LEAK_NODE, b_gpios),
	GPIO_DT_SPEC_GET(LEAK_NODE, b_return_gpios),
	ADC_DT_SPEC_GET_BY_NAME(LEAK_NODE, b),
};

static struct gpio_callback leak_cb;
static struct k_sem *leak_wake_sem;

/* Last reported wet/dry state: gates log-on-change and is the idle state to
 * return to when a read fails. */
static bool leak_wet_state;

/* Whether A was the driving side the last time the sensor was armed. */
static bool leak_a_armed;

/* A pin that was driving sits at VDD; left to fall through its 1 MΩ it would
 * need about 140 µs. Pulled low through the pins first, both nodes start from
 * zero and the divider settles within LEAK_SETTLE_US even at 10 MΩ. */
#define LEAK_DISCHARGE_US 10
#define LEAK_SETTLE_US    100

/* Fallback drive level for the resistance estimate when the battery voltage is
 * unknown (the driving GPIO swings to VDD ≈ the CR2 supply). */
#define LEAK_VDRIVE_NOMINAL_MV 3000

/* Above this the resistance estimate is just noise; report it as "open". */
#define LEAK_R_OPEN_OHM (10 * 1000 * 1000)

static void leak_isr(const struct device *port, struct gpio_callback *cb, uint32_t pins)
{
	ARG_UNUSED(port);
	ARG_UNUSED(cb);
	ARG_UNUSED(pins);

	if (leak_wake_sem != nullptr) {
		k_sem_give(leak_wake_sem);
	}
}

static void leak_edges_off(void)
{
	gpio_pin_interrupt_configure_dt(&side_a.pin, GPIO_INT_DISABLE);
	gpio_pin_interrupt_configure_dt(&side_b.pin, GPIO_INT_DISABLE);
}

static void leak_all_low(void)
{
	gpio_pin_configure_dt(&side_a.pin, GPIO_OUTPUT_INACTIVE);
	gpio_pin_configure_dt(&side_a.ret, GPIO_OUTPUT_INACTIVE);
	gpio_pin_configure_dt(&side_b.pin, GPIO_OUTPUT_INACTIVE);
	gpio_pin_configure_dt(&side_b.ret, GPIO_OUTPUT_INACTIVE);
}

/* Discharge both nodes, then let one side drive. The caller has the edge
 * interrupts off. */
static void leak_set_direction(bool a_drives, bool wake_on_wet)
{
	const struct leak_side &drv = a_drives ? side_a : side_b;
	const struct leak_side &sns = a_drives ? side_b : side_a;

	leak_all_low();
	k_busy_wait(LEAK_DISCHARGE_US);

	gpio_pin_configure_dt(&sns.pin, GPIO_INPUT);
	if (wake_on_wet) {
		/* Enable the edge before driving. The sensing node was just pulled
		 * to zero, so a contact that is already wet rises after the
		 * interrupt is on and still wakes the device. */
		gpio_pin_interrupt_configure_dt(&sns.pin, GPIO_INT_EDGE_TO_ACTIVE);
	}
	gpio_pin_set_dt(&drv.ret, 1);
	gpio_pin_set_dt(&drv.pin, 1);
}

static int leak_sample(const struct leak_side &sns, int32_t *mv)
{
	int16_t raw = 0;
	struct adc_sequence seq = {
		.buffer = &raw,
		.buffer_size = sizeof(raw),
	};
	adc_sequence_init_dt(&sns.adc, &seq);

	int ret = adc_read_dt(&sns.adc, &seq);
	if (ret) {
		return ret;
	}

	int32_t v = raw;
	adc_raw_to_millivolts_dt(&sns.adc, &v);
	*mv = MAX(v, 0);
	return 0;
}

void leak_init(sensor_state &state, struct k_sem *wake_sem)
{
	if (!gpio_is_ready_dt(&side_a.pin) || !gpio_is_ready_dt(&side_a.ret) ||
	    !gpio_is_ready_dt(&side_b.pin) || !gpio_is_ready_dt(&side_b.ret)) {
		LOG_WRN("Leak sensor GPIOs not ready");
		return;
	}
	if (!adc_is_ready_dt(&side_a.adc) || adc_channel_setup_dt(&side_a.adc) != 0 ||
	    !adc_is_ready_dt(&side_b.adc) || adc_channel_setup_dt(&side_b.adc) != 0) {
		LOG_WRN("Leak sensor ADC not ready");
		return;
	}

	leak_wake_sem = wake_sem;
	gpio_init_callback(&leak_cb, leak_isr, BIT(side_a.pin.pin) | BIT(side_b.pin.pin));
	if (gpio_add_callback(side_a.pin.port, &leak_cb) != 0) {
		LOG_WRN("Leak interrupt setup failed; polling only");
	}

	leak_a_armed = true;
	leak_set_direction(leak_a_armed, true);

	state.have_leak = true;
	LOG_INF("Leak sensor ready");
}

int leak_read(sensor_state &state)
{
	if (!state.have_leak) {
		return -ENODEV;
	}

	leak_edges_off();

	/* Sense voltage with A driving (read on B), then with B driving (read on A). */
	int32_t mv_a_drives = 0;
	int32_t mv_b_drives = 0;

	leak_set_direction(true, false);
	k_busy_wait(LEAK_SETTLE_US);
	int ret = leak_sample(side_b, &mv_a_drives);
	if (ret == 0) {
		leak_set_direction(false, false);
		k_busy_wait(LEAK_SETTLE_US);
		ret = leak_sample(side_a, &mv_b_drives);
	}
	if (ret) {
		LOG_WRN("Leak ADC read failed: %d", ret);
		state.leak.valid = false;
		if (leak_wet_state) {
			leak_all_low();
		} else {
			leak_set_direction(leak_a_armed, true);
		}
		return ret;
	}

	int32_t mv = leak_mean_mv(mv_a_drives, mv_b_drives);
	struct leak_decision d = leak_decide(mv, CONFIG_APP_LEAK_THRESHOLD_MV, leak_wet_state);

	if (d.wet) {
		/* Parked: the edges are already off. */
		leak_all_low();
	} else {
		leak_a_armed = !leak_a_armed;
		leak_set_direction(leak_a_armed, true);
	}

	state.leak.wet = d.wet;
	state.leak.valid = true;

	/* Resistance estimate for bench calibration, as on the one-way board. */
	int32_t vdrive = (state.battery_voltage.valid && state.battery_voltage.millivolts > 0)
				 ? (int32_t)state.battery_voltage.millivolts
				 : LEAK_VDRIVE_NOMINAL_MV;
	int32_t r_ohm = leak_water_ohm(mv, vdrive);
	if (r_ohm >= LEAK_R_OPEN_OHM) {
		LOG_INF("Leak: %d mV (A>B %d, B>A %d; open @ %d mV)", mv, mv_a_drives, mv_b_drives,
			vdrive);
	} else {
		LOG_INF("Leak: %d mV (A>B %d, B>A %d; ~%d kohm @ %d mV)", mv, mv_a_drives,
			mv_b_drives, r_ohm / 1000, vdrive);
	}

	if (leak_directions_disagree(mv_a_drives, mv_b_drives, CONFIG_APP_LEAK_THRESHOLD_MV)) {
		LOG_WRN("Leak: directions disagree (A>B %d mV, B>A %d mV): water reads alike both "
			"ways, check the SAADC channels and the return pins",
			mv_a_drives, mv_b_drives);
	}

	if (d.log_change) {
		LOG_INF("Leak: %s (%d mV)", d.wet ? "WET" : "dry", mv);
		leak_wet_state = d.wet;
	}
	return 0;
}
