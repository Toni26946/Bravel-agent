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
import benzinske
import podrska
import monitoring

# ---- Konfiguracija ----
PORT = 8080
CACHE_TTL = 30  # sekundi: unutar ovog prozora posluzujemo iz kesa

# Kod brzog restarta (npr. nakon `fly secrets set`) stari proces moze jos
# drzati port 8080 -> bind pada s OSError. Pokusaj vise puta prije predaje.
_BIND_RETRIES = 6
_BIND_RETRY_DELAY = 2.0  # sekundi izmedu pokusaja

_API_KEY = os.getenv("FLOTA_OS_KEY", "").strip()

# WhatsApp webhook: verify token (proizvoljan niz koji odaberemo; isti se
# upisuje u Meta App → WhatsApp → Configuration). _on_incoming je callback
# koji main.py registrira da proslijedi dolazne poruke na Telegram.
_WA_VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN", "").strip()
_on_incoming = None
_on_support = None   # callback za dolazne poruke iz živog chata (podrška)

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


async def handle_putanja(request):
    """Ruta (povijest kretanja) jednog vozila za zadnjih 'sati' sati.
    GET /api/putanja?reg=<registracija>&sati=<broj>  (štiti X-Api-Key)."""
    err = _check_key(request)
    if err is not None:
        return err

    reg = (request.query.get("reg") or "").strip()
    if not reg:
        return _json({"error": "Nedostaje parametar 'reg'."}, status=400)
    try:
        sati = float(request.query.get("sati", "6"))
    except ValueError:
        sati = 6.0
    sati = max(0.5, min(sati, 336.0))  # ograniči raspon (0.5 h – 14 dana)

    try:
        loop = asyncio.get_event_loop()
        rez = await loop.run_in_executor(
            None, lambda: mobilisis.putanja_za_reg(reg, sati))
    except Exception as e:
        _log(f"putanja GRESKA: {e}")
        monitoring.error("Web API: dohvat putanje nije uspio",
                         source="web_api", exc=e)
        return _json({"error": f"Putanja nedostupna: {e}"}, status=503)

    return _json(rez)


async def handle_benzinske(request):
    """GET /api/benzinske — registar benzinskih lanaca s lokacijama i zadnjim
    cijenama goriva + zabiljezena promjena. Stiti X-Api-Key. Cita iz baze
    (cijene puni scheduled scraper), pa je poziv brz i bez vanjskih poziva."""
    err = _check_key(request)
    if err is not None:
        return err
    try:
        loop = asyncio.get_event_loop()
        podaci = await loop.run_in_executor(None, benzinske.trenutno)
    except Exception as e:
        _log(f"benzinske GRESKA: {e}")
        monitoring.error("Web API: dohvat benzinskih nije uspio",
                         source="web_api", exc=e)
        return _json({"error": f"Benzinske trenutno nedostupne: {e}"}, status=503)
    return _json({"vrijeme_dohvata": _now_iso(), "lanci": podaci})


async def handle_podrska_ws(request):
    """WebSocket živog chata (podrška). Štiti ?key=FLOTA_OS_KEY (isti kao API);
    zatim delegira na podrska.ws_handler."""
    if not _API_KEY:
        return _json({"error": "Server nije konfiguriran (FLOTA_OS_KEY)."}, status=503)
    if request.query.get("key", "") != _API_KEY:
        return _json({"error": "Neispravan ili nedostajući key."}, status=401)
    return await podrska.ws_handler(request)


async def handle_podrska_demo(request):
    """Demo/test chat stranica (bez frontenda). Ključ se upisuje u samoj stranici."""
    return await podrska.handle_demo(request)


# ==================== WhatsApp webhook ====================

async def handle_wa_webhook_verify(request):
    """GET — Meta verifikacija pretplate. Vrati hub.challenge (plain text)
    ako se hub.verify_token slaže s WHATSAPP_VERIFY_TOKEN; inače 403."""
    mode = request.query.get("hub.mode")
    token = request.query.get("hub.verify_token")
    challenge = request.query.get("hub.challenge", "")
    if mode == "subscribe" and _WA_VERIFY_TOKEN and token == _WA_VERIFY_TOKEN:
        _log("WhatsApp webhook verificiran")
        return web.Response(text=challenge, status=200)
    _log("WhatsApp webhook verifikacija odbijena (mode/token se ne slažu)")
    return web.Response(text="Forbidden", status=403)


def _obradi_wa_event(data):
    """Izvuci dolazne poruke iz Meta payloada i proslijedi ih _on_incoming."""
    if not isinstance(data, dict):
        return
    for entry in data.get("entry", []) or []:
        for change in entry.get("changes", []) or []:
            value = change.get("value", {}) or {}
            ime_po_broju = {}
            for c in value.get("contacts", []) or []:
                wa = c.get("wa_id")
                if wa:
                    ime_po_broju[wa] = (c.get("profile") or {}).get("name")
            for m in value.get("messages", []) or []:
                frm = m.get("from")
                ime = ime_po_broju.get(frm) or frm
                if _on_incoming:
                    # Obrada (vision, SharePoint, slanje) je BLOKIRAJUĆA — u zaseban
                    # thread da ne blokira aiohttp loop i da webhook odmah vrati 200
                    # (inače Meta misli da je pao i ponavlja isporuku → duplikati).
                    threading.Thread(target=_on_incoming, args=(frm, ime, m),
                                     daemon=True).start()


