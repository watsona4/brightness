#!/usr/bin/env python3
import os
import socket
import sys
import time
from pathlib import Path


def fail(msg: str, code: int = 1) -> int:
    print(msg, file=sys.stderr)
    return code


def main() -> int:
    # ---- 1) recent publish check ----
    hb_path = Path(os.getenv("HEARTBEAT_FILE", "/tmp/last_publish"))
    if not hb_path.exists():
        return fail(f"no heartbeat file: {hb_path}")

    try:
        last = float((hb_path.read_text() or "").strip() or "0")
    except Exception as e:
        return fail(f"bad heartbeat: {e}")

    # Default to 3 minutes; override with HEALTH_MAX_AGE_SECONDS.
    max_age = int(os.getenv("HEALTH_MAX_AGE_SECONDS", "180"))
    age = time.time() - last
    if age > max_age:
        return fail(f"stale heartbeat: age={age:.1f}s > {max_age}s")

    # ---- 2) optional: TCP reachability check (no MQTT connect) ----
    # This avoids generating "auto-..." clients in Mosquitto logs.
    if os.getenv("HEALTHCHECK_TCP", "1") == "1":
        host = os.getenv("MQTT_HOST", "").strip()
        port = int(os.getenv("MQTT_PORT", "1883"))
        if host:
            try:
                with socket.create_connection((host, port), timeout=2):
                    pass
            except Exception as e:
                return fail(f"mqtt tcp unreachable {host}:{port}: {e}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
