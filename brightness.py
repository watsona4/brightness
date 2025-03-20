import json
import logging
import signal
import sys
import time

import paho.mqtt.client as mqtt
import pandas as pd
from pvlib import atmosphere, clearsky, irradiance, location

LAT = 43.09176073408273
LON = -73.49606500488254
ALT = 121


logging.basicConfig(
    format="%(asctime)s [%(levelname)s]: %(message)s", level=logging.DEBUG
)


client = mqtt.Client()
client.enable_logger()

client.connect("192.168.1.6", 1883, 60)
client.loop_start()


def handler(signum, frame):
    client.disconnect()
    client.loop_stop()
    sys.exit(0)
    

signal.signal(signal.SIGTERM, handler)

msg_info = client.publish(
    "homeassistant/sensor/brightness/brightness/config",
    json.dumps({
        "name": "Solar Irradiance",
        "state_topic": "brightness",
        "value_template": (
            "{{ (value_json.poa_global|float - value_json.poa_direct|float) +"
            " 1 }}"
        ),
        "unique_id": "17c4c005-01ad-4c87-8cc6-a4901ff1ebd0",
        "device_class": "irradiance",
        "unit_of_measurement": "W/m²",
        "state_class": "measurement",
        "json_attributes_topic": "brightness",
    }),
    retain=True,
)

loc = location.Location(latitude=LAT, longitude=LON, altitude=ALT)

while True:

    now = pd.Timestamp.now()

    times = pd.date_range(now, now, tz="America/New_York")
    logging.info(f"{times[0]=}")

    solpos = loc.get_solarposition(times)

    relative_airmass = atmosphere.get_relative_airmass(solpos.apparent_zenith)
    absolute_airmass = atmosphere.get_absolute_airmass(relative_airmass)

    linke_turbidity = clearsky.lookup_linke_turbidity(times, LAT, LON)

    sky = clearsky.ineichen(
        apparent_zenith=solpos.apparent_zenith,
        airmass_absolute=absolute_airmass,
        linke_turbidity=linke_turbidity,
        altitude=ALT,
    )

    irr = irradiance.get_total_irradiance(
        surface_tilt=90,
        surface_azimuth=180,
        solar_zenith=solpos.zenith,
        solar_azimuth=solpos.azimuth,
        dni=sky["dni"],
        ghi=sky["ghi"],
        dhi=sky["dhi"],
    )

    msg = irr.T.squeeze().to_json(orient="index")
    logging.info(f"publishing {msg=}")

    msg_info = client.publish("brightness", msg, qos=1)

    time.sleep(10)
