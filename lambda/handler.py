import json
import boto3
import urllib.request

# ── Configuration ─────────────────────────────────────────────────────
# Update DJANGO_API_URL and DJANGO_API_KEY after Django is deployed on Render
DJANGO_API_URL = "https://water-monitor-oodh.onrender.com/api/readings/"
DJANGO_API_KEY = "Vkd7G5rBmKonJP_N9zkT1Nk-hD0IytLjlTqmJHauWKg"
SNS_TOPIC_ARN  = "arn:aws:sns:eu-north-1:480493465332:water-monitor-alerts"

THRESHOLDS = {
    "ph":          (6.5, 8.5),
    "temperature": (None, 30.0),
    "tds":         (None, 500.0),
    "turbidity":   (None, 4.0),
}

sns = boto3.client("sns")


# ═════════════════════════════════════════════════════════════════════════════
# 1. THRESHOLD CHECKING
# ═════════════════════════════════════════════════════════════════════════════

def check_thresholds(reading):
    """Check if any sensor value exceeds safe thresholds."""
    alerts = []
    for param, (lo, hi) in THRESHOLDS.items():
        value = reading.get(param)
        if value is None:
            continue
        if lo is not None and value < lo:
            alerts.append(f"{param} is {value} (below minimum {lo})")
        if hi is not None and value > hi:
            alerts.append(f"{param} is {value} (above maximum {hi})")
    return alerts


# ═════════════════════════════════════════════════════════════════════════════
# 2. FORWARD TO DJANGO
# ═════════════════════════════════════════════════════════════════════════════

def forward_to_django(reading):
    """POST the reading to Django. Django saves it and runs ML inference."""
    data = json.dumps(reading).encode("utf-8")
    req  = urllib.request.Request(
        DJANGO_API_URL,
        data    = data,
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {DJANGO_API_KEY}",
        },
        method  = "POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = resp.read().decode("utf-8")
            print(f"Django response: {resp.status}")
            return json.loads(body)
    except Exception as e:
        print(f"Failed to forward to Django: {e}")
        return None


# ═════════════════════════════════════════════════════════════════════════════
# 3. GET ML RESULT FROM DJANGO
# ═════════════════════════════════════════════════════════════════════════════

