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

        # Get power status (includes today's production)
        try:
            power = client.get_power_status()
            print(f"FusionSolar power_status: {power}")
            if power:
                stats["production"] = round(float(getattr(power, 'total_current_day_energy_kwh', 0) or getattr(power, 'current_power_kw', 0)), 2)
                if stats["production"] > 0:
                    stats["selfConsumption"] = 100.0
                print(f"FusionSolar: production={stats['production']} kWh")
        except Exception as e:
            print(f"FusionSolar power_status error: {e}")

        # Try station KPIs for more detail
        try:
            stations = client.get_station_list()
            print(f"FusionSolar stations: {len(stations) if stations else 0}")
            if stations:
                station_code = stations[0].get("stationCode", stations[0].get("dn", ""))
                print(f"FusionSolar station_code: {station_code}")

                kpi = client.get_station_real_kpi(station_code)
                print(f"FusionSolar real_kpi raw: {kpi}")
                if kpi:
                    k = kpi[0] if isinstance(kpi, list) else kpi
                    dp = k.get("dataItemMap", k) if isinstance(k, dict) else {}
                    if dp:
                        prod = float(dp.get("day_power", dp.get("inverter_power", dp.get("total_power", 0))))
                        cons = float(dp.get("day_consumption", dp.get("use_power", 0)))
                        exp = float(dp.get("day_ongrid_power", dp.get("ongrid_power", 0)))
                        if prod > 0:
                            stats["production"] = round(prod, 2)
                        if cons > 0:
                            stats["consumption"] = round(cons, 2)
                        if exp > 0:
                            stats["export"] = round(exp, 2)
                        if stats["production"] > 0 and stats["export"] >= 0:
                            stats["selfConsumption"] = round(
                                (stats["production"] - stats["export"]) / stats["production"] * 100, 1
                            )
                        print(f"FusionSolar KPI: {stats}")
        except Exception as e:
            print(f"FusionSolar station KPI error: {e}")

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
