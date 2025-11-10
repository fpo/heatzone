# /config/custom_components/heatzone/sensor.py
from __future__ import annotations

import logging
from typing import Optional
from datetime import datetime

from homeassistant.const import EVENT_STATE_CHANGED, UnitOfTemperature
from homeassistant.components.sensor import (
    SensorEntity,
    SensorDeviceClass,
)
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
    entities: list[SensorEntity] = []

    for zone_id, zone_data in zones.items():
        entities.append(ZoneCurrentTemperatureSensor(hass, entry, zone_id, zone_data))
        entities.append(ZoneCurrentHumiditySensor(hass, entry, zone_id, zone_data))
        entities.append(ZoneWindowContactSensor(hass, entry, zone_id, zone_data))
        entities.append(ZoneTargetTemperatureSensor(hass, entry, zone_id, zone_data))

    _LOGGER.debug("Setting up %d sensor entities for %d zones", len(entities), len(zones))
    async_add_entities(entities)


# -----------------------------------------------------------------------------
# Basisklasse für alle Sensoren auf ZoneEntityCore
# -----------------------------------------------------------------------------

class ZoneSensorBase(ZoneEntityCore, SensorEntity):
    """Basisklasse für alle Heatzone-Sensoren."""

    _attr_icon: str | None = None
    _attr_native_unit_of_measurement: str | None = None
    _attr_device_class: SensorDeviceClass | None = None
    # _attr_unique_suffix: str = "sensor"
    # _attr_name_suffix: str = "Sensor"

    async def async_added_to_hass(self) -> None:
        """Restore aus Core + Sensor-spezifische Initialisierung."""
        await super().async_added_to_hass()


# -----------------------------------------------------------------------------
# Target Temperature Sensor
# -----------------------------------------------------------------------------

