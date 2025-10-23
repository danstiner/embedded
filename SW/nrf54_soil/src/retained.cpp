/*
 * Retained RAM implementation
 */

#include "retained.h"
#include <zephyr/retention/retention.h>
#include <zephyr/sys/crc.h>

/* Retained data stored in special RAM section */
static const struct device *retention_dev = DEVICE_DT_GET(DT_NODELABEL(retention));

struct retained_data retained;

static uint32_t retained_checksum(void)
{
	return crc32_ieee((uint8_t *)&retained,
	                  offsetof(struct retained_data, checksum));
}

bool retained_validate(void)
{
	int ret;

	if (!device_is_ready(retention_dev)) {
		return false;
	}

	ret = retention_read(retention_dev, 0, (uint8_t *)&retained, sizeof(retained));
	if (ret < 0) {
		return false;
	}

	if (retained.magic != RETAINED_MAGIC) {
		return false;
	}

	return retained.checksum == retained_checksum();
}

void retained_update(void)
{
	retained.magic = RETAINED_MAGIC;
	retained.checksum = retained_checksum();

	if (device_is_ready(retention_dev)) {
		retention_write(retention_dev, 0, (uint8_t *)&retained, sizeof(retained));
	}
}
