"""
Solar Arena - Data Collector (Vercel Serverless Function)
Triggered daily by Vercel Cron at 23:55 CET.
Also callable manually: GET /api/collect?date=2026-04-04
"""

from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from datetime import datetime, date, timedelta
import json
import os
import requests


# ---------------------------------------------------------------------------
# Config from environment variables (set in Vercel Dashboard)
# ---------------------------------------------------------------------------

def get_env(key, default=""):
    return os.environ.get(key, default)


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

def empty_stats():
    return {"production": 0.0, "consumption": 0.0, "export": 0.0, "selfConsumption": 0.0}


# ---------------------------------------------------------------------------
# Upstash Redis storage
# ---------------------------------------------------------------------------

class Storage:
    """Upstash Redis REST API client."""

    def __init__(self):
        self.url = get_env("KV_REST_API_URL")
        self.token = get_env("KV_REST_API_TOKEN")

    def _req(self, *args):
        r = requests.post(
            f"{self.url}",
            headers={"Authorization": f"Bearer {self.token}"},
            json=list(args),
            timeout=10,
        )
        r.raise_for_status()
        return r.json().get("result")

    def get_all_data(self) -> dict:
        """Get all arena data."""
        r = requests.post(
            f"{self.url}",
            headers={"Authorization": f"Bearer {self.token}"},
            json=["GET", "solar_arena_data"],
            timeout=10,
        )
        r.raise_for_status()
        result = r.json().get("result")
        if result:
            return json.loads(result)
        return {}

    def save_day(self, date_key: str, matko: dict, sasiad: dict):
        """Save one day's data."""
        data = self.get_all_data()
        data[date_key] = {"matko": matko, "sasiad": sasiad}
        r = requests.post(
            f"{self.url}",
            headers={"Authorization": f"Bearer {self.token}"},
            json=["SET", "solar_arena_data", json.dumps(data)],
            timeout=10,
        )
        r.raise_for_status()
        return data


# ---------------------------------------------------------------------------
# Home Assistant (Matko / DEYE)
# ---------------------------------------------------------------------------

def fetch_ha_data(target_date: date) -> dict:
    """Fetch daily data from Home Assistant REST API."""
    ha_url = get_env("HA_URL", "http://homeassistant.local:8123").rstrip("/")
    ha_token = get_env("HA_TOKEN")

    if not ha_token or ha_token == "TWOJ_HA_TOKEN":
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
            if target_date == date.today():
                r = requests.get(f"{ha_url}/api/states/{entity_id}", headers=headers, timeout=10)
                r.raise_for_status()
                state = r.json()
                val = state.get("state", "0")
                raw[field] = float(val) if val not in ("unavailable", "unknown", "") else 0.0
            else:
                start = datetime.combine(target_date, datetime.min.time()).isoformat()
                end = datetime.combine(target_date + timedelta(days=1), datetime.min.time()).isoformat()
                r = requests.get(
                    f"{ha_url}/api/history/period/{start}",
                    headers=headers,
                    params={"filter_entity_id": entity_id, "end_time": end, "minimal_response": "true"},
                    timeout=10,
                )
                r.raise_for_status()
                history = r.json()
                if history and history[0]:
                    vals = [float(s["state"]) for s in history[0]
                            if s.get("state") not in ("unavailable", "unknown", "")]
                    raw[field] = max(vals) if vals else 0.0
                else:
                    raw[field] = 0.0
        except Exception as e:
            print(f"HA error {entity_id}: {e}")
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


# ---------------------------------------------------------------------------
# Huawei FusionSolar (Żocho)
# ---------------------------------------------------------------------------

def fusionsolar_login(session, base_url, username, password):
    """Login via SSO - regular user account."""
    r = session.post(
        f"{base_url}/unisso/v2/validateUser.action",
        json={"organizationName": "", "username": username, "password": password},
        timeout=15,
    )
    r.raise_for_status()
    data = r.json()
    if data.get("errorCode"):
        raise Exception(f"FusionSolar login failed: {data.get('errorMsg', data)}")

    redirect_url = data.get("redirectURL") or data.get("redirectUrl")
    if redirect_url:
        session.get(redirect_url, timeout=15, allow_redirects=True)

    xsrf = session.cookies.get("XSRF-TOKEN")
    if xsrf:
        session.headers.update({"XSRF-TOKEN": xsrf})