class ZoneTargetTemperatureSensor(ZoneSensorBase):
    """Zeigt den Sollwert der Zone abhängig vom Modus und Boost an."""

    _attr_icon = "mdi:thermostat-box"
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_name_suffix = "Temperatur-Soll"
    _attr_unique_suffix = "target_temperature"

    def __init__(self, hass, entry, zone_id: str, zone_data: dict):
        super().__init__(hass, entry, zone_id, zone_data)
        self._auto_entity_id = f"number.{zone_id}_target_temp"
        self._manual_entity_id = f"number.{zone_id}_manual_temp"
        self._mode_entity_id = f"select.{zone_id}_mode"
        self._boost_entity_id = f"switch.{zone_id}_boost"

        self._current_mode = None
        self._current_boost = False
        self._unsub_mode = None
        self._unsub_target = None
        self._unsub_boost = None

    async def async_added_to_hass(self) -> None:
        """Listener für Modus-, Temperatur- und Boost-Änderungen."""
        await super().async_added_to_hass()

        # Initiale Zustände
        if (mode_state := self.hass.states.get(self._mode_entity_id)):
            self._current_mode = mode_state.state

        if (boost_state := self.hass.states.get(self._boost_entity_id)):
            self._current_boost = boost_state.state == "on"

        # --- Listener für Modusänderungen ---
        @callback
        def _handle_mode_change(event: Event):
            if event.data.get("entity_id") != self._mode_entity_id:
                return
            new_mode = event.data["new_state"].state
            if new_mode != self._current_mode:
                self._current_mode = new_mode
                _LOGGER.debug("[%s] Modus geändert auf: %s", self._zone_id, new_mode)
                self.async_schedule_update_ha_state(True)

        self._unsub_mode = self.hass.bus.async_listen(EVENT_STATE_CHANGED, _handle_mode_change)

        # --- Listener für Zieltemperaturänderungen (Auto/Manuell) ---
        @callback
        def _handle_target_change(event: Event):
            if event.data.get("entity_id") in (self._auto_entity_id, self._manual_entity_id):
                self.async_schedule_update_ha_state(True)

        self._unsub_target = self.hass.bus.async_listen(EVENT_STATE_CHANGED, _handle_target_change)

        # --- Listener für Boost-Änderungen ---
        @callback
        def _handle_boost_change(event: Event):
            if event.data.get("entity_id") != self._boost_entity_id:
                return
            new_boost_state = event.data["new_state"].state == "on"
            if new_boost_state != self._current_boost:
                self._current_boost = new_boost_state
                _LOGGER.debug("[%s] Boost geändert auf: %s", self._zone_id, self._current_boost)
                self.async_schedule_update_ha_state(True)

        self._unsub_boost = self.hass.bus.async_listen(EVENT_STATE_CHANGED, _handle_boost_change)

        self.async_schedule_update_ha_state(True)

    async def async_will_remove_from_hass(self) -> None:
        """Aufräumen."""
        for unsub in (self._unsub_mode, self._unsub_target, self._unsub_boost):
            if unsub:
                unsub()
        self._unsub_mode = self._unsub_target = self._unsub_boost = None

    @property
    def native_value(self) -> Optional[float]:
        """Berechne aktive Solltemperatur."""
        # 1️⃣ Boost überschreibt alles
        if self._current_boost:
            global_boost_entity = "number.global_boost_temp"
            state = self.hass.states.get(global_boost_entity)

            if not state or state.state in ("unknown", "unavailable"):
                _LOGGER.warning("[%s] Globale Boost-Temperatur (%s) nicht verfügbar – Fallback: %.1f°C",
                                self._zone_id, global_boost_entity, self._boost_temp)
                return TEMP_FALLBACK 

            try:
                boost_temp = float(state.state)
                _LOGGER.debug("[%s] Boost aktiv → globale %.1f°C", self._zone_id, boost_temp)
                return boost_temp
            except (ValueError, TypeError):
                _LOGGER.warning("[%s] Ungültiger Wert in %s: %s – Fallback: %.1f°C",
                                self._zone_id, global_boost_entity, state.state, self._boost_temp)
                return TEMP_FALLBACK
            
        # 2️⃣ Sonst nach Modus
        if self._current_mode == HeaterMode.OFF.value:
            return TEMP_OFF
        if self._current_mode == HeaterExtendedMode.BYPASS.value:
            return TEMP_BYPASS

        entity_id = (
            self._manual_entity_id
            if self._current_mode == HeaterMode.MANUAL.value
            else self._auto_entity_id
        )

        if (state := self.hass.states.get(entity_id)) is None or state.state in ("unknown", "unavailable"):
            return None

        try:
            return float(state.state)
        except (ValueError, TypeError):
            _LOGGER.warning("[%s] Ungültiger Wert in %s: %s", self._zone_id, entity_id, state.state)
            return None


# -----------------------------------------------------------------------------
# Sensor-Mirror-Basis (spiegelt Sensorwert aus Select)
# -----------------------------------------------------------------------------

class ZoneMirrorSensorBase(ZoneSensorBase):
    """Basisklasse für Sensoren, die den Wert aus einem Select-gebundenen Sensor spiegeln."""

    _select_suffix: str = ""

    def __init__(self, hass, entry, zone_id, zone_data):
        # Dann Core-Konstruktor starten → erstellt korrekte unique_id + entity_id
        super().__init__(hass, entry, zone_id, zone_data)
        
        if self._select_suffix:
            self._attr_unique_suffix = self._select_suffix
            self._attr_unique_id = f"{entry.entry_id}_{zone_id}_{self._select_suffix}"
            self.entity_id = f"sensor.{zone_id}_{self._select_suffix}"
        
        # Jetzt alles Mirror-spezifische
        self._selected_entity_id: str | None = None
        self._unsub_select = None
        self._unsub_sensor = None
        self._select_entity_id = f"select.{zone_id}_{self._select_suffix}"

        # Entity-ID sicherstellen (optional, falls Core nichts gesetzt hat)
        if not getattr(self, "entity_id", None):
            self.entity_id = f"sensor.{zone_id}_{self._select_suffix}"

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
                self.async_schedule_update_ha_state(force_refresh=True)

        self._unsub_sensor = self.hass.bus.async_listen(EVENT_STATE_CHANGED, _handle_sensor_change)

    async def _update_selected_sensor_id(self):
        """Liest aus Select den aktuell gewählten Sensor."""
        select_state = self.hass.states.get(self._select_entity_id)
        if not select_state:
            self._selected_entity_id = None
            return

        selected_friendly = select_state.state
        if selected_friendly in (None, "unknown", "Kein"):
            self._selected_entity_id = None
            return

        entity_map = select_state.attributes.get("entity_map")
        if not entity_map:
            self._selected_entity_id = None
            return

        self._selected_entity_id = entity_map.get(selected_friendly)
        _LOGGER.debug("[%s] Selected sensor: %s", self._zone_id, self._selected_entity_id)
        self.async_schedule_update_ha_state(force_refresh=True)

    async def async_will_remove_from_hass(self):
        """Alle Listener entfernen."""
        if self._unsub_select:
            self._unsub_select()
            self._unsub_select = None
        if self._unsub_sensor:
            self._unsub_sensor()
            self._unsub_sensor = None

    @property
    def native_value(self):
        """Liefert den aktuellen Wert des ausgewählten Sensors."""
        if not self._selected_entity_id:
            return None

        target_state = self.hass.states.get(self._selected_entity_id)
        if not target_state or target_state.state in ("unknown", "unavailable"):
            return None

        try:
            return float(target_state.state)
        except ValueError:
            return target_state.state


