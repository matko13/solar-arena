"""Solar Arena - Data Collector v7 (Kiosk API - no auth needed!)"""
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from datetime import datetime, date, timedelta
import json, os, requests

def env(key, default=""):
    return os.environ.get(key, default)

def empty():
    return {"production": 0.0, "consumption": 0.0, "export": 0.0, "selfConsumption": 0.0}

class Storage:
    def __init__(self):
        self.url = env("KV_REST_API_URL")
        self.token = env("KV_REST_API_TOKEN")
    def get_all(self):
        r = requests.post(self.url, headers={"Authorization": f"Bearer {self.token}"}, json=["GET", "solar_arena_data"], timeout=10)
        r.raise_for_status()
        result = r.json().get("result")
        return json.loads(result) if result else {}
    def save(self, date_key, matko, sasiad):
        data = self.get_all()
        data[date_key] = {"matko": matko, "sasiad": sasiad}
        requests.post(self.url, headers={"Authorization": f"Bearer {self.token}"}, json=["SET", "solar_arena_data", json.dumps(data)], timeout=10)
        return data

def fetch_ha(target_date):
    ha_url = env("HA_URL").rstrip("/")
    ha_token = env("HA_TOKEN")
    if not ha_token:
        print("HA_TOKEN not set"); return empty()
    headers = {"Authorization": f"Bearer {ha_token}"}
    sensors = {
        "production": env("HA_SENSOR_PRODUCTION", "sensor.inverter_today_production"),
        "consumption": env("HA_SENSOR_CONSUMPTION", "sensor.inverter_today_load_consumption"),
        "export": env("HA_SENSOR_EXPORT", "sensor.inverter_today_energy_export"),
    }
    raw = {}
    for field, eid in sensors.items():
        try:
            r = requests.get(f"{ha_url}/api/states/{eid}", headers=headers, timeout=10)
            r.raise_for_status()
            val = r.json().get("state", "0")
            raw[field] = float(val) if val not in ("unavailable", "unknown", "") else 0.0
            print(f"  HA {eid}: {raw[field]}")
        except Exception as e:
            print(f"  HA error {eid}: {e}"); raw[field] = 0.0
    s = {"production": round(raw.get("production", 0), 2), "consumption": round(raw.get("consumption", 0), 2),
         "export": round(raw.get("export", 0), 2), "selfConsumption": 0.0}
    if s["production"] > 0:
        s["selfConsumption"] = round((s["production"] - s["export"]) / s["production"] * 100, 1)
    return s

def fetch_kiosk():
    """Fetch Zocho data from FusionSolar Kiosk API - no auth needed!"""
    kk = env("FS_KIOSK_KEY", "nhxMmrcO5vHyiy0BMda3C13juu1dJumu")
    base = env("FS_KIOSK_HOST", "https://uni003eu5.fusionsolar.huawei.com")
    url = f"{base}/rest/pvms/web/kiosk/v1/station-kiosk-file?kk={kk}"
    s = empty()
    try:
        print(f"  Kiosk: fetching {url[:60]}...")
        r = requests.get(url, timeout=15)
        r.raise_for_status()
        resp = r.json()
        print(f"  Kiosk response keys: {list(resp.keys())}")
        # The 'data' field is a JSON string that needs to be parsed again
        data_str = resp.get("data", "{}")
        if isinstance(data_str, str):
            data = json.loads(data_str.replace("&quot;", '"'))
        else:
            data = data_str
        print(f"  Kiosk data keys: {list(data.keys()) if isinstance(data, dict) else type(data)}")
        # Extract realKpi
        kpi = data.get("realKpi", {})
        print(f"  Kiosk realKpi: {kpi}")
        s["production"] = round(float(kpi.get("dailyEnergy", 0)), 2)
        # Look for consumption/export in various places
        for section_name in ["socialContribution", "stationOverview", "powerFlow", data]:
            section = data.get(section_name, {}) if isinstance(section_name, str) else section_name
            if not isinstance(section, dict):
                continue
            print(f"  Kiosk {section_name if isinstance(section_name, str) else 'root'}: {list(section.keys())[:15]}")
            # Try to find consumption
            for ck in ["dailyConsumption", "daily_consumption", "dailyUsePower", "day_consumption", "totalUsePower"]:
                if ck in section and float(section[ck] or 0) > 0:
                    s["consumption"] = round(float(section[ck]), 2)
                    print(f"    consumption={s['consumption']} from {ck}")
            # Try to find export
            for ek in ["dailyExport", "daily_export", "dailyOngridPower", "day_ongrid_power", "dailyFeedinPower"]:
                if ek in section and float(section[ek] or 0) > 0:
                    s["export"] = round(float(section[ek]), 2)
                    print(f"    export={s['export']} from {ek}")
        if s["production"] > 0:
            s["selfConsumption"] = round((s["production"] - s["export"]) / s["production"] * 100, 1) if s["export"] > 0 else 100.0
        print(f"  Kiosk final: {s}")
    except Exception as e:
        print(f"  Kiosk error: {e}")
    return s

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            query = parse_qs(urlparse(self.path).query)
            date_str = query.get("date", [None])[0]
            target = date.fromisoformat(date_str) if date_str else date.today()
            dk = target.isoformat()
            print(f"=== Collecting {dk} ===")
            matko = fetch_ha(target)
            print(f"Matko: {matko}")
            zocho = fetch_kiosk()
            print(f"Zocho: {zocho}")
            storage = Storage()
            all_data = storage.save(dk, matko, zocho)
            mk, zk = float(env("MATKO_KWP","7.95")), float(env("ZOCHO_KWP","6.16"))
            mn = matko["production"]/mk if mk > 0 else 0
            zn = zocho["production"]/zk if zk > 0 else 0
            w = "Matko" if mn > zn else "Zocho" if zn > mn else "Remis"
            self.send_response(200)
            self.send_header("Content-type","application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"ok":True,"date":dk,"matko":matko,"zocho":zocho,"winner":w,"total_days":len(all_data)}).encode())
        except Exception as e:
            print(f"Error: {e}")
            self.send_response(500)
            self.send_header("Content-type","application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"ok":False,"error":str(e)}).encode())
