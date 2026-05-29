# Water Quality Monitoring System — Project Context

> Complete technical reference for the project architecture, data contracts, ML pipeline,
> and deployment configuration. Intended as a standalone briefing document — reading this
> file should give a developer (or an LLM) everything needed to understand, modify, or
> debug any part of the system.

---

## 1. Project Summary

A university IoT system that monitors water quality in real time. Physical sensors on a
Raspberry Pi measure pH, TDS, turbidity, and temperature. Readings are published to
AWS IoT Core over MQTT, processed by a Lambda function, stored in a Django/PostgreSQL
backend, and displayed on a live web dashboard. An LSTM Autoencoder runs server-side
anomaly detection, and a two-layer alerting system (threshold + ML gating) sends
email/SMS notifications through Amazon SNS.

---

## 2. Sensors

| Sensor | Model | Measures | Unit | Interface | Safe Range | Alert Threshold |
|---|---|---|---|---|---|---|
| pH | DFRobot SEN0161 | Acidity / alkalinity | pH 0–14 | ADS1115 ch A3 | 6.5 – 8.5 | < 6.5 or > 8.5 |
| TDS | DFRobot SEN0244 | Total dissolved solids | mg/L | ADS1115 ch A0 | < 500 | > 500 mg/L |
| Turbidity | DFRobot SEN0189 | Cloudiness / particles | NTU | ADS1115 ch A1 | < 4 | > 4 NTU |
| Temperature | DS18B20 | Water temperature | °C | GPIO4 (1-Wire) | 0 – 30 | > 30 °C |

**Notes:**
- Dissolved oxygen sensor was not available and is excluded from the project.
- The DS18B20 is owned but not always physically connected during development.
  When absent, the code handles `None` gracefully — TDS compensation falls back
  to 25 °C, and the JSON payload sends `"temperature": null`.
- The ADS1115 is a 16-bit I2C ADC (address 0x48) required because the Raspberry Pi
  has no built-in analog-to-digital converter.

### Sensor Wiring (ADS1115)

| ADS1115 Channel | Sensor | Notes |
|---|---|---|
| A0 | TDS (SEN0244) | Analog voltage output |
| A1 | Turbidity (SEN0189) | Through 10kΩ/10kΩ voltage divider |
| A3 | pH (SEN0161) | Analog voltage output |
| — | DS18B20 | GPIO4 (1-Wire bus), 4.7kΩ pull-up to 3.3V |

### Calibration

- **pH**: Two-point calibration with pH 4.0 and 7.0 buffer solutions.
  Formula: `ph = 7.0 + (v7 - voltage) * (7.0 - 4.0) / (v7 - v4)`.
  Run `pi/callibrate_ph.py` to measure and store `v7` and `v4` in `config.py`.
- **TDS**: Temperature-compensated using the DFRobot cubic formula.
  Compensation: `tds_compensated = tds_raw / (1 + 0.02 * (temperature - 25))`.
  Without DS18B20, assumes 25 °C (compensation factor = 1.0).
- **Turbidity**: Higher voltage = clearer water (inverse relationship).
  Uses linear interpolation between two calibration points (3.75V → 5 NTU, 3.28V → 500 NTU).
- **DS18B20**: Factory calibrated ±0.5 °C, no user calibration needed.

---

## 3. Edge Device (Raspberry Pi)

- **Hardware**: Raspberry Pi (any model with GPIO and WiFi)
- **Language**: Python 3
- **Key libraries**: `paho-mqtt`, `adafruit-blinka`, `adafruit-circuitpython-ads1x15`
- **Operation modes** (controlled by `CLOUD_ENABLED` flag in `main.py`):
  - `False` — terminal-only mode: reads sensors, prints colour-coded output, no cloud
  - `True` — cloud mode: same as above + publishes every reading to AWS IoT Core via MQTT
- **Read interval**: 10 seconds (configurable via `READ_INTERVAL`)

### MQTT Configuration

