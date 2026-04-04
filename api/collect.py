"""
Solar Arena - Data Collector (Vercel Serverless Function)
Triggered daily by Vercel Cron at 23:55 CET.
"""

from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from datetime import datetime, date, timedelta
import json
import os
import requests


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
        r = requests.post(self.url, headers={"Authorization": f"Bearer {self.token}"}, json=["SET", "solar_arena_data", json.dumps(data)], timeout=10)
        r.raise_for_status()
        return data


def fetch_ha_data(target_date):
    ha_url = get_env("HA_URL").rstrip("/")
    ha_token = get_env("HA_TOKEN")
    if not ha_token:
        print("HA_TOKEN not set")
        return empty_stats()

    headers = {"Authorization": f"Bearer {ha_token}", "Content-Type": "application/json"}
    sensors = {
        "production": get_env("HA_SENSOR_PRODUCTION", "sensor.inverter_today_production"),
        "consumption": get_env("HA_SENSOR_CONSUMPTION", "sensor.inverter_today_load_consumption"),
        "export": get_env("HA_SENSOR_EXPORT", "sensor.inverter_today_energy_export"),
    }

    raw = {}
    for field, entity_id in sensors.items():
        try:
            r = requests.get(f"{ha_url}/api/states/{entity_id}", headers=headers, timeout=10)
            r.raise_for_status()
            val = r.json().get("state", "0")
            raw[field] = float(val) if val not in ("unavailable", "unknown", "") else 0.0
            print(f"  HA {entity_id}: {raw[field]}")
        except Exception as e:
            print(f"  HA error {entity_id}: {e}")
            raw[field] = 0.0

    stats = {
        "production": round(raw.get("production", 0), 2),
        "consumption": round(raw.get("consumption", 0), 2),
        "export": round(raw.get("export", 0), 2),
        "selfConsumption": 0.0,
    }
    if stats["production"] > 0:
        stats["selfConsumption"] = round(
            (stats["production"] - stats["export"]) / stats["production"] * 100, 1
        )
    return stats


