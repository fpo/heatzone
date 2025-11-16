# /config/custom_components/heatzone/select.py
from __future__ import annotations
from enum import StrEnum
from typing import Optional
from homeassistant.components.select import SelectEntity
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback, Event
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers import translation
from homeassistant.helpers.event import async_call_later
from homeassistant.const import EVENT_STATE_CHANGED
from .entity import ZoneEntityCore
from .const import *

import logging
_LOGGER = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, 
                            async_add_entities: AddEntitiesCallback) -> None:
    """Set up select entities for all zones."""
    zones = entry.options.get("zones") or entry.data.get("zones", {})
    entities: list[SelectEntity] = []

    entities.append(GlobalModeSelect(hass, entry))

    for zone_id, zone_data in zones.items():
        entities.append(ZoneModeSelect(hass, entry, zone_id, zone_data))
        entities.append(ZoneWindowSelect(hass, entry, zone_id, zone_data))
        entities.append(ZoneTemperatureSelect(hass, entry, zone_id, zone_data))
        entities.append(ZoneHumiditySelect(hass, entry, zone_id, zone_data))
        entities.append(ZoneThermostatSelect(hass, entry, zone_id, zone_data))

    _LOGGER.debug("Setting up %d select entities", len(entities))
    async_add_entities(entities)

# ---------------------------------------------------------------------------
# Basis-Klasse für Select
# ---------------------------------------------------------------------------

class ZoneSelectBase(ZoneEntityCore, SelectEntity):
    """Basisklasse für alle zonenbezogenen Selects mit sicherem Restore, Mapping und dynamischen Optionen."""

    _attr_icon: str | None = None
    _domain_filter: str = ""
    _device_classes: tuple[str, ...] = ()
    _attr_options: list[str] = []
    _attr_current_option: Optional[str] = None

    _entity_map: dict[str, str] = {}  # FriendlyName → entity_id
    _restored_option: Optional[str] = None
    _state_listener_unsubscribe: Optional[Callable] = None

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

        # Restore letzten Zustand
        if (last_state := await self.async_get_last_state()) is not None:
            if last_state.state not in (None, "unknown", "unavailable"):
                self._restored_option = last_state.state
                _LOGGER.debug(
                    "[%s/%s] Restored option: %s",
                    getattr(self, "_zone_name", "Global"),
                    self.__class__.__name__,
                    self._restored_option,
                )

        # Optionen initial laden (und Default anwenden)
        await self._load_options()

        # Verzögerter Reload nach Startup - unterschiedliche Delays je nach Domain
        delay_map = {
            "climate": 10,      # Climate-Entities brauchen länger
            "sensor": 3,       # Sensoren sind meist schneller
            "binary_sensor": 3 # Binary Sensoren auch schnell
        }
        
        delay = delay_map.get(self._domain_filter, 3)  # Default: 3 Sekunden
        
        async def delayed_reload(_now):
            """Reload options after other entities are fully loaded."""
            _LOGGER.debug(
                "[%s/%s] Running delayed options reload (after %d seconds)",
                getattr(self, "_zone_name", "Global"),
                self.__class__.__name__,
                delay,
            )
            await self._load_options()
        
        async_call_later(self.hass, delay, delayed_reload)

        # Listener für Änderungen in anderen Entities aktivieren
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

    async def _async_reload_options(self) -> None:
        """Reload options asynchronously."""
        await self._load_options()

    async def _load_options(self) -> None:
        """Lade verfügbare Optionen und baue FriendlyName→entity_id Mapping."""
        if not self._domain_filter:
            self._apply_restored_or_default_option()
            return

        old_options = set(self._attr_options)
        self._attr_options = ["Kein"]
        self._entity_map = {"Kein": None}  # Reset Mapping

        for state in self.hass.states.async_all(self._domain_filter):
            # Für climate gilt: keine device_class vorhanden
            if self._domain_filter == "climate" or (
                self._device_classes
                and state.attributes.get("device_class") in self._device_classes
            ):
                friendly = state.name
                entity_id = state.entity_id
                self._attr_options.append(friendly)
                self._entity_map[friendly] = entity_id

        self._attr_options.sort(key=lambda x: (x != "Kein", x))

        if set(self._attr_options) != old_options:
            _LOGGER.debug(
                "[%s/%s] Options updated (%d items): %s",
                getattr(self, "_zone_name", "Global"),
                self.__class__.__name__,
                len(self._attr_options),
                ", ".join(self._attr_options),
            )
            self._apply_restored_or_default_option()

    def _apply_restored_or_default_option(self) -> None:
        """Wende Restored- oder Default-Option an."""
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
        elif "Kein" in self._attr_options:
            self._attr_current_option = "Kein"
            _LOGGER.debug("[%s/%s] No restore/default, fallback 'Kein'",
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
# Global Select
# ---------------------------------------------------------------------------

class GlobalModeSelect(ZoneSelectBase):
    """Globaler Modus-Select."""

    _attr_is_global = True
    _attr_icon = "mdi:home-thermometer"
    _attr_name_suffix = "Modus"
    _attr_unique_suffix = "global_mode"
    _attr_options = HEATER_MODES
    _attr_default_value = HeaterMode.OFF.value


# ---------------------------------------------------------------------------
# Zone Selects
# ---------------------------------------------------------------------------

class ZoneModeSelect(ZoneSelectBase):
    """Zonen-Modus (statische Liste)."""

    _attr_icon = "mdi:radiator"
    _attr_name_suffix = "Modus"
    _attr_unique_suffix = "mode"
    _attr_options = HEATER_MODES
    _attr_default_value = HeaterMode.OFF.value

# ---------------------------------------------------------------------------
# Sensorbased Selects
# ---------------------------------------------------------------------------

class ZoneWindowSelect(ZoneSelectBase):
    """Fenster-/Türkontakt-Auswahl."""

    _attr_icon = "mdi:window-open-variant"
    _domain_filter = "binary_sensor"
    _device_classes = ("window", "door", "opening")
    _attr_name_suffix = "Window contact"
    _attr_unique_suffix = "window_sensor"

class ZoneTemperatureSelect(ZoneSelectBase):
    """Temperatursensor-Auswahl."""

    _attr_icon = "mdi:thermometer"
    _domain_filter = "sensor"
    _device_classes = ("temperature",)
    _attr_name_suffix = "Temperature sensor"
    _attr_unique_suffix = "temperature_sensor"

class ZoneHumiditySelect(ZoneSelectBase):
    """Feuchtigkeitssensor-Auswahl."""

    _attr_icon = "mdi:water-percent"
    _domain_filter = "sensor"
    _device_classes = ("humidity",)
    _attr_name_suffix = "Humidy sensor"
    _attr_unique_suffix = "humidity_sensor"
    
class ZoneThermostatSelect(ZoneSelectBase):
    """Thermostat-Auswahl."""

    _attr_icon = "mdi:thermostat"
    _domain_filter = "climate"
    _attr_name_suffix = "Thermostat"
    _attr_unique_suffix = "thermostat_sensor"