from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers import entity_registry as er
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.components.number import NumberEntity
from homeassistant.components.select import SelectEntity
from homeassistant.components.sensor import SensorEntity
from homeassistant.components.switch import SwitchEntity
from homeassistant.components.text import TextEntity
from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.helpers import translation

from .const import *
import logging

_LOGGER = logging.getLogger(__name__)


class ZoneEntityCore(RestoreEntity):
    """Plattformunabhängiger Kern (Zonen + global)."""

    _attr_unique_suffix: str = "base"   # unique_id 
    _attr_name_suffix: str = "Entity"   # Fallback if no name is set
    _attr_is_global: bool = False       # global oder zone
    _attr_use_translation: bool = True  # use translation for names
    _attr_has_entity_name = False       # no automatic prefixing !

    _attr_default_value: str | float | None = None
    _attr_native_value: str | float | None = None

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry,
                zone_id: str | None = None, zone_data: dict | None = None,) -> None:
        
        self.hass = hass
        self._config_entry = entry

        # global / zone
        self._is_global = getattr(self, "_attr_is_global", False) or zone_id is None

        if not self._is_global:
            self._zone_id = zone_id
            self._zone_name = (zone_data or {}).get("name", zone_id)
            entity_prefix = zone_id
        else:
            self._zone_id = None
            self._zone_name = GLOBAL_DEVICE_NAME
            entity_prefix = "global"

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
        """restore state, Defaults & Name-Translation."""
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
