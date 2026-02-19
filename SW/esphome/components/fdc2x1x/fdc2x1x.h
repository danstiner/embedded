#pragma once

#include "esphome/components/i2c/i2c.h"
#include "esphome/components/sensor/sensor.h"
#include "esphome/core/component.h"

namespace esphome
{
namespace fdc2x1x
{

/// Expected device values
static constexpr uint16_t EXPECTED_MANUFACTURER_ID = 0x5449; // "TI" in ASCII

/// Configuration values
static constexpr uint16_t CONFIG_ACTIVE_CHAN = 0x0000;         // CH0 active
static constexpr uint16_t CONFIG_SLEEP_MODE_EN = 0x2000;       // Sleep mode enable
static constexpr uint16_t CONFIG_SENSOR_ACTIVATE_SEL = 0x0800; // Sensor activate mode
static constexpr uint16_t CONFIG_AUTO_SCAN_EN = 0x8000;        // Auto-scan mode
static constexpr uint16_t CONFIG_HIGH_CURRENT_DRV = 0x0000;    // Normal current drive

// Configuration values for debug
static constexpr uint16_t RCOUNT_CH0 = 0x8329;
static constexpr uint16_t SETTLECOUNT_CH0 = 0x0020;
static constexpr uint16_t CLOCK_DIVIDER_CH0 = 0x1001; // CH0_FIN_DIVIDER = 1, FREF_DIVIDER = 1
static constexpr uint16_t DRIVE_CURRENT = 0x9000;
static constexpr uint16_t MUX_CONFIG = 0x020D;
static constexpr uint16_t CONFIG = 0x1481;
static constexpr uint16_t ERROR_CONFIG = 0x3800;

/// I2C register addresses.
enum {
	// FDC2212 / FDC2214 data registers (up to 28-bit resolution split across two registers)
	REG_DATA_CH0_MSR = 0x00,
	REG_DATA_CH0_LSR = 0x01,
	REG_DATA_CH1_MSR = 0x02,
	REG_DATA_CH1_LSR = 0x03,
	REG_DATA_CH2_MSR = 0x04,
	REG_DATA_CH2_LSR = 0x05,
	REG_DATA_CH3_MSR = 0x06,
	REG_DATA_CH3_LSR = 0x07,

	// FDC2112 / FDC2114 data registers (up to 12-bit resolution)
	REG_DATA_CH0 = REG_DATA_CH0_MSR,
	REG_DATA_CH1 = REG_DATA_CH1_MSR,
	REG_DATA_CH2 = REG_DATA_CH2_MSR,
	REG_DATA_CH3 = REG_DATA_CH3_MSR,

	// Reference count registers
	REG_RCOUNT_CH0 = 0x08,
	REG_RCOUNT_CH1 = 0x09,
	REG_RCOUNT_CH2 = 0x0A,
	REG_RCOUNT_CH3 = 0x0B,

	// Offset value registers
	REG_OFFSET_CH0 = 0x0C,
	REG_OFFSET_CH1 = 0x0D,
	REG_OFFSET_CH2 = 0x0E,
	REG_OFFSET_CH3 = 0x0F,

	// Settling reference count registers
	REG_SETTLECOUNT_CH0 = 0x10,
	REG_SETTLECOUNT_CH1 = 0x11,
	REG_SETTLECOUNT_CH2 = 0x12,
	REG_SETTLECOUNT_CH3 = 0x13,

	// Clock divider settings registers
	REG_CLOCK_DIVIDERS_CH0 = 0x14,
	REG_CLOCK_DIVIDERS_CH1 = 0x15,
	REG_CLOCK_DIVIDERS_CH2 = 0x16,
	REG_CLOCK_DIVIDERS_CH3 = 0x17,

	// Status register
	REG_STATUS = 0x18,

	// Error configuration register
	REG_ERROR_CONFIG = 0x19,

	// Configuration register
	REG_CONFIG = 0x1A,

	// Channel multiplexing configuration register
	REG_MUX_CONFIG = 0x1B,

	// Reset device
	REG_RESET_DEV = 0x1C,

	// Drive current registers
	REG_DRIVE_CH0 = 0x1E,
	REG_DRIVE_CH1 = 0x1F,
	REG_DRIVE_CH2 = 0x20,
	REG_DRIVE_CH3 = 0x21,

	// Device identification registers
	REG_MANUFACTURER_ID = 0x7E,
	REG_DEVICE_ID = 0x7F,
};

enum ErrorCode {
	NONE = 0,
	READ_MANUFACTURER_ID_FAILED,
	WRONG_CHIP_ID,
	READ_DEVICE_ID_FAILED,
	RESET_FAILED,
	CONFIGURATION_FAILED,
};

class FDC2x1xSensor : public PollingComponent, public i2c::I2CDevice
{
      public:
	FDC2x1xSensor() : PollingComponent(60000)
	{
	}

	void setup() override;
	void dump_config() override;
	void update() override;

	void set_channel0_sensor(sensor::Sensor *sensor)
	{
		this->channel0_sensor_ = sensor;
	}

      protected:
	ErrorCode error_code_{NONE};
	sensor::Sensor *channel0_sensor_{nullptr};

	// Helper methods for 16-bit register operations
	i2c::ErrorCode write_register16(uint8_t reg, uint16_t value);
	i2c::ErrorCode read_register16(uint8_t reg, uint16_t &value);
};

} // namespace fdc2x1x
} // namespace esphome
