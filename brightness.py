import asyncio
import json
import logging
import os
import signal
import sys
import time
from typing import Callable

import paho.mqtt.client as mqtt
import pandas as pd
from paho.mqtt.enums import CallbackAPIVersion
from pvlib import atmosphere, clearsky, irradiance, location  # type: ignore

MQTT_HOST: str = str(os.environ.get("MQTT_HOST", ""))
MQTT_PORT: int = int(os.environ.get("MQTT_PORT", 1883))
MQTT_USERNAME: str = str(os.environ.get("MQTT_USERNAME", ""))
MQTT_PASSWORD: str = str(os.environ.get("MQTT_PASSWORD", ""))

DISCOVERY_PREFIX: str = str(os.environ.get("DISCOVERY_PREFIX", "homeassistant"))
BASE_TOPIC: str = str(os.environ.get("BASE_TOPIC", "brightness"))

LATITUDE: float = float(os.environ.get("LATITUDE", 0))
LONGITUDE: float = float(os.environ.get("LONGITUDE", 0))
ALTITUDE: float = float(os.environ.get("ALTITUDE", 0))

TZ: str = str(os.environ.get("TZ", "UTC"))

CLIENT: mqtt.Client = mqtt.Client(
    callback_api_version=CallbackAPIVersion.VERSION2,
    client_id="brightness-publisher",
    clean_session=True,
)

logging.basicConfig(format="%(asctime)s [%(levelname)s]: %(message)s", level=logging.DEBUG)


def on_disconnect(client, userdata, rc, properties=None):
    logging.warning(f"MQTT disconnected rc={rc}")


def handler(signum: int, frame: Callable):
    CLIENT.disconnect()
    CLIENT.loop_stop()
    sys.exit(signum)


signal.signal(signal.SIGTERM, handler)


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

    CLIENT.publish(BASE_TOPIC, msg, qos=1)

    # Touch a heartbeat file for the Docker healthcheck
    with open("/tmp/last_publish", "w") as f:
        f.write(str(time.time()))


def main():

    CLIENT.enable_logger()

    CLIENT.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)

    CLIENT.will_set(f"{BASE_TOPIC}/availability", "offline", qos=1, retain=True)

    CLIENT.reconnect_delay_set(min_delay=1, max_delay=60)

    CLIENT.on_disconnect = on_disconnect

    CLIENT.connect_async(MQTT_HOST, MQTT_PORT, keepalive=120)
    CLIENT.loop_start()

    CLIENT.publish(f"{BASE_TOPIC}/availability", "online", qos=1, retain=True)

    CLIENT.publish(
        f"{DISCOVERY_PREFIX}/sensor/brightness/brightness/config",
        json.dumps({
            "name": "Solar Irradiance",
            "state_topic": BASE_TOPIC,
            "value_template": "{{ (value_json.poa_global|float - value_json.poa_direct|float) + 1 }}",
            "unique_id": "17c4c005-01ad-4c87-8cc6-a4901ff1ebd0",
            "device_class": "irradiance",
            "unit_of_measurement": "W/m²",
            "state_class": "measurement",
            "json_attributes_topic": BASE_TOPIC,
            "availability_topic": f"{BASE_TOPIC}/availability",
            "qos": 1,
            "device": {
                "identifiers": ["custom-brightness-publisher"],
                "name": "Brightness Publisher",
                "manufacturer": "custom",
                "model": "pvlib-ineichen",
            },
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