- Protocol: MQTT over TLS, port 8883
- Auth: X.509 mutual TLS (three certificate files in `pi/certs/`)
- Topic: `watermonitor/readings`
- QoS: 1 (at least once delivery)
- Endpoint: stored in `pi/config.py` as `MQTT_ENDPOINT`

### Certificate Files (never committed to Git)

```
pi/certs/
├── device-certificate.pem.crt    # From AWS IoT Core console
├── private.pem.key                # From AWS IoT Core console
└── AmazonRootCA1.pem              # From https://www.amazontrust.com/repository/
```

---

## 4. JSON Payload Format

Every message the Pi publishes to IoT Core follows this structure.
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

## 5. Cloud Architecture (AWS)

All AWS services are within free tier limits.

| Service | Free Tier Limit | Role |
|---|---|---|
| AWS IoT Core | 250K messages/month | MQTT broker; receives Pi data; triggers Lambda via Rules Engine |
| AWS Lambda | 1M invocations/month | Forwards readings to Django; runs threshold checks; sends SNS alerts |
| Amazon SNS | 1M publishes/month | Sends email/SMS notifications for water quality alerts |

### Data Flow

```
Raspberry Pi
    │
    │ MQTT/TLS (port 8883)
    ▼
AWS IoT Core (topic: watermonitor/readings)
    │
    │ Rules Engine trigger
    ▼
AWS Lambda (handler.py)
    │
    ├──── POST /api/readings/ ────▶ Django (Render)
    │                                  │
    │                                  ├─ Save to PostgreSQL
    │                                  ├─ Fetch last 30 readings
    │                                  ├─ Run ML inference (ONNX)
    │                                  ├─ Determine alert_level
    │                                  └─ Return response with ML fields
    │
    │◀── Response (is_anomaly, anomaly_score, ml_confidence) ───┘
    │
    ├─ Apply two-layer decision matrix
    │
    └──── SNS publish (if alert triggered) ────▶ Email / SMS
```

---

## 6. Lambda Function (`lambda/handler.py`)

The Lambda function performs three tasks on every invocation:

1. **Forward to Django**: POST the raw reading to `/api/readings/`.
   Django saves it, runs ML inference, and returns ML fields in the response.

2. **Extract ML result**: Parse `is_anomaly`, `anomaly_score`, and `ml_confidence`
   from Django's response (with fallback to GET `/api/readings/latest/`).

3. **Two-layer alerting**: Apply the decision matrix to determine whether to send an
   SNS notification, and at what severity level.

### Two-Layer Decision Matrix

| Threshold Breach | ML Anomaly | ML Confidence | Action |
|:---:|:---:|:---:|---|
| Yes | Yes | high / medium | CRITICAL alert via SNS |
| Yes | Yes | low | WARNING alert via SNS |
| Yes | No | any | Suppressed — likely a noise spike |
| No | Yes | high | Soft alert via SNS (pattern deviation) |
| No | Yes | medium / low | Logged only, no notification |
| No | No | any | All normal |

Key design decisions:
- Threshold breaches alone do **not** trigger alerts. The ML model acts as a gatekeeper
  to suppress false alarms from noise spikes.
- The ML model **can** trigger alerts even without a threshold breach (high-confidence
  anomaly detection catches subtle multi-parameter pattern deviations).

---

## 7. Backend (Django)

- **Framework**: Django 4.x + Django REST Framework
- **Database**: PostgreSQL (hosted on Render free tier)
- **Hosting**: Render free tier (Docker web service)
- **Public URL**: `https://water-monitor-oodh.onrender.com`
- **Static files**: WhiteNoise middleware

### REST API Endpoints

| Method | Endpoint | Auth | Purpose |
|---|---|---|---|
| POST | `/api/readings/` | API key (Bearer header) | Save reading + run ML inference + set alert level |
| GET | `/api/readings/latest/` | Public | Most recent reading as JSON |
| GET | `/api/readings/history/?n=60` | Public | Last N readings (oldest → newest) for charts |
| GET | `/api/readings/anomalies/` | Public | Last 20 ML-flagged anomalous readings |
| GET | `/api/readings/alerts/` | Public | Last 20 readings with non-null alert_level |
| GET | `/dashboard/` | Public | HTML dashboard page |
| GET | `/ml-debug/` | Public | Diagnostic endpoint (model status, DB columns) |

