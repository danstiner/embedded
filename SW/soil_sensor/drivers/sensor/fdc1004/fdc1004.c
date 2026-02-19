#define DT_DRV_COMPAT ti_fdc1004

#include <zephyr/kernel.h>
#include <zephyr/drivers/sensor.h>
#include <zephyr/drivers/i2c.h>
#include <zephyr/logging/log.h>
#include <zephyr/sys/byteorder.h>

#include "fdc1004.h"

LOG_MODULE_REGISTER(fdc1004, CONFIG_SENSOR_LOG_LEVEL);

static int fdc1004_reg_read(const struct i2c_dt_spec *i2c, uint8_t reg, uint16_t *val)
{
	uint8_t buf[2];
	int ret;

	ret = i2c_burst_read_dt(i2c, reg, buf, sizeof(buf));
	if (ret < 0) {
		return ret;
	}

	*val = sys_get_be16(buf);
	return 0;
}

static int fdc1004_reg_write(const struct i2c_dt_spec *i2c, uint8_t reg, uint16_t val)
{
	uint8_t buf[2];

	sys_put_be16(val, buf);
	return i2c_burst_write_dt(i2c, reg, buf, sizeof(buf));
}

static int fdc1004_init(const struct device *dev)
{
	const struct fdc1004_config *cfg = dev->config;
	struct fdc1004_data *data = dev->data;
	uint16_t mfg_id, dev_id;
	int ret;

	if (!i2c_is_ready_dt(&cfg->i2c)) {
		LOG_ERR("I2C bus not ready");
		return -ENODEV;
	}

	/* Verify manufacturer and device ID */
	ret = fdc1004_reg_read(&cfg->i2c, FDC1004_REG_MANUFACTURER_ID, &mfg_id);
	if (ret < 0) {
		LOG_ERR("Failed to read manufacturer ID: %d", ret);
		return ret;
	}

	ret = fdc1004_reg_read(&cfg->i2c, FDC1004_REG_DEVICE_ID, &dev_id);
	if (ret < 0) {
		LOG_ERR("Failed to read device ID: %d", ret);
		return ret;
	}

	if (mfg_id != FDC1004_MANUFACTURER_ID || dev_id != FDC1004_DEVICE_ID) {
		LOG_ERR("Unexpected ID: mfg=0x%04x dev=0x%04x (expected 0x%04x/0x%04x)", mfg_id,
			dev_id, FDC1004_MANUFACTURER_ID, FDC1004_DEVICE_ID);
		return -ENODEV;
	}

	LOG_INF("FDC1004 found (mfg=0x%04x dev=0x%04x)", mfg_id, dev_id);

	/* Software reset */
	ret = fdc1004_reg_write(&cfg->i2c, FDC1004_REG_FDC_CONF, FDC1004_FDC_CONF_RST);
	if (ret < 0) {
		LOG_ERR("Reset failed: %d", ret);
		return ret;
	}
	k_msleep(10);

	/* Configure measurement channels from DT */
	data->num_channels = cfg->num_channels;

	for (uint8_t i = 0; i < cfg->num_channels; i++) {
		const struct fdc1004_channel_config *ch = &cfg->ch_cfg[i];
		uint16_t conf = FDC1004_CONF_CHA(ch->cha) | FDC1004_CONF_CHB(ch->chb) |
				FDC1004_CONF_CAPDAC(ch->capdac);

		ret = fdc1004_reg_write(&cfg->i2c, FDC1004_REG_CONF_MEAS(i), conf);
		if (ret < 0) {
			LOG_ERR("Failed to configure channel %d: %d", i, ret);
			return ret;
		}

		LOG_INF("CH%d: CHA=%d CHB=%d CAPDAC=%d", i, ch->cha, ch->chb, ch->capdac);
	}

	return 0;
}

static int fdc1004_sample_fetch(const struct device *dev, enum sensor_channel chan)
{
	const struct fdc1004_config *cfg = dev->config;
	struct fdc1004_data *data = dev->data;
	uint16_t trigger = 0;
	uint16_t conf;
	int ret;

	/* Build trigger mask for all configured channels */
	for (uint8_t i = 0; i < data->num_channels; i++) {
		trigger |= FDC1004_FDC_CONF_MEAS(i);
	}

	/* Set sample rate and trigger */
	trigger |= (cfg->sample_rate & 0x3) << 10;

	ret = fdc1004_reg_write(&cfg->i2c, FDC1004_REG_FDC_CONF, trigger);
	if (ret < 0) {
		LOG_ERR("Failed to trigger measurement: %d", ret);
		return ret;
	}

	/* Poll for all channels done (timeout ~100ms) */
	uint16_t done_mask = 0;
	for (uint8_t i = 0; i < data->num_channels; i++) {
		done_mask |= FDC1004_FDC_CONF_DONE(i);
	}

	for (int attempt = 0; attempt < 100; attempt++) {
		k_msleep(1);

		ret = fdc1004_reg_read(&cfg->i2c, FDC1004_REG_FDC_CONF, &conf);
		if (ret < 0) {
			return ret;
		}

		if ((conf & done_mask) == done_mask) {
			break;
		}
	}

	if ((conf & done_mask) != done_mask) {
		LOG_ERR("Measurement timeout (conf=0x%04x, need=0x%04x)", conf, done_mask);
		return -ETIMEDOUT;
	}

	/* Read 24-bit results from MSB/LSB register pairs */
	for (uint8_t i = 0; i < data->num_channels; i++) {
		uint16_t msb, lsb;

		ret = fdc1004_reg_read(&cfg->i2c, FDC1004_REG_MEAS_MSB(i), &msb);
		if (ret < 0) {
			return ret;
		}

		ret = fdc1004_reg_read(&cfg->i2c, FDC1004_REG_MEAS_LSB(i), &lsb);
		if (ret < 0) {
			return ret;
		}

		/* Combine: MSB[15:0] = data[23:8], LSB[15:8] = data[7:0] */
		int32_t raw = ((int32_t)msb << 8) | (lsb >> 8);

		/* Sign-extend 24-bit to 32-bit */
		if (raw & 0x800000) {
			raw |= 0xFF000000;
		}

		data->raw[i] = raw;
	}

	return 0;
}

