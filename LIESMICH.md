# HeatZone integration for Home Assistant

Heatzone ist als als Heizungssteuerung innerhalb von Home Assistant integriert worden. 

> [!WARNING]  
> **Achtung** dies ist ein sehr früher Entwicklungsstand und nicht für den Produktiveinsatz
> vorgesehen. Nutzung auf eigene Gefahr. **

## Features

Heatzone steuert Thermostate nach einem Zeitplan in Abhängigkeit einiger Modi und
Sensoren. Die Definition erfolgt in einem mqtt-Profil.

## Vorraussetzungen

Heatzone arbeitet nur in Verbindung mit mqtt. Um alle Funktionalitäten zu nutzen,
ist zwingend eine Installation eines mqtt Brokers notwendig. 

Heatzone hat in seiner Integration mehrere Geräte mit folgenden Funktionen:

1. Globale Einstellungen:
    - Globaler Modus (Steuert bei Änderung alle Zonen in den gleichen Modus. Z.Bsp. bei Urlaub)
    - Boostdauer in Minuten - Gibt die Dauer des Boost vor. Gilt für alle Zonen gleich.
    - Die Boosttemperatur - Diese Temparatur wird während der Boostdauer gesetzt.

2. Zone - Die einzelnen Zonen z.Bsp. Wohnzimmer mit folgenden Einstellungen:
    - Anwesend = Definiert ob diese Zone die Temperatur für Abwesend erhällt.
    - Boost = Wenn aktiviert läuft dieser solange wie in den Globalen Einstellungen definiert.
    - Fensterkontakt = Auswahl einer Entität für den Fensterkontakt
    - Feuchtigkeitssensor = Auswahl einer Entität für den Feuchtigkeit.
    - Manuelle Temperatur = Definition einer Temperatur für den manuellen Modus.
    - Profil = Der Profilname des Profils welches für diese Zone verwendet werden soll.
    (siehe auch Profildefinition mqtt - Dies ist gleichzeitig der subtopic des Profils)
    - Temperatursensor = Auswahl einer Entität für die Ist-Temperatur
    - Thermostat = Der Thermostat der gesteuert werden soll.
    - Verzögerung = Die Zeit in der keine Änderung passieren soll wenn der Fensterkontakt offen ist.

Es können beliebige Zonen hinzugefügt werden. Und auch wieder gelöscht werden. Nur die Globalen 
Einstellungen können nicht gelöscht werden.


## Einstellungen Integration

Über das Zahnradsymbol sind die Einstellunegn der Integration möglich. Hier definieren sie bitte
die Zugangsdaten für den mqtt Broker. Diese Clientdefinitionen laufen völlig getrennt von dem 
internen mqtt Broker von Home Assistant.

## Sensoren der Zonen

Folgende Sensoren besitzen die Zonen:
- Fensterkontakt = Offen/Geschlosssen
- Feuchtigkeit = Wert des ausgewählten Feuchtigkeitssensors
- Temperatur-Ist = Wert des ausgewählten Temparatursensors
- Temperatur-Soll = Wert der errechneten Temperatur
( siehe auch Temperaturermittlung)

## Temperaturermittlung

Die Temperaturermittlung läuft jede Minute ab. Nur teilweise real time.

Oberste Priorität hat der Modus "Aus". Wenn der Modus "Aus" ist, 
wird generell die Solltemperatur auf 0° gestellt. 
Alle anderen Einstellungen sind dann wirkungslos. 

Steht Anwesend auf Aus wird die Temperatur die im Profil unter Abwesend definiert ist genommen.

Danach wird geprüft ob Fenster geöffnet sind und die Sperrzeit (Verzögerung)
abgelaufen ist, dann wird egal welcher ermittelte Wert die Temperatur auf 0° gestellt.

Steht der Modus auf Urlaub wird unabhängig der Zeit die Temperatur auf den Wert gestellt, 
der im Profil für Urlaub definiert ist.

Steht der Modus auf Profil dann wird im Profil geschaut welche Temperatur zur jetztigen Zeit definiert ist. 
Es besteht die Möglichkeit vier verscheidene Temparaturen, sowie Bypass = -1° oder Aus = 0° im Profil zu definieren.

## Profildefinition mqtt

Die Integration erwartet entsprechende Profildefinitionen im mqtt unter heatzone/profiles/profilename
Zur Definition des Profils können sie komfortabel die Custom Card heatzone-profile nehmen. 
Hier aber die eingentlichen subtopis:

- Temp1 = Wert für Temperatur 1
- Temp2 = Wert für Temperatur 2
- Temp3 = Wert für Temparatur 3
- Temp4 = Wert für Temparatur 4
- TempAway = Wert für Temperatur Abwesend
- TempHoliday = Wert für Temparatur Urlaub
- Day1 - Day7 = JSON für die Einstellungen zeitabhängig in der folgenden Form:
([{"From":"0:00","To":"9:00","TempID":0},{"From":"9:00","To":"8:00","TempID":1}]) 


## Installation

```bash
cd YOUR_HASS_CONFIG_DIRECTORY    # same place as configuration.yaml
mkdir -p custom_components/heatzone
cd custom_components/heatzone
unzip heatzone-main.zip
mv heatzone-main/custom_components/heatzone/* .
```

