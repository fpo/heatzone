# /config/custom_components/heatzone/websocket_api.py

import logging
import voluptuous as vol
from homeassistant.components import websocket_api

_LOGGER = logging.getLogger(__name__)

# --------------------------------------------------------------------
# The setup function is called when the integration starts.
# --------------------------------------------------------------------
 
async def async_setup_ws_api(hass):
    """Register HeatZone WebSocket API commands."""
    _LOGGER.debug("Registering HeatZone WebSocket command...")
    websocket_api.async_register_command(hass, handle_get_private_config)
    _LOGGER.info("HeatZone WebSocket command registered successfully.")

# --------------------------------------------------------------------
# WebSocket-command
# --------------------------------------------------------------------

@websocket_api.websocket_command({
    vol.Required("type"): "heatzone/get_private_config"
    })

@websocket_api.async_response
async def handle_get_private_config(hass, connection, msg):
    """Send stored MQTT configuration from config entry."""
    entry = next(iter(hass.config_entries.async_entries("heatzone")), None)
    if not entry:
        _LOGGER.warning("No config entry found for HeatZone.")
        connection.send_error(msg["id"], "not_found", "No config entry found.")
        return

    data = entry.data
    mqtt_config = {
        "host": data.get("mqtt_host"),
        "port": data.get("mqtt_port"),
        "websocket_port": data.get("mqtt_websocket_port"),
        "username": data.get("mqtt_user"),
        "password": data.get("mqtt_password"),
    }

    _LOGGER.debug("Sending MQTT config to frontend: %s", mqtt_config)
    connection.send_result(msg["id"], mqtt_config)
