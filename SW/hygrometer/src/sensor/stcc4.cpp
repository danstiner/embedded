/*
 * Minimal STCC4 CO2 sensor driver over raw I2C
 *
 * Reference: https://github.com/Sensirion/embedded-i2c-stcc4
 */

#include "stcc4.h"

#include <zephyr/drivers/i2c.h>
#include <zephyr/kernel.h>
#include <zephyr/logging/log.h>

LOG_MODULE_REGISTER(stcc4, LOG_LEVEL_INF);

/* I2C commands (big-endian) */
#define CMD_GET_PRODUCT_ID        0x365B
#define CMD_EXIT_SLEEP            0x00 /* Single byte! */
#define CMD_SET_RHT_COMP          0xE000
#define CMD_SET_PRESSURE_COMP     0xE016
#define CMD_ENTER_SLEEP           0x3650
#define CMD_MEASURE_SINGLE_SHOT   0x219D
#define CMD_READ_MEASUREMENT      0xEC05
#define CMD_FORCE_RECALIBRATION   0x362F
#define CMD_PERFORM_CONDITIONING  0x29BC
#define CMD_PERFORM_FACTORY_RESET 0x3632
#define CMD_PERFORM_SELF_TEST     0x278C
#define CMD_DISABLE_TESTING_MODE  0x3F3D

/* Sensirion CRC-8: polynomial 0x31, init 0xFF */
static uint8_t sensirion_crc8(const uint8_t *data, size_t len)
{
	uint8_t crc = 0xFF;

	for (size_t i = 0; i < len; i++) {
		crc ^= data[i];
		for (int bit = 0; bit < 8; bit++) {
			if (crc & 0x80) {
				crc = (crc << 1) ^ 0x31;
			} else {
				crc <<= 1;
			}
		}
	}
	return crc;
}

/* Send a 2-byte command with no data */
static int send_cmd(const struct device *i2c, uint16_t cmd)
{
	uint8_t buf[2] = {(uint8_t)(cmd >> 8), (uint8_t)(cmd & 0xFF)};

	return i2c_write(i2c, buf, sizeof(buf), STCC4_I2C_ADDR);
}

/* Read words from sensor, validating CRC per 2-byte word.
 * out_data must have room for (num_words * 2) bytes. */
static int read_words(const struct device *i2c, uint8_t *out_data, size_t num_words)
{
	/* Each word is 3 bytes on wire: MSB, LSB, CRC */
	size_t wire_len = num_words * 3;
	uint8_t wire_buf[18]; /* max 6 words */

	if (wire_len > sizeof(wire_buf)) {
		return -EINVAL;
	}

	int ret = i2c_read(i2c, wire_buf, wire_len, STCC4_I2C_ADDR);
	if (ret) {
		return ret;
	}

	for (size_t i = 0; i < num_words; i++) {
		uint8_t *word = &wire_buf[i * 3];
		uint8_t crc = sensirion_crc8(word, 2);

		if (crc != word[2]) {
			LOG_ERR("CRC mismatch: word %zu got 0x%02x expected 0x%02x", i, word[2],
				crc);
			return -EIO;
		}
		out_data[i * 2] = word[0];
		out_data[i * 2 + 1] = word[1];
	}

	return 0;
}

bool stcc4_probe(const struct device *i2c)
{
	int ret = send_cmd(i2c, CMD_GET_PRODUCT_ID);
	if (ret) {
		LOG_ERR("STCC4 get_product_id cmd failed: %d", ret);
		return false;
	}

	k_msleep(1);

	/* Read product_id (4 bytes = 2 words) + serial (8 bytes = 4 words) */
	uint8_t data[12];

	ret = read_words(i2c, data, 6);
	if (ret) {
		LOG_ERR("STCC4 product_id read failed: %d", ret);
		return false;
	}

	uint32_t product_id = ((uint32_t)data[0] << 24) | ((uint32_t)data[1] << 16) |
			      ((uint32_t)data[2] << 8) | data[3];
	LOG_INF("STCC4 product_id=0x%08X", product_id);

	return true;
}

