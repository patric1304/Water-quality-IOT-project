# Water Quality Monitoring System — Project Context

> This file is a complete briefing of the project architecture, decisions, and implementation plan.
> It is intended to be fed into an LLM (Claude) as context so you can ask questions, generate code,
> or continue development from exactly where the team left off.

---

## What this project is

A university IoT project that monitors water quality in real time using physical sensors connected
to a Raspberry Pi. The Pi reads sensor data, sends it to the cloud via WiFi, and a web dashboard
displays live readings and fires alerts if any parameter goes out of range.

---

## Sensors

| Sensor | Measures | Unit | Safe range | Alert if |
|---|---|---|---|---|
| pH | Acidity / alkalinity | pH scale 0–14 | 6.5 – 8.5 | < 6.5 or > 8.5 |
| Temperature | Water temperature | °C | 0 – 30 °C | > 30 °C |
| TDS | Total dissolved solids | mg/L | < 500 mg/L | > 500 mg/L |
| Turbidity | Cloudiness / particles | NTU | < 4 NTU | > 4 NTU |

**Note:** Dissolved oxygen sensor was not available and is excluded from the project.
Temperature sensor (DS18B20, 1-Wire) is owned but not always physically connected during development.
The codebase comments out DS18B20 sections so the rest of the scripts run without it.

---

## Edge device

- **Hardware:** Raspberry Pi (any model with GPIO and WiFi)
- **Connectivity:** WiFi only — no LoRa, no cellular, no Ethernet required
- **Language:** Python 3
- **Key libraries:** `paho-mqtt`, `RPi.GPIO`, `adafruit-blinka`, `adafruit-circuitpython-ads1x15`
- **ADC:** ADS1115 (4-channel, 16-bit) — required because Pi has no built-in ADC;
  pH, TDS, and turbidity sensors all output analog voltage
- **DS18B20** connects directly to GPIO via 1-Wire protocol (no ADC needed)

### Sensor wiring (ADS1115)

| ADS1115 channel | Sensor |
|---|---|
| A0 | pH sensor analog out |
| A1 | TDS sensor analog out |
| A2 | Turbidity sensor analog out |

DS18B20 data pin → GPIO4 (Pi physical pin 7), with 4.7kΩ pull-up resistor to 3.3V.

---

## JSON payload format (the contract between Pi and cloud)

Every message the Pi sends must have exactly this structure.
All numeric values are floats. Timestamp is ISO 8601 UTC.

```json
{
  "ph": 7.2,
  "temperature": 22.1,
  "tds": 340.5,
  "turbidity": 1.8,
  "timestamp": "2025-06-01T14:32:00Z"
}
```

When the DS18B20 is not connected, `temperature` is sent as `null`.

---

## Cloud architecture

### AWS services used (all free tier)

| Service | Free tier limit | Role in project |
|---|---|---|
| AWS IoT Core | 250K messages/month | MQTT broker; receives data from Pi; routes to Lambda |
| AWS Lambda | 1M invocations/month | Checks thresholds; forwards reading to Django; triggers SNS |
| Amazon SNS | 1M publishes/month | Sends email/SMS alert when a parameter is out of range |

### AWS IoT Core — how the Pi connects

- Protocol: **MQTT over TLS**, port **8883**
- Authentication: **X.509 certificates** (device certificate + private key + AWS root CA)
- MQTT topic: `watermonitor/readings`
- The Pi publishes one JSON message per reading to this topic
- IoT Core Rules Engine triggers the Lambda function on every message

### Certificate files (never commit these to Git)

```
pi/certs/
├── device-certificate.pem.crt   # Downloaded from AWS IoT Core console
├── private.pem.key               # Downloaded from AWS IoT Core console
└── AmazonRootCA1.pem             # Downloaded from https://www.amazontrust.com/repository/AmazonRootCA1.pem
```

All three files go in `pi/certs/` which is listed in `.gitignore`.

### AWS IoT Core endpoint

Found in: AWS Console → IoT Core → Settings → Device data endpoint.
Format: `xxxxxx-ats.iot.eu-west-1.amazonaws.com`
Store in `pi/config.py` as `MQTT_ENDPOINT` (config.py is also gitignored).

### Lambda function behaviour

Triggered by IoT Core every time a message arrives on `watermonitor/readings`.
The function does two things in order:
1. POSTs the reading to Django's REST API: `POST /api/readings/`
   with header `Authorization: Bearer <API_KEY>`
2. Checks each value against thresholds; if any is out of range,
   publishes to the SNS topic to trigger email/SMS

### SNS alert format

Subject: `[WATER ALERT] Parameter out of range`
Body lists which parameters triggered, their values, and the thresholds.

---

## Backend — Django

- **Framework:** Django 4.x + Django REST Framework
- **Database:** PostgreSQL (hosted on Render free tier)
- **Hosting:** Render free tier (web service + PostgreSQL)
- **Public URL format:** `https://your-app-name.onrender.com`

