# /config/custom_components/heatzone/select.py

from __future__ import annotations
from typing import Optional, Callable
from homeassistant.components.select import SelectEntity
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback, Event
from homeassistant.helpers.event import async_call_later
from .entity import ZoneEntityCore
from .const import *

import logging
_LOGGER = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# ANCHOR - Setup
# ---------------------------------------------------------------------------

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, 
                            async_add_entities: AddEntitiesCallback) -> None:
    """Set up select entities for all zones."""
    zones = entry.options.get("zones") or entry.data.get("zones", {})
    entities: list[SelectEntity] = []

    for zone_id in zones:
        entities.append(ZoneModeSelect(hass, entry, zone_id))
        entities.append(ZoneWindowSelect(hass, entry, zone_id))
        entities.append(ZoneTemperatureSelect(hass, entry, zone_id))
        entities.append(ZoneHumiditySelect(hass, entry, zone_id))
        entities.append(ZoneThermostatSelect(hass, entry, zone_id))

    _LOGGER.debug("Setting up %d select entities", len(entities))
    async_add_entities(entities)

# ---------------------------------------------------------------------------
# ANCHOR - Base class for select
# ---------------------------------------------------------------------------

class ZoneSelectBase(ZoneEntityCore, SelectEntity):
    """Base class for all zone-related selects with secure restore,mapping and dynamic options."""

    _attr_icon: str | None = None
    _domain_filter: str = ""
    _device_classes: tuple[str, ...] = ()
    _attr_options: list[str] = []
    _attr_current_option: Optional[str] = None

    _entity_map: dict[str, str] = {}  # FriendlyName → entity_id
    _restored_option: Optional[str] = None
    _state_listener_unsubscribe: Optional[Callable] = None
    _reload_attempts: int = 0
    _max_reload_attempts: int = 5

    @property
    def extra_state_attributes(self) -> dict:
        """Expose entity mapping as attribute."""
        return {
            "entity_map": self._entity_map, 
            "selected_entity_id": self.selected_entity_id 
            }

    @property
    def current_option(self) -> str | None:
        """Return the currently selected option."""
        return self._attr_current_option

    @property
    def selected_entity_id(self) -> Optional[str]:
        """Return the entity_id of the selected option (if available)."""
        if not self._attr_current_option:
            return None
        return self._entity_map.get(self._attr_current_option)

    async def async_added_to_hass(self) -> None:
        """Setup entity, restore state, and attach listener."""
        await ZoneEntityCore.async_added_to_hass(self)

        # restore last state
        if (last_state := await self.async_get_last_state()) is not None:
            if last_state.state not in (None, "unknown", "unavailable"):
                self._restored_option = last_state.state
                _LOGGER.debug(
                    "[%s/%s] Restored option: %s",
                    getattr(self, "_zone_name", "Global"),
                    self.__class__.__name__,
                    self._restored_option,
                )

        # load options initial
        await self._load_options()

        # staggered reload strategy with multiple attempts
        await self._schedule_reload_attempts()

        # enable listener for changes in other entities
        @callback
        def _state_changed_listener(event: Event) -> None:
            entity_id = event.data.get("entity_id")
            if not entity_id or not entity_id.startswith(f"{self._domain_filter}."):
                return
            new_state = event.data.get("new_state")
            if new_state and new_state.attributes.get("device_class") in self._device_classes:
                self.hass.async_create_task(self._async_reload_options())

        self._state_listener_unsubscribe = self.hass.bus.async_listen(
            "state_changed", _state_changed_listener
        )

    async def _schedule_reload_attempts(self) -> None:
        """Schedule multiple reload attempts with increasing delays."""
        # Different delays depending on the domain
        delay_map = {
            "climate": [3, 8, 15, 25, 40],      # Climate entities need more time
            "sensor": [2, 5, 10],                # Sensors are faster
            "binary_sensor": [2, 5, 10]          # Binary sensors too
        }
        
        delays = delay_map.get(self._domain_filter, [2, 5, 10])
        
        for attempt, delay in enumerate(delays, start=1):
            async def delayed_reload(_now, attempt_num=attempt):
                """Reload options after delay."""
                _LOGGER.debug(
                    "[%s/%s] Reload attempt %d/%d (after %d seconds)",
                    getattr(self, "_zone_name", "Global"),
                    self.__class__.__name__,
                    attempt_num,
                    len(delays),
                    delay,
                )
                
                old_count = len(self._attr_options)
                await self._load_options()
                new_count = len(self._attr_options)
                
                # Stop further attempts if entities were found
                if new_count > 1:  # More than just "None"
                    _LOGGER.debug(
                        "[%s/%s] Successfully loaded %d options, stopping further attempts",
                        getattr(self, "_zone_name", "Global"),
                        self.__class__.__name__,
                        new_count,
                    )
                    self._reload_attempts = len(delays)  # Mark as complete
                elif attempt_num == len(delays):
                    _LOGGER.warning(
                        "[%s/%s] No %s entities found after %d attempts",
                        getattr(self, "_zone_name", "Global"),
                        self.__class__.__name__,
                        self._domain_filter,
                        len(delays),
                    )
            
            async_call_later(self.hass, delay, delayed_reload)

    async def _async_reload_options(self) -> None:
        """Reload options asynchronously."""
        await self._load_options()

    async def _load_options(self) -> None:
        """Load available options and build FriendlyName → entity_id mapping"""
        if not self._domain_filter:
            self._apply_restored_or_default_option()
            return

        old_options = set(self._attr_options)
        old_count = len(self._attr_options)
        
        self._attr_options = ["None"]
        self._entity_map = {"None": None}  # Reset Mapping

        # Count available entities for logging
        available_count = 0
        
        for state in self.hass.states.async_all(self._domain_filter):
            # For climate: no device_class exists
            if self._domain_filter == "climate" or (
                self._device_classes
                and state.attributes.get("device_class") in self._device_classes
            ):
                friendly = state.name
                entity_id = state.entity_id
                self._attr_options.append(friendly)
                self._entity_map[friendly] = entity_id
                available_count += 1

        self._attr_options.sort(key=lambda x: (x != "None", x))

        new_count = len(self._attr_options)
        
        # Log only if something changed
        if set(self._attr_options) != old_options:
            _LOGGER.debug(
                "[%s/%s] Options updated: %d → %d items (%d %s entities found)",
                getattr(self, "_zone_name", "Global"),
                self.__class__.__name__,
                old_count,
                new_count,
                available_count,
                self._domain_filter,
            )
            self._apply_restored_or_default_option()
        elif new_count == 1:  # Only "None" available
            _LOGGER.debug(
                "[%s/%s] No %s entities available yet (will retry)",
                getattr(self, "_zone_name", "Global"),
                self.__class__.__name__,
                self._domain_filter,
            )

    def _apply_restored_or_default_option(self) -> None:
        """Apply the restored or default option."""
        # Restore
        if self._restored_option and self._restored_option in self._attr_options:
            self._attr_current_option = self._restored_option
            _LOGGER.debug("[%s/%s] Applied restored option: %s",
                          getattr(self, "_zone_name", "Global"),
                          self.__class__.__name__,
                          self._restored_option)
        # Default
        elif getattr(self, "_attr_default_value", None) in self._attr_options:
            self._attr_current_option = self._attr_default_value
            _LOGGER.debug("[%s/%s] Applied default option: %s",
                          getattr(self, "_zone_name", "Global"),
                          self.__class__.__name__,
                          self._attr_default_value)
        # Fallback
        elif "None" in self._attr_options:
            self._attr_current_option = "None"
            _LOGGER.debug("[%s/%s] No restore/default, fallback 'None'",
                          getattr(self, "_zone_name", "Global"),
                          self.__class__.__name__)

        self._attr_native_value = self._attr_current_option
        self.async_write_ha_state()

    async def async_select_option(self, option: str) -> None:
        """Handle option selection for SelectEntity."""
        if option not in self._attr_options:
            _LOGGER.warning(
                f"{self.entity_id}: Invalid option '{option}' (valid: {self._attr_options})"
            )
            return

        self._attr_current_option = option
        self._attr_native_value = option
        self.async_write_ha_state()
        _LOGGER.debug(f"Selected {option} for {self.entity_id}")
        
