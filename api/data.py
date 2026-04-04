"""
Solar Arena - Data API
GET /api/data - returns all stored data
GET /api/data?date=2026-04-04 - returns specific day
"""

from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import json
import os
import requests


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            kv_url = os.environ.get("KV_REST_API_URL", "")
            kv_token = os.environ.get("KV_REST_API_TOKEN", "")

            if not kv_url or not kv_token:
                self.send_response(500)
                self.send_header("Content-type", "application/json")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(json.dumps({"error": "KV not configured"}).encode())
                return

            # Fetch all data from Redis
            r = requests.post(
                kv_url,
                headers={"Authorization": f"Bearer {kv_token}"},
                json=["GET", "solar_arena_data"],
                timeout=10,
            )
            r.raise_for_status()
            result = r.json().get("result")
            data = json.loads(result) if result else {}

            # Optional date filter
            query = parse_qs(urlparse(self.path).query)
            date_str = query.get("date", [None])[0]
            if date_str and date_str in data:
                data = {date_str: data[date_str]}

            # Config info
            response = {
                "data": data,
                "config": {
                    "matkoKwp": float(os.environ.get("MATKO_KWP", "7.95")),
                    "sasiadKwp": float(os.environ.get("ZOCHO_KWP", "6.16")),
                    "normalize": True,
                },
                "totalDays": len(data),
            }

            self.send_response(200)
            self.send_header("Content-type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Cache-Control", "public, max-age=300")
            self.end_headers()
            self.wfile.write(json.dumps(response, ensure_ascii=False).encode())

        except Exception as e:
            self.send_response(500)
            self.send_header("Content-type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps({"error": str(e)}).encode())
