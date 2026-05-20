"""
config.example.py
-----------------
Copy this file to config.py and fill in your values.
config.py is gitignored — never commit it.

  cp config.example.py config.py

Then run calibrate_ph.py which will fill in the PH_VOLTAGE_* values automatically.
The MQTT settings are only needed when CLOUD_ENABLED = True in main.py.
"""

# ── pH calibration (filled by calibrate_ph.py) ───────────────────────────────
PH_VOLTAGE_AT_7 = 0.0    # Replace with your measured voltage at pH 7.0
PH_VOLTAGE_AT_4 = 0.0    # Replace with your measured voltage at pH 4.0

# ── AWS IoT Core MQTT settings ────────────────────────────────────────────────
# Found in: AWS Console → IoT Core → Settings → Device data endpoint
MQTT_ENDPOINT = "REPLACE_WITH_YOUR_IOT_CORE_ENDPOINT"
# e.g. "xxxxxx-ats.iot.eu-west-1.amazonaws.com"

MQTT_PORT = 8883   # Standard MQTT over TLS — do not change

MQTT_TOPIC = "watermonitor/readings"

# Paths to the three certificate files downloaded from AWS IoT Core
MQTT_CERT_PATH    = "certs/device-certificate.pem.crt"
MQTT_KEY_PATH     = "certs/private.pem.key"
MQTT_CA_PATH      = "certs/AmazonRootCA1.pem"

# A short identifier for this device — appears in database records
DEVICE_ID = "pi-01"
