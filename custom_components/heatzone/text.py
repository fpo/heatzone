# /config/custom_components/heatzone/text.py

from homeassistant.components.text import TextEntity
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from .entity import ZoneEntityCore
from .const import *

import logging
_LOGGER = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# ANCHOR - Setup
# ---------------------------------------------------------------------------

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, 
                            async_add_entities: AddEntitiesCallback) -> None:
    """Set up text entities for all zones."""
    
    zones = entry.options.get("zones", {})
    
    entities = []
    for zone_id in zones:
        entities.append(ZoneProfileText(hass, entry, zone_id))
    
    _LOGGER.debug(f"Setting up {len(entities)} text entities for {len(zones)} zones")
    async_add_entities(entities)

# ---------------------------------------------------------------------------
# ANCHOR - Base class texts
# ---------------------------------------------------------------------------

class ZoneTextBase(ZoneEntityCore, TextEntity):
    """Base class for text"""

    async def async_set_value(self, value: str) -> None:
        """Set new text value."""
        self._attr_native_value = value.strip()
        self.async_write_ha_state()
        _LOGGER.debug(f"Updated {self.entity_id} text to {value}")

# ---------------------------------------------------------------------------
# ANCHOR - Zone texts
# ---------------------------------------------------------------------------

class ZoneProfileText(ZoneTextBase):
    """Represents the MQTT subtopic text field for a zone."""

    _attr_mode = "text"
    _attr_name_suffix = "Profile"
    _attr_unique_suffix = "profile"
    _attr_default_value = "Default"
    _update_temps = True



        
        