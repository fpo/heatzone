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
    
    # Alle Zonen aus options holen (nur zone_id und name)
    zones = entry.options.get("zones", {})
    
    # Device Registry
    device_registry = dr.async_get(hass)
    
    # Daten speichern
    hass.data[DOMAIN][entry.entry_id] = {
        "mqtt_config": {
            "host": entry.data.get("mqtt_host"),
            "port": entry.data.get("mqtt_port", 1883),
            "user": entry.data.get("mqtt_user", ""),
            "password": entry.data.get("mqtt_password", ""),
        },
        "zones": zones,
    }
    
    # Profile Manager laden aber noch nicht starten
    profile_manager = ProfileManager(hass, entry)
    hass.data[DOMAIN][entry.entry_id]["profile_manager"] = profile_manager
    
    # Plattformen laden
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    
    # Profile Manager starten
    await profile_manager.start()

    
    # Service registrieren für manuelles Update
    async def handle_force_update(call):
        """Manuelles Update der Temperaturen triggern."""
        _LOGGER.info("Manual temperature update triggered via service")
        await profile_manager.update_temps()
    
    hass.services.async_register(
        DOMAIN, 
        "force_update",
        handle_force_update
    )
    
    # Update Listener für Options-Änderungen
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    
    _LOGGER.info(f"Setting up HeatZone with {len(zones)} zones")
    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    # Hole den Manager und stoppe ihn
    manager = hass.data.get(DOMAIN, {}).get(entry.entry_id, {}).get("profile_manager")
    if manager:
        await manager.stop()
    
    # Service entfernen
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
    # Prüfen ob es das Hub-Gerät ist
    for identifier in device_entry.identifiers:
        if identifier[0] == DOMAIN and identifier[1] == GLOBAL_DEVICE_ID:
            # Optionale Info für den Nutzer
            hass.async_create_task(
                hass.services.async_call(
                    "persistent_notification",
                    "create",
                    {
                        "title": "Löschen nicht möglich",
                        "message": (
                            "Das globale Gerät dieser Integration kann nicht gelöscht "
                            "werden, da es für die Funktion benötigt wird."
                        ),
                        "notification_id": f"{DOMAIN}_global_device_protected",
                    },
                    blocking=False,
                )
            )
            return False
    
    # Finde die Zone ID aus den identifiers
    zone_id = None
    for identifier in device_entry.identifiers:
        if identifier[0] == DOMAIN:
            zone_id = identifier[1]
            break
    
    if not zone_id:
        return True
    
    # Zone aus options entfernen
    zones = dict(entry.options.get("zones", {}))
    if zone_id in zones:
        zone_name = zones[zone_id].get("name", zone_id)
        zones.pop(zone_id)
        new_options = dict(entry.options)
        new_options["zones"] = zones
        hass.config_entries.async_update_entry(entry, options=new_options)
        _LOGGER.info(f"Removed zone '{zone_name}' ({zone_id}) from config")
    
    # Entities des Devices sammeln
    entity_reg = er.async_get(hass)
    entities = er.async_entries_for_device(entity_reg, device_entry.id)
    
    entity_ids_to_remove = [entity.entity_id for entity in entities]
    
    # Entities aus Registry entfernen
    for entity in entities:
        entity_reg.async_remove(entity.entity_id)
        _LOGGER.debug(f"Removed entity {entity.entity_id}")
    
    # Restore-Daten explizit löschen
    if entity_ids_to_remove:
        from homeassistant.helpers.restore_state import RestoreStateData, DATA_RESTORE_STATE
        
        # Hole die RestoreStateData Instanz aus hass.data
        if DATA_RESTORE_STATE in hass.data:
            restore_data: RestoreStateData = hass.data[DATA_RESTORE_STATE]
            
            # Entferne die entity_ids aus last_states Dictionary
            removed_count = 0
            for entity_id in entity_ids_to_remove:
                if entity_id in restore_data.last_states:
                    restore_data.last_states.pop(entity_id)
                    removed_count += 1
                    _LOGGER.debug(f"Removed restore state for {entity_id}")
            
            # Speichere die Änderungen sofort
            if removed_count > 0:
                await restore_data.async_dump_states()
                _LOGGER.info(f"Removed {removed_count} restore state entries and saved to disk")
        else:
            _LOGGER.debug("RestoreStateData not yet initialized, no cleanup needed")
    
    return True

async def async_setup(hass, config):
    """Set up HeatZone integration and serve custom card."""
    
    # Initialize data storage
    hass.data.setdefault(DOMAIN, {})
    
    # Quelle in der Integration
    src = hass.config.path("custom_components/heatzone/www/heatzone-card.js")
    if not os.path.exists(src):
        _LOGGER.error("HeatZone Card not found at %s", src)
        return True

    # Ziel unter /config/www/community (=> /local/community/)
    dest_dir = hass.config.path("www")
    dest = hass.config.path("www/heatzone-card.js")

    # Verzeichnisse anlegen (evtl. im Executor, da IO)
    def _prepare():
        os.makedirs(dest_dir, exist_ok=True)
        shutil.copy2(src, dest)

    # do the job
    await hass.async_add_executor_job(_prepare)

    _LOGGER.warning(
        "HeatZone card deployed to %s (reachable at /local/heatzone-card.js)",
        dest,
    )

    # Optional: Debug-Check, ob Datei lesbar ist
    if not os.path.exists(dest):
        _LOGGER.error("Card copy failed, %s not found after copy.", dest)
    else:
        _LOGGER.debug("Card present at %s", dest)

    # WebSocket-API registrieren
    await websocket_api.async_setup_ws_api(hass)
    _LOGGER.info("HeatZone WebSocket API initialized successfully.")

    return True


