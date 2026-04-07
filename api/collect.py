"""Solar Arena v9 - per-day Redis keys (no more data loss)"""
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
            # Save ONLY this day's key - never touches other days
            redis_cmd("SET", f"sa:{dk}", json.dumps({"matko": {"production": m}, "sasiad": {"production": z}}))
            # Get all days for response
            keys = redis_cmd("KEYS", "sa:*") or []
            days = len(keys)
            mk, zk = float(env("MATKO_KWP","7.95")), float(env("ZOCHO_KWP","6.16"))
            mn, zn = m/mk if mk else 0, z/zk if zk else 0
            diff = abs(mn-zn)
            pts = 3 if diff>0.7 else 2 if diff>0.3 else 1 if diff>0 else 0
            w = "Matko" if mn>zn else "Zocho" if zn>mn else "Remis"
            self.send_response(200)
            self.send_header("Content-type","application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"ok":True,"date":dk,"matko":m,"zocho":z,"mkwp":round(mn,2),"zkwp":round(zn,2),"pts":pts,"winner":w,"days":days}).encode())
        except Exception as e:
            print(f"Error: {e}")
            self.send_response(500)
            self.send_header("Content-type","application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"ok":False,"error":str(e)}).encode())
