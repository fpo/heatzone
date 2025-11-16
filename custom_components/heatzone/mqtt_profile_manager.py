# /config/custom_components/heatzone/mqtt_profile_manager.py

import json
from datetime import datetime, timedelta
from typing import Optional, Dict
from homeassistant.core import HomeAssistant
from homeassistant.helpers.event import async_track_time_interval
import paho.mqtt.client as mqtt_client
from .const import *

import logging
_LOGGER = logging.getLogger(__name__)

class ProfileData:
    """Speichert die Profildaten für ein MQTT Topic."""
    
    def __init__(self, topic: str):
        self.topic = topic
        self.data = {}
        self.last_update = None
        self.last_access = datetime.now()
        self.last_sent_temp: Optional[float] = None
    
    def update_subtopic(self, subtopic: str, value: str):
        """Aktualisiert einen Sub-Topic Wert."""
        self.data[subtopic] = value
        self.last_update = datetime.now()
        self.last_access = datetime.now()
        _LOGGER.debug(f"Topic {self.topic}: {subtopic} = {value}")
    
    def mark_accessed(self):
        """Markiert das Profil als kürzlich verwendet."""
        self.last_access = datetime.now()
    
    def is_complete(self) -> bool:
        """Prüft ob alle notwendigen Daten vorhanden sind."""
        required = REQIRED_SUBTOPICS
        return all(key in self.data for key in required)
    
    def is_expired(self, timeout_minutes: int) -> bool:
        """Prüft ob das Profil seit X Minuten nicht mehr verwendet wurde."""
        if not self.last_access:
            return True
        delta = datetime.now() - self.last_access
        return delta.total_seconds() > (timeout_minutes * 60)


