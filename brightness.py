import json
import logging
import os
import signal
import socket
import sys
import time
from pathlib import Path
from typing import Callable, Optional, Tuple

import paho.mqtt.client as mqtt
import pandas as pd
from paho.mqtt.enums import CallbackAPIVersion
from pvlib import atmosphere, clearsky, irradiance, location  # type: ignore

# Optional timezone lookup from coordinates (gpsd)
try:
    from timezonefinder import TimezoneFinder
except ImportError:
    TimezoneFinder = None

MQTT_HOST: str = str(os.environ.get("MQTT_HOST", "")).strip()
MQTT_PORT: int = int(os.environ.get("MQTT_PORT", 1883))
MQTT_USERNAME: str = str(os.environ.get("MQTT_USERNAME", "")).strip()
MQTT_PASSWORD: str = str(os.environ.get("MQTT_PASSWORD", "")).strip()

DISCOVERY_PREFIX: str = str(os.environ.get("DISCOVERY_PREFIX", "homeassistant")).strip()
BASE_TOPIC: str = str(os.environ.get("BASE_TOPIC", "brightness")).strip()

LATITUDE: float = float(os.environ.get("LATITUDE", 0))
LONGITUDE: float = float(os.environ.get("LONGITUDE", 0))
ALTITUDE: float = float(os.environ.get("ALTITUDE", 0))

TZ: str = str(os.environ.get("TZ", "UTC")).strip()

# How often to publish irradiance (seconds)
PUBLISH_INTERVAL_S: int = int(os.environ.get("PUBLISH_INTERVAL", 60))

# Optional: fetch coordinates from a remote gpsd
GPSD_HOST: str = str(os.environ.get("GPSD_HOST", "")).strip()
GPSD_PORT: int = int(os.environ.get("GPSD_PORT", 2947))
GPSD_TIMEOUT_S: int = int(os.environ.get("GPSD_TIMEOUT", 5))
GPSD_REFRESH_S: int = int(os.environ.get("GPSD_REFRESH", 900))  # periodic refresh

# MQTT connection behavior
MQTT_KEEPALIVE_S: int = int(os.environ.get("MQTT_KEEPALIVE", 300))
CLIENT_ID: str = str(os.environ.get("MQTT_CLIENT_ID", f"brightness-publisher-{socket.gethostname()}")).strip()

HEARTBEAT_FILE = Path(os.environ.get("HEARTBEAT_FILE", "/tmp/last_publish"))

CLIENT: mqtt.Client = mqtt.Client(
    CallbackAPIVersion.VERSION2,
    client_id=CLIENT_ID,
    clean_session=False,
    protocol=mqtt.MQTTv311,
)

logging.basicConfig(format="%(asctime)s [%(levelname)s]: %(message)s", level=logging.DEBUG)

_connected: bool = False
_tz_finder: Optional[TimezoneFinder] = TimezoneFinder() if TimezoneFinder is not None else None


def get_fix_from_gpsd(host: str, port: int = 2947, timeout_s: int = 5) -> Optional[Tuple[float, float, float]]:
    """Return (lat, lon, alt_m) from gpsd, or None if unavailable."""
    if not host:
        return None

    deadline = time.time() + max(1, timeout_s)
    buf = b""

    try:
        with socket.create_connection((host, port), timeout=2) as s:
            s.settimeout(2)
            s.sendall(b'?WATCH={"enable":true,"json":true}\n')

            while time.time() < deadline:
                try:
                    chunk = s.recv(4096)
                    if not chunk:
                        break
                    buf += chunk

                    while b"\n" in buf:
                        line, buf = buf.split(b"\n", 1)
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            msg = json.loads(line.decode("utf-8", errors="ignore"))
                        except json.JSONDecodeError:
                            continue

                        if msg.get("class") != "TPV":
                            continue

                        mode = int(msg.get("mode") or 0)
                        lat = msg.get("lat")
                        lon = msg.get("lon")
                        alt = msg.get("alt")

                        if mode >= 2 and lat is not None and lon is not None:
                            alt_m = float(alt) if (alt is not None and mode >= 3) else 0.0
                            return float(lat), float(lon), alt_m

                except socket.timeout:
                    continue

    except Exception as e:
        logging.warning("gpsd lookup failed (%s:%s): %s", host, port, e)

    return None


