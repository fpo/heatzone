# /config/custom_components/heatzone/switch.py

from __future__ import annotations
import logging
from homeassistant.components.switch import SwitchEntity
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from .entity import ZoneEntityCore
from .const import *

_LOGGER = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# ANCHOR - Setup
# ---------------------------------------------------------------------------

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, 
                            async_add_entities: AddEntitiesCallback) -> None:
    """Set up switch entities for all zones."""
    zones = entry.options.get("zones", {})
    entities: list[SwitchEntity] = []

    for zone_id in zones:
        entities.append(ZonePresentSwitch(hass, entry, zone_id))
        entities.append(ZoneBoostSwitch(hass, entry, zone_id))

    _LOGGER.debug("Setting up %d switch entities for %d zones", 
                  len(entities), len(zones))
    
    async_add_entities(entities)

# -----------------------------------------------------------------------------
# ANCHOR - Base class switches
# -----------------------------------------------------------------------------

class ZoneSwitchBase(ZoneEntityCore, SwitchEntity):
    """Base class for all zone-based switch entities."""

    _attr_icon: str | None = None
    _attr_is_on: bool = False

    @property
    def is_on(self) -> bool:
        """Return true if the switch is on."""
        return self._attr_is_on

    async def async_added_to_hass(self) -> None:
        """Restore last known state (boolean switches)."""
        await super().async_added_to_hass()  # führt ZoneEntityCore-Restore aus
        if (last_state := await self.async_get_last_state()) is not None:
            self._attr_is_on = last_state.state == "on"
            _LOGGER.debug(f"Restored {self.entity_id} to {self._attr_is_on}")

# -----------------------------------------------------------------------------
# ANCHOR - Zone present switch
# -----------------------------------------------------------------------------

class ZonePresentSwitch(ZoneSwitchBase):
    """Switches a zone to present/absent."""
    _attr_icon = "mdi:radiator"
    _attr_unique_suffix = "present"
    _attr_name_suffix = "Present"
    _default_present = True
    _update_temps = True

    async def async_turn_on(self, **kwargs) -> None:
        _LOGGER.info("[%s] Present", self._zone_id)
        self._attr_is_on = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        _LOGGER.info("[%s] Absent", self._zone_id)
        self._attr_is_on = False
        self.async_write_ha_state()

# -----------------------------------------------------------------------------
# ANCHOR - Zone-Boost-Switch
# -----------------------------------------------------------------------------

class ZoneBoostSwitch(ZoneSwitchBase):
    """A time-limited boost switch."""
    _attr_icon = "mdi:fire"
    _attr_unique_suffix = "boost"
    _attr_name_suffix = "Boost"
    _update_temps = True

    def __init__(self, hass, entry, zone_id):
        super().__init__(hass, entry, zone_id)

    async def async_turn_on(self, **kwargs) -> None:  
        """Start Boost."""
        self._attr_is_on = True
        self._manager.start_boost(self._zone_id)
        self.async_write_ha_state()
        
    async def async_turn_off(self, **kwargs) -> None:  
        """Cancel Boost manual."""
        self._attr_is_on = False
        if self._manager.is_boost_active(self._zone_id):
            self._manager.stop_boost(self._zone_id)
        self.async_write_ha_state()
        
    async def async_update(self):
        """Sync state with manager."""
        self._attr_is_on = self._manager.is_boost_active(self._zone_id)