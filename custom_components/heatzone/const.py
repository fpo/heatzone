from enum import StrEnum

DOMAIN = "heatzone"
DEFAULT_NAME = "HeatZone"

PLATFORMS = ["number", "switch", "select", "text", "sensor"] 

GLOBAL_DEVICE_NAME = "Global"
GLOBAL_DEVICE_ID = "global"
GLOBAL_MODEL = "Settings"

MANUFACTURER = "HeatZone"
ZONE_MODEL = "Climate Zone"
DEFAULT_AREA = ""

MQTT_HOST = "localhost"
MQTT_PORT = 1883
MQTT_WEBSOCKET_PORT = 1884
MQTT_USER = "mqtt"
MQTT_PASSWORD = "password"


class HeaterMode(StrEnum):
    OFF = "Aus"
    MANUAL = "Manuell"
    PROFIL = "Profil"

class HeaterExtendedMode(StrEnum):
    BOOST = "Boost"
    OPEN = "Offen"
    BYPASS = "Bypass"
    AWAY = "Abwesend"
    HOLIDAY = "Urlaub"

HEATER_MODES = [mode.value for mode in HeaterMode]

PREFIX_TOPIC = "heatzone/profiles/"

TEMP_BYPASS = -1.0
TEMP_OFF = 0.0
TEMP_FALLBACK = -1.0
MAX_RETRYS = 12
CLEANUP_TIMEOUT_MINUTES = 10

# Feste Sub-Topics für Profile
PROFILE_SUBTOPICS = [
    "Temp1", "Temp2", "Temp3", "Temp4", "TempAway", "TempHoliday",
    "Day1", "Day2", "Day3", "Day4", "Day5", "Day6", "Day7",
    "Activated"]

REQIRED_SUBTOPICS = ["Temp1", "Temp2", "Temp3", "Temp4", "TempAway", "TempHoliday", 
    "Day1", "Day2", "Day3", "Day4", "Day5", "Day6", "Day7"]
