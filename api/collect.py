"""Solar Arena v7 - Production only, Kiosk API"""
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from datetime import date
import json, os, requests

def env(key, default=""):
    return os.environ.get(key, default)

class Storage:
    def __init__(self):
        self.url, self.token = env("KV_REST_API_URL"), env("KV_REST_API_TOKEN")
    def load(self):
        r = requests.post(self.url, headers={"Authorization": f"Bearer {self.token}"}, json=["GET", "solar_arena_data"], timeout=10)
        return json.loads(r.json().get("result") or "{}")
    def save(self, data):
        requests.post(self.url, headers={"Authorization": f"Bearer {self.token}"}, json=["SET", "solar_arena_data", json.dumps(data)], timeout=10)

def fetch_matko():
    ha_url = env("HA_URL").rstrip("/")
    ha_token = env("HA_TOKEN")
    if not ha_token: return 0.0
    try:
        eid = env("HA_SENSOR_PRODUCTION", "sensor.inverter_today_production")
        r = requests.get(f"{ha_url}/api/states/{eid}", headers={"Authorization": f"Bearer {ha_token}"}, timeout=10)
        val = r.json().get("state", "0")
        prod = float(val) if val not in ("unavailable", "unknown", "") else 0.0
        print(f"Matko: {prod} kWh")
        return round(prod, 2)
    except Exception as e:
        print(f"Matko error: {e}"); return 0.0

def fetch_zocho():
    kk = env("FS_KIOSK_KEY", "nhxMmrcO5vHyiy0BMda3C13juu1dJumu")
    host = env("FS_KIOSK_HOST", "https://uni003eu5.fusionsolar.huawei.com")
    try:
        r = requests.get(f"{host}/rest/pvms/web/kiosk/v1/station-kiosk-file?kk={kk}", timeout=15)
        data_str = r.json().get("data", "{}")
        data = json.loads(data_str.replace("&quot;", '"')) if isinstance(data_str, str) else data_str
        prod = round(float(data.get("realKpi", {}).get("dailyEnergy", 0)), 2)
        print(f"Zocho: {prod} kWh")
        return prod
    except Exception as e:
        print(f"Zocho error: {e}"); return 0.0

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            q = parse_qs(urlparse(self.path).query)
            d = q.get("date", [None])[0]
            dk = d if d else date.today().isoformat()
            print(f"=== {dk} ===")
            mp, zp = fetch_matko(), fetch_zocho()
            mk, zk = float(env("MATKO_KWP","7.95")), float(env("ZOCHO_KWP","6.16"))
            mn, zn = mp/mk if mk else 0, zp/zk if zk else 0
            w = "Matko" if mn>zn else "Zocho" if zn>mn else "Remis"
            storage = Storage()
            data = storage.load()
            data[dk] = {"matko": {"production": mp}, "sasiad": {"production": zp}}
            storage.save(data)
            self.send_response(200)
            self.send_header("Content-type","application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"ok":True,"date":dk,"matko":mp,"zocho":zp,"matko_kwp":round(mn,2),"zocho_kwp":round(zn,2),"winner":w,"days":len(data)}).encode())
        except Exception as e:
            self.send_response(500)
            self.send_header("Content-type","application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"ok":False,"error":str(e)}).encode())
