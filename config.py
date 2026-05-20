# config.py
# gitignored — never commit this file

# ── pH calibration ────────────────────────────────────────────────────
PH_VOLTAGE_AT_7 = 1.609437   # your measured value
PH_VOLTAGE_AT_4 = 2.067      # corrected stable value

# ── AWS IoT Core MQTT settings ────────────────────────────────────────
# Fill these in when you are ready to enable cloud publishing
MQTT_ENDPOINT = "REPLACE_WITH_YOUR_IOT_CORE_ENDPOINT"
MQTT_PORT     = 8883
MQTT_TOPIC    = "watermonitor/readings"

MQTT_CERT_PATH = "certs/device-certificate.pem.crt"
MQTT_KEY_PATH  = "certs/private.pem.key"
MQTT_CA_PATH   = "certs/AmazonRootCA1.pem"

# ── Device ID ─────────────────────────────────────────────────────────
DEVICE_ID = "pi-01"