### SensorReading Model Fields

**Sensor data:**

| Field | Type | Notes |
|---|---|---|
| id | AutoField | Primary key |
| timestamp | DateTimeField | Auto-set on save (UTC), indexed |
| ph | FloatField | Nullable |
| temperature | FloatField | Nullable |
| tds | FloatField | Nullable |
| turbidity | FloatField | Nullable |
| source | CharField(50) | Device identifier, default "pi-01" |

**ML anomaly detection (populated by `predict_anomaly()`):**

| Field | Type | Notes |
|---|---|---|
| is_anomaly | BooleanField | Nullable. True if model flagged this reading |
| anomaly_score | FloatField | Nullable. Reconstruction error (higher = more anomalous) |
| ml_confidence | CharField(10) | Nullable. "high", "medium", or "low" |
| is_anomaly_ph | BooleanField | True if pH drove the anomaly |
| is_anomaly_temp | BooleanField | True if temperature drove the anomaly |
| is_anomaly_tds | BooleanField | True if TDS drove the anomaly |
| is_anomaly_turb | BooleanField | True if turbidity drove the anomaly |

**Smart alerting (determined by threshold + ML gating):**

| Field | Type | Notes |
|---|---|---|
| alert_level | CharField(10) | "CRITICAL", "WARNING", or "INFO". Null if normal |
| alert_sent | BooleanField | Whether SNS notification was sent (Lambda sets this) |

### ML Inference in Django (`monitor/ml_inference.py`)

The `predict_anomaly()` function is called by `CreateReadingView` on every POST:

1. Fetch the last 30 readings from the database (ordered oldest → newest)
2. Build a DataFrame and run `engineer_features()` to compute 20 features
3. Take the last 20 rows (= 1 LSTM sequence), scale with the saved `StandardScaler`
4. Run ONNX Runtime inference to reconstruct the sequence
5. Compute reconstruction error (MSE on the last timestep only)
6. Compare error to the saved threshold; determine confidence tier
7. Decompose error by feature to identify which sensor(s) drove the anomaly
8. Return `{is_anomaly, anomaly_score, confidence, anomalous_features}`

**Minimum readings required**: 25 (sequence length 20 + 5 for rolling window features).
Until 25 readings exist, `predict_anomaly()` returns `None` and alert_level falls back
to threshold-only logic determined by Django's `_determine_alert_level()`.

---

## 8. Machine Learning Pipeline (`ml/`)

### Architecture

LSTM Autoencoder trained on normal sensor data to learn "what normal looks like".
Anomalies are detected by high reconstruction error.

```
Encoder:  Input(20, 20) → LSTM(64) → LSTM(32) → Dense(16, ReLU)   [bottleneck]
Decoder:  RepeatVector(20) → LSTM(32) → LSTM(64) → TimeDistributed(Dense(20))
```

### Feature Engineering (`feature_engineering.py`)

20 features derived from 4 raw sensor values:

| Category | Count | Features |
|---|---|---|
| Raw sensors | 4 | ph, temperature, tds, turbidity |
| Deltas | 4 | Change from previous reading per sensor |
| Rolling mean (w=5) | 4 | 5-reading moving average per sensor |
| Rolling std (w=5) | 4 | 5-reading moving standard deviation per sensor |
| Cross-sensor ratios | 2 | ph/tds, tds/turbidity |
| Cyclical time | 2 | sin(hour), cos(hour) — 24-hour cycle |

### Training Pipeline (`train_model.py`)

