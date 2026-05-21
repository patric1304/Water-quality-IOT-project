import json
import boto3
import urllib.request

# ── Configuration ─────────────────────────────────────────────────────
# Update DJANGO_API_URL and DJANGO_API_KEY after Django is deployed on Render
DJANGO_API_URL = "https://your-app.onrender.com/api/readings/"
DJANGO_API_KEY = "REPLACE_WITH_YOUR_API_KEY"
SNS_TOPIC_ARN  = "arn:aws:sns:eu-north-1:480493465332:water-monitor-alerts"

THRESHOLDS = {
    "ph":          (6.5, 8.5),
    "temperature": (None, 30.0),
    "tds":         (None, 500.0),
    "turbidity":   (None, 4.0),
}

sns = boto3.client("sns")

def check_thresholds(reading):
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

def forward_to_django(reading):
    data = json.dumps(reading).encode("utf-8")
    req  = urllib.request.Request(
        DJANGO_API_URL,
        data    = data,
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {DJANGO_API_KEY}"},
        method  = "POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            print(f"Django response: {resp.status}")
    except Exception as e:
        print(f"Failed to forward to Django: {e}")

def send_alert(alerts, reading):
    message  = "WATER QUALITY ALERT\n\n"
    message += "\n".join(f"  • {a}" for a in alerts)
    message += f"\n\nFull reading: {json.dumps(reading, indent=2)}"
    sns.publish(
        TopicArn = SNS_TOPIC_ARN,
        Subject  = "[WATER ALERT] Parameter out of range",
        Message  = message
    )
    print(f"Alert sent for: {alerts}")

def lambda_handler(event, context):
    print(f"Received: {json.dumps(event)}")
    forward_to_django(event)
    alerts = check_thresholds(event)
    if alerts:
        send_alert(alerts, event)
    return {"statusCode": 200, "body": "OK"}