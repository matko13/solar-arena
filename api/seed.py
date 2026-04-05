from http.server import BaseHTTPRequestHandler
import json, os, requests
class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        url = os.environ.get("KV_REST_API_URL")
        token = os.environ.get("KV_REST_API_TOKEN")
        r = requests.post(url, headers={"Authorization": f"Bearer {token}"}, json=["GET", "solar_arena_data"], timeout=10)
        data = json.loads(r.json().get("result") or "{}")
        data["2026-04-04"] = {"matko": {"production": 23.1}, "sasiad": {"production": 18.96}}
        requests.post(url, headers={"Authorization": f"Bearer {token}"}, json=["SET", "solar_arena_data", json.dumps(data)], timeout=10)
        self.send_response(200)
        self.send_header("Content-type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"ok": True, "dates": sorted(data.keys())}).encode())
