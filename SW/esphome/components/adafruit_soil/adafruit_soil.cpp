#include "adafruit_soil.h"

#include "esphome/core/hal.h"
#include "esphome/core/log.h"

namespace esphome
{
namespace adafruit_soil
{

static const char *const TAG = "adafruit_soil";

void StemmaSoilSensor::setup()
{
	ESP_LOGCONFIG("adafruit_soil", "Setting up Adafruit STEMMA soil sensor...");

	// Start the seesaw.
	// Perform software reset.
	ESP_LOGD("adafruit_soil", "Sending software reset command...");
	this->write_seesaw8(SEESAW_STATUS_BASE, SEESAW_STATUS_SWRST, 0xFF);
	delay(500);

	// Check for seesaw.
	ESP_LOGD("adafruit_soil", "Reading hardware ID...");
	uint8_t c = this->read_seesaw8(SEESAW_STATUS_BASE, SEESAW_STATUS_HW_ID);
	ESP_LOGD("adafruit_soil", "Hardware ID read: 0x%02X (expected: 0x%02X)", c,
		 SEESAW_HW_ID_CODE);

	if (c != SEESAW_HW_ID_CODE) {
		ESP_LOGE("adafruit_soil",
			 "Failed to connect to soil sensor. Expected HW ID 0x%02X, got 0x%02X",
			 SEESAW_HW_ID_CODE, c);
		this->mark_failed();
		return;
	}

	// Check what modules are available
	ESP_LOGD("adafruit_soil", "Reading seesaw options/capabilities...");
	uint8_t options = this->read_seesaw8(SEESAW_STATUS_BASE, SEESAW_STATUS_OPTIONS);
	ESP_LOGD("adafruit_soil", "Seesaw options: 0x%02X", options);

	// Check version
	ESP_LOGD("adafruit_soil", "Reading seesaw version...");
	uint8_t version = this->read_seesaw8(SEESAW_STATUS_BASE, SEESAW_STATUS_VERSION);
	ESP_LOGD("adafruit_soil", "Seesaw version: 0x%02X", version);

	ESP_LOGI("adafruit_soil", "Successfully initialized STEMMA soil sensor");
}

void StemmaSoilSensor::dump_config()
{
	ESP_LOGCONFIG("adafruit_soil", "Adafruit STEMMA Soil Sensor:");
	LOG_I2C_DEVICE(this);
	if (this->is_failed()) {
		ESP_LOGE("adafruit_soil", "Communication with STEMMA soil sensor failed!");
	}
	LOG_UPDATE_INTERVAL(this);
}

void StemmaSoilSensor::update()
{
	if (this->is_failed()) {
		return;
	}

	float tempC = this->read_temperature();
	uint16_t capread = this->read_touch(0);

	if (this->temperature_sensor_ != nullptr) {
		this->temperature_sensor_->publish_state(tempC);
	}
	if (this->moisture_sensor_ != nullptr) {
		this->moisture_sensor_->publish_state(capread);
	}
}

// Get the temperature of the seesaw board in degrees Celsius
float StemmaSoilSensor::read_temperature()
{
	ESP_LOGD("adafruit_soil", "Reading temperature from seesaw sensor");
	uint8_t buf[4];
	this->read_seesaw(SEESAW_STATUS_BASE, SEESAW_STATUS_TEMP, buf, 4);
	int32_t ret = ((uint32_t)buf[0] << 24) | ((uint32_t)buf[1] << 16) |
		      ((uint32_t)buf[2] << 8) | (uint32_t)buf[3];
	float tempC = (1.0 / (1UL << 16)) * ret;
	ESP_LOGD("adafruit_soil", "Temperature raw: 0x%02X%02X%02X%02X, value: %.2f°C", buf[0],
		 buf[1], buf[2], buf[3], tempC);
	return tempC;
}

uint16_t StemmaSoilSensor::read_touch(uint8_t pin)
{
	ESP_LOGD("adafruit_soil", "Reading touch sensor on pin %d", pin);
	uint8_t buf[2]{};
	uint16_t ret = 65535;
	int attempts = 0;
	do {
		attempts++;
		ESP_LOGD("adafruit_soil", "Touch read attempt %d", attempts);
		delay(1);
		this->read_seesaw(SEESAW_TOUCH_BASE, SEESAW_TOUCH_CHANNEL_OFFSET + pin, buf, 2,
				  5000);
		ret = ((uint16_t)buf[0] << 8) | buf[1];
		ESP_LOGD("adafruit_soil", "Touch raw: 0x%02X%02X, value: %d", buf[0], buf[1], ret);
		if (attempts > 3) {
			ESP_LOGW("adafruit_soil",
				 "Touch sensor read taking too many attempts, breaking loop");
			break;
		}
	} while (ret > 4095);
	ESP_LOGD("adafruit_soil", "Touch sensor final value: %d after %d attempts", ret, attempts);
	return ret;
}

uint8_t StemmaSoilSensor::read_seesaw8(uint8_t reg_high, uint8_t reg_low, uint16_t delay_us)
{
	uint8_t ret = 0;
	read_seesaw(reg_high, reg_low, &ret, 1, delay_us);
	ESP_LOGD("adafruit_soil", "read_seesaw8: result=0x%02X", ret);
	return ret;
}

bool StemmaSoilSensor::read_seesaw(uint8_t reg_high, uint8_t reg_low, uint8_t *data, size_t len,
				   uint16_t delay_us)
{
	const uint16_t reg = (reg_high << 8) | reg_low;
	ESP_LOGD("adafruit_soil", "read_seesaw: reg=0x%04X, len=%zu", reg, len);

	// See
	// https://learn.adafruit.com/adafruit-seesaw-atsamd09-breakout/reading-and-writing-data

	// First send the register to be read
	if (this->write_register16(reg, nullptr, 0) != i2c::ERROR_OK) {
		ESP_LOGE("adafruit_soil", "Failed to write register 0x%04X", reg);
		return false;
	} else {
		ESP_LOGD("adafruit_soil", "Successfully wrote register 0x%04X", reg);
	}

	// Then wait a short delay for the seesaw to respond
	delayMicroseconds(delay_us);

	// Then read the response, as a new transaction
	if (this->read(data, len) != i2c::ERROR_OK) {
		ESP_LOGE("adafruit_soil", "Failed to read response");
		return false;
	} else {
		ESP_LOGD("adafruit_soil", "Successfully read %zu bytes", len);
		return true;
	}
}

void StemmaSoilSensor::write_seesaw8(uint8_t reg_high, uint8_t reg_low, uint8_t value)
{
	const uint16_t reg = (reg_high << 8) | reg_low;
	ESP_LOGD("adafruit_soil", "write_seesaw8: reg=0x%04X, value=0x%02X", reg, value);
	if (this->write_register16(reg, &value, 1) != i2c::ERROR_OK) {
		ESP_LOGE("adafruit_soil", "Failed to write register 0x%04X, value=0x%02X", reg,
			 value);
	} else {
		ESP_LOGD("adafruit_soil", "Successfully wrote register 0x%04X, value=0x%02X", reg,
			 value);
	}
}

} // namespace adafruit_soil
} // namespace esphome
