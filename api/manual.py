"""Solar Arena - Manual Data Entry API"""
from http.server import BaseHTTPRequestHandler
import json, os, requests

def get_env(key, default=""):
    return os.environ.get(key, default)

class Storage:
    def __init__(self):
        self.url = get_env("KV_REST_API_URL")
        self.token = get_env("KV_REST_API_TOKEN")
    def get_all_data(self):
        r = requests.post(self.url, headers={"Authorization": f"Bearer {self.token}"}, json=["GET", "solar_arena_data"], timeout=10)
        r.raise_for_status()
        result = r.json().get("result")
        return json.loads(result) if result else {}
    def save_all(self, data):
        requests.post(self.url, headers={"Authorization": f"Bearer {self.token}"}, json=["SET", "solar_arena_data", json.dumps(data)], timeout=10)

class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        try:
            length = int(self.headers.get('Content-Length', 0))
            body = json.loads(self.rfile.read(length))
            player = body.get("player", "sasiad")
            date_key = body.get("date")
            if not date_key: raise ValueError("date is required")
            prod = float(body.get("production", 0))
            cons = float(body.get("consumption", 0))
            exp = float(body.get("export", 0))
            sc = round((prod - exp) / prod * 100, 1) if prod > 0 and exp >= 0 else (100.0 if prod > 0 else 0.0)
            entry = {"production": round(prod, 2), "consumption": round(cons, 2), "export": round(exp, 2), "selfConsumption": sc}
            storage = Storage()
            data = storage.get_all_data()
            if date_key not in data: data[date_key] = {}
            data[date_key][player] = entry
            storage.save_all(data)
            print(f"Manual entry: {player} {date_key} -> {entry}")
            self.send_response(200)
            self.send_header("Content-type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.end_headers()
            self.wfile.write(json.dumps({"ok": True, "player": player, "date": date_key, "entry": entry}).encode())
        except Exception as e:
            print(f"Manual entry error: {e}")
            self.send_response(400)
            self.send_header("Content-type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps({"ok": False, "error": str(e)}).encode())
    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
