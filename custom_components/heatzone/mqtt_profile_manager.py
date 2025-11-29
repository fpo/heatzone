# /config/custom_components/heatzone/mqtt_profile_manager.py

import json
import asyncio
from datetime import datetime, timedelta
from typing import Optional, Dict
from homeassistant.core import HomeAssistant
from homeassistant.helpers.event import async_track_time_interval
import paho.mqtt.client as mqtt_client
from homeassistant.helpers.dispatcher import async_dispatcher_send
from .const import *

import logging
_LOGGER = logging.getLogger(__name__)

class ProfileData:
    """Stores the profile data for an MQTT topic."""
    
    def __init__(self, topic: str):
        self.topic = topic
        self.data = {}
        self.last_update = None
        self.last_access = datetime.now()
    
    def update_subtopic(self, subtopic: str, value: str):
        """Updates a sub-topic value."""
        self.data[subtopic] = value
        self.last_update = datetime.now()
        self.last_access = datetime.now()
        _LOGGER.debug(f"Topic {self.topic}: {subtopic} = {value}")
    
    def mark_accessed(self):
        """Marks the profile as recently used."""
        self.last_access = datetime.now()
    
    def is_complete(self) -> bool:
        """Checks if all necessary data is available."""
        required = REQIRED_SUBTOPICS
        return all(key in self.data for key in required)
    
    def is_expired(self, timeout_minutes: int) -> bool:
        """Checks if the profile has not been used for X minutes."""
        if not self.last_access:
            return True
        delta = datetime.now() - self.last_access
        return delta.total_seconds() > (timeout_minutes * 60)


class ProfileManager:
    """Manages MQTT profiles on a topic-based basis and calc temps"""
    
    def __init__(self, hass: HomeAssistant, config_entry):
        self.hass = hass
        self.config_entry = config_entry
        self.profiles: Dict[str, ProfileData] = {}  # {topic: ProfileData}
        self.subscribed_topics: Dict[str, list] = {} 
         # {topic: [full_topics]}
        self.zone_last_temps: Dict[str, float] = {} 
        # {zone_id: {"active": bool, "until": datetime, "temp": float}}
        self.zone_boost_data: Dict[str, dict] = {} 
        self.zone_boost_tasks: Dict[str, asyncio.Task] = {}
        self.zone_window_open: Dict[str, bool] = {}
        self.zone_window_timers: Dict[str, any] = {}
        self.zone_current_temp: Dict[str, float] = {}     
        self.zone_entity_values: Dict[str, dict]
        self.global_temp_diff = None
    
        self._mqtt_client = None
        self._mqtt_connected = False
        self.retrys = 0
        self.global_temp_diff: Optional[float] = 0.0
        self.global_heating_demand = False
        
        self._startup_complete = False
        self._update_lock = asyncio.Lock()
        