int stcc4_exit_sleep(const struct device *i2c)
{
	/* exit_sleep_mode is a single payload byte 0x00 that is NOT acknowledged */
	uint8_t cmd = CMD_EXIT_SLEEP;

	/* Zephyr I2C always expects acknowledgement, so ignore the timeout */
	(void)i2c_write(i2c, &cmd, 1, STCC4_I2C_ADDR);

	k_msleep(5);
	return 0;
}

int stcc4_enter_sleep(const struct device *i2c)
{
	int ret = send_cmd(i2c, CMD_ENTER_SLEEP);
	if (ret) {
		LOG_ERR("STCC4 enter_sleep failed: %d", ret);
		return ret;
	}

	k_msleep(1);
	return 0;
}

int stcc4_set_rht_compensation(const struct device *i2c, uint16_t raw_temp, uint16_t raw_humidity)
{
	uint8_t buf[8];

	/* Command */
	buf[0] = (uint8_t)(CMD_SET_RHT_COMP >> 8);
	buf[1] = (uint8_t)(CMD_SET_RHT_COMP & 0xFF);
	/* Temperature word + CRC */
	buf[2] = (uint8_t)(raw_temp >> 8);
	buf[3] = (uint8_t)(raw_temp & 0xFF);
	buf[4] = sensirion_crc8(&buf[2], 2);
	/* Humidity word + CRC */
	buf[5] = (uint8_t)(raw_humidity >> 8);
	buf[6] = (uint8_t)(raw_humidity & 0xFF);
	buf[7] = sensirion_crc8(&buf[5], 2);

	int ret = i2c_write(i2c, buf, sizeof(buf), STCC4_I2C_ADDR);
	if (ret) {
		LOG_ERR("set_rht_compensation failed: %d", ret);
		return ret;
	}

	k_msleep(1);
	return 0;
}

int stcc4_set_pressure_compensation(const struct device *i2c, uint16_t pressure_pa_div2)
{
	uint8_t buf[5];

	/* Command */
	buf[0] = (uint8_t)(CMD_SET_PRESSURE_COMP >> 8);
	buf[1] = (uint8_t)(CMD_SET_PRESSURE_COMP & 0xFF);
	/* Pressure word + CRC */
	buf[2] = (uint8_t)(pressure_pa_div2 >> 8);
	buf[3] = (uint8_t)(pressure_pa_div2 & 0xFF);
	buf[4] = sensirion_crc8(&buf[2], 2);

	int ret = i2c_write(i2c, buf, sizeof(buf), STCC4_I2C_ADDR);
	if (ret) {
		LOG_ERR("set_pressure_compensation failed: %d", ret);
		return ret;
	}

	k_msleep(1);
	return 0;
}

int stcc4_measure(const struct device *i2c, int16_t &co2_ppm, uint16_t *status)
{
	int ret;

	/* Trigger single-shot measurement */
	ret = send_cmd(i2c, CMD_MEASURE_SINGLE_SHOT);
	if (ret) {
		LOG_ERR("measure_single_shot failed: %d", ret);
		return ret;
	}

	k_msleep(500);

	/* Read measurement */
	ret = send_cmd(i2c, CMD_READ_MEASUREMENT);
	if (ret) {
		LOG_ERR("read_measurement cmd failed: %d", ret);
		return ret;
	}

	k_msleep(1);

	/* Response: co2(2) + temp(2) + hum(2) + status(2) = 4 words */
	uint8_t data[8];

	ret = read_words(i2c, data, 4);
	if (ret) {
		LOG_ERR("read_measurement data failed: %d", ret);
		return ret;
	}

	/* Datasheet Table 11: CO2 output is signed int16 ppm, used directly (C = Output). */
	co2_ppm = (int16_t)(((uint16_t)data[0] << 8) | data[1]);

	/* Status word at data[6..7]. Datasheet §3.4.13: testing mode = 2nd MSB of the
	 * status LSB byte (STCC4_STATUS_TESTING_MODE, 0x0040). Any non-zero status means the
	 * reading should not be trusted (see sensor_read_stcc4). */
	if (status) {
		*status = ((uint16_t)data[6] << 8) | data[7];
	}

	return 0;
}

int stcc4_start_conditioning(const struct device *i2c)
{
	int ret = send_cmd(i2c, CMD_PERFORM_CONDITIONING);
	if (ret) {
		LOG_ERR("start_conditioning failed: %d", ret);
		return ret;
	}

	LOG_INF("STCC4 conditioning started (~22s)");

	return 0;
}

