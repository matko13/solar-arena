# Solar Arena ⚡☀️

Gamifikowany dashboard porównujący produkcję PV między dwoma instalacjami.

**Matko** (DEYE 7.95 kWp) vs **Żocho** (Huawei 6.16 kWp)

## Deploy na Vercel (5 minut)

### 1. Utwórz repo na GitHub

```bash
cd solar-arena
git init
git add .
git commit -m "Solar Arena v1"
git remote add origin git@github.com:TWOJ_USER/solar-arena.git
git push -u origin main
```

### 2. Deploy na Vercel

1. Wejdź na [vercel.com](https://vercel.com) i zaloguj się kontem GitHub
2. "Import Project" → wybierz repo `solar-arena`
3. Framework: **Other**
4. Deploy

### 3. Dodaj Upstash Redis (storage)

1. W Vercel Dashboard → projekt → **Storage** tab
2. "Create Database" → **KV (Upstash Redis)** → Free tier
3. "Connect" - automatycznie doda `KV_REST_API_URL` i `KV_REST_API_TOKEN`

### 4. Ustaw Environment Variables

Vercel Dashboard → Settings → Environment Variables:

| Zmienna | Wartość |
|---------|---------|
| `HA_URL` | URL Twojego HA (np. https://XXXX.ui.nabu.casa) |
| `HA_TOKEN` | Long-lived access token z HA |
| `FS_BASE_URL` | `https://uni003eu5.fusionsolar.huawei.com` |
| `FS_USERNAME` | `bartekzochowski` |
| `FS_PASSWORD` | hasło FusionSolar |
| `MATKO_KWP` | `7.95` |
| `ZOCHO_KWP` | `6.16` |

**Ważne:** `HA_URL` musi być dostępny z internetu (Nabu Casa lub Tailscale).

### 5. Test

Odwiedź: `https://solar-arena.vercel.app/api/collect`

Powinno zwrócić JSON z danymi obu instalacji.

### 6. Gotowe!

- Dashboard: `https://solar-arena.vercel.app`
- Dane zbierane automatycznie o 23:55 CET (cron w vercel.json)
- Żocho otwiera ten sam URL w przeglądarce

## Ręczne zbieranie danych

```
GET /api/collect              # zbierz za dziś
GET /api/collect?date=2026-04-03  # zbierz za konkretny dzień
GET /api/data                 # pokaż wszystkie dane
```

## Architektura

```
Browser (Matko/Żocho)
  │
  ├── GET / → public/index.html (static dashboard)
  └── GET /api/data → Upstash Redis → JSON response
  
Vercel Cron (23:55 daily)
  │
  └── GET /api/collect
        ├── Home Assistant REST API → dane Matko (DEYE)
        ├── FusionSolar SSO API → dane Żocho (Huawei)
        └── Upstash Redis ← save
```
