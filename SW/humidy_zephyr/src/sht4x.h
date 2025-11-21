#pragma once

#include <lib/core/CHIPError.h>

using namespace chip;

class Sht4x {
public:
	static Sht4x &Instance()
	{
		static Sht4x instance;
		return instance;
	};

	CHIP_ERROR Init();

    void Read();

private:
    const struct device *sht;
};