1. Load `combined_data.csv` (synthetic + real data)
2. Engineer 20 features
3. Fit `StandardScaler` on **normal data only**
4. Create sliding-window sequences (length 20)
5. Label sequences by the **last** reading's anomaly flag
6. Split normal sequences 80/20 train/test
7. Train autoencoder on normal sequences only (100 epochs, batch 64)
8. Compute reconstruction error threshold (95th percentile of training errors)
9. Evaluate on test set (normal + anomaly sequences)
10. Export: Keras → ONNX, scaler → joblib, config → JSON

### Training Results

| Metric | Value |
|---|---|
| ROC AUC | 0.946 |
| Precision | 0.802 |
| Recall | 0.837 |
| F1 Score | 0.818 |
| Threshold | 0.8788 |

Confusion matrix (test set):
- True Negatives: 3642 | False Positives: 206
- False Negatives: 163 | True Positives: 837

### Confidence Tiering

| Error Range | Confidence |
|---|---|
| > 2× threshold | high |
| > 1.5× threshold | medium |
| ≤ 1.5× threshold | low |

### Artifacts (committed to repo)

| File | Purpose |
|---|---|
| `ml/model.onnx` | Trained LSTM Autoencoder in ONNX format |
| `ml/scaler.joblib` | StandardScaler fitted on normal training data |
| `ml/model_config.json` | Threshold value, feature column names, sequence length |

### Training Data

| File | Size | Description |
|---|---|---|
| `ml/data/mock_data.csv` | ~2 MB | 19,000 normal + 1,000 anomalous synthetic readings |
| `ml/data/real_data.csv` | ~13 KB | ~180 real readings exported from production DB |
| `ml/data/combined_data.csv` | ~2 MB | Mock + real data merged |

Anomaly types in synthetic data: pH spikes, TDS jumps, turbidity bursts,
correlated multi-sensor anomalies, gradual drift.

---

## 9. Frontend Dashboard

- **CSS framework**: Bootstrap 5 (loaded from CDN)
- **Charts**: Chart.js 4 (loaded from CDN)
- **Auto-refresh**: JavaScript `setInterval` + `fetch()` every 10 seconds
- No page reload — numbers and charts update silently
- Sensor cards with colour-coded status badges (green = safe, red = alert)
- Rolling line charts per sensor showing recent history
- Anomaly indicators showing ML-flagged readings and per-sensor attribution
- Alert log panel showing recent alert-level readings

---

## 10. Repository Structure

```
water-quality-IOT-project/
├── pi/                              # Raspberry Pi edge device
│   ├── main.py                      # Sensor loop + MQTT publish
│   ├── test_sensor.py               # Hardware test (TDS + turbidity + temp)
│   ├── callibrate_ph.py             # Interactive pH calibration
│   ├── config.py                    # Secrets (gitignored)
│   ├── config.example.py            # Config template
│   ├── sensors/                     # Sensor driver modules
│   │   ├── ph.py
│   │   ├── tds.py
│   │   ├── turbidity.py
│   │   └── temperature.py
│   └── certs/                       # AWS IoT X.509 certs (gitignored)
├── lambda/
│   └── handler.py                   # ML-gated alerting + Django forwarding
├── backend/                         # Django REST backend (Render)
│   ├── manage.py
│   ├── Dockerfile
│   ├── entrypoint.sh
│   ├── requirements.txt
│   ├── .env.example
│   ├── watermonitor/                # Django project settings
│   │   ├── settings.py
│   │   └── urls.py
│   └── monitor/                     # Main Django app
│       ├── models.py                # SensorReading (sensors + ML + alerts)
│       ├── serializers.py           # DRF serializer
│       ├── views.py                 # API views + dashboard
│       ├── ml_inference.py          # ONNX Runtime inference
│       ├── authentication.py        # API key auth
│       ├── urls.py
│       └── templates/
├── ml/                              # Machine learning pipeline
│   ├── train_model.py               # LSTM Autoencoder training
│   ├── feature_engineering.py       # 20-feature engineering module
│   ├── generate_mock_data.py        # Synthetic data generator
│   ├── export_real_data.py          # Export real readings from DB
│   ├── eda.py                       # Exploratory data analysis
│   ├── model.onnx                   # Trained model
│   ├── scaler.joblib                # Fitted scaler
│   ├── model_config.json            # Threshold + feature config
│   ├── data/                        # Training datasets
│   └── plots/                       # Evaluation plots
├── requirements.txt                 # Pi-side Python dependencies
├── config.example.py                # Pi config template
└── .gitignore
```

