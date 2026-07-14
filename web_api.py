# ============================================================
#  WEB API - lagani HTTP server UZ Telegram bot (aiohttp)
#
#  Bot radi u polling modu (sync telebot). Ovaj modul podize aiohttp
#  server u ZASEBNOM daemon threadu s vlastitim asyncio loopom, pa NE
#  blokira Telegram polling ni scheduled jobove.
#
#  Rute:
#    GET /zdrav          -> {"status":"ok"}          (bez kljuca, health check)
#    GET /api/pozicije   -> pozicije vozila (Mobilisis), stiti X-Api-Key
#
#  Zastita: header X-Api-Key mora odgovarati env FLOTA_OS_KEY.
#  Kes: rezultat Mobilisis poziva se kesira 30 s (vise klijenata = 1 poziv).
#  Robusnost: Mobilisis nedostupan -> 503 + zadnji uspjesni rezultat
#             ("zastarjelo": true) ako postoji.
#  CORS: Access-Control-Allow-Origin "*" (demo faza) + OPTIONS preflight.
# ============================================================

import os
import json
import time
import asyncio
import threading
from datetime import datetime, timezone

from aiohttp import web

import mobilisis
import monitoring

# ---- Konfiguracija ----
PORT = 8080
CACHE_TTL = 30  # sekundi: unutar ovog prozora posluzujemo iz kesa

_API_KEY = os.getenv("FLOTA_OS_KEY", "").strip()

# ---- Kes zadnjeg uspjesnog dohvata (dijeljen unutar jednog event loopa) ----
#   ts   = time.monotonic() zadnjeg uspjesnog dohvata (za TTL)
#   iso  = ISO8601 UTC vrijeme tog dohvata (za "vrijeme_dohvata")
#   data = lista vozila (za posluzivanje i stale fallback)
_cache = {"ts": 0.0, "iso": None, "data": None}
_fetch_lock = None  # asyncio.Lock; kreira se unutar loopa u _run()


def _log(msg):
    print(f"[web_api] {msg}", flush=True)


def is_configured():
    """Server ima smisla dizati samo ako je zastitni kljuc postavljen."""
    return bool(_API_KEY)


# ==================== POMOCNO ====================

def _json(obj, status=200):
    """JSON odgovor s hrvatskim znakovima (ensure_ascii=False)."""
    return web.json_response(
        obj, status=status,
        dumps=lambda o: json.dumps(o, ensure_ascii=False),
    )


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _check_key(request):
    """Vrati None ako je kljuc ispravan, inace gotov (error) odgovor."""
    if not _API_KEY:
        # Bez konfiguriranog kljuca nikoga ne mozemo autenticirati -> odbij.
        return _json({"error": "Server nije konfiguriran (FLOTA_OS_KEY)."},
                     status=503)
    if request.headers.get("X-Api-Key", "") != _API_KEY:
        return _json({"error": "Neispravan ili nedostajući X-Api-Key."},
                     status=401)
    return None


async def _get_positions_cached():
    """Vrati (vozila, iso, iz_kesa). Unutar 30 s posluzuje iz kesa; inace
    dohvaca s Mobilisisa (blokirajuci poziv u executoru). Vise istovremenih
    zahtjeva se serijalizira lockom pa se radi samo JEDAN poziv."""
    now = time.monotonic()
    if _cache["data"] is not None and (now - _cache["ts"]) < CACHE_TTL:
        return _cache["data"], _cache["iso"], True

    async with _fetch_lock:
        # Ponovna provjera: mozda je drugi zahtjev vec osvjezio kes.
        now = time.monotonic()
        if _cache["data"] is not None and (now - _cache["ts"]) < CACHE_TTL:
            return _cache["data"], _cache["iso"], True

        loop = asyncio.get_event_loop()
        data = await loop.run_in_executor(None, mobilisis.all_positions)
        iso = _now_iso()
        _cache.update(ts=time.monotonic(), iso=iso, data=data)
        return data, iso, False


# ==================== RUTE ====================

async def handle_zdrav(request):
    return _json({"status": "ok"})


async def handle_pozicije(request):
    err = _check_key(request)
    if err is not None:
        return err

    try:
        vozila, iso, iz_kesa = await _get_positions_cached()
    except Exception as e:
        _log(f"pozicije GRESKA: {e}")
        monitoring.error("Web API: dohvat pozicija nije uspio",
                         source="web_api", exc=e)
        body = {"error": f"Mobilisis trenutno nedostupan: {e}"}
        # Stale fallback: zadnji uspjesni rezultat ako postoji.
        if _cache["data"] is not None:
            body["zastarjelo"] = True
            body["vrijeme_dohvata"] = _cache["iso"]
            body["iz_kesa"] = True
            body["vozila"] = _cache["data"]
        return _json(body, status=503)

    return _json({
        "vrijeme_dohvata": iso,
        "iz_kesa": iz_kesa,
        "vozila": vozila,
    })


# ==================== CORS ====================

@web.middleware
async def _cors_mw(request, handler):
    # OPTIONS preflight -> odgovori odmah (bez trazenja rute/kljuca).
    if request.method == "OPTIONS":
        resp = web.Response(status=204)
    else:
        resp = await handler(request)
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Methods"] = "GET, OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "X-Api-Key, Content-Type"
    resp.headers["Access-Control-Max-Age"] = "86400"
    return resp


# ==================== POKRETANJE ====================

def _run():
    global _fetch_lock
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    _fetch_lock = asyncio.Lock()

    app = web.Application(middlewares=[_cors_mw])
    app.router.add_get("/zdrav", handle_zdrav)
    app.router.add_get("/api/pozicije", handle_pozicije)

    runner = web.AppRunner(app)
    loop.run_until_complete(runner.setup())
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    loop.run_until_complete(site.start())
    _log(f"HTTP server sluša na 0.0.0.0:{PORT} "
         f"(rute: /zdrav, /api/pozicije)")
    monitoring.info(f"Web API pokrenut na portu {PORT}", source="web_api")
    loop.run_forever()


def start():
    """UVIJEK diže HTTP server u zasebnom daemon threadu. Server mora slušati
    na portu 8080 da Fly health/smoke check kod deploya prođe (fly.toml ima
    [http_service]) i da /zdrav odgovara. Ako FLOTA_OS_KEY nije postavljen,
    server i dalje radi, ali /api/pozicije vraća 503 dok se tajna ne postavi."""
    if not is_configured():
        _log("UPOZORENJE: FLOTA_OS_KEY nije postavljen — /api/pozicije vraća 503 "
             "dok se tajna ne postavi. /zdrav i HTTP server rade normalno.")
        monitoring.warning("Web API: FLOTA_OS_KEY nije postavljen (/api/pozicije = 503).",
                           source="web_api")
    threading.Thread(target=_run, daemon=True, name="web-api").start()
