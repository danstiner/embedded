import esphome.codegen as cg
import esphome.config_validation as cv
from esphome.components import i2c, sensor
from esphome.const import (
    CONF_ID,
    STATE_CLASS_MEASUREMENT,
)

CODEOWNERS = ["@danstiner"]
DEPENDENCIES = ["i2c"]

DEFAULT_I2C_ADDRESS = 0x2A

CONF_CHANNEL0 = "channel0"

fdc_ns = cg.esphome_ns.namespace("fdc2x1x")

FDC2x1xSensor = fdc_ns.class_("FDC2x1xSensor", cg.PollingComponent, i2c.I2CDevice)

CONFIG_SCHEMA = (
    cv.Schema(
        {
            cv.GenerateID(): cv.declare_id(FDC2x1xSensor),
            cv.Optional(CONF_CHANNEL0): sensor.sensor_schema(
                accuracy_decimals=0,
                state_class=STATE_CLASS_MEASUREMENT,
            ),
        }
    )
    .extend(cv.polling_component_schema("60s"))
    .extend(i2c.i2c_device_schema(DEFAULT_I2C_ADDRESS))
)


async def to_code(config):
    var = cg.new_Pvariable(config[CONF_ID])
    await cg.register_component(var, config)
    await i2c.register_i2c_device(var, config)

    if CONF_CHANNEL0 in config:
        sens = await sensor.new_sensor(config[CONF_CHANNEL0])
        cg.add(var.set_channel0_sensor(sens))