# -----------------------------------------------------------------------------
# Spiegel-Sensoren
# -----------------------------------------------------------------------------

class ZoneCurrentTemperatureSensor(ZoneMirrorSensorBase):
    """Spiegelt die Temperatur des gewählten Sensors."""
    _select_suffix = "temperature_sensor"
    _attr_native_unit_of_measurement = "°C"
    _attr_icon = "mdi:thermometer"
    _attr_name_suffix = "Temperatur-Ist"

class ZoneCurrentHumiditySensor(ZoneMirrorSensorBase):
    """Spiegelt die Feuchtigkeit des gewählten Sensors."""
    _select_suffix = "humidity_sensor"
    _attr_native_unit_of_measurement = "%"
    _attr_icon = "mdi:water-percent"
    _attr_name_suffix = "Feuchtigkeit"

class ZoneWindowContactSensor(ZoneMirrorSensorBase):
    """Spiegelt den Zustand des gewählten Fensterkontakts."""
    _select_suffix = "window_sensor"
    _attr_icon = "mdi:window-open-variant"
    _attr_name_suffix = "Fensterkontakt"
    
    @property
    def native_value(self):
        """Liefert 'Offen' oder 'Geschlossen'."""
        if not self._selected_entity_id:
            return "Unbekannt"

        target_state = self.hass.states.get(self._selected_entity_id)
        if not target_state or target_state.state in ("unknown", "unavailable"):
            return "Unbekannt"

        if target_state.state == "on":
            return "Offen"
        elif target_state.state == "off":
            return "Geschlossen"
        return target_state.state

# -----------------------------------------------------------------------------
# Status Sensor
# -----------------------------------------------------------------------------

