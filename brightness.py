import asyncio
import json
import logging
import os
import signal
import sys
import time
from typing import Callable

import paho.mqtt.client as mqtt
from paho.mqtt.enums import CallbackAPIVersion
import pandas as pd
from pvlib import atmosphere, clearsky, irradiance, location  # type: ignore

MQTT_HOST: str = str(os.environ.get("MQTT_HOST", ""))
MQTT_PORT: int = int(os.environ.get("MQTT_PORT", 1883))

LATITUDE: float = float(os.environ.get("LATITUDE", 0))
LONGITUDE: float = float(os.environ.get("LONGITUDE", 0))
ALTITUDE: float = float(os.environ.get("ALTITUDE", 0))

TZ: str = str(os.environ.get("TZ", "UTC"))

CLIENT: mqtt.Client = mqtt.Client(CallbackAPIVersion.VERSION2)

logging.basicConfig(format="%(asctime)s [%(levelname)s]: %(message)s", level=logging.DEBUG)


def handler(signum: int, frame: Callable):
    CLIENT.disconnect()
    CLIENT.loop_stop()
    sys.exit(signum)


async def publish_data(loc: location.Location) -> mqtt.MQTTMessageInfo:

    now = pd.Timestamp.now()

    times = pd.date_range(now, now, tz=TZ)

    logging.info(f"{times[0]=}")

    solpos = loc.get_solarposition(times)

    relative_airmass = atmosphere.get_relative_airmass(solpos.apparent_zenith)
    absolute_airmass = atmosphere.get_absolute_airmass(relative_airmass)

    linke_turbidity = clearsky.lookup_linke_turbidity(times, LATITUDE, LONGITUDE)

    sky = clearsky.ineichen(
        apparent_zenith=solpos.apparent_zenith,
        airmass_absolute=absolute_airmass,
        linke_turbidity=linke_turbidity,
        altitude=ALTITUDE,
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

    return CLIENT.publish("brightness", msg, qos=1)


def main():

    CLIENT.enable_logger()

    CLIENT.connect(MQTT_HOST, MQTT_PORT, 60)
    CLIENT.loop_start()

    signal.signal(signal.SIGTERM, handler)

    CLIENT.publish(
        "homeassistant/sensor/brightness/brightness/config",
        json.dumps({
            "name": "Solar Irradiance",
            "state_topic": "brightness",
            "value_template": (
                "{{ (value_json.poa_global|float - value_json.poa_direct|float) + 1 }}"
            ),
            "unique_id": "17c4c005-01ad-4c87-8cc6-a4901ff1ebd0",
            "device_class": "irradiance",
            "unit_of_measurement": "W/m²",
            "state_class": "measurement",
            "json_attributes_topic": "brightness",
        }),
        retain=True,
    )

    loc = location.Location(LATITUDE, LONGITUDE, TZ, ALTITUDE)

    while True:
        asyncio.run(publish_data(loc))
        time.sleep(10)


if __name__ == "__main__":

    try:
        sys.exit(main())
    except Exception:
        sys.exit(1)
