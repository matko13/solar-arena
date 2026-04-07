"""Seed historical data using per-day keys"""
from http.server import BaseHTTPRequestHandler
import json, os, requests

def redis_cmd(*args):
    url = os.environ.get("KV_REST_API_URL")
    token = os.environ.get("KV_REST_API_TOKEN")
    r = requests.post(url, headers={"Authorization": f"Bearer {token}"}, json=list(args), timeout=10)
    r.raise_for_status()
    return r.json().get("result")

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        redis_cmd("SET", "sa:2026-04-04", json.dumps({"matko": {"production": 23.1}, "sasiad": {"production": 18.96}}))
        keys = redis_cmd("KEYS", "sa:*") or []
        self.send_response(200)
        self.send_header("Content-type","application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"ok": True, "keys": sorted(keys)}).encode())
