# /config/custom_components/heatzone/config_flow.py

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.helpers import selector
from homeassistant.core import callback
from .const import *

import logging
_LOGGER = logging.getLogger(__name__)

class HeatzoneConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for HeatZone Hub."""
    VERSION = 1
    
    async def async_step_user(self, user_input=None):
        """create hub."""
        
        if user_input is not None:
            return self.async_create_entry(
                title=user_input.get("name", "HeatZone"),
                data={
                    "name": "HeatZone",
                    "mqtt_host": user_input.get("mqtt_host", MQTT_HOST),
                    "mqtt_port": user_input.get("mqtt_port", MQTT_PORT),
                    "mqtt_websocket_port": user_input.get("mqtt_websocket_port", MQTT_WEBSOCKET_PORT),
                    "mqtt_user": user_input.get("mqtt_user", MQTT_USER),
                    "mqtt_password": user_input.get("mqtt_password", MQTT_PASSWORD),
                },
                options={
                    "zones": {}  
                }
            )

        schema = vol.Schema({
            vol.Required("mqtt_host", default=MQTT_HOST): str,
            vol.Optional("mqtt_port", default=MQTT_PORT): int,
            vol.Optional("mqtt_websocket_port", default=MQTT_WEBSOCKET_PORT): int,
            vol.Optional("mqtt_user", default=MQTT_USER): str,
            vol.Optional("mqtt_password", default=MQTT_PASSWORD): selector.TextSelector(
                selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
            ),
        })
        return self.async_show_form(step_id="user", data_schema=schema)
        
    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Options flow for hub."""
        return HeatzoneOptionsFlow()


class HeatzoneOptionsFlow(config_entries.OptionsFlow):
    """Options flow for Hub: MQTT settings and adding devices.."""
    
    async def async_step_init(self, user_input=None):
        """Main-Menue."""
        return self.async_show_menu(
            step_id="init",
            menu_options=["add_zone", "mqtt_settings" ]
            # menu_options={"add_zone": "Add new zone", "mqtt_settings": "MQTT-Settings"}
        )
    
    async def async_step_add_zone(self, user_input=None):
        """Add new zone."""
        
        if user_input is not None:
            zone_name = user_input["name"]
            zone_id = zone_name.lower().replace(' ', '_').replace('ä', 'ae').replace('ö', 'oe').replace('ü', 'ue').replace('ß', 'ss')
            
            # get zones from options
            zones = dict(self.config_entry.options.get("zones", {}))
            
            # check if zone exists
            if zone_id in zones:
                return self.async_show_form(
                    step_id="add_zone",
                    data_schema=vol.Schema({
                        vol.Required("name"): str,
                    }),
                    errors={"name": "zone_exists"}
                )
            
            # add new zone
            zones[zone_id] = { "name": zone_name, }
            
            # keep all existing options!
            new_options = dict(self.config_entry.options)
            new_options["zones"] = zones
            
            # update options
            return self.async_create_entry( title="", data=new_options )

        schema = vol.Schema({ vol.Required("name"): str, })
        
        return self.async_show_form( step_id="add_zone", data_schema=schema )
    
    async def async_step_mqtt_settings(self, user_input=None):
        """Edit MQTT settings."""
        
        if user_input is not None:
            # update data
            new_data = {
                "name": self.config_entry.data.get("name"),
                "mqtt_host": user_input.get("mqtt_host", MQTT_HOST),
                "mqtt_port": user_input.get("mqtt_port", MQTT_PORT),
                "mqtt_websocket_port": user_input.get("mqtt_websocket_port", MQTT_WEBSOCKET_PORT),
                "mqtt_user": user_input.get("mqtt_user", MQTT_USER),
                "mqtt_password": user_input.get("mqtt_password", MQTT_PASSWORD),
            }
            
            self.hass.config_entries.async_update_entry(
                self.config_entry, 
                data=new_data
            )
            
            return self.async_create_entry(title="", data=self.config_entry.options)
        
        schema = vol.Schema({
            vol.Required("mqtt_host", default=self.config_entry.data.get("mqtt_host", MQTT_HOST)): str,
            vol.Optional("mqtt_port", default=self.config_entry.data.get("mqtt_port", MQTT_PORT)): int,
            vol.Optional("mqtt_websocket_port", default=self.config_entry.data.get("mqtt_websocket_port", MQTT_WEBSOCKET_PORT)): int,
            vol.Optional("mqtt_user", default=self.config_entry.data.get("mqtt_user", MQTT_USER)): str,
            vol.Optional("mqtt_password", default=self.config_entry.data.get("mqtt_password", MQTT_PASSWORD)): selector.TextSelector(
                selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
            ),
        })
        
        return self.async_show_form(step_id="mqtt_settings", data_schema=schema)