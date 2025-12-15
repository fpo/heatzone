# FIXME - create status - /config/custom_components/heatzone/sensor.py

from __future__ import annotations
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
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.event import async_track_state_change_event
from .entity import ZoneEntityCore, ZoneMirrorEntityBase
from .const import *

import logging
_LOGGER = logging.getLogger(__name__)

# -----------------------------------------------------------------------------
# ANCHOR - Setup
# -----------------------------------------------------------------------------

async def async_setup_entry(hass: HomeAssistant,entry: ConfigEntry,
                            async_add_entities: AddEntitiesCallback,) -> None:
    """Set up sensor entities for all zones."""
    zones = entry.options.get("zones", {})
    entities: list[SensorEntity] = []

    # global sensor
    entities.append(GlobalTempDiffSensor(hass, entry))

    for zone_id in zones:
        entities.append(ZoneCurrentTemperatureSensor(hass, entry, zone_id))
        entities.append(ZoneCurrentHumiditySensor(hass, entry, zone_id))
        entities.append(ZoneTargetTemperatureSensor(hass, entry, zone_id))

    _LOGGER.debug("Setting up %d sensor entities for %d zones",
                  len(entities), len(zones))
    async_add_entities(entities)

# -----------------------------------------------------------------------------
# ANCHOR - Base class for all sensors
# -----------------------------------------------------------------------------

class ZoneSensorBase(ZoneEntityCore, SensorEntity):
    """Base class for all sensors."""

    _attr_icon: str | None = None
    _attr_native_unit_of_measurement: str | None = None
    _attr_device_class: SensorDeviceClass | None = None

# -----------------------------------------------------------------------------
# Target Temperature Sensor
# -----------------------------------------------------------------------------

class ZoneTargetTemperatureSensor(ZoneSensorBase):
    """Zeigt den Sollwert der Zone abhängig vom Modus an."""

    _attr_icon = "mdi:thermostat-box"
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_name_suffix = "Target temperature"
    _attr_unique_suffix = "target_temperature"
    _attr_should_poll = False  # don't poll
    _update_temps = False      # don't update temp comes from update_temps

    def __init__(self, hass, entry, zone_id: str):
        super().__init__(hass, entry, zone_id)
        self._attr_native_value = None
    
    async def async_added_to_hass(self):
        await super().async_added_to_hass()

        self._unsub = async_dispatcher_connect(
            self.hass,
            f"zone_target_temp_update_{self._zone_id}",
            self._handle_set_temp
        )

    async def async_will_remove_from_hass(self):
        """cleanup if entity is removed."""
        try:
            if getattr(self, "_unsub", None):
                self._unsub()
                self._unsub = None
        except Exception: 
            _LOGGER.error(
                "Error removing the dispatcher listener for zone %s",
                zone_id)
            
    async def _handle_set_temp(self, temperature):
        await self.async_set_temperature(temperature)
    
    async def async_set_temperature(self, temperature: float):
        """used by manager to set the temperature"""
        _LOGGER.debug(f"Setting target temperature for zone "
                      f"{self._zone_id} to {temperature}")
        old_value = self._attr_native_value     # old value
        self._attr_native_value = temperature   # new value
        self.async_write_ha_state()             # update state
        
        # send to climate if value changed
        old = float(old_value) if old_value not in (None, " ") else None
        if old is None or abs(old - temperature) >= 0.1:
            await self._send_to_climate(temperature)
    
    async def _send_to_climate_entity(self, entity_id: str, temperature: float) -> None:
        """Sendet Temperatur an eine einzelne Climate-Entität."""
        climate_state = self.hass.states.get(entity_id)
        
        if not climate_state:
            _LOGGER.warning(
                "[%s] Climate-Entity %s existiert nicht oder ist nicht verfügbar",
                self._zone_id, entity_id
            )
            return
        
        # Lese min/max Temperatur aus den Attributen
        min_temp = climate_state.attributes.get("min_temp", 5.0)
        max_temp = climate_state.attributes.get("max_temp", 30.0)
        
        # Begrenze die Temperatur auf min/max
        clamped_temperature = max(min_temp, min(max_temp, temperature))
        
        if clamped_temperature != temperature:
            _LOGGER.warning(
                "[%s] Temperatur %.1f°C liegt außerhalb der Grenzen (%.1f-%.1f°C), "
                "verwende %.1f°C",
                self._zone_id, temperature, min_temp, max_temp, clamped_temperature
            )
        
        _LOGGER.info("[%s] Sende Solltemperatur %.1f°C an %s",
                    self._zone_id, clamped_temperature, entity_id)
        
        try:
            await self.hass.services.async_call(
                "climate",
                "set_temperature",
                {
                    "entity_id": entity_id,
                    "temperature": clamped_temperature
                },
                blocking=False
            )
            _LOGGER.debug("[%s] Temperatur %.1f°C an %s gesendet",
                        self._zone_id, clamped_temperature, entity_id)
        except Exception as err:
            _LOGGER.error("[%s] Fehler beim Senden der Temperatur an %s: %s",
                        self._zone_id, entity_id, err)

    async def _send_to_climate(self, temperature: float) -> None:
        """Sendet Temperatur an alle zugehörigen Climate-Entitäten."""
        # Hole Climate Entity IDs aus Select
        select_entity_id = f"select.{self._zone_id}_thermostat_sensor"
        select_state = self.hass.states.get(select_entity_id)
        
        if not select_state or select_state.state in ("unknown", "unavailable", ""):
            _LOGGER.debug(
                "[%s] Kein Thermostat ausgewählt, überspringe Temperatur-Update",
                self._zone_id
            )
            return
        
        # Hole Liste der ausgewählten Climate-Entities
        climate_entity_ids = select_state.attributes.get("selected_entity_ids", [])
        
        if not climate_entity_ids:
            _LOGGER.debug(
                "[%s] Keine Thermostate in der Liste, überspringe Temperatur-Update",
                self._zone_id
            )
            return
        
        _LOGGER.debug(
            "[%s] Sende Temperatur %.1f°C an %d Thermostat(e)",
            self._zone_id, temperature, len(climate_entity_ids)
        )
        
        # Sende an alle ausgewählten Thermostaten
        for climate_entity_id in climate_entity_ids:
            await self._send_to_climate_entity(climate_entity_id, temperature)
            
