# ============================================================
#  PODRSKA - zivi chat (support) za internu Flotu OS
#
#  Tok:
#    - Korisnik (dispecer) na Floti OS otvori WebSocket na /api/podrska/ws
#      -> kreira se sesija (kratki numericki id). Salje poruke (JSON {tekst}).
#    - Svaka korisnikova poruka ide callbackom na Telegram vlasnicima
#      (main.py _podrska_dolazna) — most prema podrsci.
#    - Vlasnik odgovori na Telegramu (/podrska <id> <tekst> ili reply na
#      obavijest) -> main.py zove posalji_klijentu(id, tekst) -> poruka se
#      preko WS-a vrati korisniku u realnom vremenu.
#
#  NITI (vazno): aiohttp radi u ZASEBNOM threadu s vlastitim event loopom
#  (web_api._run). Telegram bot je u glavnom threadu (sync telebot). Zato:
#    - WS handler (aiohttp loop thread) prima korisnikove poruke i forwarda ih
#      na Telegram preko run_in_executor (da ne blokira loop).
#    - posalji_klijentu (Telegram thread) gura poruku u sesijin asyncio.Queue
#      preko loop.call_soon_threadsafe (thread-safe predaja u aiohttp loop).
#
#  Autentikacija WS-a radi se u web_api (?key=FLOTA_OS_KEY) prije delegiranja.
# ============================================================

import json
import asyncio
from itertools import count
from datetime import datetime, timezone

from aiohttp import web

import monitoring

MAX_HIST = 50  # koliko zadnjih poruka pamtimo po sesiji (za kontekst)

_loop = None        # aiohttp event loop (postavlja se u configure)
_on_client = None   # callback(session_id, ime, text) -> generira AI odgovor
_on_zatvoreno = None  # callback(session_id) -> pospremi (npr. obrisi povijest)
_sessions = {}      # id(str) -> Session
_seq = count(1)     # izvor kratkih numerickih id-eva


def _log(m):
    print(f"[podrska] {m}", flush=True)


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


class Session:
    def __init__(self, sid, ime):
        self.id = sid
        self.ime = ime
        self.queue = asyncio.Queue()   # poruke podrska -> klijent
        self.hist = []                 # [(tko, tekst, vrijeme)]
        self.otvoreno = datetime.now(timezone.utc)


def configure(loop, on_client=None):
    """Pozvano iz web_api._run kad je aiohttp loop kreiran. Sprema loop (za
    thread-safe predaju poruka) i opcionalno callback prema Telegramu."""
    global _loop, _on_client
    _loop = loop
    if on_client is not None:
        _on_client = on_client
    _log("konfiguriran (loop postavljen)")


def set_on_client(cb):
    global _on_client
    _on_client = cb


def set_on_zatvoreno(cb):
    global _on_zatvoreno
    _on_zatvoreno = cb


# ==================== WEBSOCKET (klijent <-> podrska) ====================

async def ws_handler(request):
    """WebSocket ruta za klijenta (Flota OS). Prima {tekst:...} i forwarda na
    Telegram; sve poruke podrske iz sesijinog reda salje natrag klijentu."""
    ws = web.WebSocketResponse(heartbeat=30)
    await ws.prepare(request)

    ime = (request.query.get("ime") or "Korisnik").strip()[:60] or "Korisnik"
    sid = str(next(_seq))
    sess = Session(sid, ime)
    _sessions[sid] = sess
    _log(f"nova sesija #{sid} ({ime})")

    await ws.send_json({"tip": "sustav", "session": sid,
                        "tekst": "Podrška Flota OS (AI asistent). Kako vam mogu pomoći?",
                        "vrijeme": _now_iso()})

    async def pump():
        """Salje poruke podrske (iz reda) klijentu."""
        try:
            while True:
                item = await sess.queue.get()
                if item is None:
                    break
                await ws.send_json(item)
        except Exception:
            pass

    pump_task = asyncio.ensure_future(pump())
    try:
        async for msg in ws:
            if msg.type == web.WSMsgType.TEXT:
                try:
                    data = json.loads(msg.data)
                    text = (data.get("tekst") or data.get("text") or "").strip()
                except Exception:
                    text = (msg.data or "").strip()
                if not text:
                    continue
                sess.hist.append(("klijent", text, _now_iso()))
                del sess.hist[:-MAX_HIST]
                await _forward(sid, ime, text)
            elif msg.type == web.WSMsgType.ERROR:
                break
    finally:
        sess.queue.put_nowait(None)
        pump_task.cancel()
        _sessions.pop(sid, None)
        if _on_zatvoreno:
            try:
                _on_zatvoreno(sid)
            except Exception:
                pass
        _log(f"zatvorena sesija #{sid}")
    return ws


async def _forward(sid, ime, text):
    """Forwardaj korisnikovu poruku na Telegram (u executoru — telebot je
    blokirajuci; ne smije blokirati aiohttp loop). Cuva redoslijed (await)."""
    if not _on_client:
        return
    try:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, _safe_on_client, sid, ime, text)
    except Exception as e:
        monitoring.warning(f"podrska forward: {e}", source="podrska")


