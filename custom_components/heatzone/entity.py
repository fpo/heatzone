from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.components.number import NumberEntity
from homeassistant.components.select import SelectEntity
from homeassistant.components.sensor import SensorEntity
from homeassistant.components.switch import SwitchEntity
from homeassistant.components.text import TextEntity
from homeassistant.components.binary_sensor import BinarySensorEntity
from .const import *
import logging

_LOGGER = logging.getLogger(__name__)

class ZoneEntityCore(RestoreEntity):
    """Plattformunabhängiger Kern (Zonen + global)."""

    _attr_unique_suffix: str = "base"
    _attr_name_suffix: str = "Entity"
    _attr_is_global: bool = False
    _attr_has_entity_name = False
    _attr_default_value: str | float | None = None
    _attr_native_value: str | float | None = None

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry,
                 zone_id: str | None = None, zone_data: dict | None = None,) -> None:
        self.hass = hass
        self._config_entry = entry

        # global umschaltbar per Attribut oder Parameter
        self._is_global = getattr(self, "_attr_is_global", False) or zone_id is None
        self._attr_name = self._attr_name_suffix    

        if not self._is_global:
            self._zone_id = zone_id
            self._zone_name = (zone_data or {}).get("name", zone_id)
            entity_prefix = zone_id
        else:
            self._zone_id = None
            self._zone_name = "Global"
            entity_prefix = "global"

        # stabile Unique-ID
        self._attr_unique_id = f"{entry.entry_id}_{entity_prefix}_{self._attr_unique_suffix}"
        
        # entity_id MIT Prefix (zone_id oder global)
        platform = self._detect_platform()
        if platform:
            self.entity_id = f"{platform}.{entity_prefix}_{self._attr_unique_suffix}"

    # Platform-Erkennung (MRO-basiert)
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

    async def async_added_to_hass(self) -> None:
        """Restore last known state or apply default values."""
        await super().async_added_to_hass()

        last_state = await self.async_get_last_state()

        if last_state is not None and last_state.state not in (None, "unknown", "unavailable"):
            self._attr_native_value = last_state.state
            _LOGGER.debug(f"Restored {self.entity_id} to {last_state.state}")
            return

        native_default = getattr(self, "_attr_native_default_value", None)
        if native_default is not None:
            self._attr_native_value = native_default
            _LOGGER.debug(f"Applied native default for {self.entity_id}: {native_default}")
            return

        if getattr(self, "_attr_default_value", None) is not None:
            self._attr_native_value = self._attr_default_value
            _LOGGER.debug(f"Applied custom default for {self.entity_id}: {self._attr_default_value}")
            return

        _LOGGER.debug(f"No restore/default for {self.entity_id}")

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