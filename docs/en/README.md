# HeatZone Integration for Home Assistant

[![EN](https://img.shields.io/badge/EN-English-blue)](https://github.com/fpo/heatzone/blob/main/docs/en/README.md) [![DE](https://img.shields.io/badge/DE-Deutsch-red)](https://github.com/fpo/heatzone/blob/main/docs/de/README.md)

Heatzone has been integrated as a heating control system within Home Assistant.

![Warning](/assets/warning-red-warning-en.svg)

## Installation via HACS

[![Add to HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=fpo&repository=heatzone&category=integration)

## Features

Heatzone controls thermostats according to a schedule depending on several modes and sensors. 
The definition is done in an MQTT profile.

## Requirements

Heatzone only works in conjunction with MQTT. To use all functionalities, 
it is mandatory to install an MQTT broker.

Heatzone has several devices in its integration with the following functions:

1. Global settings:
    - Global mode (When changed, all zones are set to the same mode. E.g. for holiday)
    - Boost duration in minutes - Specifies the duration of the boost. Applies equally to all zones.
    - Boost temperature - This temperature is set during the boost duration.

2. Zone - The individual zones, e.g. living room, with the following settings:
    - Present = Defines whether this zone receives the temperature for absent.
    - Boost = When activated, runs as long as defined in the global settings.
    - Window contact = Selection of an entity for the window contact
    - Humidity sensor = Selection of an entity for humidity
    - Manual temperature = Definition of a temperature for manual mode
    - Profile = The profile name of the profile to be used for this zone
    (see also profile definition MQTT - This is also the subtopic of the profile)
    - Priority (Only important for heating control - see heating control)
    - Temperature sensor = Selection of an entity for the actual temperature
    - Thermostat = The thermostat to be controlled
    - Delay = The time during which no change should occur if the window contact is open

Any number of zones can be added and also deleted. Only the global settings cannot be deleted.


## Integration settings

Via the gear icon, you can access the integration settings. 
Here, please define the access data for the MQTT broker. 
These client definitions run completely separately from the internal MQTT broker of Home Assistant.

## Zone sensors

The zones have the following sensors:
- Window contact = Open/Closed
- Humidity = Value of the selected humidity sensor
- Actual temperature = Value of the selected temperature sensor
- Target temperature = Value of the calculated temperature
(see also temperature determination)

## Temperature determination

Temperature determination runs every minute. Only partially real time.

Top priority is the "Off" mode. 
If the mode is "Off", the target temperature is generally set to 0°. 
All other settings are then ineffective.

If Present is set to Off, the temperature defined in the profile under Absent is used.

Then it is checked whether windows are open and the lock time (delay) has expired. 
If so, regardless of the determined value, the temperature is set to 0°.

If the mode is set to holiday, the temperature is set to the value defined 
in the profile for holiday, regardless of the time.

If the mode is set to Profile, the profile is checked to see which temperature is defined for the current time. 
It is possible to define four different temperatures, as well as Bypass = -1° or Off = 0° in the profile.

## Profile definition MQTT

The integration expects corresponding profile definitions in MQTT under heatzone/profiles/profilename
To define the profile, you can conveniently use the custom card heatzone-profile.
Here are the actual subtopics:

- Temp1 = Value for temperature 1
- Temp2 = Value for temperature 2
- Temp3 = Value for temperature 3
- Temp4 = Value for temperature 4
- TempAway = Value for temperature absent
- TempHoliday = Value for temperature holiday
- Day1 - Day7 = JSON for the time-dependent settings in the following form:
([{"From":"0:00","To":"9:00","TempID":0},{"From":"9:00","To":"8:00","TempID":1}])


## Manual Installation

```bash
cd YOUR_HASS_CONFIG_DIRECTORY    # same place as configuration.yaml
mkdir -p custom_components/heatzone
cd custom_components/heatzone
unzip heatzone-main.zip
mv heatzone-main/custom_components/heatzone/* .
```

## Thermostats

Currently supported are:
+ Aqara E1
+ Homematic (External temperature sensor not possible!)

(Please leave information here about which thermostats you would like supported and how)

Alternatively, an unknown thermostat can also be used with this integration by creating 
an automation that transmits the external temperature to the thermostat. 
The target temperature is also transmitted without direct support.

## Heating Control

The heating control is currently still in the testing phase. 
My goal was and is to control a Vaillant gas boiler. I always found it quite inconvenient
to do this via the control unit. In addition, with the standard Vaillant solution, 
I only have one reference point (namely the living room). The goal is therefore to have 
the most convenient control possible with weekly profiles that allow for additional 
prioritization of the heating zones and thus also a shifting of the reference point. 
The priority setting is used for this purpose.

## Custom Cards

The integration works perfectly well without custom cards. However, it is 
significantly more convenient to control the corresponding MQTT-profiles with 
the available custom cards. Of course, you can also control the individual entities 
with standard cards. 

Please note, however, that zones are not climate entities.

They are available here: [HeatZone Custom Cards](https://github.com/fpo/heatzone-card/blob/main/docs/de/README.md)