async def handle_wa_webhook_event(request):
    """POST — dolazne poruke i statusi dostave. Meta očekuje brz 200 (inače
    ponavlja isporuku), pa nikad ne vraćamo grešku prema Meti."""
    try:
        data = await request.json()
    except Exception:
        return web.Response(text="EVENT_RECEIVED", status=200)
    try:
        _obradi_wa_event(data)
    except Exception as e:
        monitoring.warning(f"WhatsApp webhook obrada nije uspjela: {e}", source="web_api")
    return web.Response(text="EVENT_RECEIVED", status=200)


# ==================== Pravila privatnosti (za Meta Live mode) ====================

_PRIVATNOST_HTML = """<!doctype html>
<html lang="hr"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Pravila privatnosti — Bravel d.o.o.</title>
<style>
 body{font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;line-height:1.65;
   color:#1c2333;max-width:760px;margin:0 auto;padding:32px 20px;background:#fff}
 h1{font-size:26px;margin:0 0 4px} h2{font-size:18px;margin:28px 0 8px;color:#0f4c81}
 .datum{color:#667085;font-size:14px;margin-bottom:24px}
 ul{padding-left:20px} li{margin:4px 0} a{color:#0f4c81}
 footer{margin-top:36px;padding-top:16px;border-top:1px solid #e4e7ec;color:#667085;font-size:13px}
</style></head><body>
<h1>Pravila privatnosti</h1>
<div class="datum">Bravel d.o.o. · zadnje ažuriranje: 15. srpnja 2026.</div>

<p>Ova pravila objašnjavaju koje osobne podatke Bravel d.o.o. („mi") prikuplja
i obrađuje putem svojih internih alata za upravljanje flotom (Telegram bot,
WhatsApp poslovni broj, praćenje vozila) te u koju svrhu.</p>

<h2>1. Voditelj obrade</h2>
<p>Bravel d.o.o., Republika Hrvatska. Zahtjeve vezane uz privatnost možete
uputiti društvu Bravel d.o.o.</p>

<h2>2. Koje podatke prikupljamo i zašto</h2>
<ul>
 <li><b>Telegram:</b> identifikator računa i sadržaj poruka te fotografije
   računa/primki — radi evidencije troškova i dokumenata poslovanja.</li>
 <li><b>WhatsApp:</b> telefonski broj i sadržaj poruka — radi poslovne
   komunikacije, obavijesti i potvrda.</li>
 <li><b>Lokacija vozila (GPS):</b> pozicija, brzina i status vozila flote —
   radi operativnog upravljanja i nadzora prijevoza.</li>
</ul>
<p>Ne prikupljamo podatke u marketinške svrhe i ne prodajemo osobne podatke.</p>

<h2>3. Gdje se podaci pohranjuju i tko ih obrađuje</h2>
<p>Podaci se pohranjuju u poslovnom okruženju Microsoft 365 (SharePoint) i na
poslužiteljima naših pružatelja usluga. Kao izvršitelji obrade koriste se:
Meta Platforms (WhatsApp Business Platform), Mobilisis (GPS praćenje),
Microsoft (pohrana i Graph API) te Anthropic (obrada teksta i slika računa).
Podaci se ne dijele s trećim stranama izvan navedenih izvršitelja.</p>

<h2>4. Rok čuvanja</h2>
<p>Podatke čuvamo dok traje poslovna svrha odnosno koliko nalažu zakonski
propisi (npr. računovodstveni rokovi), nakon čega se brišu ili anonimiziraju.</p>

<h2>5. Vaša prava (GDPR)</h2>
<p>Imate pravo na pristup, ispravak, brisanje i ograničenje obrade svojih
podataka te na prigovor. Zahtjev možete uputiti društvu Bravel d.o.o.</p>

<h2>6. Izmjene</h2>
<p>Ova pravila možemo povremeno ažurirati; nova verzija objavljuje se na ovoj
adresi s ažuriranim datumom.</p>

<footer>© Bravel d.o.o. Sva prava pridržana.</footer>
</body></html>"""


async def handle_privatnost(request):
    """Javna stranica s pravilima privatnosti (Privacy Policy URL za Meta)."""
    return web.Response(text=_PRIVATNOST_HTML, content_type="text/html", charset="utf-8")


# ==================== CORS ====================

@web.middleware
async def _cors_mw(request, handler):
    # OPTIONS preflight -> odgovori odmah (bez trazenja rute/kljuca).
    if request.method == "OPTIONS":
        resp = web.Response(status=204)
    else:
        resp = await handler(request)
    # WebSocket odgovor je vec pripremljen (upgrade) — ne diraj mu headere.
    if isinstance(resp, web.WebSocketResponse) or getattr(resp, "prepared", False):
        return resp
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Methods"] = "GET, OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "X-Api-Key, Content-Type"
    resp.headers["Access-Control-Max-Age"] = "86400"
    return resp


