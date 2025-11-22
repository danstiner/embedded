#pragma once

#include <lib/core/CHIPError.h>

using namespace chip;

class Sht4x {
public:
	CHIP_ERROR Init();

	bool Ready();


	// Read temperature and humidity
	// Returns true on success, false on error
	// temperature: in 0.01°C units (Matter format)
	// humidity: in 0.01% units (0-10000 = 0-100%)
	// Will activate heater as necessary
	bool Read(int16_t &temperature, uint16_t &humidity);

private:
	const struct device *sht;
};