int stcc4_force_recalibration(const struct device *i2c, uint16_t target_co2_ppm,
			      uint16_t &correction)
{
	uint8_t buf[5];

	/* Command */
	buf[0] = (uint8_t)(CMD_FORCE_RECALIBRATION >> 8);
	buf[1] = (uint8_t)(CMD_FORCE_RECALIBRATION & 0xFF);
	/* Datasheet Table 11: FRC target input is the CO2 ppm value directly
	 * (Input = C_Target), no scaling. */
	buf[2] = (uint8_t)(target_co2_ppm >> 8);
	buf[3] = (uint8_t)(target_co2_ppm & 0xFF);
	buf[4] = sensirion_crc8(&buf[2], 2);

	int ret = i2c_write(i2c, buf, sizeof(buf), STCC4_I2C_ADDR);
	if (ret) {
		LOG_ERR("force_recalibration write failed: %d", ret);
		return ret;
	}

	/* Sensor needs ~90ms to perform FRC */
	k_msleep(100);

	/* Read 1-word result: raw correction value (decode in caller) */
	uint8_t data[2];

	ret = read_words(i2c, data, 1);
	if (ret) {
		LOG_ERR("force_recalibration read failed: %d", ret);
		return ret;
	}

	correction = ((uint16_t)data[0] << 8) | data[1];

	if (correction == 0xFFFF) {
		LOG_ERR("FRC failed (sensor returned 0xFFFF)");
		return -EIO;
	}

	/* Datasheet Table 11: applied correction C_FRC = Output - 32768 (ppm, signed). */
	int delta = correction - 32768;

	/* A correction this large means the FRC railed: the sensor had no valid reading to
	 * correct against (e.g. it was railed at the placeholder/output floor). Reject it
	 * rather than bake in a garbage offset. */
	if (delta > 3000 || delta < -3000) {
		LOG_ERR("FRC railed (raw=0x%04X, correction=%d ppm) — no valid reading", correction,
			delta);
		return -EIO;
	}

	LOG_INF("FRC raw=0x%04X, correction=%d ppm", correction, delta);
	return 0;
}

int stcc4_disable_testing_mode(const struct device *i2c)
{
	int ret = send_cmd(i2c, CMD_DISABLE_TESTING_MODE);
	if (ret) {
		LOG_ERR("STCC4 disable_testing_mode failed: %d", ret);
		return ret;
	}

	k_msleep(1);
	return 0;
}

int stcc4_self_test(const struct device *i2c, uint16_t *result)
{
	int ret = send_cmd(i2c, CMD_PERFORM_SELF_TEST);
	if (ret) {
		LOG_ERR("STCC4 self_test cmd failed: %d", ret);
		return ret;
	}

	k_msleep(360); /* datasheet §3.4.12 execution time */

	uint8_t data[2];

	ret = read_words(i2c, data, 1);
	if (ret) {
		LOG_ERR("STCC4 self_test read failed: %d", ret);
		return ret;
	}

	/* Datasheet §3.4.12: 0x0000 = pass; non-zero bits flag faults (bit0 supply,
	 * bits3:1 debug, bit4 SHT not connected, bits6:5 memory). Caller logs/interprets. */
	if (result) {
		*result = ((uint16_t)data[0] << 8) | data[1];
	}

	return 0;
}

int stcc4_perform_factory_reset(const struct device *i2c)
{
	int ret = send_cmd(i2c, CMD_PERFORM_FACTORY_RESET);
	if (ret) {
		LOG_ERR("STCC4 factory_reset cmd failed: %d", ret);
		return ret;
	}

	k_msleep(90); /* datasheet §3.4.11 execution time */

	/* Datasheet §3.4.11: read-back word 0 = pass, 0xFFFF = command failed. */
	uint8_t data[2];

	ret = read_words(i2c, data, 1);
	if (ret) {
		LOG_ERR("STCC4 factory_reset read failed: %d", ret);
		return ret;
	}

	uint16_t status = ((uint16_t)data[0] << 8) | data[1];
	if (status == 0xFFFF) {
		LOG_ERR("STCC4 factory_reset reported failure");
		return -EIO;
	}

	return 0;
}
