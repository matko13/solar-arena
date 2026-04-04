"""Solar Arena - Data Collector v6"""
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from datetime import datetime, date, timedelta
import json, os, requests

def get_env(key, default=""):
    return os.environ.get(key, default)

def empty_stats():
    return {"production": 0.0, "consumption": 0.0, "export": 0.0, "selfConsumption": 0.0}

class Storage:
    def __init__(self):
        self.url = get_env("KV_REST_API_URL")
        self.token = get_env("KV_REST_API_TOKEN")
    def get_all_data(self):
        r = requests.post(self.url, headers={"Authorization": f"Bearer {self.token}"}, json=["GET", "solar_arena_data"], timeout=10)
        r.raise_for_status()
        result = r.json().get("result")
        return json.loads(result) if result else {}
    def save_day(self, date_key, matko, sasiad):
        data = self.get_all_data()
        data[date_key] = {"matko": matko, "sasiad": sasiad}
        requests.post(self.url, headers={"Authorization": f"Bearer {self.token}"}, json=["SET", "solar_arena_data", json.dumps(data)], timeout=10)
        return data

def fetch_ha_data(target_date):
    ha_url = get_env("HA_URL").rstrip("/")
    ha_token = get_env("HA_TOKEN")
    if not ha_token:
        print("HA_TOKEN not set"); return empty_stats()
    headers = {"Authorization": f"Bearer {ha_token}"}
    sensors = {
        "production": get_env("HA_SENSOR_PRODUCTION", "sensor.inverter_today_production"),
        "consumption": get_env("HA_SENSOR_CONSUMPTION", "sensor.inverter_today_load_consumption"),
        "export": get_env("HA_SENSOR_EXPORT", "sensor.inverter_today_energy_export"),
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
    stats = {"production": round(raw.get("production", 0), 2), "consumption": round(raw.get("consumption", 0), 2),
             "export": round(raw.get("export", 0), 2), "selfConsumption": 0.0}
    if stats["production"] > 0:
        stats["selfConsumption"] = round((stats["production"] - stats["export"]) / stats["production"] * 100, 1)
    return stats

def fetch_fusionsolar_data(target_date):
    username = get_env("FS_USERNAME")
    password = get_env("FS_PASSWORD")
    subdomain = get_env("FS_SUBDOMAIN", "uni003eu5")
    if not username or not password:
        print("FS credentials not set"); return empty_stats()
    stats = empty_stats()
    try:
        from fusion_solar_py.client import FusionSolarClient
        print(f"FusionSolar: logging in as {username} on {subdomain}...")
        client = FusionSolarClient(username, password, huawei_subdomain=subdomain)
        print("FusionSolar: login OK")

        # Get production from PowerStatus
        try:
            power = client.get_power_status()
            if power:
                stats["production"] = round(float(getattr(power, 'energy_today_kwh', 0)), 2)
                print(f"  production={stats['production']} kWh")
        except Exception as e:
            print(f"  PowerStatus error: {e}")

        # Find the session object dynamically
        session = None
        for attr_name in ['_session', 'session', '_client', '_requests_session']:
            session = getattr(client, attr_name, None)
            if session and hasattr(session, 'get'):
                print(f"  Found session as client.{attr_name}")
                break
            session = None

        if session is None:
            all_attrs = [a for a in dir(client) if not a.startswith('__')]
            print(f"  No session found! Client attrs: {all_attrs}")
            # Try to find any requests.Session in the object
            for attr_name in all_attrs:
                obj = getattr(client, attr_name, None)
                if isinstance(obj, requests.Session):
                    session = obj
                    print(f"  Found Session as client.{attr_name}")
                    break

        if session is None:
            print("  Cannot access session - returning production only")
            if stats["production"] > 0:
                stats["selfConsumption"] = 100.0
            return stats

        # Use authenticated session for REST API
        base = f"https://{subdomain}.fusionsolar.huawei.com"
        xsrf = session.cookies.get("XSRF-TOKEN")
        if xsrf:
            session.headers["XSRF-TOKEN"] = xsrf

        # Get station code
        station_code = ""
        for list_url in [f"{base}/rest/pvms/web/station/v1/station/station-list",
                         f"https://eu5.fusionsolar.huawei.com/rest/pvms/web/station/v1/station/station-list"]:
            try:
                xsrf = session.cookies.get("XSRF-TOKEN")
                if xsrf: session.headers["XSRF-TOKEN"] = xsrf
                r = session.post(list_url, json={"curPage": 1, "pageSize": 10, "timeZone": 2}, timeout=15)
                print(f"  station-list: {r.status_code} {r.headers.get('content-type','')[:20]}")
                if r.status_code == 200 and "json" in r.headers.get("content-type", ""):
                    data = r.json()
                    sl = data.get("data", {})
                    slist = sl.get("list", []) if isinstance(sl, dict) else (sl if isinstance(sl, list) else [])
                    if slist:
                        station_code = slist[0].get("stationCode") or slist[0].get("dn", "")
                        print(f"  station={station_code}")
                        break
            except Exception as e:
                print(f"  station-list error: {e}")

        if not station_code:
            print("  No station, returning production only")
            if stats["production"] > 0: stats["selfConsumption"] = 100.0
            return stats

        ct = int(datetime.combine(target_date, datetime.min.time()).timestamp() * 1000)
        for domain in [base, "https://eu5.fusionsolar.huawei.com"]:
            for path in ["/rest/pvms/web/station/v1/overview/energy-balance",
                         "/rest/pvms/web/station/v1/overview/energy-flow"]:
                try:
                    xsrf = session.cookies.get("XSRF-TOKEN")
                    if xsrf: session.headers["XSRF-TOKEN"] = xsrf
                    r = session.post(f"{domain}{path}", json={"stationDn": station_code, "timeDim": 2, "queryTime": ct, "timeZone": 2}, timeout=15)
                    print(f"  {path[-20:]}: {r.status_code} {r.headers.get('content-type','')[:20]}")
                    if r.status_code == 200 and "json" in r.headers.get("content-type", ""):
                        d = r.json().get("data", {})
                        if isinstance(d, dict) and d:
                            print(f"    keys={list(d.keys())[:10]}")
                            for ck in ["usePower","use_power","selfUsePower","consumePower"]:
                                if d.get(ck) and float(d[ck] or 0) > 0:
                                    stats["consumption"] = round(float(d[ck]), 2); break
                            for ek in ["ongridPower","ongrid_power","feedinPower"]:
                                if d.get(ek) and float(d[ek] or 0) > 0:
                                    stats["export"] = round(float(d[ek]), 2); break
                            if stats["consumption"] > 0 or stats["export"] > 0:
                                print(f"    Got details: cons={stats['consumption']} exp={stats['export']}")
                                break
                except Exception as e:
                    print(f"  REST error: {e}")
            if stats["consumption"] > 0 or stats["export"] > 0: break

        if stats["production"] > 0:
            stats["selfConsumption"] = round((stats["production"] - stats["export"]) / stats["production"] * 100, 1) if stats["export"] > 0 else 100.0

    except Exception as e:
        print(f"FusionSolar fatal: {e}")
    return stats

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            query = parse_qs(urlparse(self.path).query)
            date_str = query.get("date", [None])[0]
            target = date.fromisoformat(date_str) if date_str else date.today()
            dk = target.isoformat()
            print(f"=== Collecting {dk} ===")
            matko = fetch_ha_data(target)
            print(f"Matko: {matko}")
            zocho = fetch_fusionsolar_data(target)
            print(f"Zocho: {zocho}")
            storage = Storage()
            all_data = storage.save_day(dk, matko, zocho)
            mk, zk = float(get_env("MATKO_KWP","7.95")), float(get_env("ZOCHO_KWP","6.16"))
            mn = matko["production"]/mk if mk>0 else 0
            zn = zocho["production"]/zk if zk>0 else 0
            w = "Matko" if mn>zn else "Zocho" if zn>mn else "Remis"
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
