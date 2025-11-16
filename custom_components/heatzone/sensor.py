# /config/custom_components/heatzone/sensor.py
from __future__ import annotations

import logging
import json
from typing import Optional
from datetime import datetime
from homeassistant.const import EVENT_STATE_CHANGED, UnitOfTemperature
from homeassistant.const import STATE_ON, STATE_OFF, STATE_OPEN, STATE_CLOSED, STATE_UNKNOWN
from homeassistant.components.sensor import ( SensorEntity, SensorDeviceClass,)
from homeassistant.components import mqtt
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_call_later
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback, Event
from .entity import ZoneEntityCore
from .const import *

_LOGGER = logging.getLogger(__name__)

# -----------------------------------------------------------------------------
# SETUP
# -----------------------------------------------------------------------------

async def async_setup_entry(hass: HomeAssistant,entry: ConfigEntry,
                            async_add_entities: AddEntitiesCallback,) -> None:
    """Set up sensor entities for all zones."""
    zones = entry.options.get("zones", {})
    entities: list[SensorEntity] = []

    for zone_id, zone_data in zones.items():
        entities.append(ZoneCurrentTemperatureSensor(hass, entry, zone_id, zone_data))
        entities.append(ZoneCurrentHumiditySensor(hass, entry, zone_id, zone_data))
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

    async def async_added_to_hass(self) -> None:
        """Restore aus Core + Sensor-spezifische Initialisierung."""
        await super().async_added_to_hass()


# -----------------------------------------------------------------------------
# Target Temperature Sensor
# -----------------------------------------------------------------------------

