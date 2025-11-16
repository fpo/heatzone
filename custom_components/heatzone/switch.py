# /config/custom_components/heatzone/switch.py
from __future__ import annotations
import asyncio
from datetime import datetime, timedelta
import logging
from homeassistant.components.switch import SwitchEntity
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers import translation
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from .entity import ZoneEntityCore
from .const import *

_LOGGER = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, 
                            async_add_entities: AddEntitiesCallback) -> None:
    """Set up switch entities for all zones."""
    zones = entry.options.get("zones", {})
    entities: list[SwitchEntity] = []

    for zone_id, zone_data in zones.items():
        entities.append(ZonePresentSwitch(hass, entry, zone_id, zone_data))
        entities.append(ZoneBoostSwitch(hass, entry, zone_id, zone_data))

    _LOGGER.debug("Setting up %d switch entities for %d zones", len(entities), len(zones))
    async_add_entities(entities)

# ---------------------------------------------------------------------------
# Base class switches
# ---------------------------------------------------------------------------

class ZoneSwitchBase(ZoneEntityCore, SwitchEntity):
    """Basisklasse für alle zonenbasierten Switch-Entities."""

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

# ---------------------------------------------------------------------------
# Zonen-Present-Schalter
# ---------------------------------------------------------------------------

class ZonePresentSwitch(ZoneSwitchBase):
    """Schaltet eine Zone auf An-/Abwesend."""

    _attr_icon = "mdi:radiator"
    _attr_unique_suffix = "present"
    _attr_name_suffix = "Present"

    def __init__(self, hass, entry, zone_id, zone_data):
        super().__init__(hass, entry, zone_id, zone_data)
        self._attr_is_on = zone_data.get("enabled", True)

    async def async_turn_on(self, **kwargs) -> None:
        """Turn the switch on."""
        self._attr_is_on = True
        self.async_write_ha_state()
        _LOGGER.info("[%s] Anwesend", self._zone_id)

    async def async_turn_off(self, **kwargs) -> None:
        """Turn the switch off."""
        self._attr_is_on = False
        self.async_write_ha_state()
        _LOGGER.info("[%s] Abwesend", self._zone_id)

# ---------------------------------------------------------------------------
# Zonen-Boost-Schalter
# ---------------------------------------------------------------------------

class ZoneBoostSwitch(ZoneSwitchBase):
    """Ein zeitlich begrenzter Boost-Schalter."""

    _attr_icon = "mdi:fire"
    _attr_unique_suffix = "boost"
    _attr_name_suffix = "Boost"

    def __init__(self, hass, entry, zone_id, zone_data):
        super().__init__(hass, entry, zone_id, zone_data)
        self._boost_temp = zone_data.get("boost_temp", 25.0)
        self._default_duration = zone_data.get("boost_duration", 10)
        self._global_duration_entity_id = "number.global_boost_duration"
        self._boost_until: datetime | None = None

    def _get_global_boost_duration(self) -> int:
        """Liest den globalen Boostdauerwert aus."""
        state = self.hass.states.get(self._global_duration_entity_id)
        if not state or state.state in ("unknown", "unavailable"):
            _LOGGER.warning(
                "[%s] Globale Boostdauer (%s) nicht verfügbar – Fallback: %ds",
                self._zone_id,
                self._global_duration_entity_id,
                self._default_duration,
            )
            return self._default_duration
        try:
            return int(float(state.state))
        except ValueError:
            return self._default_duration

    async def async_turn_on(self, **kwargs):
        """Boost starten."""
        duration = self._get_global_boost_duration()

        if self._attr_is_on:
            # Timer neu starten
            self._boost_until = datetime.now() + timedelta(seconds=duration)
            _LOGGER.debug("[%s] Boost-Timer neu gestartet (%ds)", self._zone_id, duration)
            return

        self._attr_is_on = True
        self._boost_until = datetime.now() + timedelta(seconds=duration)
        self.async_write_ha_state()

        _LOGGER.info("[%s] Boost gestartet: %.1f°C für %ds", self._zone_id, self._boost_temp, duration)

        async def _disable_later():
            await asyncio.sleep(duration)
            self._attr_is_on = False
            self._boost_until = None
            self.async_write_ha_state()
            _LOGGER.info("[%s] Boost beendet", self._zone_id)

        self.hass.async_create_task(_disable_later())

    async def async_turn_off(self, **kwargs):
        """Boost manuell abbrechen."""
        if not self._attr_is_on:
            return
        self._attr_is_on = False
        self._boost_until = None
        self.async_write_ha_state()
        _LOGGER.info("[%s] Boost manuell beendet", self._zone_id)