static int fdc1004_channel_get(const struct device *dev, enum sensor_channel chan,
			       struct sensor_value *val)
{
	const struct fdc1004_config *cfg = dev->config;
	struct fdc1004_data *data = dev->data;
	int ch_idx;

	switch ((int)chan) {
	case SENSOR_CHAN_FDC1004_CAPACITANCE_CH0:
		ch_idx = 0;
		break;
	case SENSOR_CHAN_FDC1004_CAPACITANCE_CH1:
		ch_idx = 1;
		break;
	case SENSOR_CHAN_FDC1004_CAPACITANCE_CH2:
		ch_idx = 2;
		break;
	case SENSOR_CHAN_FDC1004_CAPACITANCE_CH3:
		ch_idx = 3;
		break;
	default:
		return -ENOTSUP;
	}

	if (ch_idx >= data->num_channels) {
		return -EINVAL;
	}

	/*
	 * C(pF) = raw / 2^19 + CAPDAC * 3.125
	 *
	 * To avoid floating point:
	 * C(pF) = raw / 524288 + CAPDAC * 3125 / 1000
	 *
	 * We compute in micro-pF (1e-6 pF) for precision, then convert to sensor_value:
	 *   val1 = integer pF, val2 = fractional in millionths of pF
	 *
	 * micro_pf = raw * 1000000 / 524288 + capdac * 3125000
	 */
	int64_t raw = data->raw[ch_idx];
	uint8_t capdac = cfg->ch_cfg[ch_idx].capdac;

	int64_t micro_pf = (raw * 1000000LL) / 524288LL + (int64_t)capdac * FDC1004_CAPDAC_STEP_UPF;

	val->val1 = (int32_t)(micro_pf / 1000000LL);
	val->val2 = (int32_t)(micro_pf % 1000000LL);

	/* Normalize negative fractional part */
	if (val->val2 < 0 && val->val1 > 0) {
		val->val1--;
		val->val2 += 1000000;
	} else if (val->val2 > 0 && val->val1 < 0) {
		val->val1++;
		val->val2 -= 1000000;
	}

	return 0;
}

static DEVICE_API(sensor, fdc1004_api) = {
	.sample_fetch = fdc1004_sample_fetch,
	.channel_get = fdc1004_channel_get,
};

/* Parse channel child nodes from DT */
#define FDC1004_CHANNEL_CFG(node)                                                                  \
	{                                                                                          \
		.cha = DT_PROP(node, cha),                                                         \
		.chb = DT_PROP(node, chb),                                                         \
		.capdac = DT_PROP(node, capdac),                                                   \
	},

#define FDC1004_INIT(inst)                                                                         \
	static const struct fdc1004_channel_config fdc1004_ch_cfg_##inst[] = {                     \
		DT_INST_FOREACH_CHILD(inst, FDC1004_CHANNEL_CFG)};                                 \
                                                                                                   \
	static const struct fdc1004_config fdc1004_cfg_##inst = {                                  \
		.i2c = I2C_DT_SPEC_INST_GET(inst),                                                 \
		.sample_rate = DT_INST_PROP_OR(inst, sample_rate, 0),                              \
		.num_channels = ARRAY_SIZE(fdc1004_ch_cfg_##inst),                                 \
		.ch_cfg = fdc1004_ch_cfg_##inst,                                                   \
	};                                                                                         \
                                                                                                   \
	static struct fdc1004_data fdc1004_data_##inst;                                            \
                                                                                                   \
	SENSOR_DEVICE_DT_INST_DEFINE(inst, fdc1004_init, NULL, &fdc1004_data_##inst,               \
				     &fdc1004_cfg_##inst, POST_KERNEL,                             \
				     CONFIG_SENSOR_INIT_PRIORITY, &fdc1004_api);

DT_INST_FOREACH_STATUS_OKAY(FDC1004_INIT)