# -----------------------------------------------------------------------------
# ANCHOR - Window Logic
# -----------------------------------------------------------------------------
 
    def is_window_delay_active(self, zone_id: str) -> bool:
        """Checks if window timer is still running (lockout time active)."""
        return zone_id in self.zone_window_timers

    def is_window_open(self, zone_id: str) -> bool:
        """Checks if the window for the zone is open."""
        return self.zone_window_open.get(zone_id, False)

    def on_window_opened(self, zone_id: str):
        """Called by the binary sensor when a window is opened."""
        was_open = self.zone_window_open.get(zone_id, False)
        
        if not was_open:
            # get delay from entity
            delay_state = self._get_entity_state(zone_id, "window_delay")
            try:
                delay = int(float(delay_state)) if delay_state else 10
            except (ValueError, TypeError):
                delay = 10
            
            _LOGGER.info(f"Zone {zone_id}: Window opened, starting {delay}s delay")
            
            # cancel old timer
            if zone_id in self.zone_window_timers:
                self.zone_window_timers[zone_id]()
                self.zone_window_timers.pop(zone_id)
            
            self.zone_window_open[zone_id] = True
            
            delay = delay * 60   # delay is in minutes
            
            # timer start
            from homeassistant.helpers.event import async_call_later
            self.zone_window_timers[zone_id] = async_call_later(
                self.hass,
                delay,
                self._apply_window_open_callback(zone_id)
            )

    def on_window_closed(self, zone_id: str):
        """Called by the binary sensor when the window is closed."""
        was_open = self.zone_window_open.get(zone_id, False)
        
        if was_open:
            _LOGGER.info(f"Zone {zone_id}: Window closed, restoring temperature immediately")
            
            # cancel timer
            if zone_id in self.zone_window_timers:
                self.zone_window_timers[zone_id]()
                self.zone_window_timers.pop(zone_id)
            
            self.zone_window_open[zone_id] = False
            
            # Immediate update
            self.hass.async_create_task(self.update_temps())

    def _apply_window_open_callback(self, zone_id: str):
        """Create callback for timer."""
        async def callback(now):
            await self._apply_window_open(zone_id, now)
        return callback

    async def _apply_window_open(self, zone_id: str, now=None):
        """After Delay: The window is indeed open."""
        _LOGGER.info(f"Zone {zone_id}: Window delay expired")
        self.zone_window_timers.pop(zone_id, None)
        await self.update_temps()
        
# -----------------------------------------------------------------------------
# ANCHOR - Boost logic
# -----------------------------------------------------------------------------
 
    def start_boost(self, zone_id: str):
        """Starts boost for one zone."""
        duration = int(self._get_global_boost_duration())
        boost_until = datetime.now() + timedelta(minutes=duration)
        boost_temp = self._get_global_boost_temp()
        
        # cancel old task if exists
        if zone_id in self.zone_boost_tasks:
            old_task = self.zone_boost_tasks[zone_id]
            if not old_task.done():
                old_task.cancel()
            _LOGGER.debug(f"Zone {zone_id}: Cancelled previous boost task")
        
        self.zone_boost_data[zone_id] = {
            "active": True,
            "until": boost_until,
            "temp": boost_temp
        }
        
        _LOGGER.info(f"Zone {zone_id}: Boost started at {boost_temp}°C for {duration} min")
        
        # update temps immediately
        self.hass.async_create_task(self.update_temps())
        
        # store task-reference
        async def _disable_later():
            try:
                await asyncio.sleep(duration * 60)
                self.stop_boost(zone_id)
            except asyncio.CancelledError:
                _LOGGER.debug(f"Zone {zone_id}: Boost timer cancelled")
        
        task = self.hass.async_create_task(_disable_later())
        self.zone_boost_tasks[zone_id] = task
 
    def stop_boost(self, zone_id: str):
        """stop boost for this zone"""
        if zone_id in self.zone_boost_data:
            self.zone_boost_data[zone_id]["active"] = False
            _LOGGER.info(f"Zone {zone_id}: Boost stopped")
        
            # cancel task
            if zone_id in self.zone_boost_tasks:
                task = self.zone_boost_tasks[zone_id]
                if not task.done():
                    task.cancel()
                del self.zone_boost_tasks[zone_id]
        
            # set switch state direct
            switch_entity_id = f"switch.{zone_id}_boost"
            self.hass.states.async_set(switch_entity_id, "off")        
        
            # trigger update_temps
            self.hass.async_create_task(self.update_temps())   
   
    def _get_global_boost_duration(self) -> int:
        """get the global boost-duration."""
        _default_boost_duration = 10
        state = self.hass.states.get("number.global_boost_duration")
        if not state or state.state in ("unknown", "unavailable"):
            return _default_boost_duration
        try:
            return int(float(state.state))
        except ValueError:
            return _default_boost_duration
        
    def _get_global_boost_temp(self) -> int:
        """get the global boost temp."""
        _default_boost_temp = 25.0
        state = self.hass.states.get("number.global_boost_temp")
        if not state or state.state in ("unknown", "unavailable"):
            return _default_boost_temp
        try:
            return int(float(state.state))
        except ValueError:
            return _default_boost_temp          
        
    def is_boost_active(self, zone_id: str) -> bool:
        """checks if boost active."""
        if zone_id not in self.zone_boost_data:
            return False
        return self.zone_boost_data[zone_id].get("active", False)
    
    def get_boost_temp(self, zone_id: str) -> Optional[float]:
        """get the boost temp if active."""
        if not self.is_boost_active(zone_id):
            return None
        return self.zone_boost_data[zone_id].get("temp")
    
    def get_boost_until(self, zone_id: str) -> Optional[datetime]:
        """get the boost end time."""
        if zone_id not in self.zone_boost_data:
            return None
        return self.zone_boost_data[zone_id].get("until")