class ZoneTargetTemperatureSensor(ZoneSensorBase):
    """Zeigt den Sollwert der Zone abhängig vom Modus, Boost und Fensterkontakt an."""

    _attr_icon = "mdi:thermostat-box"
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_name_suffix = "Target temperature"
    _attr_unique_suffix = "target_temperature"

    def __init__(self, hass, entry, zone_id: str, zone_data: dict):
        super().__init__(hass, entry, zone_id, zone_data)
        self._target_entity_id = f"number.{zone_id}_target_temp"
        self._manual_entity_id = f"number.{zone_id}_manual_temp"
        self._mode_entity_id = f"select.{zone_id}_mode"
        self._boost_entity_id = f"switch.{zone_id}_boost"
        self._window_entity_id = f"binary_sensor.{zone_id}_window_sensor"
        self._present_entity_id = f"switch.{zone_id}_present"
        self._thermostat_select_entity_id = f"select.{zone_id}_thermostat_sensor"
        
        # Climate-Integration
        self._thermostat_selector_entity_id = f"select.{zone_id}_thermostat_sensor"
        self._current_climate_entity_id = None  # Wird dynamisch aus Select geladen
        self._last_sent_temp = None  # Verhindert unnötige Service Calls

        self._current_mode = None
        self._current_boost = False
        self._present = True
        self._unsub_mode = None
        self._unsub_target = None
        self._unsub_boost = None
        self._unsub_window = None
        self._unsub_present = None
        self._unsub_thermostat = None
        self._window_open = False
        self._window_timer = None
        self._window_delay_seconds = 30

        
    async def async_added_to_hass(self) -> None:
        """Listener für Modus-, Temperatur-, Boost-, Fensterkontakt- und Present-Änderungen."""
        await super().async_added_to_hass()

        # Initiale Zustände
        if (mode_state := self.hass.states.get(self._mode_entity_id)):
            self._current_mode = mode_state.state

        if (boost_state := self.hass.states.get(self._boost_entity_id)):
            self._current_boost = boost_state.state == "on"

        if (window_state := self.hass.states.get(self._window_entity_id)):
            self._window_open = window_state.state in (STATE_ON, STATE_OPEN)

        if (present_state := self.hass.states.get(self._present_entity_id)):
            self._present = present_state.state == "on"

        # Initiales Thermostat aus Select laden
        if (thermostat_state := self.hass.states.get(self._thermostat_selector_entity_id)):
            self._current_climate_entity_id = thermostat_state.state
            _LOGGER.debug("[%s] Initiales Thermostat: %s", self._zone_id, self._current_climate_entity_id)


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
            if event.data.get("entity_id") in (self._target_entity_id, self._manual_entity_id):
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

        # --- Listener für Fensterkontakt-Änderungen ---
        @callback
        def _handle_window_change(event: Event):
            """Handle window sensor state changes."""
            if event.data.get("entity_id") != self._window_entity_id:
                return
            
            self._window_open = event.data["new_state"].state in (STATE_ON, STATE_OPEN) 
            
            _LOGGER.debug(f"Zone {self._zone_id}: Window sensor changed to {self._window_open}")
    
            if self._window_open:
                # Fenster wurde geöffnet - MIT Sperrzeit
                _LOGGER.info(f"Zone {self._zone_id}: Window opened, starting {self._window_delay_seconds}s delay")
                
                # Alten Timer abbrechen falls vorhanden
                if self._window_timer:
                    self._window_timer()
                    self._window_timer = None
                
                # Neuen Timer starten
                self._window_timer = async_call_later(self.hass, self._window_delay_seconds, self._apply_window_open)
            
            else:
                # Fenster wurde geschlossen - SOFORT reagieren
                _LOGGER.info(f"Zone {self._zone_id}: Window closed, restoring temperature immediately")
                
                # Timer abbrechen falls noch läuft
                if self._window_timer:
                    self._window_timer()
                    self._window_timer = None
                
                self.async_schedule_update_ha_state(True)
                
                # Sofortiges Temperature-Update
                profile_manager = self.hass.data[DOMAIN][self._config_entry.entry_id]["profile_manager"]
                self.hass.async_create_task(profile_manager.update_temps())

        self._unsub_window = self.hass.bus.async_listen(EVENT_STATE_CHANGED, _handle_window_change)

        # --- Listener für Present-Änderungen ---
        @callback
        def _handle_present_change(event: Event):
            if event.data.get("entity_id") != self._present_entity_id:
                return
            new_present_state = event.data["new_state"].state == "on"
            if new_present_state != self._present:
                old_value = self._present
                self._present = new_present_state
                self.async_schedule_update_ha_state(True)
                # Temperaturen sofort aktualisieren
                profile_manager = self.hass.data[DOMAIN][self._config_entry.entry_id]["profile_manager"]
                self.hass.async_create_task(profile_manager.update_temps())

        self._unsub_present = self.hass.bus.async_listen(EVENT_STATE_CHANGED, _handle_present_change)

        # --- Listener für Thermostat-Selector-Änderungen ---
        @callback
        def _handle_thermostat_change(event: Event):
            if event.data.get("entity_id") != self._thermostat_select_entity_id:
                return
            
            new_state = event.data.get("new_state")
            if new_state is None:
                return
            
            #TODO - Check
            selected_entity_id = new_state.attributes.get("selected_entity_id")
            _LOGGER.debug("Event received for thermostat change: %s", selected_entity_id)
             
            if selected_entity_id == self._thermostat_selector_entity_id:
                return
            new_climate_entity = selected_entity_id
            if new_climate_entity != self._current_climate_entity_id:
                old_entity = self._current_climate_entity_id
                self._current_climate_entity_id = new_climate_entity
                _LOGGER.info(
                    "[%s] Thermostat geändert von %s zu %s",
                    self._zone_id,
                    old_entity,
                    new_climate_entity
                )
                # Aktuelle Temperatur sofort an neues Thermostat senden
                self._last_sent_temp = None  # Reset um sofortiges Senden zu erzwingen
                self.async_schedule_update_ha_state(True)

        self._unsub_thermostat = self.hass.bus.async_listen(EVENT_STATE_CHANGED, _handle_thermostat_change)
        
    async def _apply_window_open(self, now=None):        
        """Called after delay when window is still open."""
        _LOGGER.info(f"Zone {self._zone_id}: Window delay expired, setting temperature to 0°C")
        
        self._window_timer = None
        self.async_schedule_update_ha_state(True)
    
        # Temperature-Update triggern
        profile_manager = self.hass.data[DOMAIN][self._config_entry.entry_id]["profile_manager"]
        self.hass.async_create_task(profile_manager.update_temps())
    
    
        
    async def async_will_remove_from_hass(self) -> None:
        """Aufräumen."""
        for unsub in (self._unsub_mode, self._unsub_target, self._unsub_boost, self._unsub_window, self._unsub_present, self._unsub_thermostat):
            if unsub:
                unsub()
        self._unsub_mode = self._unsub_target = self._unsub_boost = self._unsub_window = self._unsub_present = self._unsub_thermostat = None

    @property
    def native_value(self) -> Optional[float]:
        """Berechne aktive Solltemperatur."""
        # 1️⃣ Fensterkontakt hat höchste Priorität - only if the timer does not run
        if self._window_open and self._window_timer == None:
            _LOGGER.debug("[%s] Fenster offen → Temperatur auf 0°C", self._zone_id)
            return 0.0

        # 2️⃣ Boost überschreibt alles (außer offenes Fenster)
        if self._current_boost:
            global_boost_entity = "number.global_boost_temp"
            state = self.hass.states.get(global_boost_entity)

            if not state or state.state in ("unknown", "unavailable"):
                _LOGGER.warning("[%s] Globale Boost-Temperatur (%s) nicht verfügbar – Fallback: %.1f°C",
                                self._zone_id, global_boost_entity, TEMP_FALLBACK)
                return TEMP_FALLBACK 

            try:
                boost_temp = float(state.state)
                _LOGGER.debug("[%s] Boost aktiv → globale %.1f°C", self._zone_id, boost_temp)
                return boost_temp
            except (ValueError, TypeError):
                _LOGGER.warning("[%s] Ungültiger Wert in %s: %s – Fallback: %.1f°C",
                                self._zone_id, global_boost_entity, state.state, TEMP_FALLBACK)
                return TEMP_FALLBACK
            
        # 3️⃣ Sonst nach Modus
        if self._current_mode == HeaterMode.OFF.value:
            return TEMP_OFF
        if self._current_mode == HeaterExtendedMode.BYPASS.value:
            return TEMP_BYPASS
        if self._current_mode == HeaterMode.MANUAL.value:
            # value comes from manual entity
            entity_id = self._manual_entity_id
        else:
            # all other modes use target entity
            entity_id = self._target_entity_id

        if (state := self.hass.states.get(entity_id)) is None or state.state in ("unknown", "unavailable"):
            return None
        try:
            return float(state.state)
        except (ValueError, TypeError):
            _LOGGER.warning("[%s] Ungültiger Wert in %s: %s", self._zone_id, entity_id, state.state)
            return None

    async def async_update(self) -> None:
        """Update wird nach async_schedule_update_ha_state(True) aufgerufen."""
        # Hier native_value berechnen lassen
        new_temp = self.native_value
        
        # An Climate-Entität senden wenn sich geändert hat
        if new_temp is not None and new_temp != self._last_sent_temp:
            await self._send_to_climate(new_temp)
            self._last_sent_temp = new_temp

    async def _send_to_climate(self, temperature: float) -> None:
        """Sendet Temperatur an die zugehörige Climate-Entität."""
        # Prüfe ob ein Climate-Entity ausgewählt ist
        if not self._current_climate_entity_id:
            _LOGGER.debug(
                "[%s] Kein Thermostat ausgewählt, überspringe Temperatur-Update",
                self._zone_id
            )
            return
        
        # Hole den State des Climate-Entity
        climate_state = self.hass.states.get(self._current_climate_entity_id)
        
        if not climate_state:
            _LOGGER.warning(
                "[%s] Climate-Entity %s existiert nicht oder ist nicht verfügbar",
                self._zone_id,
                self._current_climate_entity_id
            )
            return
        
        # Lese min/max Temperatur aus den Attributen
        min_temp = climate_state.attributes.get("min_temp", 5.0)
        max_temp = climate_state.attributes.get("max_temp", 30.0)
        
        # Begrenze die Temperatur auf min/max
        clamped_temperature = max(min_temp, min(max_temp, temperature))
        
        if clamped_temperature != temperature:
            _LOGGER.warning(
                "[%s] Temperatur %.1f°C liegt außerhalb der Grenzen (%.1f-%.1f°C), verwende %.1f°C",
                self._zone_id,
                temperature,
                min_temp,
                max_temp,
                clamped_temperature
            )
        
        _LOGGER.info(
            "[%s] Sende Solltemperatur %.1f°C an %s",
            self._zone_id,
            clamped_temperature,
            self._current_climate_entity_id
        )
        
        try:
            await self.hass.services.async_call(
                "climate",
                "set_temperature",
                {
                    "entity_id": self._current_climate_entity_id,
                    "temperature": clamped_temperature
                },
                blocking=False
            )
            _LOGGER.debug(
                "[%s] Temperatur %.1f°C an %s gesendet",
                self._zone_id,
                clamped_temperature,
                self._current_climate_entity_id
            )
        except Exception as err:
            _LOGGER.error(
                "[%s] Fehler beim Senden der Temperatur an %s: %s",
                self._zone_id,
                self._current_climate_entity_id,
                err
            )

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

        # _LOGGER.error(f"Zone {self._zone_id}: Mirroring value from {self._selected_entity_id}: {target_state.state}")
        
        return target_state.state

