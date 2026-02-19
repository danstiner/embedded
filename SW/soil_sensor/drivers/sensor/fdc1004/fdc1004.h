#ifndef DRIVERS_SENSOR_FDC1004_H_
#define DRIVERS_SENSOR_FDC1004_H_

#include <zephyr/drivers/sensor.h>
#include <zephyr/drivers/i2c.h>

/* Custom sensor channels starting from private range */
enum fdc1004_channel {
	SENSOR_CHAN_FDC1004_CAPACITANCE_CH0 = SENSOR_CHAN_PRIV_START,
	SENSOR_CHAN_FDC1004_CAPACITANCE_CH1,
	SENSOR_CHAN_FDC1004_CAPACITANCE_CH2,
	SENSOR_CHAN_FDC1004_CAPACITANCE_CH3,
};

/* Register addresses */
#define FDC1004_REG_MEAS_MSB(n)     (0x00 + (n) * 2) /* n = 0..3 */
#define FDC1004_REG_MEAS_LSB(n)     (0x01 + (n) * 2)
#define FDC1004_REG_CONF_MEAS(n)    (0x08 + (n)) /* n = 0..3 */
#define FDC1004_REG_FDC_CONF        0x0C
#define FDC1004_REG_MANUFACTURER_ID 0xFE
#define FDC1004_REG_DEVICE_ID       0xFF

/* Expected ID values */
#define FDC1004_MANUFACTURER_ID 0x5449
#define FDC1004_DEVICE_ID       0x1004

/* FDC_CONF bits */
#define FDC1004_FDC_CONF_RST     BIT(15)
#define FDC1004_FDC_CONF_MEAS(n) BIT(7 - (n)) /* trigger meas n (0..3) */
#define FDC1004_FDC_CONF_DONE(n) BIT(3 - (n)) /* done flag for meas n (0..3) */

/* CONF_MEASx bit fields */
#define FDC1004_CONF_CHA(x)    ((x) << 13)
#define FDC1004_CONF_CHB(x)    ((x) << 10)
#define FDC1004_CONF_CAPDAC(x) ((x) << 5)

/* Max channels */
#define FDC1004_MAX_CHANNELS 4

/* CAPDAC step in milli-pF for integer math: 3.125 pF = 3125000 micro-pF */
#define FDC1004_CAPDAC_STEP_UPF 3125000

struct fdc1004_channel_config {
	uint8_t cha;
	uint8_t chb;
	uint8_t capdac;
};

struct fdc1004_config {
	struct i2c_dt_spec i2c;
	uint8_t sample_rate;
	uint8_t num_channels;
	const struct fdc1004_channel_config *ch_cfg;
};

struct fdc1004_data {
	/* Raw 24-bit readings per channel */
	int32_t raw[FDC1004_MAX_CHANNELS];
	uint8_t num_channels;
};

#endif /* DRIVERS_SENSOR_FDC1004_H_ */
