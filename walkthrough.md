# Water Quality Monitor — Django Backend Walkthrough

## What was built

The Django backend is now complete and tested locally. It consists of:

| Component | File | Purpose |
|---|---|---|
| **SensorReading model** | `monitor/models.py` | Stores readings (pH, temp, TDS, turbidity, source, timestamp) |
| **DRF serializer** | `monitor/serializers.py` | Validates + serializes sensor data |
| **API key auth** | `monitor/authentication.py` | Bearer token check for the POST endpoint |
| **API views** | `monitor/views.py` | POST create, GET latest, GET history |
| **Dashboard** | `monitor/templates/monitor/dashboard.html` | Dark glassmorphism UI with Chart.js |
| **Django settings** | `watermonitor/settings.py` | Env-driven config, SQLite local / PostgreSQL prod |
| **Dockerfile** | `Dockerfile` | For Render free tier deployment |

### API Endpoints

| Method | URL | Auth | Purpose |
|---|---|---|---|
| `POST` | `/api/readings/` | `Bearer <key>` | Lambda saves a new reading |
| `GET` | `/api/readings/latest/` | Public | Dashboard fetches current values |
| `GET` | `/api/readings/history/?n=60` | Public | Dashboard fetches chart data |
| `GET` | `/dashboard/` | Public | Serves the live dashboard HTML |

### Local test results

All endpoints verified working:
- ✅ `POST /api/readings/` → 201 Created
- ✅ `GET /api/readings/latest/` → 200 OK (returns most recent reading)
- ✅ `GET /api/readings/history/?n=5` → 200 OK (returns 5 readings oldest→newest)
- ✅ `GET /dashboard/` → 200 OK (serves full HTML page)
- ✅ Dashboard auto-refresh confirmed in server logs (requests every 10s)

---

## Running Locally

```bash
cd backend

# 1. Create virtual environment (optional but recommended)
python -m venv venv
venv\Scripts\activate    # Windows
# source venv/bin/activate  # Linux/Mac

# 2. Install dependencies
pip install -r requirements.txt

# 3. Create .env from template
cp .env.example .env
# Edit .env if needed (defaults work for local dev)

# 4. Run migrations
python manage.py migrate

# 5. Start dev server
python manage.py runserver 8000

# 6. Open dashboard
# http://127.0.0.1:8000/dashboard/
```

### Injecting test data locally

```powershell
# PowerShell
$h = @{"Authorization"="Bearer dev-api-key"}
Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/readings/" `
  -Method POST -ContentType "application/json" -Headers $h `
  -Body '{"ph": 7.2, "temperature": null, "tds": 340.5, "turbidity": 1.8}'
```

---

## Deploying to Render (Docker — Free Tier)

> [!IMPORTANT]
> Render free tier only supports deployment via **Dockerfile**. The Dockerfile is already created at `backend/Dockerfile`.

### Step 1 — Push code to GitHub

Make sure the `backend/` directory is committed and pushed:

```bash
git add backend/
git commit -m "Add Django backend with REST API and dashboard"
git push origin main
```

> [!CAUTION]
> Never commit `backend/.env` — it contains your API key. It's already in `.gitignore`.

### Step 2 — Create a PostgreSQL database on Render

