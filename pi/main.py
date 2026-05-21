"""
main.py
-------
Main sensor loop for the water quality monitoring system.

Reads all four sensors on a fixed interval and either:
  - Prints readings to the terminal (CLOUD_ENABLED = False)
  - Prints to terminal AND publishes to AWS IoT Core via MQTT (CLOUD_ENABLED = True)

── Quick start ──────────────────────────────────────────────────────────────
  1. Copy config.example.py to config.py
  2. Run calibrate_ph.py to fill in pH calibration values
  3. Run this script:  python3 main.py

  For terminal-only mode (no AWS needed):
    Set CLOUD_ENABLED = False below — the default.

  When you are ready to send data to the cloud:
    Set CLOUD_ENABLED = True and make sure config.py has your MQTT settings
    and the certs/ folder has your three AWS certificate files.

── DS18B20 temperature sensor ───────────────────────────────────────────────
  The DS18B20 is currently NOT connected. The temperature sensor module
  returns None, which is handled gracefully:
    - TDS compensation falls back to assuming 25 °C
    - JSON payload sends  "temperature": null
  When you connect the DS18B20, uncomment the marked sections in
  sensors/temperature.py and the script will use real readings automatically.
"""

import json
import time
import datetime

from sensors.ph          import PHSensor
from sensors.tds         import TDSSensor
from sensors.turbidity   import TurbiditySensor
from sensors.temperature import TemperatureSensor   # returns None until DS18B20 connected

# ── Configuration ─────────────────────────────────────────────────────────────

# Set to False to print to terminal only (safe for testing without AWS setup).
# Set to True when you have AWS IoT Core configured and certs in place.
CLOUD_ENABLED = False

# How often to take a reading (seconds).
READ_INTERVAL = 10

# ── Alert thresholds (for terminal colour coding) ──────────────────────────────
THRESHOLDS = {
    "ph":          (6.5, 8.5),    # (min, max) — alert outside this range
    "temperature": (None, 30.0),  # alert if above 30 °C; no lower limit
    "tds":         (None, 500.0), # alert if above 500 mg/L
    "turbidity":   (None, 4.0),   # alert if above 4 NTU
}


# ── MQTT cloud publishing ─────────────────────────────────────────────────────
# This entire section is skipped when CLOUD_ENABLED = False.
# All cloud-related imports and setup are inside this block so the script
# runs cleanly without paho-mqtt installed when not needed.

mqtt_client = None

if CLOUD_ENABLED:
    import paho.mqtt.client as mqtt
    import ssl
    import config as cfg

    def _on_connect(client, userdata, flags, rc):
        if rc == 0:
            print("[MQTT] Connected to AWS IoT Core.")
        else:
            print(f"[MQTT] Connection failed with code {rc}.")

    def _on_publish(client, userdata, mid):
        print(f"[MQTT] Message {mid} delivered to broker.")

    def _on_disconnect(client, userdata, rc):
        if rc != 0:
            print(f"[MQTT] Unexpected disconnection (code {rc}). Will attempt reconnect.")

    mqtt_client = mqtt.Client(client_id=cfg.DEVICE_ID)
    mqtt_client.on_connect    = _on_connect
    mqtt_client.on_publish    = _on_publish
    mqtt_client.on_disconnect = _on_disconnect

    # TLS mutual authentication with AWS X.509 certificates
    mqtt_client.tls_set(
        ca_certs    = cfg.MQTT_CA_PATH,
        certfile    = cfg.MQTT_CERT_PATH,
        keyfile     = cfg.MQTT_KEY_PATH,
        tls_version = ssl.PROTOCOL_TLSv1_2,
    )

    print(f"[MQTT] Connecting to {cfg.MQTT_ENDPOINT}:{cfg.MQTT_PORT} ...")
    mqtt_client.connect(cfg.MQTT_ENDPOINT, cfg.MQTT_PORT, keepalive=60)
    mqtt_client.loop_start()   # non-blocking background network thread


# ── Helper: terminal formatting ───────────────────────────────────────────────

RESET  = "\033[0m"
RED    = "\033[91m"
GREEN  = "\033[92m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
BOLD   = "\033[1m"


def _status(value, param):
    """
    Return a coloured status string for terminal display.
    GREEN = within safe range. RED = alert. YELLOW = no reading.

    Args:
        value: the sensor reading (float or None)
        param: key in THRESHOLDS dict

    Returns:
        Tuple of (formatted_value_string, status_label_string)
    """
    if value is None:
        return f"{YELLOW}N/A{RESET}", f"{YELLOW}NO SENSOR{RESET}"

    lo, hi = THRESHOLDS.get(param, (None, None))
    out_of_range = (lo is not None and value < lo) or \
                   (hi is not None and value > hi)

    colour = RED if out_of_range else GREEN
    label  = f"{RED}⚠ ALERT{RESET}" if out_of_range else f"{GREEN}OK{RESET}"

    return f"{colour}{value:.2f}{RESET}", label