---

## 11. Environment Variables & Secrets

### Pi (`pi/config.py` — gitignored)

| Variable | Description |
|---|---|
| `PH_VOLTAGE_AT_7` | Calibrated voltage at pH 7.0 |
| `PH_VOLTAGE_AT_4` | Calibrated voltage at pH 4.0 |
| `MQTT_ENDPOINT` | AWS IoT Core device data endpoint |
| `MQTT_PORT` | 8883 (MQTT over TLS) |
| `MQTT_TOPIC` | `watermonitor/readings` |
| `MQTT_CERT_PATH` | Path to device certificate |
| `MQTT_KEY_PATH` | Path to private key |
| `MQTT_CA_PATH` | Path to AWS root CA |
| `DEVICE_ID` | Device identifier (e.g., "pi-01") |

### Backend (`backend/.env` — gitignored)

| Variable | Description |
|---|---|
| `SECRET_KEY` | Django secret key |
| `DEBUG` | `True` for development, `False` for production |
| `ALLOWED_HOSTS` | Comma-separated hostnames |
| `DATABASE_URL` | PostgreSQL connection string (empty = SQLite) |
| `DJANGO_API_KEY` | Bearer token for Lambda authentication |
| `DEVICE_SOURCE` | Default device identifier |

### Lambda (`handler.py` — hardcoded)

| Variable | Description |
|---|---|
| `DJANGO_API_URL` | Django POST endpoint URL |
| `DJANGO_API_KEY` | Must match backend's `DJANGO_API_KEY` |
| `SNS_TOPIC_ARN` | ARN of the SNS alert topic |

---

## 12. Deployment

### Backend (Render)

The backend is deployed as a Docker web service on Render free tier.

- **Build context**: Repository root (the Dockerfile references both `backend/` and `ml/`)
- **Dockerfile**: `backend/Dockerfile`
- **Process**: `entrypoint.sh` runs migrations then starts Gunicorn on port 8000
- **ML model**: Copied into the Docker image at `/app/ml/` so inference works server-side
- **Cold start**: Render free tier spins down after 15 minutes of inactivity.
  First request after spin-down takes ~30 seconds. Hit the dashboard URL before demos.

### Lambda

- Runtime: Python 3.11
- Handler: `handler.lambda_handler`
- Memory: 128 MB (default, sufficient)
- Timeout: 30 seconds (allows time for Django POST + response)
- IAM role needs: `sns:Publish` permission on the SNS topic ARN
- Trigger: AWS IoT Core rule on SQL topic `watermonitor/readings`

---

## 13. Key Operational Notes

1. **Never commit `pi/certs/`** — AWS private key exposure triggers automatic
   certificate revocation by AWS's credential scanner.
2. **Never commit `pi/config.py` or `backend/.env`** — contains API keys and secrets.
3. **Warm up Render before demos** — open the dashboard URL ~1 minute before presenting.
4. **Calibrate pH before each demo session** — buffer solutions drift; recalibrate
   if the sensor has been stored dry.
5. **TDS assumes 25 °C when DS18B20 is absent** — readings will be slightly off if water
   temperature differs significantly from 25 °C.
6. **MQTT topic must be consistent** — `watermonitor/readings` in Pi config, IoT Core rule,
   and Lambda function. A mismatch silently breaks the pipeline.
7. **ML cold start** — first 25 readings after a fresh database produce no ML results.
   Alert_level during this period is determined by `_determine_alert_level()` in Django,
   which treats missing ML data as "ML says no anomaly" (threshold breach alone → INFO).