def lookup_timezone(lat: float, lon: float) -> Optional[str]:
    """Best-effort timezone lookup for coordinates."""
    if _tz_finder is None:
        logging.debug("timezonefinder not available, using configured TZ")
        return None

    try:
        tz_name = _tz_finder.timezone_at(lat=lat, lng=lon)
        if tz_name:
            return tz_name
        logging.warning("No timezone found for lat=%s lon=%s, using configured TZ", lat, lon)
    except Exception as e:
        logging.warning("Timezone lookup failed for lat=%s lon=%s: %s", lat, lon, e)
    return None


def handler(signum: int, frame: Callable):
    try:
        CLIENT.publish(f"{BASE_TOPIC}/availability", "offline", qos=1, retain=True)
    except Exception:
        pass

    CLIENT.disconnect()
    CLIENT.loop_stop()
    sys.exit(signum)


signal.signal(signal.SIGINT, handler)


def on_connect(client, userdata, flags, rc, properties=None):
    global _connected
    if rc == 0:
        _connected = True
        logging.info("MQTT connected (client_id=%s)", CLIENT_ID)

        # Announce online and (re)publish discovery on every connect.
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
            qos=1,
        )
    else:
        logging.warning("MQTT connect failed rc=%s", rc)


def on_disconnect(client, userdata, rc, properties=None):
    global _connected
    _connected = False
    logging.warning("MQTT disconnected rc=%s", rc)


def publish_data(loc: location.Location, tz: str) -> None:
    now = pd.Timestamp.now(tz=tz)
    times = pd.DatetimeIndex([now])

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

    # Publish a clean JSON dict (not an indexed DataFrame JSON blob)
    payload = irr.iloc[0].to_dict()
    payload["ts"] = now.isoformat()

    msg = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
    logging.info("publishing ts=%s", payload.get("ts"))

    CLIENT.publish(BASE_TOPIC, msg, qos=1)

    # Touch a heartbeat file for the Docker healthcheck
    HEARTBEAT_FILE.write_text(str(time.time()))


def main():

    lat, lon, alt = LATITUDE, LONGITUDE, ALTITUDE
    tz = TZ

    CLIENT.enable_logger()

    CLIENT.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)

    CLIENT.will_set(f"{BASE_TOPIC}/availability", "offline", qos=1, retain=True)

    CLIENT.on_connect = on_connect
    CLIENT.on_disconnect = on_disconnect

    CLIENT.reconnect_delay_set(min_delay=1, max_delay=60)

    if not MQTT_HOST:
        logging.error("MQTT_HOST is empty")
        return 2

    # Initial gpsd fix if configured
    last_gpsd_check = 0.0
    if GPSD_HOST:
        fix = get_fix_from_gpsd(GPSD_HOST, GPSD_PORT, GPSD_TIMEOUT_S)
        if fix:
            lat, lon, alt = fix
            logging.info("Using gpsd fix: lat=%s lon=%s alt=%sm", lat, lon, alt)
            gps_tz = lookup_timezone(lat, lon)
            if gps_tz:
                tz = gps_tz
                logging.info("Using timezone from gpsd fix: %s", tz)
        else:
            logging.warning("gpsd configured but no fix, using env LAT/LON/ALT")
        last_gpsd_check = time.time()

    logging.info("Active timezone: %s", tz)

    CLIENT.connect_async(MQTT_HOST, MQTT_PORT, keepalive=MQTT_KEEPALIVE_S)
    CLIENT.loop_start()

    # Wait for initial connect (avoid publishing before we have a session)
    start = time.time()
    while not _connected and time.time() - start < 30:
        time.sleep(0.2)

    loc = location.Location(lat, lon, tz, alt, "Home")
    logging.info(loc)

    while True:
        # Periodically refresh GPSD coordinates (optional)
        if GPSD_HOST and (time.time() - last_gpsd_check) >= GPSD_REFRESH_S:
            fix = get_fix_from_gpsd(GPSD_HOST, GPSD_PORT, GPSD_TIMEOUT_S)
            last_gpsd_check = time.time()
            if fix:
                lat, lon, alt = fix
                gps_tz = lookup_timezone(lat, lon)
                if gps_tz:
                    tz = gps_tz
                    logging.info("Using timezone from gpsd fix: %s", tz)
                loc = location.Location(lat, lon, tz, alt)
                logging.info("Updated gpsd fix: lat=%s lon=%s alt=%sm", lat, lon, alt)
                logging.info(loc)
            else:
                logging.warning("gpsd refresh failed, keeping previous location")

        if _connected:
            publish_data(loc, tz)
        else:
            logging.warning("MQTT not connected, skipping publish")

        time.sleep(PUBLISH_INTERVAL_S)


if __name__ == "__main__":

    try:
        raise SystemExit(main())
    except Exception:
        logging.exception("fatal error")
        raise SystemExit(1)
