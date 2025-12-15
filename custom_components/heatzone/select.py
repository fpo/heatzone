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
# ANCHOR - Base class for select mit Multi-Select Support
# ---------------------------------------------------------------------------

class ZoneSelectBase(ZoneEntityCore, SelectEntity):
    """Base class for all zone-related selects with optional multi-select support."""

    _attr_icon: str | None = None
    _domain_filter: str = ""
    _device_classes: tuple[str, ...] = ()
    _attr_options: list[str] = []
    _attr_current_option: Optional[str] = None
    _attr_allow_multiple: bool = False  # NEU: Default False für Abwärtskompatibilität

    _entity_map: dict[str, str] = {}
    _selected_entities: list[str] = []  # NEU: Liste für Multi-Select
    _restored_option: Optional[str] = None
    _state_listener_unsubscribe: Optional[Callable] = None
    _reload_attempts: int = 0
    _max_reload_attempts: int = 5

    @property
    def extra_state_attributes(self) -> dict:
        """Expose entity mapping and selected entities as attributes."""
        attrs = {
            "entity_map": self._entity_map,
            "allow_multiple": self._attr_allow_multiple,
        }
        
        # NEU: Speichere Liste für Restore
        if self._attr_allow_multiple:
            attrs["selected_entity_ids"] = self._selected_entities
            attrs["selection_count"] = len(self._selected_entities)
        else:
            attrs["selected_entity_id"] = self.selected_entity_id
            
        return attrs

    @property
    def current_option(self) -> str | None:
        """Return the currently selected option."""
        return self._attr_current_option

    @property
    def selected_entity_id(self) -> Optional[str]:
        """Return the entity_id of the first selected option (backward compatible)."""
        if self._attr_allow_multiple:
            # if multi-select then first entry
            return self._selected_entities[0] if self._selected_entities else None
        else:
            if not self._attr_current_option:
                return None
            return self._entity_map.get(self._attr_current_option)

    @property
    def selected_entity_ids(self) -> list[str]:
        """Return all selected entity_ids (for multi-select)."""
        if self._attr_allow_multiple:
            return self._selected_entities.copy()
        else:
            # if single-select: list with max. 1 element
            entity_id = self.selected_entity_id
            return [entity_id] if entity_id else []

    async def _translate_selected_state(self) -> str:
        """Translate the selected state for multi-select display."""
          
        # try translate - fallback english
        path = f"component.{DOMAIN}.entity.select.{self._attr_unique_suffix}.state.selected"
        translated = self.platform.platform_data.platform_translations.get(path)
        
        if translated:
            count_text = translated.format(count=len(self._selected_entities))
        else:
            count_text = f"{len(self._selected_entities)} selected"
        
        return count_text

    async def async_added_to_hass(self) -> None:
        """Setup entity, restore state, and attach listener."""
        await ZoneEntityCore.async_added_to_hass(self)

        # restore for multi-select
        if (last_state := await self.async_get_last_state()) is not None:
            if self._attr_allow_multiple:
                # restore list
                if entity_ids := last_state.attributes.get("selected_entity_ids"):
                    self._selected_entities = list(entity_ids)
                    _LOGGER.debug(
                        "[%s/%s] Restored %d entities: %s",
                        getattr(self, "_zone_name", "Global"),
                        self.__class__.__name__,
                        len(entity_ids),
                        entity_ids,
                    )
            else:
                # restore single-entry
                if last_state.state not in (None, "unknown", "unavailable"):
                    self._restored_option = last_state.state
                    _LOGGER.debug(
                        "[%s/%s] Restored option: %s",
                        getattr(self, "_zone_name", "Global"),
                        self.__class__.__name__,
                        self._restored_option,
                    )

        await self._load_options()
        await self._schedule_reload_attempts()

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
        delay_map = {
            "climate": [3, 8, 15, 25, 40],
            "sensor": [2, 5, 10],
            "binary_sensor": [2, 5, 10]
        }
        
        delays = delay_map.get(self._domain_filter, [2, 5, 10])
        
        for attempt, delay in enumerate(delays, start=1):
            async def delayed_reload(_now, attempt_num=attempt):
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
                
                if new_count > 1:
                    _LOGGER.debug(
                        "[%s/%s] Successfully loaded %d options, stopping further attempts",
                        getattr(self, "_zone_name", "Global"),
                        self.__class__.__name__,
                        new_count,
                    )
                    self._reload_attempts = len(delays)
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
            await self._apply_restored_or_default_option()
            return

        old_options = set(self._attr_options)
        old_count = len(self._attr_options)
        
        # WICHTIG: Liste komplett neu initialisieren
        self._attr_options = []
        self._entity_map = {}
        
        # Füge "None" hinzu
        self._attr_options.append("None")
        self._entity_map["None"] = None

        available_count = 0
                
        for state in self.hass.states.async_all(self._domain_filter):
            if self._domain_filter == "climate" or (
                self._device_classes
                and state.attributes.get("device_class") in self._device_classes
            ):
                friendly = state.name
                entity_id = state.entity_id
                
                # NEU: Bei Multi-Select Checkmark hinzufügen
                if self._attr_allow_multiple:
                    is_selected = entity_id in self._selected_entities
                    display_name = f"{'✓ ' if is_selected else '  '}{friendly}"
                    self._attr_options.append(display_name)
                    self._entity_map[display_name] = entity_id
                else:
                    self._attr_options.append(friendly)
                    self._entity_map[friendly] = entity_id
                    
                available_count += 1

        # Sortiere alphabetisch, None bleibt oben
        if len(self._attr_options) > 1:
            none_option = self._attr_options[0]
            rest = self._attr_options[1:]
            rest.sort(key=lambda x: x.lstrip('✓ '))
            self._attr_options = [none_option] + rest
        
        # NEU: Bei Multi-Select füge Status-Option hinzu wenn mehrere ausgewählt
        if self._attr_allow_multiple and len(self._selected_entities) > 1:

            count_text = await self._translate_selected_state()
            count_option = f"✓ {count_text}"
            self._attr_options.insert(0, count_option)
            self._entity_map[count_option] = None

        new_count = len(self._attr_options)
        
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
            await self._apply_restored_or_default_option()
        elif new_count == 1:
            _LOGGER.debug(
                "[%s/%s] No %s entities available yet (will retry)",
                getattr(self, "_zone_name", "Global"),
                self.__class__.__name__,
                self._domain_filter,
            )

    async def _apply_restored_or_default_option(self) -> None:
        """Apply the restored or default option."""
        if self._attr_allow_multiple:
            # multi-select restore/default
            if len(self._selected_entities) == 0:
                # none selected
                self._attr_current_option = "None"
            elif len(self._selected_entities) == 1:
                # single select
                entity_id = self._selected_entities[0]
                # found display name and remove checkmark if present
                for display_name, eid in self._entity_map.items():
                    if eid == entity_id:
                        self._attr_current_option = display_name
                        break
                else:
                    self._attr_current_option = "None"
            else:
                # multiple select, try translate - fallback english
                count_text = await self._translate_selected_state()
                self._attr_current_option = f"✓ {count_text}"
        else:
            # single-select restore/default
            if self._restored_option and self._restored_option in self._attr_options:
                self._attr_current_option = self._restored_option
                _LOGGER.debug("[%s/%s] Applied restored option: %s",
                              getattr(self, "_zone_name", "Global"),
                              self.__class__.__name__,
                              self._restored_option)
            elif getattr(self, "_attr_default_value", None) in self._attr_options:
                self._attr_current_option = self._attr_default_value
                _LOGGER.debug("[%s/%s] Applied default option: %s",
                              getattr(self, "_zone_name", "Global"),
                              self.__class__.__name__,
                              self._attr_default_value)
            elif "None" in self._attr_options:
                self._attr_current_option = "None"
                _LOGGER.debug("[%s/%s] No restore/default, fallback 'None'",
                              getattr(self, "_zone_name", "Global"),
                              self.__class__.__name__)

        self._attr_native_value = self._attr_current_option
        self.async_write_ha_state()

    async def async_select_option(self, option: str) -> None:
        """Handle option selection - toggle for multi-select, replace for single-select."""
        if option not in self._attr_options:
            _LOGGER.warning(
                f"{self.entity_id}: Invalid option '{option}' (valid: {self._attr_options})"
            )
            return

        if self._attr_allow_multiple:
            # multi-select handling

            # ignore if already selected status option
            if "selected" in option:
                return
            
            # handle "None" - clear all selections
            if option == "None":
                if self._selected_entities:
                    self._selected_entities.clear()
                    _LOGGER.debug(f"{self.entity_id}: Cleared all selections")
                    await self._load_options()
                    self._attr_current_option = "None"
                    self._attr_native_value = self._attr_current_option
                    self.async_write_ha_state()
                return
                
            # get entity_id
            entity_id = self._entity_map.get(option)
            if not entity_id:
                _LOGGER.warning(f"{self.entity_id}: No entity_id for option '{option}'")
                return
            
            # toggle in list
            if entity_id in self._selected_entities:
                self._selected_entities.remove(entity_id)
                action = "Removed"
            else:
                self._selected_entities.append(entity_id)
                action = "Added"
            
            _LOGGER.debug(f"{self.entity_id}: {action} {option} ({entity_id})")
            
            # reload to update state and checkmarks
            self.hass.async_create_task(self._load_options())
            
            # state update
            if len(self._selected_entities) == 0:
                self._attr_current_option = "None"
            elif len(self._selected_entities) == 1:
                # show the selected name
                entity_id = self._selected_entities[0]
                for display_name, eid in self._entity_map.items():
                    if eid == entity_id:
                        self._attr_current_option = display_name
                        break
            else:
                # try translate - fallback english
                count_text = await self._translate_selected_state()
                self._attr_current_option = f"✓ {count_text}"
        else:
            self._attr_current_option = option
        
        self._attr_native_value = self._attr_current_option
        self.async_write_ha_state()
        
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
    _attr_allow_multiple = True

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
    """Thermostat selection - mit Multi-Select Support."""

    _attr_icon = "mdi:thermostat"
    _domain_filter = "climate"
    _attr_name_suffix = "Thermostat"
    _attr_unique_suffix = "thermostat_sensor"
    _attr_allow_multiple = True 