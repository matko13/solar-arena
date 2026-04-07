"""Seed data. GET /api/seed?dates=2026-04-04:23.1:18.96,2026-04-05:24.17:38.57"""
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
