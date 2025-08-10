#!/usr/bin/env python3
import os, sys, time
from pathlib import Path
import paho.mqtt.client as mqtt

# 1) recent publish check
p = Path("/tmp/last_publish")
if not p.exists():
    sys.exit("no heartbeat")
try:
    last = float(p.read_text().strip() or "0")
except Exception as e:
    sys.exit(f"bad heartbeat: {e}")
if time.time() - last > 45:
    sys.exit("stale heartbeat")

# 2) broker reachability check
host = os.getenv("MQTT_HOST", "")
port = int(os.getenv("MQTT_PORT", "1883"))
user = os.getenv("MQTT_USERNAME", "")
pwd = os.getenv("MQTT_PASSWORD", "")
c = mqtt.Client()
if user:
    c.username_pw_set(user, pwd)
try:
    c.connect(host, port, 10)
    c.disconnect()
except Exception as e:
    sys.exit(f"broker unreachable: {e}")
