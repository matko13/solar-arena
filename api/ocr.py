"""Solar Arena - OCR via Claude Vision API"""
from http.server import BaseHTTPRequestHandler
import json, os, requests

def get_env(key, default=""):
    return os.environ.get(key, default)

PROMPT = """Analyze this solar inverter/monitoring app screenshot. Extract these daily values:
- production: total PV production today (kWh)
- consumption: total home consumption today (kWh)
- export: total grid export today (kWh)
Return ONLY a JSON object like: {"production": 12.5, "consumption": 8.3, "export": 4.2}
If a value is not visible, use 0. Numbers only, no units.
Look for: Production, Yield, Generation, Export, Feed-in, Consumption, Load, Self-use,
Produkcja, Zuzycie, Eksport, Oddane do sieci, Pobrane z sieci, Purchased."""

class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        try:
            api_key = get_env("ANTHROPIC_API_KEY")
            if not api_key:
                self._json(400, {"ok": False, "error": "ANTHROPIC_API_KEY not set"})
                return
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
            image_b64 = body.get("image", "")
            media_type = body.get("media_type", "image/png")
            if "base64," in image_b64:
                image_b64 = image_b64.split("base64,")[1]
            if not image_b64:
                self._json(400, {"ok": False, "error": "No image"})
                return
            print(f"OCR: {len(image_b64)//1000}KB")
            r = requests.post("https://api.anthropic.com/v1/messages", headers={
                "x-api-key": api_key, "anthropic-version": "2023-06-01", "content-type": "application/json",
            }, json={
                "model": "claude-sonnet-4-20250514", "max_tokens": 300,
                "messages": [{"role": "user", "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": image_b64}},
                    {"type": "text", "text": PROMPT}
                ]}]
            }, timeout=30)
            r.raise_for_status()
            text = r.json().get("content", [{}])[0].get("text", "{}")
            print(f"OCR raw: {text}")
            clean = text.strip()
            if clean.startswith("```"):
                clean = clean.split("\n", 1)[1] if "\n" in clean else clean[3:]
                clean = clean.rsplit("```", 1)[0]
            parsed = json.loads(clean.strip())
            self._json(200, {"ok": True, "production": round(float(parsed.get("production", 0)), 2),
                "consumption": round(float(parsed.get("consumption", 0)), 2), "export": round(float(parsed.get("export", 0)), 2)})
        except json.JSONDecodeError:
            self._json(200, {"ok": False, "error": "Nie odczytano wartosci. Wpisz recznie."})
        except Exception as e:
            print(f"OCR error: {e}")
            self._json(500, {"ok": False, "error": str(e)})
    def do_OPTIONS(self):
        self.send_response(200)
        for h, v in [("Access-Control-Allow-Origin","*"),("Access-Control-Allow-Methods","POST, OPTIONS"),("Access-Control-Allow-Headers","Content-Type")]:
            self.send_header(h, v)
        self.end_headers()
    def _json(self, code, data):
        self.send_response(code)
        for h, v in [("Content-type","application/json"),("Access-Control-Allow-Origin","*")]:
            self.send_header(h, v)
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())
