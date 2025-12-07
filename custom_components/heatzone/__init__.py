# /config/custom_components/heatzone/__init__.py

import os
import shutil
from homeassistant.components.http import StaticPathConfig
from homeassistant.components import frontend
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er
from .mqtt_profile_manager import ProfileManager
from . import websocket_api
from .const import *

import logging
_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up from a config entry."""
    
    hass.data.setdefault(DOMAIN, {})
    
    # Get all zones from options (only zone_id and name)
    zones = entry.options.get("zones", {})
    
    # Device Registry
    device_registry = dr.async_get(hass)
    
    # store data
    hass.data[DOMAIN][entry.entry_id] = {
        "mqtt_config": {
            "host": entry.data.get("mqtt_host"),
            "port": entry.data.get("mqtt_port", 1883),
            "user": entry.data.get("mqtt_user", ""),
            "password": entry.data.get("mqtt_password", ""),
        },
        "zones": zones,
    }
    
    # copy paho-mqtt.js to www-folder
    await _copy_mqtt_js(hass)
    
    # Profile Manager is loading but not yet starting.
    profile_manager = ProfileManager(hass, entry)
    hass.data[DOMAIN][entry.entry_id]["profile_manager"] = profile_manager
    
    # load platforms
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    
    # Profile manager start
    await profile_manager.start()

    
    # Register service for temp update
    async def handle_force_update(call):
        """Trigger manual temperature update."""
        _LOGGER.info("Manual temperature update triggered via service")
        await profile_manager.update_temps()
    
    hass.services.async_register(
        DOMAIN, 
        "force_update",
        handle_force_update
    )
    
    # Update listener for option update
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    
    _LOGGER.info(f"Setting up HeatZone with {len(zones)} zones")
    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    # get the manager and stop
    manager = hass.data.get(DOMAIN, {}).get(entry.entry_id, {}).get("profile_manager")
    if manager:
        await manager.stop()
    
    # remove service
    hass.services.async_remove(DOMAIN, "force_update")
    
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
        
    return unload_ok

async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload config entry when options change."""
    await hass.config_entries.async_reload(entry.entry_id)

async def async_remove_config_entry_device(
    hass: HomeAssistant, entry: ConfigEntry, device_entry: dr.DeviceEntry) -> bool:
    """Remove a config entry device (called when user deletes device from UI)."""
    # check if global device
    for identifier in device_entry.identifiers:
        if identifier[0] == DOMAIN and identifier[1] == GLOBAL_DEVICE_ID:
            return False
    
    # get the zone_id from identifiers
    zone_id = None
    for identifier in device_entry.identifiers:
        if identifier[0] == DOMAIN:
            zone_id = identifier[1]
            break
    
    if not zone_id:
        return True
    
    # remove zone from options
    zones = dict(entry.options.get("zones", {}))
    if zone_id in zones:
        zone_name = zones[zone_id].get("name", zone_id)
        zones.pop(zone_id)
        new_options = dict(entry.options)
        new_options["zones"] = zones
        hass.config_entries.async_update_entry(entry, options=new_options)
        _LOGGER.info(f"Removed zone '{zone_name}' ({zone_id}) from config")
    
    # Collect device entities
    entity_reg = er.async_get(hass)
    entities = er.async_entries_for_device(entity_reg, device_entry.id)
    
    entity_ids_to_remove = [entity.entity_id for entity in entities]
    
    # remove entities from registry
    for entity in entities:
        entity_reg.async_remove(entity.entity_id)
        _LOGGER.debug(f"Removed entity {entity.entity_id}")
    
    # Explicitly delete restore data
    if entity_ids_to_remove:
        from homeassistant.helpers.restore_state import RestoreStateData, DATA_RESTORE_STATE
        
        # Retrieve the RestoreStateData instance from hass.data
        if DATA_RESTORE_STATE in hass.data:
            restore_data: RestoreStateData = hass.data[DATA_RESTORE_STATE]
            
            # Remove the entity_ids from the last_states dictionary
            removed_count = 0
            for entity_id in entity_ids_to_remove:
                if entity_id in restore_data.last_states:
                    restore_data.last_states.pop(entity_id)
                    removed_count += 1
                    _LOGGER.debug(f"Removed restore state for {entity_id}")
            
            # Save the changes immediately
            if removed_count > 0:
                await restore_data.async_dump_states()
                _LOGGER.info(f"Removed {removed_count} restore state entries and saved to disk")
        else:
            _LOGGER.debug("RestoreStateData not yet initialized, no cleanup needed")
    
    return True


async def _copy_mqtt_js(hass: HomeAssistant) -> None:
    """Copy paho-mqtt.js to www folder."""
    try:
        source = Path(__file__).parent / "www" / "paho-mqtt.js"
        www_dir = Path(hass.config.path("www"))
        target = www_dir / "paho-mqtt.js"
        
        # www-Ordner erstellen falls nicht vorhanden
        www_dir.mkdir(exist_ok=True)
        
        # Datei kopieren (überschreibt alte Version)
        if source.exists():
            await hass.async_add_executor_job(shutil.copy2, source, target)
            _LOGGER.info("paho-mqtt.js copied to %s", target)
        else:
            _LOGGER.error("paho-mqtt.js not found in %s", source)
            
    except Exception as err:
        _LOGGER.error("Error copying paho-mqtt.js: %s", err)


async def async_setup(hass, config):
    """Set up HeatZone integration and serve custom card."""
    
    # Initialize data storage
    hass.data.setdefault(DOMAIN, {})
    
    # WebSocket-API registrieren
    await websocket_api.async_setup_ws_api(hass)
    _LOGGER.info("HeatZone WebSocket API initialized successfully.")

    return True


