import esphome.codegen as cg
import esphome.config_validation as cv
from esphome.const import (
    CONF_ID,
    CONF_MOISTURE,
    CONF_TEMPERATURE,
    DEVICE_CLASS_MOISTURE,
    DEVICE_CLASS_TEMPERATURE,
    ICON_THERMOMETER,
    ICON_WATER,
    STATE_CLASS_MEASUREMENT,
    UNIT_CELSIUS,
)

from esphome.components import i2c, sensor

CODEOWNERS = ["@danstiner"]
DEPENDENCIES = ["i2c"]

DEFAULT_I2C_ADDRESS = 0x36

soil_ns = cg.esphome_ns.namespace("adafruit_soil")

StemmaSoilSensor = soil_ns.class_("StemmaSoilSensor", cg.PollingComponent)

CONFIG_SCHEMA = (
    cv.Schema(
        {
            cv.GenerateID(): cv.declare_id(StemmaSoilSensor),
            cv.Optional(CONF_TEMPERATURE): sensor.sensor_schema(
                unit_of_measurement=UNIT_CELSIUS,
                icon=ICON_THERMOMETER,
                accuracy_decimals=1,
                device_class=DEVICE_CLASS_TEMPERATURE,
                state_class=STATE_CLASS_MEASUREMENT,
            ),
            cv.Optional(CONF_MOISTURE): sensor.sensor_schema(
                icon=ICON_WATER,
                accuracy_decimals=0,
                device_class=DEVICE_CLASS_MOISTURE,
                state_class=STATE_CLASS_MEASUREMENT,
            ),
        }
    )
    .extend(cv.polling_component_schema("60s"))
    .extend(i2c.i2c_device_schema(DEFAULT_I2C_ADDRESS))
)

TYPES = {
    CONF_TEMPERATURE: "set_temperature_sensor",
    CONF_MOISTURE: "set_moisture_sensor",
}


async def to_code(config):
    var = cg.new_Pvariable(config[CONF_ID])
    await cg.register_component(var, config)
    await i2c.register_i2c_device(var, config)

    for key, funcName in TYPES.items():
        if key in config:
            sens = await sensor.new_sensor(config[key])
            cg.add(getattr(var, funcName)(sens))
