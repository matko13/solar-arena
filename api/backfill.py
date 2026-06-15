"""Solar Arena - backfill missing Matko days from Home Assistant history."""
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs, quote
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import json
import os
import requests

TZ = ZoneInfo("Europe/Warsaw")


def env(key, default=""):
    return os.environ.get(key, default)


def redis_cmd(*args):
    url = env("KV_REST_API_URL")
    token = env("KV_REST_API_TOKEN")
    r = requests.post(url, headers={"Authorization": f"Bearer {token}"}, json=list(args), timeout=10)
    r.raise_for_status()
    return r.json().get("result")


def ha_iso(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def fetch_matko_history(day_key):
    """Return end-of-day production for a past date from HA history."""
    sensor = env("HA_SENSOR_PRODUCTION", "sensor.inverter_today_production")
    ha_url = env("HA_URL", "").rstrip("/")
    ha_token = env("HA_TOKEN", "")
    if not ha_url or not ha_token:
        raise ValueError("HA_URL and HA_TOKEN must be configured")

    day = datetime.strptime(day_key, "%Y-%m-%d").replace(tzinfo=TZ)
    start = day.replace(hour=0, minute=0, second=0, microsecond=0)
    end = day.replace(hour=23, minute=59, second=59, microsecond=0)

    start_q = quote(ha_iso(start), safe="")
    end_q = quote(ha_iso(end), safe="")
    url = (
        f"{ha_url}/api/history/period/{start_q}"
        f"?end_time={end_q}&minimal_response&filter_entity_id={sensor}"
    )
    r = requests.get(url, headers={"Authorization": f"Bearer {ha_token}"}, timeout=20)
    if not r.ok:
        detail = r.text.strip()[:300]
        raise ValueError(f"HA history {r.status_code}: {detail}")

    history = r.json()
    if not history or not history[0]:
        return None

    best = 0.0
    for entry in history[0]:
        state = entry.get("state", "")
        if state in ("unavailable", "unknown", ""):
            continue
        try:
            value = float(state)
        except ValueError:
            continue
        if value > best:
            best = value
    return round(best, 2) if best > 0 else None


def load_day(day_key):
    raw = redis_cmd("GET", f"sa:{day_key}")
    return json.loads(raw) if raw else {}


def save_day(day_key, payload):
    redis_cmd("SET", f"sa:{day_key}", json.dumps(payload))


def days_with_missing_matko():
    keys = redis_cmd("KEYS", "sa:*") or []
    missing = []
    for key in sorted(keys):
        day_key = key.replace("sa:", "")
        day = load_day(day_key)
        matko = day.get("matko", {}).get("production", 0) or 0
        zocho = day.get("sasiad", {}).get("production", 0) or 0
        if matko == 0 and zocho > 0:
            missing.append(day_key)
    return missing


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            q = parse_qs(urlparse(self.path).query)
            auto = q.get("auto", ["false"])[0].lower() in ("1", "true", "yes")
            dry_run = q.get("dry_run", ["false"])[0].lower() in ("1", "true", "yes")
            force = q.get("force", ["false"])[0].lower() in ("1", "true", "yes")
            dates = q.get("dates", [""])[0]

            if auto:
                target_dates = days_with_missing_matko()
            elif dates:
                target_dates = [d.strip() for d in dates.split(",") if d.strip()]
            else:
                target_dates = days_with_missing_matko()

            results = []
            updated = 0
            for day_key in target_dates:
                existing = load_day(day_key)
                old_matko = existing.get("matko", {}).get("production", 0) or 0
                zocho = existing.get("sasiad", {}).get("production", 0) or 0

                if old_matko > 0 and not force:
                    results.append({"date": day_key, "status": "skipped", "reason": "already_has_data", "matko": old_matko})
                    continue

                try:
                    matko = fetch_matko_history(day_key)
                except Exception as e:
                    results.append({"date": day_key, "status": "error", "error": str(e)})
                    continue

                if matko is None or matko <= 0:
                    results.append({"date": day_key, "status": "not_found", "matko": 0, "zocho": zocho})
                    continue

                if not dry_run:
                    existing.setdefault("matko", {})
                    existing["matko"]["production"] = matko
                    if "sasiad" not in existing:
                        existing["sasiad"] = {"production": zocho}
                    save_day(day_key, existing)
                    updated += 1

                results.append({"date": day_key, "status": "updated" if not dry_run else "would_update", "matko": matko, "zocho": zocho})

            self.send_response(200)
            self.send_header("Content-type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps({
                "ok": True,
                "dry_run": dry_run,
                "target_days": len(target_dates),
                "updated": updated,
                "results": results,
            }).encode())
        except Exception as e:
            self.send_response(500)
            self.send_header("Content-type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"ok": False, "error": str(e)}).encode())
