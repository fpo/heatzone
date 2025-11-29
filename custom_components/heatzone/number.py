# /config/custom_components/heatzone/number.py

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.const import UnitOfTemperature
from homeassistant.helpers.entity import EntityCategory
from .entity import ZoneEntityCore
from .const import *

import logging
_LOGGER = logging.getLogger(__name__)

# -----------------------------------------------------------------------------
# ANCHOR - Setup
# -----------------------------------------------------------------------------

async def async_setup_entry(hass, entry, async_add_entities: AddEntitiesCallback):
    """Set up number entities for all zones."""
    zones = entry.options.get("zones", {})
    entities = []

    entities.append(GlobalBoostDurationNumber(hass, entry))
    entities.append(GlobalBoostTemperatureNumber(hass, entry))
    entities.append(GlobalHysteresisNumber(hass, entry))
    
    for zone_id in zones:
        entities.append(ZoneManualTemperature(hass, entry, zone_id))
        entities.append(ZoneDelay(hass, entry, zone_id))
        entities.append(ZonePriority(hass, entry, zone_id))
        entities.append(ZoneTempCalibrate(hass, entry, zone_id))
        
    _LOGGER.debug(
        f"Setting up {len(entities)} number entities for {len(zones)} zones")
    
    async_add_entities(entities)

# -----------------------------------------------------------------------------
# ANCHOR - Base class numbers
# -----------------------------------------------------------------------------

class ZoneNumberBase(ZoneEntityCore, NumberEntity):
    """Base class for all zone number entities."""

    async def async_set_native_value(self, value: float) -> None:
        """Set a new numerical value with optional clamping."""
        min_val = getattr(self, "_attr_native_min_value", None)
        max_val = getattr(self, "_attr_native_max_value", None)

        if min_val is not None and max_val is not None:
            value = max(min_val, min(max_val, value))

        self._attr_native_value = value
        self.async_write_ha_state()
        _LOGGER.debug(f"Updated {self.entity_id} to {value}")

# -----------------------------------------------------------------------------
# ANCHOR - Global numbers
# -----------------------------------------------------------------------------

class GlobalBoostDurationNumber(ZoneNumberBase):
    """Global boost duration in seconds."""
    
    _attr_name_suffix = "Boost-Duration"
    _attr_unique_suffix = "boost_duration"
    _attr_icon = "mdi:timer-outline"
    _attr_native_unit_of_measurement = "min"
    _attr_native_min_value = 0
    _attr_native_max_value = 60
    _attr_native_step = 1
    _attr_mode = NumberMode.BOX
    _attr_default_value = 60
    _attr_is_global = True 

class GlobalBoostTemperatureNumber(ZoneNumberBase):
    """Global boost temparature."""
    
    _attr_name_suffix = "Boost-Temp"
    _attr_unique_suffix = "boost_temp"
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_native_min_value = 0
    _attr_native_max_value = 60
    _attr_native_step = 1
    _attr_mode = NumberMode.BOX
    _attr_default_value = 25.0
    _attr_is_global = True 

class GlobalHysteresisNumber(ZoneNumberBase):
    """Global hysteresis."""
    
    _attr_name_suffix = "Hysteresis"
    _attr_unique_suffix = "hysteresis"
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_native_min_value = 0
    _attr_native_max_value = 3.0
    _attr_native_step = 0.1
    _attr_mode = NumberMode.BOX
    _attr_default_value = 0.5
    _attr_is_global = True 

# -----------------------------------------------------------------------------
# ANCHOR - Zone numbers
# -----------------------------------------------------------------------------

class ZoneManualTemperature(ZoneNumberBase):
    """Manually adjustable temperature."""

    _attr_name_suffix = "Manual temperature"
    _attr_unique_suffix = "manual_temp"
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_native_min_value = -2.0
    _attr_native_max_value = 50.0
    _attr_native_step = 0.5
    _attr_default_value = 20.0
    _attr_mode = NumberMode.SLIDER
    _update_temps = True

class ZonePriority(ZoneNumberBase):
    """Priority for a zone."""

    _attr_name_suffix = "Priority"
    _attr_unique_suffix = "priority"
    _attr_native_min_value = 0
    _attr_native_max_value = 10
    _attr_native_step = 1
    _attr_default_value = 5
    _attr_mode = NumberMode.SLIDER
    _update_temps = True

class ZoneDelay(ZoneNumberBase):
    """Delay in closing window."""

    _attr_name_suffix = "Delay"
    _attr_unique_suffix = "delay"
    _attr_native_unit_of_measurement = "min"
    _attr_native_min_value = 0
    _attr_native_max_value = 120
    _attr_native_step = 1
    _attr_default_value = 0
    _attr_mode = NumberMode.BOX

class ZoneTempCalibrate(ZoneNumberBase):
    """Calibration for current temp."""

    _attr_name_suffix = "Temp-Calibrate"
    _attr_unique_suffix = "temp_calibrate"
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_native_min_value = -2.0
    _attr_native_max_value = 2.0
    _attr_native_step = 0.1
    _attr_default_value = 0
    _attr_mode = NumberMode.SLIDER
    _update_temps = True