# -----------------------------------------------------------------------------
# ANCHOR - Profile Manager
# -----------------------------------------------------------------------------
    
    async def start(self):
        """Starts the profile manager."""
        _LOGGER.info("Starting MQTT Profile Manager")
        
        self.retrys = 0
        await self._setup_mqtt()
        
        # Wait until all entities are ready.
        await asyncio.sleep(5)
        self._startup_complete = True
    
        # Start polling timer (every 60 seconds)
        self._polling_unsub = async_track_time_interval(
            self.hass,
            self.update_temps,
            timedelta(seconds=60)
        )
    
    async def stop(self):
        """Stoppt den Profile Manager und räumt auf."""
        _LOGGER.info("Stopping MQTT Profile Manager")
        
        # cancel all boost tasks
        for zone_id, task in list(self.zone_boost_tasks.items()):
            if not task.done():
                task.cancel()
        self.zone_boost_tasks.clear()        
        
        # cancel all window timer
        for zone_id, timer in list(self.zone_window_timers.items()):
            if timer:
                timer()
        self.zone_window_timers.clear()
        
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
 
# -----------------------------------------------------------------------------
# ANCHOR - mqtt setup und Callbacks
# ----------------------------------------------------------------------------- 
 
    async def _setup_mqtt(self):
        """Set up MQTT client using credentials from Config."""
        mqtt_config = self.config_entry.data
        
        host = mqtt_config.get("mqtt_host", MQTT_HOST)
        port = mqtt_config.get("mqtt_port", MQTT_WEBSOCKET_PORT)
        user = mqtt_config.get("mqtt_user", MQTT_USER)
        password = mqtt_config.get("mqtt_password", MQTT_PASSWORD)
        
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
        """Callback if MQTT connection is established."""
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
        """Callback if the MQTT connection is disconnected."""
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
        """Callback if an MQTT message is received."""
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
        """Subscribes to all already registered profiles again."""
        for topic in list(self.profiles.keys()):
            await self._subscribe_profile(topic)
    
# -----------------------------------------------------------------------------
# ANCHOR - Profile Management
# -----------------------------------------------------------------------------
 
    async def add_profile(self, topic: str):
        """Adds a new profile and subscribes to MQTT topics."""
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
        """Removes a profile and unsubscribes MQTT topics."""
        if topic not in self.profiles:
            return
        
        await self._unsubscribe_profile(topic)
        del self.profiles[topic]
        _LOGGER.info(f"Removed profile for topic: {topic}")
    
    async def _subscribe_profile(self, topic: str):
        """Subscribe to all subtopics for a profile."""
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
        """Unsubscribed from all sub-topics for a profile."""
        if topic not in self.subscribed_topics:
            return
        
        for full_topic in self.subscribed_topics[topic]:
            self._mqtt_client.unsubscribe(full_topic)
            _LOGGER.debug(f"Unsubscribed from {full_topic}")
        
        del self.subscribed_topics[topic]
        _LOGGER.info(f"Topic {topic}: Unsubscribed all sub-topics")  

