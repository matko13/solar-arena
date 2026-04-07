"""Solar Arena v10 - never overwrite good data with zeros"""
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from datetime import date
import json, os, requests

def env(key, default=""):
    return os.environ.get(key, default)

def redis_cmd(*args):
    url = env("KV_REST_API_URL")
    token = env("KV_REST_API_TOKEN")
    r = requests.post(url, headers={"Authorization": f"Bearer {token}"}, json=list(args), timeout=10)
    r.raise_for_status()
    return r.json().get("result")

def fetch_matko():
    try:
        r = requests.get(f"{env('HA_URL').rstrip('/')}/api/states/{env('HA_SENSOR_PRODUCTION', 'sensor.inverter_today_production')}", headers={"Authorization": f"Bearer {env('HA_TOKEN')}"}, timeout=10)
        val = r.json().get("state", "0")
        return round(float(val), 2) if val not in ("unavailable", "unknown", "") else 0.0
    except Exception as e:
        print(f"Matko error: {e}"); return 0.0

def fetch_zocho():
    try:
        kk = env("FS_KIOSK_KEY", "nhxMmrcO5vHyiy0BMda3C13juu1dJumu")
        r = requests.get(f"{env('FS_KIOSK_HOST', 'https://uni003eu5.fusionsolar.huawei.com')}/rest/pvms/web/kiosk/v1/station-kiosk-file?kk={kk}", timeout=15)
        data_str = r.json().get("data", "{}")
        data = json.loads(data_str.replace("&quot;", '"')) if isinstance(data_str, str) else data_str
        return round(float(data.get("realKpi", {}).get("dailyEnergy", 0)), 2)
    except Exception as e:
        print(f"Zocho error: {e}"); return 0.0

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            q = parse_qs(urlparse(self.path).query)
            dk = q.get("date", [None])[0] or date.today().isoformat()
            m, z = fetch_matko(), fetch_zocho()
            print(f"{dk}: Matko={m} Zocho={z}")
            existing_raw = redis_cmd("GET", f"sa:{dk}")
            existing = json.loads(existing_raw) if existing_raw else {}
            old_m = existing.get("matko", {}).get("production", 0)
            old_z = existi
cd ~/Downloads/solar-arena && cat > api/seed.py << 'EOF'
"""Seed data. GET /api/seed?dates=2026-04-04:23.1:18.96,2026-04-05:X:Y"""
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import json, os, requests

def redis_cmd(*args):
    url = os.environ.get("KV_REST_API_URL")
    token = os.environ.get("KV_REST_API_TOKEN")
    r = requests.post(url, headers={"Authorization": f"Bearer {token}"}, json=list(args), timeout=10)
    r.raise_for_status()
    return r.json().get("result")

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        q = parse_qs(urlparse(self.path).query)
        dates_str = q.get("dates", ["2026-04-04:23.1:18.96"])[0]
        results = {}
        for entry in dates_str.split(","):
            parts = entry.split(":")
            if len(parts) == 3:
                dt, matko, zocho = parts[0], float(parts[1]), float(parts[2])
                redis_cmd("SET", f"sa:{dt}", json.dumps({"matko": {"production": matko}, "sasiad": {"production": zocho}}))
                results[dt] = {"matko": matko, "zocho": zocho}
        keys = redis_cmd("KEYS", "sa:*") or []
        self.send_response(200)
        self.send_header("Content-type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"ok": True, "seeded": results, "all_keys": sorted(keys)}).encode())