# ==================== POKRETANJE ====================

def _bind_site(loop, runner):
    """Startaj TCPSite na 0.0.0.0:PORT uz retry na OSError (port jos zauzet
    od starog procesa kod brzog restarta). Baca zadnju gresku ako ne uspije."""
    last = None
    for attempt in range(1, _BIND_RETRIES + 1):
        site = web.TCPSite(runner, "0.0.0.0", PORT)
        try:
            loop.run_until_complete(site.start())
            return
        except OSError as e:
            last = e
            _log(f"bind na :{PORT} nije uspio "
                 f"(pokušaj {attempt}/{_BIND_RETRIES}): {e}")
            if attempt < _BIND_RETRIES:
                loop.run_until_complete(asyncio.sleep(_BIND_RETRY_DELAY))
    raise last or OSError(f"bind na :{PORT} nije uspio")


def _run():
    # VAZNO: cijeli thread je u try/except. Bez toga bi iznimka (npr. bind na
    # zauzet port) otisla u threading.excepthook koji monitoring.install()
    # zamjenjuje -> prijavljuje SAMO monitoringu i NISTA ne ispisuje u fly
    # logove (thread "tiho umre"). Ovdje gresku logiramo GLASNO: i u logger
    # (vidljivo u `fly logs`) i u monitoring.
    global _fetch_lock
    try:
        _log(f"pokrećem HTTP server na 0.0.0.0:{PORT}…")
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        _fetch_lock = asyncio.Lock()

        # Živi chat (podrška): dajemo mu ovaj loop (za thread-safe predaju
        # poruka) i callback prema Telegramu.
        podrska.configure(loop, _on_support)

        app = web.Application(middlewares=[_cors_mw])
        app.router.add_get("/zdrav", handle_zdrav)
        app.router.add_get("/api/pozicije", handle_pozicije)
        app.router.add_get("/api/putanja", handle_putanja)
        app.router.add_get("/api/benzinske", handle_benzinske)
        app.router.add_get("/api/podrska/ws", handle_podrska_ws)
        app.router.add_get("/api/podrska", handle_podrska_demo)
        app.router.add_get("/whatsapp/webhook", handle_wa_webhook_verify)
        app.router.add_post("/whatsapp/webhook", handle_wa_webhook_event)
        app.router.add_get("/privatnost", handle_privatnost)

        runner = web.AppRunner(app)
        loop.run_until_complete(runner.setup())
        _bind_site(loop, runner)

        _log(f"HTTP server sluša na 0.0.0.0:{PORT} "
             f"(rute: /zdrav, /api/pozicije, /api/putanja, /api/benzinske, "
             f"/api/podrska(+/ws), /whatsapp/webhook, /privatnost)")
        monitoring.info(f"Web API pokrenut na portu {PORT}", source="web_api")
        loop.run_forever()
    except Exception as e:
        _log(f"GREŠKA: HTTP server se NIJE podigao / ugasio se: {e}")
        monitoring.error("Web API se ugasio (thread umro)",
                         source="web_api", exc=e)


def start(on_incoming=None, on_support=None):
    """UVIJEK diže HTTP server u zasebnom daemon threadu. Server mora slušati
    na portu 8080 da Fly health/smoke check kod deploya prođe (fly.toml ima
    [http_service]) i da /zdrav odgovara. Ako FLOTA_OS_KEY nije postavljen,
    server i dalje radi, ali /api/pozicije vraća 503 dok se tajna ne postavi.

    Sve je omotano u try/except s glasnim logiranjem (logger + monitoring) da
    se problem s pokretanjem NIKAD ne izgubi tiho.

    on_incoming(from, ime, msg) — opcionalni callback za dolazne WhatsApp
    poruke; msg je cijeli message dict (tip, text, image, interactive…).
    main.py ga veže na dispatcher (obrada računa / obavijest vlasniku).

    on_support(session_id, ime, tekst) — opcionalni callback za dolazne poruke
    iz živog chata (podrška); main.py javi vlasnicima na Telegram."""
    global _on_incoming, _on_support
    _on_incoming = on_incoming
    if on_support is not None:
        _on_support = on_support
    try:
        if not is_configured():
            _log("UPOZORENJE: FLOTA_OS_KEY nije postavljen — /api/pozicije vraća 503 "
                 "dok se tajna ne postavi. /zdrav i HTTP server rade normalno.")
            monitoring.warning("Web API: FLOTA_OS_KEY nije postavljen (/api/pozicije = 503).",
                               source="web_api")
        threading.Thread(target=_run, daemon=True, name="web-api").start()
        _log("web-api thread pokrenut")
    except Exception as e:
        _log(f"GREŠKA pri pokretanju web-api threada: {e}")
        monitoring.error("Web API: start() nije uspio", source="web_api", exc=e)
