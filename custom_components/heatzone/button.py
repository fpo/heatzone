# /config/custom_components/heatzone/button.py

from homeassistant.components.button import ButtonEntity
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from .entity import ZoneEntityCore
from .const import *

import logging
_LOGGER = logging.getLogger(__name__)

# -----------------------------------------------------------------------------
# ANCHOR - Setup
# -----------------------------------------------------------------------------

async def async_setup_entry(hass, entry, async_add_entities: AddEntitiesCallback):
    """Set up button entities."""
    entities = []
    
    # button for every mode
    entities.append(GlobalSetAllModeButton(hass, entry, HeaterMode.OFF))
    entities.append(GlobalSetAllModeButton(hass, entry, HeaterMode.MANUAL))
    entities.append(GlobalSetAllModeButton(hass, entry, HeaterMode.PROFIL))
    entities.append(GlobalSetAllModeButton(hass, entry, HeaterMode.HOLIDAY))
    
    _LOGGER.debug(f"Setting up {len(entities)} button entities")
    async_add_entities(entities)

# -----------------------------------------------------------------------------
# ANCHOR - Base class for every button with dynamic attributes
# -----------------------------------------------------------------------------

class GlobalSetAllModeButton(ZoneEntityCore, ButtonEntity):
    """Button to set all zones to a specific mode."""

    MODE_ICONS = {
        HeaterMode.OFF: "mdi:power-off",
        HeaterMode.MANUAL: "mdi:hand-back-right",
        HeaterMode.PROFIL: "mdi:calendar-clock",
        HeaterMode.HOLIDAY: "mdi:beach",
    }

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, mode: HeaterMode) -> None:
        """Initialize the button entity."""
        self._mode = mode
        self._attr_name_suffix = f"Set All {mode.value.title()}"
        self._attr_unique_suffix = f"set_all_{mode.value}"
        self._attr_icon = self.MODE_ICONS.get(mode, "mdi:gesture-tap-button")
        self._attr_is_global = True
        
        super().__init__(hass, entry)

    async def async_press(self) -> None:
        """Handle button press - set all zones to the specified mode."""
        zones = self._config_entry.options.get("zones", {})
        success_count = 0
        
        _LOGGER.info(f"Button pressed: Setting all zones to mode '{self._mode.value}'")
        
        for zone_id in zones:
            select_entity_id = f"select.{zone_id}_mode"
            
            state = self.hass.states.get(select_entity_id)
            if state:
                await self.hass.services.async_call(
                    "select",
                    "select_option",
                    {
                        "entity_id": select_entity_id,
                        "option": self._mode.value, 
                    },
                )
                success_count += 1
            else:
                _LOGGER.warning(f"Mode select for {zone_id} not found: {select_entity_id}")
        
        _LOGGER.info(f"Successfully set {success_count}/{len(zones)} zones to '{self._mode.value}' mode")