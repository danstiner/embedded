/*
 * Resistive water-leak sensor (2026v4 hardware).
 *
 * Front-end (a resistive divider across the water gap):
 *
 *   DRIVE --R1(10k)--[ electrode ]~~ water (R_water) ~~[ electrode ]--R2(10k)--+-- SENSE
 *                                                                              |    (P1.07/AIN3)
 *                                                                           R3(1M)
 *                                                                              |
 *                                                                             GND
 *
 *   V_sense = V_drive * R3 / (R1 + R2 + R_water + R3) = V_drive * 1M / (R_water + 1.02M)
 *
 *   Dry (gap open, R_water = inf):        V_sense ~ 0 V
 *   R_water = 1 MΩ, V_drive ~ 3.0 V:      V_sense ~ 1.49 V
 *
 * A plain digital read trips at the GPIO high threshold (~0.7*VDD ≈ 2.1 V), i.e.
 * when R_water ≲ 400 kΩ — too coarse for a damp/high-resistance leak. So every
 * read samples the divider with the SAADC and compares against a tunable
 * software threshold (CONFIG_APP_LEAK_THRESHOLD_MV). The digital sense line is
 * kept only as an instant wake-on-wet edge interrupt for strong leaks.
 *
 * Drive / corrosion model:
 *   - Dry:  the drive is held active. The gap is open, so no current flows. A
 *           GPIO edge interrupt on the sense line wakes the device immediately
 *           when a strong leak appears; the periodic ADC sample is the sensitive
 *           backstop for weak (high-R) leaks the digital edge would miss.
 *   - Wet:  current through the water corrodes the electrodes, so between reads
 *           the drive is parked low and the (now meaningless, storm-prone) edge
 *           interrupt is disabled. Each read briefly pulses the drive, takes one
 *           ADC sample, then parks again — a very low duty cycle. When a sample
 *           reads dry the drive is re-armed for the next interval.
 */

#include "leak.h"
#include "leak_model.h"

#include <zephyr/drivers/adc.h>
#include <zephyr/drivers/gpio.h>
#include <zephyr/kernel.h>

#include <zephyr/logging/log.h>
LOG_MODULE_REGISTER(leak, LOG_LEVEL_INF);

/* This translation unit is compiled only for the leak board
 * (target_sources_ifdef CONFIG_APP_LEAK_SENSOR), which always defines the node.
 * Assert it rather than #if-guarding each body, so a Kconfig/DT mismatch fails
 * loudly instead of silently building empty stubs. */
BUILD_ASSERT(DT_NODE_HAS_STATUS(DT_NODELABEL(leak_sensor), okay),
	     "CONFIG_APP_LEAK_SENSOR is set but the leak_sensor devicetree node is missing");

static const struct gpio_dt_spec leak_drive =
	GPIO_DT_SPEC_GET(DT_NODELABEL(leak_sensor), drive_gpios);
static const struct gpio_dt_spec leak_sense =
	GPIO_DT_SPEC_GET(DT_NODELABEL(leak_sensor), sense_gpios);
static const struct adc_dt_spec leak_adc = ADC_DT_SPEC_GET(DT_NODELABEL(leak_sensor));

static struct gpio_callback leak_cb;
static struct k_sem *leak_wake_sem;

/* Last reported wet/dry state: gates log-on-change and tells leak_read() whether
 * the drive is currently held active (dry) or parked low (wet). */
static bool leak_wet_state;

/* Settle time for the high-impedance divider after energising the drive, before
 * the SAADC samples. The SAADC acquisition time (overlay) covers its own S/H. */
#define LEAK_SETTLE_US 100

/* Fallback drive level for the resistance estimate when the battery voltage is
 * unknown (the drive GPIO swings to VDD ≈ the CR2 supply). */
#define LEAK_VDRIVE_NOMINAL_MV 3000

/* Above this the resistance estimate is just noise (R ∝ 1/V_sense, so a single
 * mV near the dry floor swings it by hundreds of MΩ); report it as "open". */
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