# ---------------------------------------------------------------------------
# ANCHOR - Zone mode select
# ---------------------------------------------------------------------------

class ZoneModeSelect(ZoneSelectBase):
    """Zone mode."""

    _attr_icon = "mdi:radiator"
    _attr_name_suffix = "Modus"
    _attr_unique_suffix = "mode"
    _attr_options = HEATER_MODES
    _attr_default_value = HeaterMode.OFF.value
    _update_temps = True

# ---------------------------------------------------------------------------
# ANCHOR - Sensorbased selects
# ---------------------------------------------------------------------------

class ZoneWindowSelect(ZoneSelectBase):
    """Window/door contact selection."""

    _attr_icon = "mdi:window-open-variant"
    _domain_filter = "binary_sensor"
    _device_classes = ("window", "door", "opening")
    _attr_name_suffix = "Window contact"
    _attr_unique_suffix = "window_sensor"

class ZoneTemperatureSelect(ZoneSelectBase):
    """Temperature sensor selection."""

    _attr_icon = "mdi:thermometer"
    _domain_filter = "sensor"
    _device_classes = ("temperature",)
    _attr_name_suffix = "Temperature sensor"
    _attr_unique_suffix = "temperature_sensor"

class ZoneHumiditySelect(ZoneSelectBase):
    """Humidity sensor selection."""

    _attr_icon = "mdi:water-percent"
    _domain_filter = "sensor"
    _device_classes = ("humidity",)
    _attr_name_suffix = "Humidy sensor"
    _attr_unique_suffix = "humidity_sensor"
    
class ZoneThermostatSelect(ZoneSelectBase):
    """Thermostat selection."""

    _attr_icon = "mdi:thermostat"
    _domain_filter = "climate"
    _attr_name_suffix = "Thermostat"
    _attr_unique_suffix = "thermostat_sensor"