def fetch_fusionsolar_data(target_date):
    username = get_env("FS_USERNAME")
    password = get_env("FS_PASSWORD")
    subdomain = get_env("FS_SUBDOMAIN", "uni003eu5")

    if not username or not password:
        print("FS credentials not set")
        return empty_stats()

    stats = empty_stats()

    try:
        from fusion_solar_py.client import FusionSolarClient

        print(f"FusionSolar: logging in as {username} on {subdomain}...")
        client = FusionSolarClient(username, password, huawei_subdomain=subdomain)
        print("FusionSolar: login OK")

        # 1. Get production from PowerStatus (this works reliably)
        try:
            power = client.get_power_status()
            if power:
                stats["production"] = round(float(getattr(power, 'energy_today_kwh', 0)), 2)
                print(f"  PowerStatus: production={stats['production']} kWh")
        except Exception as e:
            print(f"  PowerStatus error: {e}")

        # 2. Use the authenticated session to get detailed data via REST API
        try:
            session = client.session
            base_url = f"https://{subdomain}.fusionsolar.huawei.com"

            # Refresh XSRF token
            xsrf = session.cookies.get("XSRF-TOKEN")
            if xsrf:
                session.headers.update({"XSRF-TOKEN": xsrf})

            # Get station code
            station_code = ""
            try:
                r = session.get(f"{base_url}/rest/pvms/web/station/v1/station/station-list",
                    params={"curPage": 1, "pageSize": 10, "timeZone": 2},
                    timeout=15)
                print(f"  station-list status: {r.status_code}")
                if r.status_code == 200:
                    data = r.json()
                    sl = data.get("data", {})
                    station_list = sl.get("list", []) if isinstance(sl, dict) else (sl if isinstance(sl, list) else [])
                    if station_list:
                        station_code = station_list[0].get("stationCode") or station_list[0].get("dn", "")
                        print(f"  station_code: {station_code}")
            except Exception as e:
                print(f"  station-list error: {e}")

            if station_code:
                collect_time = int(datetime.combine(target_date, datetime.min.time()).timestamp() * 1000)

                # Try multiple REST endpoints for detailed data
                for endpoint_name, path, method, payload in [
                    ("energy-balance POST", "/rest/pvms/web/station/v1/overview/energy-balance", "POST",
                     {"stationDn": station_code, "timeDim": 2, "queryTime": collect_time, "timeZone": 2}),
                    ("energy-flow POST", "/rest/pvms/web/station/v1/overview/energy-flow", "POST",
                     {"stationDn": station_code, "timeDim": 2, "queryTime": collect_time, "timeZone": 2}),
                    ("energy-balance GET", "/rest/pvms/web/station/v1/overview/energy-balance", "GET",
                     {"stationDn": station_code, "timeDim": 2, "queryTime": collect_time, "timeZone": 2}),
                    ("station-detail GET", f"/rest/pvms/web/station/v1/station/station-detail", "GET",
                     {"stationDn": station_code, "timeZone": 2}),
                ]:
                    try:
                        xsrf = session.cookies.get("XSRF-TOKEN")
                        if xsrf:
                            session.headers.update({"XSRF-TOKEN": xsrf})

                        if method == "POST":
                            r = session.post(f"{base_url}{path}", json=payload, timeout=15)
                        else:
                            r = session.get(f"{base_url}{path}", params=payload, timeout=15)

                        print(f"  {endpoint_name}: status={r.status_code}, ct={r.headers.get('content-type','')[:30]}")

                        if r.status_code == 200 and "json" in r.headers.get("content-type", ""):
                            data = r.json()
                            print(f"  {endpoint_name} data keys: {list(data.get('data', {}).keys()) if isinstance(data.get('data'), dict) else type(data.get('data'))}")

                            d = data.get("data", {})
                            if isinstance(d, dict) and d:
                                # Try to extract consumption and export
                                cons_keys = ["usePower", "use_power", "selfUsePower", "consumePower"]
                                exp_keys = ["ongridPower", "ongrid_power", "feedinPower", "sellPower"]
                                prod_keys = ["productPower", "inverterPower", "totalPower"]

                                for key in cons_keys:
                                    if key in d and float(d[key] or 0) > 0:
                                        stats["consumption"] = round(float(d[key]), 2)
                                        print(f"    consumption from {key}: {stats['consumption']}")
                                        break

                                for key in exp_keys:
                                    if key in d and float(d[key] or 0) > 0:
                                        stats["export"] = round(float(d[key]), 2)
                                        print(f"    export from {key}: {stats['export']}")
                                        break

                                for key in prod_keys:
                                    if key in d and float(d[key] or 0) > 0:
                                        prod_val = round(float(d[key]), 2)
                                        if prod_val > stats["production"]:
                                            stats["production"] = prod_val
                                            print(f"    production from {key}: {stats['production']}")
                                        break

                                if stats["consumption"] > 0 or stats["export"] > 0:
                                    print(f"  Got detailed data from {endpoint_name}!")
                                    break
                        elif r.status_code == 200:
                            print(f"  {endpoint_name}: got HTML, not JSON - skipping")
                    except Exception as e:
                        print(f"  {endpoint_name} error: {e}")

        except Exception as e:
            print(f"  REST API fallback error: {e}")

        # Calculate self-consumption
        if stats["production"] > 0:
            if stats["export"] > 0:
                stats["selfConsumption"] = round(
                    (stats["production"] - stats["export"]) / stats["production"] * 100, 1
                )
            else:
                stats["selfConsumption"] = 100.0

    except ImportError as e:
        print(f"fusion_solar_py import error: {e}")
    except Exception as e:
        print(f"FusionSolar error: {e}")

    return stats


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            query = parse_qs(urlparse(self.path).query)
            date_str = query.get("date", [None])[0]
            target = date.fromisoformat(date_str) if date_str else date.today()
            date_key = target.isoformat()
            print(f"=== Collecting data for {date_key} ===")

            matko = fetch_ha_data(target)
            print(f"Matko: {matko}")

            zocho = fetch_fusionsolar_data(target)
            print(f"Zocho: {zocho}")

            storage = Storage()
            all_data = storage.save_day(date_key, matko, zocho)

            matko_kwp = float(get_env("MATKO_KWP", "7.95"))
            zocho_kwp = float(get_env("ZOCHO_KWP", "6.16"))
            m_norm = matko["production"] / matko_kwp if matko_kwp > 0 else 0
            z_norm = zocho["production"] / zocho_kwp if zocho_kwp > 0 else 0
            winner = "Matko" if m_norm > z_norm else "Zocho" if z_norm > m_norm else "Remis"

            result = {
                "ok": True, "date": date_key, "matko": matko, "zocho": zocho,
                "winner": winner, "total_days": len(all_data),
            }

            self.send_response(200)
            self.send_header("Content-type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(result, ensure_ascii=False).encode())

        except Exception as e:
            print(f"Error: {e}")
            self.send_response(500)
            self.send_header("Content-type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"ok": False, "error": str(e)}).encode())
