# /config/custom_components/heatzone/text.py

from homeassistant.components.text import TextEntity, ENTITY_ID_FORMAT
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers import translation
from .entity import ZoneEntityCore
from .const import *

import logging
_LOGGER = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, 
                            async_add_entities: AddEntitiesCallback) -> None:
    """Set up text entities for all zones."""
    
    zones = entry.options.get("zones", {})
    
    entities = []
    for zone_id, zone_data in zones.items():
        entities.append(ZoneProfileText(hass, entry, zone_id, zone_data))
    #    entities.append(ZoneStateText(hass, entry, zone_id, zone_data))
    
    _LOGGER.debug(f"Setting up {len(entities)} text entities for {len(zones)} zones")
    async_add_entities(entities)

# ---------------------------------------------------------------------------
# Base class texts
# ---------------------------------------------------------------------------

class ZoneTextBase(ZoneEntityCore, TextEntity):
    """Basisklasse für Zonen-Textfelder."""

    async def async_set_value(self, value: str) -> None:
        """Set new text value."""
        self._attr_native_value = value.strip()
        self.async_write_ha_state()
        _LOGGER.debug(f"Updated {self.entity_id} text to {value}")

# ---------------------------------------------------------------------------
# Zone texts
# ---------------------------------------------------------------------------

class ZoneProfileText(ZoneTextBase):
    """Represents the MQTT topic text field for a zone."""

    _attr_mode = "text"
    _attr_name_suffix = "Profile"
    _attr_unique_suffix = "profile"
    _attr_default_value = "Default"

#class ZoneStateText(ZoneTextBase):
#    """Represents the state text field for a zone."""

#    _attr_mode = "text"
#    _attr_entity_category = EntityCategory.DIAGNOSTIC
#    _attr_name_suffix = "Status"
#    _attr_unique_suffix = "status"
#    _attr_default_value = "O.K."

        
        