# -----------------------------------------------------------------------------
# Spiegel-Sensoren
# -----------------------------------------------------------------------------

class ZoneCurrentTemperatureSensor(ZoneMirrorSensorBase):
    """Spiegelt die Temperatur des gewählten Sensors."""
    _select_suffix = "temperature_sensor"
    _attr_native_unit_of_measurement = "°C"
    _attr_icon = "mdi:thermometer"
    _attr_name_suffix = "Actual temperature"
    
    def __init__(self, hass, entry, zone_id, zone_data):
        super().__init__(hass, entry, zone_id, zone_data)
        self._thermostat_select_entity_id = f"select.{zone_id}_thermostat_sensor"
        self._current_climate_entity_id = None
        self._last_sent_temp = None
    
    async def async_added_to_hass(self) -> None:
        """Setup mit Thermostat-Listener."""
        await super().async_added_to_hass()
        
        # Initiales Climate Entity laden
        await self._update_climate_entity()
        
        # Listener für Thermostat-Änderungen
        @callback
        def _handle_thermostat_change(event: Event):
            if event.data.get("entity_id") != self._thermostat_select_entity_id:
                return
            self.hass.async_create_task(self._update_climate_entity())
        
        self._unsub_thermostat = self.hass.bus.async_listen(
            EVENT_STATE_CHANGED, _handle_thermostat_change
        )
    
    async def _update_climate_entity(self):
        """Lädt aktuelles Climate Entity aus Select."""
        select_state = self.hass.states.get(self._thermostat_select_entity_id)
        if select_state:
            entity_map = select_state.attributes.get("entity_map", {})
            self._current_climate_entity_id = entity_map.get(select_state.state)
    
    @property
    def native_value(self):
        """Liefert aktuelle Temperatur UND sendet sie ans Thermostat."""
        temp = super().native_value  # Von Basisklasse
        
        # Wenn sich Temperatur geändert hat, an Thermostat senden
        if temp and temp != self._last_sent_temp:
            self.hass.async_create_task(self._send_external_temperature(temp))
            self._last_sent_temp = temp
        
        return temp
    
    #ANCHOR - Send Temperature to Climate
    async def _send_external_temperature(self, temperature: float) -> None:
        """Sendet externe Temperatur je nach Thermostat-Typ."""
        if not self._current_climate_entity_id:
            return
        
        _LOGGER.debug(f"Zone {self._zone_id}: Sending external temperature {temperature}°C to climate entity {self._current_climate_entity_id}")    
        
        climate_state = self.hass.states.get(self._current_climate_entity_id)
        if not climate_state:
            return
        
        # Friendly Name ist direkt im State verfügbar
        friendly_name = climate_state.attributes.get("friendly_name")
        device_name = self._current_climate_entity_id.replace("climate.", "")
        
        _LOGGER.debug(f"Zone {self._zone_id}: Climate friendly name: {friendly_name}, device name: {device_name}")
        
        # Fallback auf Device Name
        if not friendly_name:
            friendly_name = device_name

        # Prüfe ob es sich um Aqara handelt
        temp_state = self.hass.states.get(f"number.{device_name}_external_temperature_input")
    
        # Model und Entity-ID für Typ-Erkennung
        model = climate_state.attributes.get("model", "").lower()
        entity_id = climate_state.entity_id.lower()
        integration = climate_state.attributes.get("integration", "").lower()
        
        _LOGGER.debug(f"Zone {self._zone_id}: Climate model={model}, entity_id={entity_id}, integration={integration}, is_aqara={temp_state is not None}")
        
        # Aqara E1 via Zigbee2MQTT
        if temp_state is not None:
            await self._send_external_temp_aqara_z2m(friendly_name, float(temperature))
        
        # Homematic
        elif "homematic" in entity_id or "homematic" in integration:
            await self._send_external_temp_homematic(climate_state, float(temperature))
        
        else:
            _LOGGER.debug(
                "[%s] Thermostat unterstützt keine externe Temperatur (Model: %s)",
                self._zone_id,
                climate_state.attributes.get("model", "unknown")
            )


    async def _send_external_temp_aqara_z2m(self, device_name: str, temperature: float) -> None:
        """Aqara E1 via Zigbee2MQTT - KORREKTE Methode."""
        try:
            # Aqara E1 akzeptiert nur 0-55°C und jeden subtopic einzeln!
            temperature = max(0.0, min(55.0, temperature))
                
            await self.hass.services.async_call( "mqtt", "publish",
                {
                    "topic": f"zigbee2mqtt/{device_name}/set/child_lock",
                    "payload": "LOCK",
                },
                blocking=False,
            )
                
            await self.hass.services.async_call( "mqtt", "publish",
                {
                    "topic": f"zigbee2mqtt/{device_name}/set/sensor",
                    "payload": "external",
                },
                blocking=False,
            )                

            await self.hass.services.async_call( "mqtt", "publish",
                {
                    "topic": f"zigbee2mqtt/{device_name}/set/external_temperature_input",
                    "payload": round(temperature, 1),
                },
                blocking=False,
            )                
                       
            _LOGGER.debug("[%s] Externe Temperatur %.1f°C an %s gesendet (via external_temperature_input)",
                          self._zone_id, temperature, device_name )
            
        except Exception as err:
            _LOGGER.error("[%s] MQTT Fehler: %s", self._zone_id, err)

    async def _send_external_temp_homematic(self, climate_state, temperature: float) -> None:
        """Homematic Thermostat."""
        entity_id = climate_state.entity_id
        
        try:
            await self.hass.services.async_call(
                "homematic",
                "set_device_value",
                {
                    "address": climate_state.attributes.get("address"),
                    "channel": 1,
                    "param": "SET_TEMPERATURE",
                    "value": temperature
                },
                blocking=False
            )
            _LOGGER.debug(
                "[%s] Externe Temperatur %.1f°C an Homematic (%s) gesendet",
                self._zone_id,
                temperature,
                entity_id
            )
        except Exception as err:
            _LOGGER.error("[%s] Homematic Fehler: %s", self._zone_id, err)

class ZoneCurrentHumiditySensor(ZoneMirrorSensorBase):
    """Spiegelt die Feuchtigkeit des gewählten Sensors."""
    _select_suffix = "humidity_sensor"
    _attr_native_unit_of_measurement = "%"
    _attr_icon = "mdi:water-percent"
    _attr_name_suffix = "Humidity"

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