# -----------------------------------------------------------------------------
# ANCHOR - Base class for sensors that reflect values ​​from Select.
# -----------------------------------------------------------------------------

class ZoneMirrorSensorBase(ZoneMirrorEntityBase, SensorEntity):
    """Base class for sensors that reflect values from Select."""

    def _get_mirrored_value(self, target_state):
        return target_state.state

    @property
    def native_value(self):
        target_state = self._get_target_state()
        return self._get_mirrored_value(target_state) if target_state else None

# -----------------------------------------------------------------------------
# ANCHOR - Mirror sensors
# -----------------------------------------------------------------------------

class ZoneCurrentTemperatureSensor(ZoneMirrorSensorBase):
    """Reflects the current temperature."""
    
    _attr_unique_suffix = "temperature_sensor"
    _attr_select_suffix = "temperature_sensor"
    _attr_native_unit_of_measurement = "°C"
    _attr_icon = "mdi:thermometer"
    _attr_name_suffix = "Actual temperature"
    _update_temps = True
    
    def __init__(self, hass, entry, zone_id):
        super().__init__(hass, entry, zone_id)
        self._thermostat_select_entity_id = f"select.{zone_id}_thermostat_sensor"
        self._calibrate_entity_id = f"number.{zone_id}_temp_calibrate"
        self._current_climate_entity_id = None
        self._last_sent_temp = None
    
    @property
    def native_value(self):
        """Provides current temperature and sends it to the thermostat."""
        # convert to float
        try: 
            temp = float(super().native_value)  # from base class
        except (TypeError, ValueError):
            temp = 0.0
        
        # apply calibration offset
        calibration_offset = self._get_calibration_offset()
        calibrated_temp = round(temp + calibration_offset, 1)
        
        # store current temp in manager (calibrated value)
        self._manager.zone_current_temp[self._zone_id] = calibrated_temp
        
        # if the temperature has changed, send a message to the thermostat.
        if calibrated_temp and calibrated_temp != self._last_sent_temp:
            self.hass.async_create_task(self._send_external_temperature(calibrated_temp))
            self._last_sent_temp = calibrated_temp
        
        return calibrated_temp
    
    def _get_calibration_offset(self):
        """Get the calibration offset from the number entity."""
        calibration_entity_id = f"number.{self._zone_id}_temp_calibrate"
        
        try:
            state = self.hass.states.get(calibration_entity_id)
            if state and state.state not in (None, "unknown", "unavailable"):
                return float(state.state)
        except (ValueError, TypeError):
            pass
        
        return 0.0  # Default: no calibration
    
    
    async def async_added_to_hass(self) -> None:
        """Setup with thermostat listener."""
        await super().async_added_to_hass()
        
        # Load initial climate entity
        await self._update_climate_entity()
        
        # Thermostat change listener
        @callback
        def _on_thermostat_change(event: Event):
            if event.data.get("entity_id") != self._thermostat_select_entity_id:
                return
            self.hass.async_create_task(self._update_climate_entity())
        
        self._unsub_thermostat = self.hass.bus.async_listen(
            EVENT_STATE_CHANGED, _on_thermostat_change)
        
        @callback
        def _on_calibrate_changed(event):
            if event.data.get("entity_id") != self._calibrate_entity_id:
                return
            _LOGGER.debug("Calibrate Updated")
            self.async_write_ha_state()

        self._unsub_calibrate = async_track_state_change_event(
            self.hass, [self._calibrate_entity_id], _on_calibrate_changed)
    
    
    async def _update_climate_entity(self):
        """Loads current Climate Entity from Select."""
        select_state = self.hass.states.get(self._thermostat_select_entity_id)
        if select_state:
            entity_map = select_state.attributes.get("entity_map", {})
            self._current_climate_entity_id = entity_map.get(select_state.state)
    
    # FIXME - Eventuell in den Manager
    # ANCHOR - Send temperature to climate
    async def _send_external_temperature(self, temperature: float) -> None:
        """Sends external temperature depending on the thermostat type."""
        if not self._current_climate_entity_id:
            return
        
        _LOGGER.debug(f"Zone {self._zone_id}: "
                      f"Sending external temperature {temperature}°C "
                      f"to climate entity {self._current_climate_entity_id}")    
        
        climate_state = self.hass.states.get(self._current_climate_entity_id)
        if not climate_state:
            return
        
        # Friendly Name is available directly in the state.
        friendly_name = climate_state.attributes.get("friendly_name")
        device_name = self._current_climate_entity_id.replace("climate.", "")
        
        _LOGGER.debug(f"Zone {self._zone_id}: Climate friendly name: {friendly_name}, device name: {device_name}")
        
        # Fallback to device name
        if not friendly_name:
            friendly_name = device_name

        # check if Aqara
        temp_state = self.hass.states.get(f"number.{device_name}_external_temperature_input")
    
        # Model and entity ID for type recognition
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
        """Aqara E1 via Zigbee2MQTT"""
        try:
            # Aqara E1 only accepts temperatures from 0-55°C and each subtopic individually!
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
    """Reflects the humidity level of the selected sensor."""
    _attr_unique_suffix = "humidity_sensor"
    _attr_select_suffix = "humidity_sensor"
    _attr_native_unit_of_measurement = "%"
    _attr_icon = "mdi:water-percent"
    _attr_name_suffix = "Humidity"

