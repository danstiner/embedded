#pragma once

#include <cinttypes>

#include "esphome/components/i2c/i2c.h"
#include "esphome/components/sensor/sensor.h"
#include "esphome/core/component.h"

namespace esphome
{
namespace adafruit_soil
{

/// seesaw HW ID code
static constexpr uint8_t SEESAW_HW_ID_CODE = 0x55;

/// Seesaw module base addreses (Upper 8 bits of register address).
enum {
	SEESAW_STATUS_BASE = 0x00,
	SEESAW_TOUCH_BASE = 0x0F,
};

/// Status module address registers.
enum {
	SEESAW_STATUS_HW_ID = 0x01,
	SEESAW_STATUS_VERSION = 0x02,
	SEESAW_STATUS_OPTIONS = 0x03,
	SEESAW_STATUS_TEMP = 0x04,
	SEESAW_STATUS_SWRST = 0x7F,
};

/// Touch module address registers.
enum {
	SEESAW_TOUCH_CHANNEL_OFFSET = 0x10,
};

class StemmaSoilSensor : public PollingComponent, public i2c::I2CDevice
{
      public:
	StemmaSoilSensor() : PollingComponent(60000)
	{
	}

	void setup() override;
	void dump_config() override;
	void update() override;

	void set_temperature_sensor(sensor::Sensor *temperature_sensor)
	{
		this->temperature_sensor_ = temperature_sensor;
	}
	void set_moisture_sensor(sensor::Sensor *moisture_sensor)
	{
		this->moisture_sensor_ = moisture_sensor;
	}

      protected:
	sensor::Sensor *temperature_sensor_{nullptr};
	sensor::Sensor *moisture_sensor_{nullptr};

	// Read temperature of the seesaw IC in degrees Celsius.
	float read_temperature();

	// Read current value of a capacitative sensor.
	uint16_t read_touch(uint8_t pin);

	// Read one byte from the specified seesaw register.
	uint8_t read_seesaw8(uint8_t reg_high, uint8_t reg_low, uint16_t delay_us = 125);

	// Read bytes from the specified seesaw register.
	bool read_seesaw(uint8_t reg_high, uint8_t reg_low, uint8_t *data, size_t len,
			 uint16_t delay_us = 125);

	// Write one byte to specified seesaw register.
	void write_seesaw8(uint8_t reg_high, uint8_t reg_low, uint8_t value);
};

} // namespace adafruit_soil
} // namespace esphome
