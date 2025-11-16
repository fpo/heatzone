# /config/custom_components/heatzone/number.py

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers import translation
from homeassistant.const import UnitOfTemperature
from homeassistant.helpers.entity import EntityCategory
from .entity import ZoneEntityCore
from .const import *

import logging
_LOGGER = logging.getLogger(__name__)


# -----------------------------------------------------------------------------
# Setup
# -----------------------------------------------------------------------------

async def async_setup_entry(hass, entry, async_add_entities: AddEntitiesCallback):
    """Set up number entities for all zones."""
    zones = entry.options.get("zones", {})
    entities = []

    entities.append(GlobalBoostDurationNumber(hass, entry))
    entities.append(GlobalBoostTemperatureNumber(hass, entry))

    for zone_id, zone_data in zones.items():
        entities.append(ZoneManualTemperature(hass, entry, zone_id, zone_data))
        entities.append(ZoneDelay(hass, entry, zone_id, zone_data))
        entities.append(ZoneTargetTemperature(hass, entry, zone_id, zone_data))
        entities.append(ZonePriority(hass, entry, zone_id, zone_data))
        
    _LOGGER.debug(
        f"Setting up {len(entities)} number entities for {len(zones)} zones"
    )
    async_add_entities(entities)

# -----------------------------------------------------------------------------
# Base class numbers
# -----------------------------------------------------------------------------

class ZoneNumberBase(ZoneEntityCore, NumberEntity):
    """Basisklasse für alle Zonen-Number-Entitäten."""

    async def async_set_native_value(self, value: float) -> None:
        """Setze neuen Zahlenwert mit optionalem Clamping."""
        min_val = getattr(self, "_attr_native_min_value", None)
        max_val = getattr(self, "_attr_native_max_value", None)

        if min_val is not None and max_val is not None:
            value = max(min_val, min(max_val, value))

        self._attr_native_value = value
        self.async_write_ha_state()
        _LOGGER.debug(f"Updated {self.entity_id} to {value}")

# -----------------------------------------------------------------------------
# Global numbers
# -----------------------------------------------------------------------------

class GlobalBoostDurationNumber(ZoneNumberBase):
    """Globale Boostdauer in Sekunden."""
    
    _attr_name_suffix = "Boost-Dauer"
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
    """Globale Boosttemperatur."""
    
    _attr_name_suffix = "Boost-Temp"
    _attr_unique_suffix = "boost_temp"
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_native_min_value = 0
    _attr_native_max_value = 60
    _attr_native_step = 1
    _attr_mode = NumberMode.BOX
    _attr_default_value = 25.0
    _attr_is_global = True 


# -----------------------------------------------------------------------------
# Zone numbers
# -----------------------------------------------------------------------------

class ZoneTargetTemperature(ZoneNumberBase):
    """Settable target temperature (setpoint) for a zone."""

    _attr_name_suffix = "Ziel-Temperatur"
    _attr_unique_suffix = "target_temp"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_native_min_value = -2.0
    _attr_native_max_value = 50.0
    _attr_native_step = 0.5
    _attr_default_value = 0.0
    _attr_mode = NumberMode.BOX

class ZoneManualTemperature(ZoneNumberBase):
    """Manuell einstellbare Temperatur."""

    _attr_name_suffix = "Manuell-Temperatur"
    _attr_unique_suffix = "manual_temp"
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_native_min_value = -2.0
    _attr_native_max_value = 50.0
    _attr_native_step = 0.5
    _attr_default_value = 20.0
    _attr_mode = NumberMode.SLIDER

class ZonePriority(ZoneNumberBase):
    """Priorität für eine Zone."""

    _attr_name_suffix = "Priorität"
    _attr_unique_suffix = "priority"
    _attr_native_min_value = 0
    _attr_native_max_value = 10
    _attr_native_step = 1
    _attr_default_value = 5
    _attr_mode = NumberMode.SLIDER

class ZoneDelay(ZoneNumberBase):
    """Verzögerung für eine Zone."""

    _attr_name_suffix = "Verzögerung"
    _attr_unique_suffix = "delay"
    _attr_native_unit_of_measurement = "min"
    _attr_native_min_value = 0
    _attr_native_max_value = 120
    _attr_native_step = 1
    _attr_default_value = 0
    _attr_mode = NumberMode.BOX