# -----------------------------------------------------------------------------
# Status sensor
# -----------------------------------------------------------------------------

# FIXME - Create one

class ZoneStatusSensor(ZoneSensorBase):
    """Displays the current heating status of the zone based on mode, 
       boost, and window condition."""

    _attr_icon = "mdi:home-thermometer-outline"
    _attr_name_suffix = "Status"
    _attr_unique_suffix = "status"

# -----------------------------------------------------------------------------
# ANCHOR - Global temperature difference sensor
# -----------------------------------------------------------------------------

class GlobalTempDiffSensor(ZoneSensorBase):
    """Global sensor for average temperature difference of all zones."""
    
    _attr_is_global = True
    _attr_unique_suffix = "temp_diff"
    _attr_name_suffix = "Temperature Difference"
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_icon = "mdi:thermometer-alert"
    _attr_should_poll = False
       
    def __init__(self, hass, entry):
        super().__init__(hass, entry)
        self._attr_native_value = None

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        
        self._attr_native_value = 0.0       # start after reload with 0.0
        self.async_write_ha_state()

        self._unsub = async_dispatcher_connect(
            self.hass,
            f"{DOMAIN}_global_temp_diff_update",
            self._handle_temp_diff
        )

    async def async_will_remove_from_hass(self):
        """cleanup if entity is removed."""
        try:
            if getattr(self, "_unsub", None):
                self._unsub()
                self._unsub = None
        except Exception: 
            _LOGGER.error("Error removing dispatcher listener temp_diff")

    async def _handle_temp_diff(self, temperature):
        await self.async_set_temperature(temperature)
        
    async def async_set_temperature(self, temperature: float):
        """used by manager to set the temperature diff"""
        _LOGGER.debug(f"Setting temperature diff to {temperature}")
        old_value = self._attr_native_value     # old value
        self._attr_native_value = temperature   # new value
        self.async_write_ha_state()             # update state   
        
        # change state boiler if value changed
        old = float(old_value) if old_value not in (None, " ") else None
        if old is None or abs(old - temperature) >= 0.1:
            await self._change_mode_boiler(temperature)
          
    async def _change_mode_boiler(self, temperature: float) -> None:
        """ChangeMode Boiler."""     
        