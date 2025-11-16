from __future__ import annotations

import logging
from typing import Optional

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.const import EVENT_STATE_CHANGED, STATE_ON, STATE_OFF
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback, Event

from .entity import ZoneEntityCore
from .const import *

_LOGGER = logging.getLogger(__name__)



# -----------------------------------------------------------------------------
# SETUP
# -----------------------------------------------------------------------------

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up sensor entities for all zones."""
    zones = entry.options.get("zones", {})
    entities: list[BinarySensorEntity] = []

    for zone_id, zone_data in zones.items():
        entities.append(ZoneWindowContactBinarySensor(hass, entry, zone_id, zone_data))

    _LOGGER.debug("Setting up %d binary_sensor entities for %d zones", len(entities), len(zones))
    async_add_entities(entities)

# -----------------------------------------------------------------------------
# Basisklasse für alle Sensoren auf ZoneEntityCore
# -----------------------------------------------------------------------------

class ZoneBinarySensorBase(ZoneEntityCore, BinarySensorEntity):
    """Basisklasse für alle Heatzone-Sensoren."""

    _attr_icon: str | None = None
    _attr_native_unit_of_measurement: str | None = None
    _attr_device_class: BinarySensorDeviceClass | None = None

    async def async_added_to_hass(self) -> None:
        """Restore aus Core + Sensor-spezifische Initialisierung."""
        await super().async_added_to_hass()

# -----------------------------------------------------------------------------
# BinarySensor-Mirror-Basis (spiegelt Sensorwert aus Select)
# -----------------------------------------------------------------------------

class ZoneMirrorBinarySensorBase(ZoneBinarySensorBase):
    """Basisklasse für BinarySensoren, die den Wert aus einem Select-gebundenen Sensor spiegeln."""

    _select_suffix: str = ""

    def __init__(self, hass, entry, zone_id, zone_data):
        # Dann Core-Konstruktor starten → erstellt korrekte unique_id + entity_id
        super().__init__(hass, entry, zone_id, zone_data)
        
        if self._select_suffix:
            self._attr_unique_suffix = self._select_suffix
            self._attr_unique_id = f"{entry.entry_id}_{zone_id}_{self._select_suffix}"
            self.entity_id = f"binary_sensor.{zone_id}_{self._select_suffix}"
        
        # Jetzt alles Mirror-spezifische
        self._selected_entity_id: str | None = None
        self._unsub_select = None
        self._unsub_sensor = None
        self._select_entity_id = f"select.{zone_id}_{self._select_suffix}"

        # Entity-ID sicherstellen (optional, falls Core nichts gesetzt hat)
        if not getattr(self, "entity_id", None):
            self.entity_id = f"binary_sensor.{zone_id}_{self._select_suffix}"

    async def async_added_to_hass(self) -> None:
        """Registriere Listener und initialisiere Auswahl."""
        await super().async_added_to_hass()

        _LOGGER.debug("[%s] Watching select entity: %s", self._zone_id, self._select_entity_id)
        await self._update_selected_sensor_id()

        @callback
        def _handle_select_change(event: Event):
            if event.data.get("entity_id") != self._select_entity_id:
                return
            _LOGGER.debug("[%s] Select changed → refreshing", self._zone_id)
            self.hass.async_create_task(self._update_selected_sensor_id())

        self._unsub_select = self.hass.bus.async_listen(EVENT_STATE_CHANGED, _handle_select_change)

        @callback
        def _handle_sensor_change(event: Event):
            if self._selected_entity_id and event.data.get("entity_id") == self._selected_entity_id:
                self.async_schedule_update_ha_state()  # ← force_refresh=True nicht nötig

        self._unsub_sensor = self.hass.bus.async_listen(EVENT_STATE_CHANGED, _handle_sensor_change)

    async def _update_selected_sensor_id(self):
        """Liest aus Select den aktuell gewählten Sensor."""
        select_state = self.hass.states.get(self._select_entity_id)
        if not select_state:
            self._selected_entity_id = None
            self.async_schedule_update_ha_state()
            return

        selected_friendly = select_state.state
        if selected_friendly in (None, "unknown", "Kein"):
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
        self.async_schedule_update_ha_state()

    async def async_will_remove_from_hass(self):
        """Alle Listener entfernen."""
        if self._unsub_select:
            self._unsub_select()
            self._unsub_select = None
        if self._unsub_sensor:
            self._unsub_sensor()
            self._unsub_sensor = None

    @property
    def is_on(self) -> bool:  # ← WICHTIG: is_on statt native_value!
        """Return true if binary sensor is on."""
        if not self._selected_entity_id:
            return False

        target_state = self.hass.states.get(self._selected_entity_id)
        
        if not target_state or target_state.state in ("unknown", "unavailable"):
            return False

        # Map both "on" and "open" to True
        return target_state.state in (STATE_ON, "open")


# -----------------------------------------------------------------------------
# Spiegel-Sensoren
# -----------------------------------------------------------------------------

class ZoneWindowContactBinarySensor(ZoneMirrorBinarySensorBase):
    """Spiegelt den Zustand des gewählten Fensterkontakts."""
    _select_suffix = "window_sensor"
    _attr_device_class = BinarySensorDeviceClass.WINDOW  # ← WICHTIG!
    _attr_icon = "mdi:window-open-variant"
    _attr_name_suffix = "Window contact"