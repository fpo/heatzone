# /config/custom_components/heatzone/entity.py

from __future__ import annotations
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers import entity_registry as er
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback, Event
from homeassistant.const import EVENT_STATE_CHANGED  
from homeassistant.components.number import NumberEntity
from homeassistant.components.select import SelectEntity
from homeassistant.components.sensor import SensorEntity
from homeassistant.components.switch import SwitchEntity
from homeassistant.components.text import TextEntity
from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.components.button import ButtonEntity
from homeassistant.helpers import translation
from typing import Optional
from abc import abstractmethod

from .const import *
import logging

_LOGGER = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# ANCHOR - Base class for all entities
# ---------------------------------------------------------------------------

class ZoneEntityCore(RestoreEntity):
    """platform-independent core (zones + global)."""

    _attr_unique_suffix: str = "base"   # unique_id 
    _attr_name_suffix: str = "Entity"   # Fallback if no name is set
    _attr_is_global: bool = False       # global oder zone
    _attr_use_translation: bool = True  # use translation for names
    _attr_has_entity_name = False       # no automatic prefixing !
    _update_temps = False               # update temps if changed

    _attr_default_value: str | float | None = None
    _attr_native_value: str | float | None = None

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry,
                zone_id: str | None = None, ) -> None:
        
        self.hass = hass
        self._config_entry = entry

        # global / zone
        self._is_global = getattr(self, "_attr_is_global", False) or zone_id is None

        if not self._is_global:
            self._zone_id = zone_id
            self._zone_name = zone_id.capitalize()
            entity_prefix = zone_id
        else:
            self._zone_id = None
            self._zone_name = GLOBAL_DEVICE_NAME        # "Global"
            entity_prefix = GLOBAL_DEVICE_ID            # "global"

        # Unique-ID
        self._attr_unique_id = f"{entry.entry_id}_{entity_prefix}_{self._attr_unique_suffix}"
        
        # translation key
        if self._attr_use_translation:
            self._attr_translation_key = self._attr_unique_suffix

        # entity_id with prefix
        platform = self._detect_platform()
        if platform:
            self.entity_id = f"{platform}.{entity_prefix}_{self._attr_unique_suffix}"

        # default name - can be overridden (translate) in async_added_to_hass
        self._attr_name = self._attr_name_suffix

    def _detect_platform(self) -> str | None:
        """The platform recognizes the class hierarchy (MRO)."""
        for cls in self.__class__.__mro__:
            if cls is NumberEntity:
                return "number"
            if cls is SelectEntity:
                return "select"
            if cls is SensorEntity:
                return "sensor"
            if cls is SwitchEntity:
                return "switch"
            if cls is BinarySensorEntity:
                return "binary_sensor"
            if cls is TextEntity:
                return "text"
            if cls is ButtonEntity:
                return "button"
        return None

    async def _translate_name(self, key: str) -> str:
        """  translate enity-name by key from translations/*.json."""
        platform = self._detect_platform()
        if not platform:
            return key

        language = self.hass.config.language

        translations = await translation.async_get_translations(
            self.hass,
            language,
            "entity",
            {DOMAIN},
        )

        translation_key = f"component.{DOMAIN}.entity.{platform}.{key}.name"
        return translations.get(translation_key, key)

    async def async_added_to_hass(self) -> None:
        """restore state, defaults & name-translation."""
        await super().async_added_to_hass()

        if self._attr_use_translation:
            translated = await self._translate_name(self._attr_unique_suffix)

            _LOGGER.info(f"Translated name for {self._attr_unique_suffix}: {translated}")

            # only if translated exists and is different from defaults
            if translated and translated != self._attr_unique_suffix and translated != self._attr_name_suffix:
                # get entry from registry
                ent_reg = er.async_get(self.hass)
                entry = ent_reg.async_get(self.entity_id)

                # only if not set
                if entry is None or entry.name is None:
                    self._attr_name = translated

                    # clean up registry entry name
                    if entry is not None and entry.original_name != translated:
                        ent_reg.async_update_entity(self.entity_id, original_name=translated,)
                    self.async_write_ha_state()

        last_state = await self.async_get_last_state()
        
        if last_state is not None and last_state.state not in (None, "unknown", "unavailable"):
            self._attr_native_value = last_state.state
            _LOGGER.debug("Restored %s to %s", self.entity_id, last_state.state)
            return

        native_default = getattr(self, "_attr_native_default_value", None)
        if native_default is not None:
            self._attr_native_value = native_default
            _LOGGER.debug("Applied native default for %s: %s", self.entity_id, native_default)
            return

        if getattr(self, "_attr_default_value", None) is not None:
            self._attr_native_value = self._attr_default_value
            _LOGGER.debug("Applied custom default for %s: %s", self.entity_id, self._attr_default_value)
            return

        _LOGGER.debug("No restore/default for %s", self.entity_id)

    @property
    def native_value(self) -> str | float | None:
        return self._attr_native_value

    @property
    def device_info(self) -> DeviceInfo:
        if self._is_global:
            return DeviceInfo(
                identifiers={(DOMAIN, GLOBAL_DEVICE_ID)},
                name=GLOBAL_DEVICE_NAME,
                manufacturer=MANUFACTURER,
                model=GLOBAL_MODEL,
            )
        return DeviceInfo(
            identifiers={(DOMAIN, self._zone_id)},
            name=self._zone_name,
            manufacturer=MANUFACTURER,
            model=ZONE_MODEL,
        )

    @property
    def _manager(self):
        """Access for profile manager"""
        try:
            return self.hass.data[DOMAIN][self._config_entry.entry_id]["profile_manager"]
        except (KeyError, AttributeError):
            return None

    @callback
    def async_write_ha_state(self) -> None:
        """override to trigger manager after state change."""
        super().async_write_ha_state()

        if not getattr(self, "_manager", None):
            return
        
        if getattr(self, "_update_temps", False):
            self.hass.async_create_task(self._manager.update_temps())