def _safe_on_client(sid, ime, text):
    try:
        if _on_client:
            _on_client(sid, ime, text)
    except Exception as e:
        monitoring.error("podrska on_client callback", source="podrska", exc=e)


# ==================== PODRSKA -> KLIJENT (iz Telegram threada) ====================

def posalji_klijentu(session_id, text, od="Podrška"):
    """Thread-safe: ubaci poruku podrske u WS klijenta. Vrati True ako sesija
    postoji (klijent spojen), False inace. Zove se iz glavnog (Telegram) threada."""
    sess = _sessions.get(str(session_id))
    if not sess or _loop is None:
        return False
    item = {"tip": "podrska", "od": od, "tekst": text, "vrijeme": _now_iso()}
    sess.hist.append(("podrska", text, item["vrijeme"]))
    try:
        _loop.call_soon_threadsafe(sess.queue.put_nowait, item)
        return True
    except Exception as e:
        monitoring.warning(f"podrska posalji_klijentu: {e}", source="podrska")
        return False


def aktivne():
    """Popis aktivnih sesija (za /podrska bez argumenata)."""
    out = []
    for sid, s in list(_sessions.items()):
        zadnja = s.hist[-1][1] if s.hist else ""
        out.append({"id": sid, "ime": s.ime,
                    "otvoreno": s.otvoreno.astimezone(timezone.utc).isoformat(),
                    "zadnja": zadnja})
    return out


# ==================== DEMO / TEST STRANICA ====================
#  Samostalna (bez vanjskih resursa) HTML chat stranica za testiranje bez
#  Flota OS frontenda. Spaja se na /api/podrska/ws?key=...&ime=...

DEMO_HTML = """<!doctype html>
<html lang="hr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Podrška — Flota OS (demo)</title>
<style>
 body{font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;margin:0;
   background:#0f172a;color:#e2e8f0;display:flex;flex-direction:column;height:100vh}
 header{padding:12px 16px;background:#111827;border-bottom:1px solid #1f2937;font-weight:600}
 #log{flex:1;overflow-y:auto;padding:16px;display:flex;flex-direction:column;gap:8px}
 .m{max-width:78%;padding:8px 12px;border-radius:12px;line-height:1.4;white-space:pre-wrap}
 .ja{align-self:flex-end;background:#2563eb;color:#fff;border-bottom-right-radius:3px}
 .pod{align-self:flex-start;background:#1f2937;border-bottom-left-radius:3px}
 .sys{align-self:center;color:#94a3b8;font-size:13px;background:transparent}
 form{display:flex;gap:8px;padding:12px;background:#111827;border-top:1px solid #1f2937}
 input{flex:1;padding:10px 12px;border-radius:10px;border:1px solid #334155;
   background:#0b1220;color:#e2e8f0;font-size:15px}
 button{padding:10px 16px;border:0;border-radius:10px;background:#2563eb;color:#fff;
   font-weight:600;cursor:pointer}
 .setup{padding:16px;display:flex;gap:8px;flex-wrap:wrap;background:#111827;
   border-bottom:1px solid #1f2937}
</style></head><body>
<header>🆘 Podrška — Flota OS <span id="st" style="float:right;font-weight:400;color:#94a3b8">nije spojeno</span></header>
<div class="setup">
  <input id="key" placeholder="FLOTA_OS_KEY" style="flex:1;min-width:160px">
  <input id="ime" placeholder="Vaše ime" value="Dispečer" style="width:160px">
  <button id="spoji">Spoji se</button>
</div>
<div id="log"></div>
<form id="f"><input id="t" placeholder="Napišite poruku…" autocomplete="off" disabled>
  <button disabled>Pošalji</button></form>
<script>
 var ws=null;
 function add(txt,cls){var d=document.getElementById('log');var e=document.createElement('div');
   e.className='m '+cls;e.textContent=txt;d.appendChild(e);d.scrollTop=d.scrollHeight;}
 function conn(){
   var key=document.getElementById('key').value.trim();
   var ime=encodeURIComponent(document.getElementById('ime').value.trim()||'Dispečer');
   var proto=location.protocol==='https:'?'wss':'ws';
   var url=proto+'://'+location.host+'/api/podrska/ws?key='+encodeURIComponent(key)+'&ime='+ime;
   ws=new WebSocket(url);
   ws.onopen=function(){document.getElementById('st').textContent='spojeno';
     document.getElementById('t').disabled=false;
     document.querySelector('#f button').disabled=false;};
   ws.onclose=function(){document.getElementById('st').textContent='veza prekinuta';
     document.getElementById('t').disabled=true;};
   ws.onmessage=function(ev){var m=JSON.parse(ev.data);
     if(m.tip==='sustav'){add(m.tekst,'sys');}
     else{add((m.od?m.od+': ':'')+m.tekst,'pod');}};
 }
 document.getElementById('spoji').onclick=conn;
 document.getElementById('f').onsubmit=function(e){e.preventDefault();
   var t=document.getElementById('t');var v=t.value.trim();
   if(!v||!ws||ws.readyState!==1)return;
   ws.send(JSON.stringify({tekst:v}));add(v,'ja');t.value='';};
</script></body></html>"""


async def handle_demo(request):
    return web.Response(text=DEMO_HTML, content_type="text/html", charset="utf-8")