class ZoneStatusSensor(ZoneSensorBase):
    """Zeigt den aktuellen Heizstatus der Zone anhand von Modus, Boost und Fensterzustand."""

    _attr_icon = "mdi:home-thermometer-outline"
    _attr_name_suffix = "Status"
    _attr_unique_suffix = "status"

    def __init__(self, hass, entry, zone_id, zone_data):
        super().__init__(hass, entry, zone_id, zone_data)

        # Zugehörige Entitäten
        self._boost_entity_id = f"switch.{zone_id}_boost"
        self._window_select_entity_id = f"select.{zone_id}_window_sensor"
        self._mode_entity_id = f"select.{zone_id}_mode"

        # Interne Zustände
        self._selected_window_entity: str | None = None
        self._current_boost = False
        self._current_window_open = False
        self._current_mode: Optional[str] = None

        # Listener
        self._unsub_boost = None
        self._unsub_window_select = None
        self._unsub_window_sensor = None
        self._unsub_mode = None

    async def async_added_to_hass(self) -> None:
        """Initialisieren und alle Listener registrieren."""
        await super().async_added_to_hass()

        await self._update_boost_state()
        await self._update_window_sensor_target()
        await self._update_mode_state()

        # --- Boost Listener ---
        @callback
        def _handle_boost_change(event: Event):
            if event.data.get("entity_id") != self._boost_entity_id:
                return
            new_state = event.data["new_state"].state
            self._current_boost = new_state == "on"
            _LOGGER.debug("[%s] Boost geändert: %s", self._zone_id, new_state)
            self.async_schedule_update_ha_state(True)

        self._unsub_boost = self.hass.bus.async_listen(EVENT_STATE_CHANGED, _handle_boost_change)

        # --- Fenster-Select Listener ---
        @callback
        def _handle_window_select_change(event: Event):
            if event.data.get("entity_id") != self._window_select_entity_id:
                return
            _LOGGER.debug("[%s] Fenster-Select geändert → neuen Kontakt suchen", self._zone_id)
            self.hass.async_create_task(self._update_window_sensor_target())

        self._unsub_window_select = self.hass.bus.async_listen(EVENT_STATE_CHANGED, _handle_window_select_change)

        # --- Fensterkontakt Listener ---
        @callback
        def _handle_window_state_change(event: Event):
            if self._selected_window_entity and event.data.get("entity_id") == self._selected_window_entity:
                new_state = event.data["new_state"].state
                self._current_window_open = new_state == "on"
                _LOGGER.debug("[%s] Fensterkontakt geändert: %s", self._zone_id, new_state)
                self.async_schedule_update_ha_state(True)

        self._unsub_window_sensor = self.hass.bus.async_listen(EVENT_STATE_CHANGED, _handle_window_state_change)

        # --- Modus Listener ---
        @callback
        def _handle_mode_change(event: Event):
            if event.data.get("entity_id") != self._mode_entity_id:
                return
            new_mode = event.data["new_state"].state
            if new_mode != self._current_mode:
                self._current_mode = new_mode
                _LOGGER.debug("[%s] Modus geändert: %s", self._zone_id, new_mode)
                self.async_schedule_update_ha_state(True)

        self._unsub_mode = self.hass.bus.async_listen(EVENT_STATE_CHANGED, _handle_mode_change)

        # Erstes Update anzeigen
        self.async_schedule_update_ha_state(True)

    async def async_will_remove_from_hass(self):
        """Alle Listener entfernen."""
        for unsub in (
            self._unsub_boost,
            self._unsub_window_select,
            self._unsub_window_sensor,
            self._unsub_mode,
        ):
            if unsub:
                unsub()
        self._unsub_boost = self._unsub_window_select = self._unsub_window_sensor = self._unsub_mode = None

    async def _update_boost_state(self):
        """Liest aktuellen Boost-Zustand."""
        if (state := self.hass.states.get(self._boost_entity_id)):
            self._current_boost = state.state == "on"

    async def _update_window_sensor_target(self):
        """Ermittelt den aktuell im Select gewählten Fensterkontakt."""
        select_state = self.hass.states.get(self._window_select_entity_id)
        if not select_state:
            self._selected_window_entity = None
            self._current_window_open = False
            return

        selected_name = select_state.state
        if selected_name in (None, "unknown", "Kein"):
            self._selected_window_entity = None
            self._current_window_open = False
            return

        entity_map = select_state.attributes.get("entity_map", {})
        self._selected_window_entity = entity_map.get(selected_name)

        if self._selected_window_entity:
            if (win_state := self.hass.states.get(self._selected_window_entity)):
                self._current_window_open = win_state.state == "on"

    async def _update_mode_state(self):
        """Liest den aktuellen Modus der Zone."""
        if (mode_state := self.hass.states.get(self._mode_entity_id)):
            self._current_mode = mode_state.state

    @property
    def native_value(self) -> str:
        """Liefert den kombinierten Status."""
        # 1️⃣ Fenster offen überschreibt alles
        if self._current_window_open:
            return HeaterExtendedMode.OPEN

        # 2️⃣ Boost aktiv
        if self._current_boost:
            return HeaterExtendedMode.BOOST

        # 3️⃣ Aktueller Modus (Profil, Manuell, etc.)
        if self._current_mode:
            return self._current_mode

        # 4️⃣ Fallback
        return HeaterMode.OFF

    @property
    def extra_state_attributes(self) -> dict:
        """Zusatzinfos für Debugging."""
        return {
            "boost_active": self._current_boost,
            "window_open": self._current_window_open,
            "mode": self._current_mode,
            "window_entity": self._selected_window_entity,
        }