# ---------------------------------------------------------------------------
# ANCHOR - Common base class for all mirror entities (Sensor + BinarySensor).
# ---------------------------------------------------------------------------

class ZoneMirrorEntityBase(ZoneEntityCore):
    """Common base class for all mirror entities (Sensor + BinarySensor)."""

    _attr_select_suffix: str = ""

    @abstractmethod
    def _get_mirrored_value(self, target_state):
        """Extracts the value from the mirrored sensor."""
        pass

    async def async_added_to_hass(self) -> None:
        """Register listeners and initialize selection."""
        await super().async_added_to_hass()
        
        # Initialize mirror-specific attributes
        self._selected_entity_id: str | None = None
        self._unsub_select = None
        self._unsub_sensor = None
        self._select_entity_id = f"select.{self._zone_id}_{self._attr_select_suffix}"

        _LOGGER.debug("[%s] Watching select entity: %s", self._zone_id, self._select_entity_id)
        await self._update_selected_sensor_id()

        # select change listener
        @callback
        def _handle_select_change(event: Event):
            if event.data.get("entity_id") != self._select_entity_id:
                return
            _LOGGER.debug("[%s] Select changed → refreshing", self._zone_id)
            self.hass.async_create_task(self._update_selected_sensor_id())

        self._unsub_select = self.hass.bus.async_listen(
            EVENT_STATE_CHANGED, _handle_select_change
        )

        # sensor change listener
        @callback
        def _handle_sensor_change(event: Event):
            if self._selected_entity_id and event.data.get("entity_id") == self._selected_entity_id:
                # force_refresh only applies to normal sensors, not to BinarySensors.
                force_refresh = self._detect_platform() == "sensor"
                self.async_schedule_update_ha_state(force_refresh=force_refresh)

        self._unsub_sensor = self.hass.bus.async_listen(
            EVENT_STATE_CHANGED, _handle_sensor_change
        )

    async def _update_selected_sensor_id(self):
        """Reads the currently selected sensor from select."""
        
        select_state = self.hass.states.get(self._select_entity_id)
        if not select_state:
            self._selected_entity_id = None
            self.async_schedule_update_ha_state()
            return

        selected_friendly = select_state.state
        if selected_friendly in (None, "unknown", "None"):
            self._selected_entity_id = None
            self.async_schedule_update_ha_state()
            return

        entity_map = select_state.attributes.get("entity_map")
        if not entity_map:
            self._selected_entity_id = None
            self.async_schedule_update_ha_state()
            return

        self._selected_entity_id = entity_map.get(selected_friendly)
        _LOGGER.debug("[%s] Selected sensor: %s", self._zone_id, self._selected_entity_id)
        
        # force_refresh only for normal sensors
        force_refresh = self._detect_platform() == "sensor"
        self.async_schedule_update_ha_state(force_refresh=force_refresh)

    async def async_will_remove_from_hass(self):
        """remove all listener"""
        
        if self._unsub_select:
            self._unsub_select()
            self._unsub_select = None
        if self._unsub_sensor:
            self._unsub_sensor()
            self._unsub_sensor = None

    def _get_target_state(self):
        """get the state of the sensor"""
        
        if not self._selected_entity_id:
            return None

        target_state = self.hass.states.get(self._selected_entity_id)
        if not target_state or target_state.state in ("unknown", "unavailable"):
            return None

        return target_state