def fetch_fusionsolar_data(target_date: date) -> dict:
    """Fetch daily data from FusionSolar."""
    base_url = get_env("FS_BASE_URL", "https://uni003eu5.fusionsolar.huawei.com")
    username = get_env("FS_USERNAME")
    password = get_env("FS_PASSWORD")

    if not username or not password:
        return empty_stats()

    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json",
    })

    try:
        fusionsolar_login(session, base_url, username, password)
    except Exception as e:
        print(f"FusionSolar login error: {e}")
        return empty_stats()

    # Auto-detect station
    station_code = get_env("FS_STATION_CODE", "")
    if not station_code:
        try:
            r = session.post(f"{base_url}/rest/pvms/web/station/v1/station/station-list", json={
                "curPage": 1, "pageSize": 10, "timeZone": 2, "sortId": "createTime", "sortDir": "DESC",
            }, timeout=15)
            r.raise_for_status()
            data = r.json()
            stations = data.get("data", {})
            if isinstance(stations, dict):
                station_list = stations.get("list", [])
            else:
                station_list = stations if isinstance(stations, list) else []
            if station_list:
                station_code = station_list[0].get("stationCode") or station_list[0].get("dn", "")
                print(f"Auto-detected station: {station_code}")
        except Exception as e:
            print(f"Station list error: {e}")
            return empty_stats()

    if not station_code:
        print("No station found")
        return empty_stats()

    collect_time = int(datetime.combine(target_date, datetime.min.time()).timestamp() * 1000)
    stats = empty_stats()

    # Try multiple endpoints
    endpoints = [
        ("/rest/pvms/web/station/v1/overview/energy-balance", {"stationDn": station_code, "timeDim": 2, "queryTime": collect_time, "timeZone": 2}),
        ("/rest/pvms/web/station/v1/overview/energy-flow", {"stationDn": station_code, "timeDim": 2, "queryTime": collect_time, "timeZone": 2}),
    ]

    for path, payload in endpoints:
        try:
            xsrf = session.cookies.get("XSRF-TOKEN")
            if xsrf:
                session.headers.update({"XSRF-TOKEN": xsrf})
            r = session.post(f"{base_url}{path}", json=payload, timeout=15)
            r.raise_for_status()
            data = r.json()
            if data.get("data"):
                d = data["data"]
                stats["production"] = round(float(d.get("productPower", d.get("inverter_power", 0))), 2)
                stats["consumption"] = round(float(d.get("usePower", d.get("use_power", 0))), 2)
                stats["export"] = round(float(d.get("ongridPower", d.get("ongrid_power", 0))), 2)
                if stats["production"] > 0:
                    stats["selfConsumption"] = round(
                        (stats["production"] - stats["export"]) / stats["production"] * 100, 1
                    )
                print(f"FusionSolar OK ({path}): prod={stats['production']}")
                return stats
        except Exception as e:
            print(f"FusionSolar {path} failed: {e}")
            continue

    return stats


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            # Verify cron secret (optional - Vercel adds this header)
            # auth = self.headers.get("Authorization")
            # cron_secret = get_env("CRON_SECRET")

            # Parse date from query string or use today
            query = parse_qs(urlparse(self.path).query)
            date_str = query.get("date", [None])[0]
            if date_str:
                target = date.fromisoformat(date_str)
            else:
                target = date.today()

            date_key = target.isoformat()
            print(f"=== Collecting data for {date_key} ===")

            # Collect from both sources
            matko = fetch_ha_data(target)
            print(f"Matko: {matko}")

            zocho = fetch_fusionsolar_data(target)
            print(f"Żocho: {zocho}")

            # Store
            storage = Storage()
            all_data = storage.save_day(date_key, matko, zocho)

            # Determine winner
            matko_kwp = float(get_env("MATKO_KWP", "7.95"))
            zocho_kwp = float(get_env("ZOCHO_KWP", "6.16"))
            m_norm = matko["production"] / matko_kwp if matko_kwp > 0 else 0
            z_norm = zocho["production"] / zocho_kwp if zocho_kwp > 0 else 0
            winner = "Matko" if m_norm > z_norm else "Żocho" if z_norm > m_norm else "Remis"

            result = {
                "ok": True,
                "date": date_key,
                "matko": matko,
                "zocho": zocho,
                "winner": winner,
                "total_days": len(all_data),
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