def _print_reading(reading: dict) -> None:
    """
    Print a formatted sensor reading to the terminal.
    Includes colour-coded status for each parameter.

    Args:
        reading: dict with keys ph, temperature, tds, turbidity, timestamp
    """
    ts = reading["timestamp"]

    ph_v,   ph_s   = _status(reading["ph"],          "ph")
    tmp_v,  tmp_s  = _status(reading["temperature"], "temperature")
    tds_v,  tds_s  = _status(reading["tds"],         "tds")
    ntu_v,  ntu_s  = _status(reading["turbidity"],   "turbidity")

    print()
    print(f"  {BOLD}── Reading @ {ts} ──────────────────────────────{RESET}")
    print(f"  pH          : {ph_v:<20} {ph_s}")
    print(f"  Temperature : {tmp_v:<20} {tmp_s}  (DS18B20 not connected)")
    print(f"  TDS         : {tds_v:<20} mg/L   {tds_s}")
    print(f"  Turbidity   : {ntu_v:<20} NTU    {ntu_s}")

    if CLOUD_ENABLED:
        print(f"  {CYAN}↑ Publishing to AWS IoT Core...{RESET}")
    else:
        print(f"  {YELLOW}[Cloud disabled — terminal only]{RESET}")


def _publish(reading: dict) -> None:
    """
    Publish a reading to AWS IoT Core via MQTT.
    Skipped entirely when CLOUD_ENABLED = False.

    Args:
        reading: the sensor reading dict to publish as JSON
    """
    if not CLOUD_ENABLED or mqtt_client is None:
        return

    import config as cfg
    payload = json.dumps(reading)

    result = mqtt_client.publish(cfg.MQTT_TOPIC, payload, qos=1)

    if result.rc != 0:
        print(f"  [MQTT] Publish failed (rc={result.rc}). Check connection.")


# ── Sensor initialisation ─────────────────────────────────────────────────────

def _init_sensors():
    """
    Initialise all sensor objects. Prints a summary of what is available.
    Returns a dict of sensor instances.
    """
    print()
    print(f"  {BOLD}Initialising sensors...{RESET}")

    sensors = {}

    try:
        sensors["ph"] = PHSensor()
        print(f"  {GREEN}✓{RESET} pH sensor (ADS1115 A0)")
    except Exception as e:
        print(f"  {RED}✗{RESET} pH sensor failed to initialise: {e}")
        sensors["ph"] = None

    try:
        sensors["tds"] = TDSSensor()
        print(f"  {GREEN}✓{RESET} TDS sensor (ADS1115 A1)")
    except Exception as e:
        print(f"  {RED}✗{RESET} TDS sensor failed to initialise: {e}")
        sensors["tds"] = None

    try:
        sensors["turbidity"] = TurbiditySensor()
        print(f"  {GREEN}✓{RESET} Turbidity sensor (ADS1115 A2)")
    except Exception as e:
        print(f"  {RED}✗{RESET} Turbidity sensor failed to initialise: {e}")
        sensors["turbidity"] = None

    # DS18B20 temperature sensor — always initialised but returns None
    # until the hardware is connected and temperature.py is uncommented.
    sensors["temperature"] = TemperatureSensor()
    print(f"  {YELLOW}○{RESET} Temperature sensor (DS18B20) — not connected, skipped")

    return sensors


# ── Main loop ─────────────────────────────────────────────────────────────────

def main():
    print()
    print(f"{BOLD}{'═' * 60}{RESET}")
    print(f"{BOLD}  Water Quality Monitor — Raspberry Pi{RESET}")
    print(f"{'═' * 60}")
    print(f"  Cloud publishing : {'ENABLED (AWS IoT Core)' if CLOUD_ENABLED else 'DISABLED (terminal only)'}")
    print(f"  Read interval    : {READ_INTERVAL} seconds")
    print(f"  Stop             : Ctrl+C")

    sensors = _init_sensors()

    print()
    print(f"  {BOLD}Starting sensor loop...{RESET}")
    print(f"{'─' * 60}")

    reading_count = 0

    try:
        while True:
            reading_count += 1

            # ── Read all sensors ──────────────────────────────────────────────

            # Temperature first — used for TDS compensation.
            # Returns None when DS18B20 is not connected (normal for now).
            temperature = None
            if sensors["temperature"]:
                temperature = sensors["temperature"].read()

            # pH
            ph = sensors["ph"].read() if sensors["ph"] else None

            # TDS — pass temperature for compensation; falls back to 25 °C internally
            tds = None
            if sensors["tds"]:
                # If temperature is None, TDSSensor uses its default of 25 °C
                tds = sensors["tds"].read(temperature=temperature if temperature is not None else 25.0)

            # Turbidity
            turbidity = sensors["turbidity"].read() if sensors["turbidity"] else None

            # ── Build payload ─────────────────────────────────────────────────
            timestamp = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")

            reading = {
                "ph":          round(ph,          2) if ph          is not None else None,
                "temperature": round(temperature, 2) if temperature is not None else None,
                "tds":         round(tds,         2) if tds         is not None else None,
                "turbidity":   round(turbidity,   2) if turbidity   is not None else None,
                "timestamp":   timestamp,
            }

            # ── Display in terminal ───────────────────────────────────────────
            _print_reading(reading)

            # ── Publish to cloud (if enabled) ─────────────────────────────────
            _publish(reading)

            # ── Wait for next reading ─────────────────────────────────────────
            time.sleep(READ_INTERVAL)

    except KeyboardInterrupt:
        print()
        print(f"  {BOLD}Stopped by user after {reading_count} reading(s).{RESET}")

    finally:
        # Clean up MQTT connection gracefully
        if CLOUD_ENABLED and mqtt_client is not None:
            mqtt_client.loop_stop()
            mqtt_client.disconnect()
            print("  [MQTT] Disconnected cleanly.")

        print()


if __name__ == "__main__":
    main()
