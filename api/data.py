"""Solar Arena - Data API (per-day Redis keys)"""
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
        try:
            keys = redis_cmd("KEYS", "sa:*") or []
            data = {}
            for key in sorted(keys):
                val = redis_cmd("GET", key)
                if val:
                    dt = key.replace("sa:", "")
                    data[dt] = json.loads(val)
            response = {"data": data, "config": {"matkoKwp": float(os.environ.get("MATKO_KWP", "7.95")), "sasiadKwp": float(os.environ.get("ZOCHO_KWP", "6.16"))}, "totalDays": len(data)}
            self.send_response(200)
            self.send_header("Content-type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(json.dumps(response).encode())
        except Exception as e:
            self.send_response(500)
            self.send_header("Content-type","application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error":str(e)}).encode())