/* Dry idle: hold the drive active and arm the wake-on-wet edge. */
static void leak_arm(void)
{
	gpio_pin_set_dt(&leak_drive, 1);
	gpio_pin_interrupt_configure_dt(&leak_sense, GPIO_INT_EDGE_TO_ACTIVE);
}

/* Wet idle: stop driving current through the water and disable the edge (the
 * line is already high, so it would only storm). */
static void leak_park(void)
{
	gpio_pin_interrupt_configure_dt(&leak_sense, GPIO_INT_DISABLE);
	gpio_pin_set_dt(&leak_drive, 0);
}

void leak_init(sensor_state &state, struct k_sem *wake_sem)
{
	if (!gpio_is_ready_dt(&leak_drive) || !gpio_is_ready_dt(&leak_sense)) {
		LOG_WRN("Leak sensor GPIOs not ready");
		return;
	}
	if (!adc_is_ready_dt(&leak_adc) || adc_channel_setup_dt(&leak_adc) != 0) {
		LOG_WRN("Leak sensor ADC not ready");
		return;
	}

	/* Start in the dry idle state: drive held active (open gap = no current). */
	gpio_pin_configure_dt(&leak_drive, GPIO_OUTPUT_ACTIVE);
	gpio_pin_configure_dt(&leak_sense, GPIO_INPUT);

	leak_wake_sem = wake_sem;
	gpio_init_callback(&leak_cb, leak_isr, BIT(leak_sense.pin));
	if (gpio_add_callback(leak_sense.port, &leak_cb) == 0) {
		gpio_pin_interrupt_configure_dt(&leak_sense, GPIO_INT_EDGE_TO_ACTIVE);
	} else {
		LOG_WRN("Leak interrupt setup failed; polling only");
	}

	state.have_leak = true;
	LOG_INF("Leak sensor ready");
}

int leak_read(sensor_state &state)
{
	if (!state.have_leak) {
		return -ENODEV;
	}

	/* Energise the drive and let the high-impedance divider settle. While dry
	 * the drive is already held active (no-op); while wet it was parked low, so
	 * this is the measurement pulse. */
	gpio_pin_set_dt(&leak_drive, 1);
	k_busy_wait(LEAK_SETTLE_US);

	int16_t raw = 0;
	struct adc_sequence seq = {
		.buffer = &raw,
		.buffer_size = sizeof(raw),
	};
	adc_sequence_init_dt(&leak_adc, &seq);

	int ret = adc_read_dt(&leak_adc, &seq);
	if (ret) {
		LOG_WRN("Leak ADC read failed: %d", ret);
		state.leak.valid = false;
		return ret;
	}

	int32_t mv = raw;
	adc_raw_to_millivolts_dt(&leak_adc, &mv);
	if (mv < 0) {
		mv = 0;
	}

	struct leak_decision d = leak_decide(mv, CONFIG_APP_LEAK_THRESHOLD_MV, leak_wet_state);

	/* Set the hardware for the intervening idle time based on this sample. */
	if (d.wet) {
		leak_park();
	} else {
		leak_arm();
	}

	state.leak.wet = d.wet;
	state.leak.timestamp = k_uptime_get();
	state.leak.valid = true;

	/* Estimate the water resistance for bench calibration, using the measured
	 * battery voltage as the drive level when available (the drive GPIO swings
	 * to VDD ≈ the CR2 supply). The estimate is only meaningful in the wet
	 * range; a dry/open gap is reported as such rather than a noisy huge value. */
	int32_t vdrive = (state.battery.valid && state.battery.millivolts > 0)
				 ? (int32_t)state.battery.millivolts
				 : LEAK_VDRIVE_NOMINAL_MV;
	int32_t r_ohm = leak_water_ohm(mv, vdrive);
	if (r_ohm >= LEAK_R_OPEN_OHM) {
		LOG_INF("Leak: %d mV (open @ %d mV)", mv, vdrive);
	} else {
		LOG_INF("Leak: %d mV (~%d kohm @ %d mV)", mv, r_ohm / 1000, vdrive);
	}

	if (d.log_change) {
		LOG_INF("Leak: %s (%d mV)", d.wet ? "WET" : "dry", mv);
		leak_wet_state = d.wet;
	}
	return 0;
}
