# /config/custom_components/heatzone/binary_sensor.py

from __future__ import annotations
from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.const import STATE_ON
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback, Event
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from .entity import ZoneEntityCore, ZoneMirrorEntityBase
from .const import *
import logging

_LOGGER = logging.getLogger(__name__)

# -----------------------------------------------------------------------------
# ANCHOR - Setup
# -----------------------------------------------------------------------------

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry,
                            async_add_entities: AddEntitiesCallback,) -> None:
    """Set up sensor entities for all zones."""
    
    zones = entry.options.get("zones", {})
    entities: list[BinarySensorEntity] = []
    
    entities.append(GlobalHeatingBinarySensor(hass, entry))

    for zone_id in zones:
        entities.append(ZoneWindowContactBinarySensor(hass, entry, zone_id))

    _LOGGER.debug("Setting up %d binary_sensor entities for %d zones", len(entities), len(zones))
    async_add_entities(entities)

# -----------------------------------------------------------------------------
# ANCHOR - global heating binary sensor
# -----------------------------------------------------------------------------

class GlobalHeatingBinarySensor(ZoneEntityCore, BinarySensorEntity):
    """Global heating binary sensor."""
    
    _attr_unique_suffix = "heating"
    _attr_name_suffix = "Heating"
    _attr_device_class = "heat"
    _attr_is_global = True
    _update_temps = False
    
    def __init__(self, hass, entry):
        super().__init__(hass, entry)
        self._unsub_dispatcher = None
    
    async def async_added_to_hass(self):
        """Subscribe to dispatcher signals."""
        await super().async_added_to_hass()
        
        # Initial state from manager
        if self._manager:
            self._attr_is_on = self._manager.global_heating_demand
            self.async_write_ha_state()  # Startwert sofort schreiben
        
        @callback
        def _handle_heating_switch(data: dict):
            self._attr_is_on = data["demand"]
            self.async_write_ha_state()
        
        self._unsub_dispatcher = async_dispatcher_connect(
            self.hass,
            f"{DOMAIN}_heating_switch",
            _handle_heating_switch
        )
    
    async def async_will_remove_from_hass(self):
        """Unsubscribe from dispatcher."""
        if self._unsub_dispatcher:
            self._unsub_dispatcher()
        await super().async_will_remove_from_hass()

# -----------------------------------------------------------------------------
# ANCHOR - Base class that reflects the value from a Select-bound sensor
# -----------------------------------------------------------------------------

class ZoneMirrorBinarySensorBase(ZoneMirrorEntityBase, BinarySensorEntity):
    """Base class that reflects the value from a Select-bound sensor."""

    def _get_mirrored_value(self, target_state) -> bool:
        """For BinarySensors: Converts state to boolean."""
        return target_state.state in (STATE_ON, "open")
    
    @property
    def is_on(self) -> bool:
        """Return true if window is open."""
        target_state = self._get_target_state()
        if not target_state:
            self._manager.on_window_closed(self._zone_id)
            return False
        
        is_open = self._get_mirrored_value(target_state)
        
        if is_open:
            self._manager.on_window_opened(self._zone_id)
        else:
            self._manager.on_window_closed(self._zone_id)
        
        return is_open

# -----------------------------------------------------------------------------
# ANCHOR - Mirror contact sensor
# -----------------------------------------------------------------------------

class ZoneWindowContactBinarySensor(ZoneMirrorBinarySensorBase):
    """Reflects the state of the selected window contact.."""
    
    _attr_select_suffix = "window_sensor"
    _attr_unique_suffix = "window_sensor"
    _attr_device_class = BinarySensorDeviceClass.WINDOW
    _attr_icon = "mdi:window-open-variant"
    _attr_name_suffix = "Window contact"