### Django app structure

```
backend/
├── watermonitor/
│   ├── settings.py
│   └── urls.py
├── monitor/
│   ├── models.py        # SensorReading model
│   ├── serializers.py   # DRF serializers
│   ├── views.py         # API views + dashboard view
│   ├── urls.py
│   └── templates/
│       └── dashboard.html
└── requirements.txt
```

### SensorReading model fields

| Field | Type | Notes |
|---|---|---|
| id | AutoField | Primary key |
| timestamp | DateTimeField | Auto-set on save (UTC) |
| ph | FloatField | nullable |
| temperature | FloatField | nullable |
| tds | FloatField | nullable |
| turbidity | FloatField | nullable |
| source | CharField | Device identifier string |

### REST API endpoints

| Method | Endpoint | Who calls it | Purpose |
|---|---|---|---|
| POST | `/api/readings/` | Lambda | Save a new reading; requires API key header |
| GET | `/api/readings/latest/` | Dashboard JS | Return most recent reading as JSON |
| GET | `/api/readings/history/?n=60` | Dashboard JS | Return last N readings for charts |
| GET | `/dashboard/` | Browser | Serve the HTML dashboard page |

---

## Frontend — Dashboard

- **CSS framework:** Bootstrap 5 (loaded from CDN — no build step)
- **Charts:** Chart.js 4 (loaded from CDN)
- **Auto-refresh:** plain JavaScript `setInterval` + `fetch()` every 10–15 seconds
- No visible page reload — numbers and charts update silently
- Four Bootstrap cards (one per sensor) with colour-coded status badges:
  green = within range, red = alert
- Four Chart.js line graphs (one per sensor) showing rolling history

---

## Repository structure (monorepo — single repo recommended)

```
water-monitor/
├── pi/
│   ├── config.py            # gitignored — contains endpoint, API key, calibration
│   ├── config.example.py    # committed — template with placeholder values
│   ├── calibrate_ph.py      # interactive pH calibration script
│   ├── sensors/
│   │   ├── ph.py
│   │   ├── tds.py
│   │   ├── turbidity.py
│   │   └── temperature.py   # DS18B20 — commented out when not connected
│   ├── main.py              # main sensor loop + MQTT publish
│   └── certs/               # gitignored — AWS certificates
├── lambda/
│   └── handler.py
├── backend/                 # Django project
├── docs/
│   └── WaterMonitor_Architecture_Guide.docx
├── PROJECT_CONTEXT.md       # this file
├── .gitignore
└── README.md
```

### .gitignore must include

```
pi/certs/
pi/config.py
.env
__pycache__/
*.pyc
.DS_Store
```

---

## Development approach for Pi scripts

The Pi scripts are written in two modes controlled by a flag at the top of `main.py`:

- `CLOUD_ENABLED = False` → readings print to terminal only; nothing is sent to AWS.
  Use this mode during local sensor testing and calibration.
- `CLOUD_ENABLED = True` → readings are published via MQTT to AWS IoT Core.
  Use this mode for full system demos.

The DS18B20 temperature sensor sections are **commented out** throughout all scripts.
Search for the comment `# DS18B20:` to find every place that needs to be uncommented
when the temperature sensor is physically connected.

---

## Calibration notes

### pH (two-point calibration)
1. Dip sensor in pH 7.0 buffer solution → record voltage as `v7`
2. Dip sensor in pH 4.0 buffer solution → record voltage as `v4`
3. Formula: `ph = 7.0 + (v7 - voltage) * (7.0 - 4.0) / (v7 - v4)`
4. Store `v7` and `v4` in `config.py`

### TDS (temperature-compensated)
- Raw voltage → raw TDS via sensor's voltage curve
- Compensation: `tds_compensated = tds_raw / (1 + 0.02 * (temperature - 25))`
- When temperature sensor is unavailable, assume 25 °C (compensation factor = 1.0)

### Turbidity
- Higher voltage = clearer water (inverse relationship)
- Calibrate zero point with distilled water
- Store offset in `config.py`

### Temperature (DS18B20)
- Factory calibrated, accurate to ±0.5 °C
- No user calibration required

---

## Key things to remember

1. **Never commit `pi/certs/`** — AWS private key exposure will get the certificates
   automatically revoked by AWS's credential scanner
2. **Never commit `pi/config.py`** — contains the MQTT endpoint and API keys
3. **Warm up Render before a demo** — free tier spins down after 15 min inactivity;
   open the dashboard URL ~1 minute before presenting
4. **Calibrate pH before every demo session** — buffer solutions drift; recalibrate
   if the sensor has been stored dry
5. **TDS assumes 25 °C when temperature sensor is absent** — readings will be slightly
   off if water temperature differs significantly; note this in the project report
6. **MQTT topic:** `watermonitor/readings` — must match in Pi script, IoT Core rule, and Lambda
