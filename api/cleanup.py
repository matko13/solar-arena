"""Delete a date from the database. GET /api/cleanup?date=2026-04-03"""
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import json, os, requests

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            url = os.environ.get("KV_REST_API_URL")
            token = os.environ.get("KV_REST_API_TOKEN")
            query = parse_qs(urlparse(self.path).query)
            date_key = query.get("date", [None])[0]
            if not date_key:
                self._json(400, {"error": "?date= required"})
                return
            r = requests.post(url, headers={"Authorization": f"Bearer {token}"}, json=["GET", "solar_arena_data"], timeout=10)
            data = json.loads(r.json().get("result") or "{}")
            removed = data.pop(date_key, None)
            requests.post(url, headers={"Authorization": f"Bearer {token}"}, json=["SET", "solar_arena_data", json.dumps(data)], timeout=10)
            self._json(200, {"ok": True, "removed": date_key, "had_data": removed is not None, "remaining_dates": sorted(data.keys())})
        except Exception as e:
            self._json(500, {"error": str(e)})
    def _json(self, code, data):
        self.send_response(code)
        self.send_header("Content-type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())