1. Go to [Render Dashboard](https://dashboard.render.com/)
2. Click **New +** → **PostgreSQL**
3. Fill in:
   - **Name:** `water-monitor-db`
   - **Region:** Choose the closest to you (e.g. Frankfurt for EU)
   - **Plan:** Free
4. Click **Create Database**
5. Wait for it to spin up, then copy the **Internal Database URL** (starts with `postgres://...`)
   - You'll need this in Step 4

### Step 3 — Create a Web Service on Render

1. In Render Dashboard, click **New +** → **Web Service**
2. Connect your GitHub repository
3. Fill in:
   - **Name:** `water-monitor` (or any name you like)
   - **Region:** Same as your database
   - **Branch:** `main`
   - **Root Directory:** `backend`
   - **Runtime:** **Docker**
4. Render will auto-detect the `Dockerfile` in the `backend/` directory
5. Click **Create Web Service**

### Step 4 — Set environment variables

In your Render Web Service settings, go to **Environment** and add:

| Key | Value | Notes |
|---|---|---|
| `SECRET_KEY` | *(generate a strong random key)* | Run: `python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"` |
| `DEBUG` | `False` | Always False in production |
| `ALLOWED_HOSTS` | `water-monitor.onrender.com` | Replace with your actual Render subdomain |
| `DATABASE_URL` | `postgres://user:pass@host:5432/dbname` | Paste the **Internal Database URL** from Step 2 |
| `DJANGO_API_KEY` | *(generate a strong random key)* | This must match what you put in Lambda's `DJANGO_API_KEY` |
| `DEVICE_SOURCE` | `pi-01` | Default device identifier |

> [!TIP]
> Generate a strong API key with: `python -c "import secrets; print(secrets.token_urlsafe(32))"`

### Step 5 — Deploy

1. Render will automatically build and deploy from the Dockerfile
2. Watch the deploy logs — you should see:
   ```
   Running migrations...
   Collecting static files...
   Starting gunicorn...
   ```
3. Once deployed, your dashboard is at: `https://water-monitor.onrender.com/dashboard/`

> [!WARNING]
> **First deploy needs manual migration.** After the first deploy, go to your Render Web Service → **Shell** tab and run:
> ```bash
> python manage.py migrate
> ```
> This creates the database tables. Subsequent deploys won't need this unless you change models.

### Step 6 — Verify deployment

Open these URLs in your browser (replace with your actual Render domain):

1. `https://water-monitor.onrender.com/dashboard/` — should show the dark dashboard (no data yet)
2. Test POST from your terminal:

```powershell
$h = @{"Authorization"="Bearer YOUR_API_KEY_HERE"}
Invoke-RestMethod -Uri "https://water-monitor.onrender.com/api/readings/" `
  -Method POST -ContentType "application/json" -Headers $h `
  -Body '{"ph": 7.2, "temperature": null, "tds": 340.5, "turbidity": 1.8}'
```

3. Refresh the dashboard — you should see the reading appear

---

## Connecting Lambda to the Deployed Backend

Once Render is deployed and verified, update **two values** in `lambda/handler.py`:

```python
# lambda/handler.py — update these lines:
DJANGO_API_URL = "https://water-monitor.onrender.com/api/readings/"
DJANGO_API_KEY = "your-actual-api-key-from-render-env"
```

Then redeploy the Lambda function on AWS (paste updated code in the Lambda console).

### Full system flow after connection

```
Pi sensors → MQTT → AWS IoT Core → Lambda → POST to Render Django → PostgreSQL
                                                                         ↓
                                              Browser ← Dashboard ← Django reads DB
```

> [!IMPORTANT]
> **Warm up Render before demos!** Free tier spins down after 15 minutes of inactivity. Open the dashboard URL ~1 minute before presenting to wake it up.

---

## Files created/modified

### New files (`backend/`)
- `manage.py` — Django CLI entry point
- `requirements.txt` — Python dependencies
- `Dockerfile` — Render Docker deployment
- `.env.example` — Environment variable template
- `.env` — Local dev environment (gitignored)
- `watermonitor/__init__.py`, `settings.py`, `urls.py`, `wsgi.py`, `asgi.py`
- `monitor/__init__.py`, `apps.py`, `models.py`, `serializers.py`, `authentication.py`, `views.py`, `urls.py`, `admin.py`
- `monitor/templates/monitor/dashboard.html`
- `monitor/migrations/0001_initial.py` (auto-generated)

### Modified files
- `PROJECT_CONTEXT.md` — Fixed ADS1115 wiring table to match actual code (A0=TDS, A1=Turbidity, A3=pH), added note about `ph.py` channel bug

---

## Known issue to fix

> [!WARNING]
> **`sensors/ph.py` line 95** uses `ADS.P0` but the pH sensor is physically wired to **A3** (matching `callibrate_ph.py` which uses `ADS.P3`). Change `ADS.P0` to `ADS.P3` in `ph.py` before the next hardware test.