def get_ml_result(django_response):
    """
    Extract ML anomaly result from Django's POST response.

    Django runs ML inference when it saves the reading and returns the
    result in the response body (is_anomaly, anomaly_score, ml_confidence).
    This avoids a second HTTP call — we already have the data.

    Falls back to fetching /api/readings/latest/ if the response doesn't
    contain ML fields (e.g., if Django version is outdated).
    """
    # ── Try to extract from the Django POST response directly ────────────
    if django_response:
        is_anomaly = django_response.get("is_anomaly")
        if is_anomaly is not None:
            return {
                "is_anomaly":    is_anomaly,
                "anomaly_score": django_response.get("anomaly_score", 0),
                "confidence":    django_response.get("ml_confidence", "low"),
            }

    # ── Fallback: fetch from /api/readings/latest/ ───────────────────────
    try:
        latest_url = DJANGO_API_URL.replace("readings/", "readings/latest/")
        req = urllib.request.Request(
            latest_url,
            headers={"Content-Type": "application/json"},
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
            return {
                "is_anomaly":    data.get("is_anomaly"),
                "anomaly_score": data.get("anomaly_score", 0),
                "confidence":    data.get("ml_confidence", "low"),
            }
    except Exception as e:
        print(f"Could not fetch ML result: {e}")
        return None


# ═════════════════════════════════════════════════════════════════════════════
# 4. ALERT SENDING
# ═════════════════════════════════════════════════════════════════════════════

def send_alert(alerts, reading, level="CRITICAL", score=None, confidence=None):
    """
    Send an SNS alert with severity level and ML context.

    Parameters
    ----------
    alerts : list[str]
        Threshold violation descriptions.
    reading : dict
        The raw sensor reading.
    level : str
        Alert severity: 'CRITICAL' or 'WARNING'.
    score : float or None
        ML anomaly score (reconstruction error).
    confidence : str or None
        ML confidence level: 'high', 'medium', or 'low'.
    """
    level_emoji = {"CRITICAL": "🚨", "WARNING": "⚠️"}.get(level, "ℹ️")

    message  = f"{level_emoji} WATER QUALITY {level} ALERT\n\n"
    message += "Threshold violations:\n"
    message += "\n".join(f"  • {a}" for a in alerts)

    if score is not None:
        message += f"\n\nML anomaly score: {score:.4f}"
    if confidence:
        message += f"\nML confidence: {confidence}"

    message += f"\n\nFull reading:\n{json.dumps(reading, indent=2)}"

    subject = f"[WATER {level}] Parameter out of range"

    sns.publish(
        TopicArn=SNS_TOPIC_ARN,
        Subject=subject,
        Message=message,
    )
    print(f"{level} alert sent: {alerts}")


def send_soft_alert(reading, ml_result):
    """
    Send a low-priority alert when the ML model detects an anomaly
    but no individual threshold was breached.

    This catches subtle pattern deviations — unusual combinations or
    temporal trends that rule-based checks miss entirely.
    """
    message  = "⚠️ WATER QUALITY PATTERN ALERT\n\n"
    message += "No individual threshold was breached, but the ML model detected\n"
    message += "an unusual pattern in the combined sensor readings.\n\n"
    message += f"Anomaly score: {ml_result.get('anomaly_score', 0):.4f}\n"
    message += f"Confidence: {ml_result.get('confidence', 'unknown')}\n\n"
    message += f"Reading:\n{json.dumps(reading, indent=2)}"

    sns.publish(
        TopicArn=SNS_TOPIC_ARN,
        Subject="[WATER INFO] Unusual sensor pattern detected",
        Message=message,
    )
    print(f"Soft alert sent (ML-only anomaly, no threshold breach)")


# ═════════════════════════════════════════════════════════════════════════════
# 5. MAIN HANDLER — ML-GATED ALERTING
# ═════════════════════════════════════════════════════════════════════════════

def lambda_handler(event, context):
    """
    AWS Lambda entry point — processes each incoming sensor reading.

    Two-Layer Alert Decision Matrix:
    ┌──────────────────┬────────────┬───────────────────┬─────────────────────────┐
    │ Threshold breach  │ ML anomaly │ ML confidence     │ Action                  │
    ├──────────────────┼────────────┼───────────────────┼─────────────────────────┤
    │ Yes              │ Yes        │ high / medium     │ 🚨 CRITICAL alert       │
    │ Yes              │ Yes        │ low               │ ⚠️ WARNING alert        │
    │ Yes              │ No         │ any               │ ℹ️ Logged only (noise)  │
    │ No               │ Yes        │ high              │ ⚠️ Soft alert           │
    │ No               │ Yes        │ medium / low      │ ℹ️ Logged only          │
    │ No               │ No         │ any               │ ✅ All normal            │
    └──────────────────┴────────────┴───────────────────┴─────────────────────────┘
    """
    print(f"Received: {json.dumps(event)}")

    # ── Step 1: Forward to Django (saves reading + runs ML inference) ─────
    django_response = forward_to_django(event)

    # ── Step 2: Get ML anomaly result ────────────────────────────────────
    ml_result = get_ml_result(django_response)

    is_anomaly = ml_result.get("is_anomaly", False) if ml_result else False
    confidence = ml_result.get("confidence", "low") if ml_result else "low"
    score      = ml_result.get("anomaly_score", 0) if ml_result else 0

    print(f"ML result: is_anomaly={is_anomaly}, confidence={confidence}, score={score}")

    # ── Step 3: Check thresholds ─────────────────────────────────────────
    threshold_alerts = check_thresholds(event)

    # ── Step 4: Two-layer decision ───────────────────────────────────────
    if threshold_alerts:
        if is_anomaly and confidence in ("high", "medium"):
            # Both layers agree — CRITICAL alert
            send_alert(threshold_alerts, event,
                       level="CRITICAL", score=score, confidence=confidence)

        elif is_anomaly and confidence == "low":
            # Borderline — WARNING
            send_alert(threshold_alerts, event,
                       level="WARNING", score=score, confidence=confidence)

        else:
            # Threshold breach but ML says normal — likely a noise spike
            print(f"[INFO] Threshold breach suppressed by ML: {threshold_alerts}")

    elif is_anomaly and confidence == "high":
        # ML flagged anomaly with no threshold breach — subtle pattern deviation
        send_soft_alert(event, ml_result)

    else:
        # Everything normal, or ML anomaly with low/medium confidence and no
        # threshold breach — just log, no notification
        if is_anomaly:
            print(f"[INFO] ML anomaly (confidence={confidence}) but no threshold "
                  f"breach — logged only")
        else:
            print("[OK] All readings normal")

    return {"statusCode": 200, "body": "OK"}