# -----------------------------------------------------------------------------
# ANCHOR - Temperature Calculation
# -----------------------------------------------------------------------------

    def _get_zone_ids(self) -> list:
        """Get all zone IDs from the config entry options."""
        zones = self.config_entry.options.get("zones", {})
        return list(zones.keys())
    
    def _get_entity_state(self, zone_id: str, entity_type: str) -> str:
        """Get the state of an entity for a zone."""
        
        # Mapping von entity_type zu tatsächlichen Entity Namen
        entity_mapping = {
            "mode": f"select.{zone_id}_mode",
            "profile": f"text.{zone_id}_profile",
            "temp_sensor": f"sensor.{zone_id}_temperature_sensor",
            "manual_temp": f"number.{zone_id}_manual_temp",
            "window_delay": f"number.{zone_id}_delay",
            "priority": f"number.{zone_id}_priority",
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
        """Update target temp sensor only if changed."""
        
        last_temp = self.zone_last_temps.get(zone_id)
        if last_temp is not None and abs(last_temp - temp) < 0.1:
            _LOGGER.debug(f"Zone {zone_id}: Temp unchanged ({temp}°C), skipping update")
            return
       
        async_dispatcher_send(self.hass, f"zone_target_temp_update_{zone_id}", temp)
        
        self.zone_last_temps[zone_id] = temp
        _LOGGER.debug(f"Zone {zone_id}: Updated target temp to {temp}°C")

    async def _update_global_temp_diff(self, temp: float):
        """Update temp diff sensor and check heating demand with hysteresis."""
        last_temp = self.global_temp_diff
        
        # Update temp diff sensor only if changed
        if last_temp is not None and abs(last_temp - temp) < 0.1:
            _LOGGER.debug(f"Global Temp diff unchanged ({temp}°C), skipping update")
            return
        
        async_dispatcher_send(self.hass, f"{DOMAIN}_global_temp_diff_update", temp)
        self.global_temp_diff = temp
        _LOGGER.debug(f"Update Temp Diff {temp}")
        
        # Check heating demand with hysteresis
        hysteresis = self._get_global_hysteresis()
        current_demand = self.global_heating_demand
        new_demand = current_demand
        
        # Hysteresis-logic
        if not current_demand and temp > hysteresis:
            # Switch-on: Difference across hysteresis
            new_demand = True
            _LOGGER.info("Global Heating ON: Δ=%.2f°C > %.2f°C", temp, hysteresis)
        
        elif current_demand and temp <= 0:
            # Switch-off: Difference <= 0
            new_demand = False
            _LOGGER.info("Global Heating OFF: Δ=%.2f°C <= 0°C", temp)
        
        # Change state if necessary
        if new_demand != current_demand:
            self.global_heating_demand = new_demand
            async_dispatcher_send(
                self.hass,
                f"{DOMAIN}_heating_switch",
                {"demand": new_demand}
            )
    
    def _get_global_hysteresis(self) -> float:
        """Get global hysteresis from number entity."""
        entity_id = "number.global_hysteresis"
        
        try:
            state = self.hass.states.get(entity_id)
            if state and state.state not in (None, "unknown", "unavailable"):
                return float(state.state)
        except (ValueError, TypeError):
            pass
        
        return 0.5  # Default hysteresis
 
    def get_temp(self, topic: str, mode: str) -> float:
        """Calculates the target temperature for a topic and mode."""
        
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
       
    # ANCHOR - update_temps
    async def update_temps(self, now=None):
        """Pollt und aktualisiert alle Zonen."""
        # startup - do nothing
        if not self._startup_complete:
            # _LOGGER.debug("Startup not complete, skipping temp update")
            return
        
        # prevent rekursiv calls
        async with self._update_lock:
            
            zone_ids = self._get_zone_ids()
            
            _LOGGER.debug(f"Update temps for zones: {zone_ids}")
            
            # get all used topics
            used_topics = set()
            for zone_id in zone_ids:
                topic = self.get_topic(zone_id)
                if topic and topic not in ("unknown", "unavailable", ""):
                    used_topics.add(topic)
            
            # load profile for used topics
            for topic in used_topics:
                if topic not in self.profiles:
                    _LOGGER.info(f"Loading profile for new topic: {topic}")
                    await self.add_profile(topic)
            
            temp_diff = 0.0
            temp_count = 0
            
            # Calculate target temperatures for zones in profile mode
            for zone_id in zone_ids:
                # get some entity states
                mode = self._get_entity_state(zone_id, "mode")
                manual_temp = self._get_entity_state(zone_id, "manual_temp")
                prio = self._get_entity_state(zone_id, "priority")
                current_temp = self.zone_current_temp.get(zone_id, DEFAULT_CURRENT_TEMP)
                present = self._get_entity_state(zone_id, "present")
                
                #default target temp
                target_temp = 0.0  
                
                if not mode or mode == HeaterMode.MANUAL.value:
                    # In manual mode, the user sets the temperature themselves.
                    target_temp = float(manual_temp) if manual_temp else TEMP_FALLBACK
    
                # get topic - composed of prefix-topic/profile
                topic = self.get_topic(zone_id)       
                if not topic or topic in ("unknown", "unavailable", ""):
                    target_temp = TEMP_FALLBACK
                else:     
                    # change mode to get the temp if not present
                    if present == "off": 
                        mode = HeaterExtendedMode.AWAY.value
                        target_temp = self.get_temp(topic, mode)
                    
                    # Calculate target temperature from profile
                    if mode == HeaterMode.PROFIL.value or mode == HeaterMode.HOLIDAY.value:
                        target_temp = self.get_temp(topic, mode)
                
                # check for boost
                if self.is_boost_active(zone_id):
                    boost_temp = self.get_boost_temp(zone_id)
                    if boost_temp is not None:
                        target_temp = boost_temp
                        _LOGGER.debug(f"Zone {zone_id}: Boost active, using {boost_temp}°C")
                        
                # Check for an open window (Only if the lock time has expired!)
                if self.is_window_open(zone_id) and not self.is_window_delay_active(zone_id):
                    target_temp = 0.0
                    _LOGGER.debug(f"Zone {zone_id}: Window open (delay expired), using 0°C")
                
                _LOGGER.debug(f"Zone {zone_id}: Calculated temp={target_temp}°C (topic={topic}, mode={mode})")
                
                # change to float
                try:
                    prio = float(prio)
                except (TypeError, ValueError):
                    prio = 0.0
                try:
                    current_temp = float(current_temp)
                except (TypeError, ValueError):
                    current_temp = 50                
                
                # get current diff < 0.0 = 0.0
                diff = max(0.0, target_temp - current_temp)
                
                temp_diff = temp_diff + prio * diff
                temp_count = temp_count + prio
                
                # update Target Temperature Sensor
                await self._update_target_temp_sensor(zone_id, target_temp)
            
            # set global temp diff
            if temp_count > 0:
                await self._update_global_temp_diff(round(temp_diff / temp_count,1))
            else:
                await self._update_global_temp_diff(0.0)
            
            # Cleanup of outdated profiles (not used for >10 minutes)
            for topic in list(self.profiles.keys()):
                if topic not in used_topics:
                    profile = self.profiles[topic]
                    if profile.is_expired(CLEANUP_TIMEOUT_MINUTES):
                        _LOGGER.info(f"Cleaning up unused profile: {topic}")
                        await self.remove_profile(topic)

    def _calculate_profile_temp(self, profile: ProfileData) -> float:
        """Calculates temperature from daily profile."""
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
    
    def get_topic(self, zone_id: str) -> Optional[str]:
        """get the MQTT topic for a zone."""
        profile = self._get_entity_state(zone_id, "profile")
        
        # check if valid
        if not profile or profile in ("unknown", "unavailable", ""):
            _LOGGER.warning(f"Zone {zone_id}: No valid profile configured")
            return None
        
        topic = PREFIX_TOPIC + profile.lower()
        return topic
    
    def _is_time_in_range(self, current: str, start: str, end: str) -> bool:
        """Checks if the current time is within the time range."""
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
        """Mapped TempID to actual temperature."""
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