class ProfileManager:
    """Verwaltet MQTT-Profile topic-basiert."""
    
    def __init__(self, hass: HomeAssistant, config_entry):
        self.hass = hass
        self.config_entry = config_entry
        self.profiles: Dict[str, ProfileData] = {}  # {topic: ProfileData}
        self.subscribed_topics: Dict[str, list] = {}  # {topic: [full_topics]}
        self._polling_unsub = None
        self._mqtt_client = None
        self._mqtt_connected = False
        self.retrys = 0
    
    async def start(self):
        """Startet den Profile Manager."""
        _LOGGER.info("Starting MQTT Profile Manager")
        
        self.retrys = 0
        await self._setup_mqtt()
        
        # Polling-Timer starten (alle 60 Sekunden)
        self._polling_unsub = async_track_time_interval(
            self.hass,
            self.update_temps,
            timedelta(seconds=60)
        )
    
    async def stop(self):
        """Stoppt den Profile Manager und räumt auf."""
        _LOGGER.info("Stopping MQTT Profile Manager")
        
        if self._polling_unsub:
            self._polling_unsub()
            self._polling_unsub = None
        
        if self._mqtt_client:
            try:
                self._mqtt_client.loop_stop()
                self._mqtt_client.disconnect()
            except Exception:
                pass
            self._mqtt_client = None
            self._mqtt_connected = False
    
    async def _setup_mqtt(self):
        """Richtet MQTT Client mit Credentials aus Config ein."""
        mqtt_config = self.config_entry.data
        
        host = mqtt_config.get("mqtt_host", "localhost")
        port = mqtt_config.get("mqtt_port", 1883)
        user = mqtt_config.get("mqtt_user", "")
        password = mqtt_config.get("mqtt_password", "")
        
        self.retrys = 0
        client_id = f"{DOMAIN}_{self.config_entry.entry_id}"
        
        self._mqtt_client = mqtt_client.Client(client_id=client_id)
        
        if user:
            self._mqtt_client.username_pw_set(user, password)
        
        self._mqtt_client.on_connect = self._on_mqtt_connect
        self._mqtt_client.on_message = self._on_mqtt_message
        self._mqtt_client.on_disconnect = self._on_mqtt_disconnect
        
        try:
            _LOGGER.info(f"Connecting to MQTT broker {host}:{port}")
            self._mqtt_client.connect(host, port, 60)
            self._mqtt_client.loop_start()
        except Exception as e:
            _LOGGER.error(f"Failed to connect to MQTT broker: {e}")
    
    def _on_mqtt_connect(self, client, userdata, flags, rc):
        """Callback wenn MQTT Verbindung hergestellt ist."""
        if rc == 0:
            _LOGGER.info("Connected to MQTT broker")
            self._mqtt_connected = True
            self.retrys = 0
            # Alle bereits registrierten Profile neu subscriben
            self.hass.loop.call_soon_threadsafe(
                lambda: self.hass.async_create_task(self._resubscribe_all())
            )
        else:
            _LOGGER.error(f"MQTT connection failed with code {rc}")
            self._mqtt_connected = False
    
    def _on_mqtt_disconnect(self, client, userdata, rc):
        """Callback wenn MQTT Verbindung getrennt wurde."""
        _LOGGER.warning(f"Disconnected from MQTT broker (code {rc})")
        self._mqtt_connected = False
        if rc != 0:
            self.retrys += 1
            if self.retrys >= MAX_RETRYS:
                _LOGGER.error("Max MQTT reconnection attempts reached, giving up.")
                try:
                    client.loop_stop()
                    self._mqtt_client = None
                except Exception as e:
                    _LOGGER.warning(f"Failed to stop MQTT loop after error: {e}")
    
    def _on_mqtt_message(self, client, userdata, msg):
        """Callback wenn MQTT Nachricht empfangen wird."""
        full_topic = msg.topic
        payload = msg.payload.decode('utf-8')
        
        def process_message():
            for topic, profile in self.profiles.items():
                if full_topic.startswith(topic + "/"):
                    subtopic = full_topic.split('/')[-1]
                    profile.update_subtopic(subtopic, payload)
                    break
        
        self.hass.loop.call_soon_threadsafe(process_message)
    
    async def _resubscribe_all(self):
        """Subscribt alle bereits registrierten Profile neu."""
        for topic in list(self.profiles.keys()):
            await self._subscribe_profile(topic)
    
    async def add_profile(self, topic: str):
        """Fügt ein neues Profil hinzu und subscribt MQTT Topics."""
        if not topic:
            _LOGGER.warning("Cannot add profile with empty topic")
            return
        
        if topic in self.profiles:
            self.profiles[topic].mark_accessed()
            _LOGGER.debug(f"Profile {topic} already exists, marked as accessed")
            return
        
        self.profiles[topic] = ProfileData(topic)
        _LOGGER.info(f"Added new profile for topic: {topic}")
        
        await self._subscribe_profile(topic)
    
    async def remove_profile(self, topic: str):
        """Entfernt ein Profil und unsubscribed MQTT Topics."""
        if topic not in self.profiles:
            return
        
        await self._unsubscribe_profile(topic)
        del self.profiles[topic]
        _LOGGER.info(f"Removed profile for topic: {topic}")
    
    async def _subscribe_profile(self, topic: str):
        """Subscribt alle Sub-Topics für ein Profil."""
        if not self._mqtt_connected:
            _LOGGER.warning("MQTT not connected, cannot subscribe")
            return
        
        if topic in self.subscribed_topics:
            _LOGGER.debug(f"Topic {topic} already subscribed")
            return
        
        full_topics = []
        for subtopic in PROFILE_SUBTOPICS:
            full_topic = f"{topic}/{subtopic}"
            self._mqtt_client.subscribe(full_topic, qos=1)
            full_topics.append(full_topic)
            _LOGGER.debug(f"Subscribed to {full_topic}")
        
        self.subscribed_topics[topic] = full_topics
        _LOGGER.info(f"Topic {topic}: Subscribed to {len(full_topics)} sub-topics")
    
    async def _unsubscribe_profile(self, topic: str):
        """Unsubscribed alle Sub-Topics für ein Profil."""
        if topic not in self.subscribed_topics:
            return
        
        for full_topic in self.subscribed_topics[topic]:
            self._mqtt_client.unsubscribe(full_topic)
            _LOGGER.debug(f"Unsubscribed from {full_topic}")
        
        del self.subscribed_topics[topic]
        _LOGGER.info(f"Topic {topic}: Unsubscribed all sub-topics")
    
    def get_temp(self, topic: str, mode: str) -> float:
        """ Berechnet die Soll-Temperatur für ein Topic und Modus."""
        
        if topic not in self.profiles:
            _LOGGER.warning(f"Topic {topic}: No profile loaded")
            return TEMP_FALLBACK
        
        profile = self.profiles[topic]
        profile.mark_accessed()
        
        if not profile.is_complete():
            _LOGGER.warning(f"Topic {topic}: Profile incomplete")
            return TEMP_FALLBACK
        
        if mode == HeaterExtendedMode.BYPASS.value:
            return TEMP_FALLBACK
        
        if mode in (HeaterMode.OFF.value, HeaterExtendedMode.OPEN.value):
            return TEMP_OFF
        
        if mode == HeaterMode.MANUAL.value:
            # Bei Manuell wird die Temperatur nicht vom Profil bestimmt
            return TEMP_FALLBACK
        
        if mode == HeaterExtendedMode.AWAY.value:
            try:
                return float(profile.data.get("TempAway", TEMP_FALLBACK))
            except (ValueError, TypeError):
                return TEMP_FALLBACK
        
        if mode == HeaterMode.HOLIDAY.value:
            try:
                return float(profile.data.get("TempHoliday", TEMP_FALLBACK))
            except (ValueError, TypeError):
                return TEMP_FALLBACK
        
        if mode == HeaterMode.PROFIL.value:
            return self._calculate_profile_temp(profile)
        
        _LOGGER.warning(f"Topic {topic}: Unknown mode {mode}")
        return TEMP_FALLBACK
    
    def _get_zone_ids(self) -> list:
        """Hole alle Zone IDs aus den config entry options."""
        zones = self.config_entry.options.get("zones", {})
        return list(zones.keys())
    
    def _get_entity_state(self, zone_id: str, entity_type: str) -> str:
        """
        Hole den State einer Entity für eine Zone.
        
        Args:
            zone_id: Zone ID (z.B. "z1")
            entity_type: Entity Typ (z.B. "modus", "profile")
        
        Returns:
            State der Entity oder None
        """
        
        # Mapping von entity_type zu tatsächlichen Entity Namen
        entity_mapping = {
            "mode": f"select.{zone_id}_mode",
            "profile": f"text.{zone_id}_profile",
            "present": f"switch.{zone_id}_present",
        }
     
        entity_id = entity_mapping.get(entity_type)
        if not entity_id:
            _LOGGER.warning(f"Unknown entity type: {entity_type}")
            return None
        
        state = self.hass.states.get(entity_id)
        if state:
            return state.state
        return None
    
    async def _update_target_temp_sensor(self, zone_id: str, temp: float):
        """ Aktualisiert den Target Temperature Sensor nur bei Änderung. """
        
        # Hole das Profil für diese Zone
        topic = self.get_topic(zone_id)
        if not topic or topic not in self.profiles:
            _LOGGER.warning(f"Zone {zone_id}: No profile found for update")
            return
        
        profile = self.profiles[topic]
        
        # Prüfe ob sich der Wert geändert hat
        if profile.last_sent_temp is not None and abs(profile.last_sent_temp - temp) < 0.1:
            _LOGGER.debug(f"Zone {zone_id}: Temp unchanged ({temp}°C), skipping update")
            return
        
        entity_id = f"number.{zone_id}_target_temp"
        
        try:
            await self.hass.services.async_call("number", "set_value",
                service_data={"value": temp},
                target={"entity_id": entity_id},
            )
            profile.last_sent_temp = temp
            _LOGGER.debug(f"Zone {zone_id}: Updated target temp to {temp}°C")
        except Exception as e:
            _LOGGER.error(f"Fehler Service Call für Set-Temp '{entity_id}' mit {temp}: {e}")
        
    # ANCHOR - Poll
    async def update_temps(self, now=None):
        """ Pollt und aktualisiert alle Zonen."""

        zone_ids = self._get_zone_ids()
        
        _LOGGER.debug(f"Poller");
        
        # Sammle alle verwendeten Topics
        used_topics = set()
        for zone_id in zone_ids:
            topic = self.get_topic(zone_id)
            if topic and topic not in ("unknown", "unavailable", ""):
                used_topics.add(topic)
        
        # Profile für verwendete Topics laden
        for topic in used_topics:
            if topic not in self.profiles:
                _LOGGER.info(f"Loading profile for new topic: {topic}")
                await self.add_profile(topic)
        
        # Soll-Temperaturen berechnen für Zonen im Profil-Modus
        for zone_id in zone_ids:
            # Hole Modus aus Entity State
            mode = self._get_entity_state(zone_id, "mode")
            present = self._get_entity_state(zone_id, "present")
            
            if not mode or mode == HeaterMode.MANUAL.value:
                # Bei Manuell bestimmt der Benutzer die Temperatur selbst
                continue
            
            # Hole topic - Zusammengesetzt aus prefix-topic/profile
            topic = self.get_topic(zone_id)       
            if not topic or topic in ("unknown", "unavailable", ""):
                continue
            
            if present == "off": 
                mode = HeaterExtendedMode.AWAY.value
            
            # Berechne Soll-Temperatur aus Profil
            soll_temp = self.get_temp(topic, mode)
            
            _LOGGER.debug(f"Zone {zone_id}: Calculated temp={soll_temp}°C (topic={topic}, mode={mode})")
            
            # update Target Temperature Sensor
            await self._update_target_temp_sensor(zone_id, soll_temp)
        
        # Cleanup veralteter Profile (nicht mehr verwendet seit >10 Minuten)
        for topic in list(self.profiles.keys()):
            if topic not in used_topics:
                profile = self.profiles[topic]
                if profile.is_expired(CLEANUP_TIMEOUT_MINUTES):
                    _LOGGER.info(f"Cleaning up unused profile: {topic}")
                    await self.remove_profile(topic)
    
    def _calculate_profile_temp(self, profile: ProfileData) -> float:
        """Berechnet Temperatur aus Tagesprofil."""
        now = datetime.now()
        weekday = now.weekday()
        current_time = now.strftime("%H:%M")
        
        day_key = f"Day{weekday + 1}"
        day_schedule_str = profile.data.get(day_key)
        
        if not day_schedule_str:
            _LOGGER.warning(f"No schedule for {day_key}")
            return TEMP_FALLBACK
        
        try:
            day_schedule = json.loads(day_schedule_str)
            
            for period in day_schedule:
                from_time = period.get("From", "0:00")
                to_time = period.get("To", "24:00")
                temp_id = period.get("TempID", 0)
                
                if self._is_time_in_range(current_time, from_time, to_time):
                    return self._get_temp_by_id(profile, temp_id)
            
            _LOGGER.debug(f"No matching period for {current_time}, using fallback")
            return TEMP_FALLBACK
            
        except (json.JSONDecodeError, ValueError, TypeError) as e:
            _LOGGER.error(f"Error parsing schedule: {e}")
            return TEMP_FALLBACK
    
    def get_topic(self, zone_id):
        profile = self._get_entity_state(zone_id, "profile")
        topic = PREFIX_TOPIC + profile.lower()
        return topic
    
    def _is_time_in_range(self, current: str, start: str, end: str) -> bool:
        """Prüft ob aktuelle Zeit in Zeitbereich liegt."""
        try:
            current_h, current_m = map(int, current.split(":"))
            start_h, start_m = map(int, start.split(":"))
            end_h, end_m = map(int, end.split(":"))
            
            current_minutes = current_h * 60 + current_m
            start_minutes = start_h * 60 + start_m
            end_minutes = end_h * 60 + end_m
            
            if end_minutes < start_minutes:
                return current_minutes >= start_minutes or current_minutes < end_minutes
            else:
                return start_minutes <= current_minutes < end_minutes
                
        except (ValueError, AttributeError):
            return False
    
    def _get_temp_by_id(self, profile: ProfileData, temp_id: int) -> float:
        """Mapped TempID zu tatsächlicher Temperatur."""
        if temp_id == 0:
            return TEMP_FALLBACK
        
        if temp_id in [1, 2, 3, 4]:
            temp_key = f"Temp{temp_id}"
            try:
                temp_value = profile.data.get(temp_key)
                if temp_value is None:
                    _LOGGER.warning(f"{temp_key} not found in profile, using fallback")
                    return TEMP_FALLBACK
                return float(temp_value)
            except (ValueError, TypeError) as e:
                _LOGGER.error(f"Cannot convert {temp_key} value to float: {e}")
                return TEMP_FALLBACK
        
        if temp_id == 5:
            return 0.0
        
        _LOGGER.warning(f"Unknown TempID {temp_id}, using fallback")
        return TEMP_FALLBACK