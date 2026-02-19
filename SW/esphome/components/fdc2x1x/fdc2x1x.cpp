#include "fdc2x1x.h"
#include "esphome/core/hal.h"
#include "esphome/core/log.h"

namespace esphome
{
namespace fdc2x1x
{

static const char *const TAG = "fdc2x1x";

void FDC2x1xSensor::setup()
{
	ESP_LOGCONFIG(TAG, "Setting up FDC2x1x sensor...");

	// Mark as not failed before initializing. Some devices will turn off sensors to save on
	// batteries and when they come back on, the COMPONENT_STATE_FAILED bit must be unset on the
	// component.
	if (this->is_failed()) {
		this->reset_to_construction_state();
	}

	// Give FDC time to be ready after power-up
	// TODO remove after verifying this is not necessary.
	delay(10);

	// Read manufacturer ID register
	uint16_t manufacturer_id;
	if (this->read_register16(REG_MANUFACTURER_ID, manufacturer_id) != i2c::ERROR_OK) {
		this->error_code_ = READ_MANUFACTURER_ID_FAILED;
		this->mark_failed();
		return;
	}

	if (manufacturer_id != EXPECTED_MANUFACTURER_ID) {
		ESP_LOGE(TAG, "Wrong manufacturer ID: 0x%04X", manufacturer_id);
		this->error_code_ = WRONG_CHIP_ID;
		this->mark_failed();
		return;
	}

	// Read device ID register
	uint16_t device_id;
	if (this->read_register16(REG_DEVICE_ID, device_id) != i2c::ERROR_OK) {
		this->error_code_ = READ_DEVICE_ID_FAILED;
		this->mark_failed();
		return;
	}

	ESP_LOGCONFIG(TAG, "Found FDC2x1x (ID: 0x%04X)", device_id);

	// Reset device
	if (this->write_register16(REG_RESET_DEV, 0x8000) != i2c::ERROR_OK) {
		this->error_code_ = RESET_FAILED;
		this->mark_failed();
		return;
	}
	delay(10);

	// Configure sensor
	if (this->write_register16(REG_CLOCK_DIVIDERS_CH0, CLOCK_DIVIDER_CH0) != i2c::ERROR_OK ||
	    this->write_register16(REG_DRIVE_CH0, DRIVE_CURRENT) != i2c::ERROR_OK ||
	    this->write_register16(REG_SETTLECOUNT_CH0, SETTLECOUNT_CH0) != i2c::ERROR_OK ||
	    this->write_register16(REG_RCOUNT_CH0, RCOUNT_CH0) != i2c::ERROR_OK ||
	    this->write_register16(REG_MUX_CONFIG, MUX_CONFIG) != i2c::ERROR_OK ||
	    this->write_register16(REG_ERROR_CONFIG, ERROR_CONFIG) != i2c::ERROR_OK ||
	    this->write_register16(REG_CONFIG, CONFIG) != i2c::ERROR_OK) {
		this->error_code_ = CONFIGURATION_FAILED;
		this->mark_failed();
		return;
	}
}

void FDC2x1xSensor::dump_config()
{
	ESP_LOGCONFIG(TAG, "FDC2x1x Sensor:");
	LOG_I2C_DEVICE(this);
	if (this->is_failed()) {
		switch (this->error_code_) {
		case READ_MANUFACTURER_ID_FAILED:
			ESP_LOGE(TAG, "Failed to read manufacturer ID");
			break;
		case WRONG_CHIP_ID:
			ESP_LOGE(TAG, "Wrong chip ID");
			break;
		case READ_DEVICE_ID_FAILED:
			ESP_LOGE(TAG, "Failed to read device ID");
			break;
		case RESET_FAILED:
			ESP_LOGE(TAG, "Reset failed");
			break;
		case CONFIGURATION_FAILED:
			ESP_LOGE(TAG, "Configuration failed");
			break;
		default:
			ESP_LOGE(TAG, "Setup failed");
			break;
		}
	}
	LOG_UPDATE_INTERVAL(this);
}

void FDC2x1xSensor::update()
{
	if (this->is_failed()) {
		return;
	}

	// Check status register first
	uint16_t status;
	if (this->read_register16(REG_STATUS, status) != i2c::ERROR_OK) {
		ESP_LOGW(TAG, "Failed to read status register");
		this->status_set_warning();
		return;
	}

	// Log status only if there are warnings/errors
	if (status & 0x0E00) { // Check error bits: watchdog(11), amp_high(10), amp_low(9)
		ESP_LOGW(TAG, "Status warnings: 0x%04X", status);
		if (status & 0x0800) {
			ESP_LOGW(TAG, "  Watchdog timeout error");
		}
		if (status & 0x0400) {
			ESP_LOGW(TAG, "  Amplitude too high");
		}
		if (status & 0x0200) {
			ESP_LOGW(TAG, "  Amplitude too low");
		}
	}

	// Only proceed if CH0 has unread data
	if (!(status & 0x0008)) {
		ESP_LOGV(TAG, "No new data available for CH0, skipping read");
		return;
	}

	// Read channel 0 data
	uint16_t ch0_data_msr;
	if (this->read_register16(REG_DATA_CH0_MSR, ch0_data_msr) != i2c::ERROR_OK) {
		ESP_LOGW(TAG, "Failed to read channel 0 data MSR");
		this->status_set_warning();
		return;
	}

	uint16_t ch0_data_lsr;
	if (this->read_register16(REG_DATA_CH0_LSR, ch0_data_lsr) != i2c::ERROR_OK) {
		ESP_LOGW(TAG, "Failed to read channel 0 data LSR");
		this->status_set_warning();
		return;
	}

	// Extract 28-bit result and error flags
	bool ch0_watchdog_timeout = ch0_data_msr & (1 << 13);
	bool ch0_amplitude_warn = ch0_data_msr & (1 << 12);
	uint16_t ch0_data_res_msr = ch0_data_msr & 0xFFF;
	uint32_t ch0_res = (ch0_data_res_msr << 16) | ch0_data_lsr;

	// Log warnings if present
	if (ch0_watchdog_timeout || ch0_amplitude_warn) {
		ESP_LOGW(TAG, "Channel 0 warnings - timeout:%d, amplitude:%d", ch0_watchdog_timeout,
			 ch0_amplitude_warn);
	}

	ESP_LOGV(TAG, "Channel 0: 0x%08X (%u)", ch0_res, ch0_res);

	// Publish to sensor if configured
	if (this->channel0_sensor_ != nullptr) {
		this->channel0_sensor_->publish_state(ch0_res);
	}

	this->status_clear_warning();
}

i2c::ErrorCode FDC2x1xSensor::write_register16(uint8_t reg, uint16_t value)
{
	uint8_t data[2];
	data[0] = (value >> 8) & 0xFF; // MSB first
	data[1] = value & 0xFF;        // LSB second

	return this->write_register(reg, data, 2);
}

i2c::ErrorCode FDC2x1xSensor::read_register16(uint8_t reg, uint16_t &value)
{
	uint8_t data[2];
	i2c::ErrorCode err = this->read_register(reg, data, 2);
	value = (data[0] << 8) | data[1]; // MSB first
	return err;
}

} // namespace fdc2x1x
} // namespace esphome
