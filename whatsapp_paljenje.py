"""WhatsApp potvrda vozača na PALJENJE kamiona (živa evidencija „tko vozi što").

Scheduler prati stanje motora svih kamiona (Mobilisis) i kad kamion prijeđe iz
UGAŠENO → UPALJENO (novi početak smjene), pošalje predložak `potvrda_vozila`
ZADNJEM vozaču tog kamiona (Flota OS /api/flota/zadnji-vozac):

    „Bok Ivan, upalio se kamion GB363. Voziš li ga danas?"  [Da, vozim] [Ne vozim]

Vozačev odgovor (gumb, „ne", ili broj drugog kamiona) piše se NATRAG u Flotu OS
(flota_zapisi_potvrdu), pa `zadnji-vozac` odmah vidi živu istinu.

SIGURNOST / TROŠAK: svaka poruka je naplativi predložak, pa je cijela funkcija
iza prekidača WHATSAPP_IGNITION_ON=1 (default OFF) i s „debounce" logikom
(jednom po smjeni): okida se samo ako je kamion bio ugašen dulje od
WHATSAPP_IGNITION_OFF_SATI (default 6 h) I ako za taj kamion nismo slali
obavijest zadnjih WHATSAPP_IGNITION_TIHI_SATI (default 16 h).

Postavke (env):
  WHATSAPP_IGNITION_ON            "1" = uključeno (default off)
  WHATSAPP_IGNITION_POLL_SEC      razmak provjere pozicija (default 180 s)
  WHATSAPP_IGNITION_OFF_SATI      koliko dugo ugašen da se broji kao smjena (6)
  WHATSAPP_IGNITION_TIHI_SATI     min. razmak obavijesti po kamionu (16)
  WHATSAPP_IGNITION_UPIT_SATI     koliko dugo vrijedi otvoreni upit vozaču (20)
  WHATSAPP_IGNITION_SAMO_GB       (test) samo ovi GB-ovi, zarezom; prazno = svi
"""

import os
import time
import unicodedata

import mobilisis
import whatsapp
import whatsapp_racuni
import monitoring


def _log(msg):
    print(f"[wa_paljenje] {msg}", flush=True)


# ---- injektirane ovisnosti iz main.py (da izbjegnemo kružni import) ----
_db = None                 # tvornica konekcija (main.db)
_flota_get = None          # main._flota_os_get(path, params) -> dict
_flota_zapisi = None       # main.flota_zapisi_potvrdu(gb, vozac, vozi) -> dict


def konfiguriraj(db_factory, flota_get, flota_zapisi):
    """Pozvati JEDNOM iz main.py nakon inicijalizacije baze i Flota OS helpera."""
    global _db, _flota_get, _flota_zapisi
    _db = db_factory
    _flota_get = flota_get
    _flota_zapisi = flota_zapisi
    _init_tablice()


# ==================== POSTAVKE ====================

def _ukljuceno():
    return os.getenv("WHATSAPP_IGNITION_ON", "").strip() == "1"


def _poll_sec():
    try:
        return max(60, int(os.getenv("WHATSAPP_IGNITION_POLL_SEC", "180")))
    except ValueError:
        return 180


def _off_prag_s():
    try:
        return float(os.getenv("WHATSAPP_IGNITION_OFF_SATI", "6")) * 3600.0
    except ValueError:
        return 6 * 3600.0


def _tihi_prag_s():
    try:
        return float(os.getenv("WHATSAPP_IGNITION_TIHI_SATI", "16")) * 3600.0
    except ValueError:
        return 16 * 3600.0


def _upit_valjan_s():
    try:
        return float(os.getenv("WHATSAPP_IGNITION_UPIT_SATI", "20")) * 3600.0
    except ValueError:
        return 20 * 3600.0


def _samo_gb():
    """Skup GB-ova za nadzor (test); prazno = svi kamioni."""
    raw = os.getenv("WHATSAPP_IGNITION_SAMO_GB", "")
    return {g.strip().lstrip("0") or g.strip()
            for g in raw.replace(";", ",").split(",") if g.strip()}


# ==================== BAZA ====================

def _init_tablice():
    with _db() as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS ignition_state (
                gb            TEXT PRIMARY KEY,
                motor         INTEGER,   -- zadnje viđeno stanje (1/0)
                off_od_ts     REAL,      -- otkad je motor ugašen (za prag >6 h)
                zadnja_obav_ts REAL      -- kad smo zadnji put slali obavijest
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS ignition_upit (
                broj   TEXT PRIMARY KEY,  -- vozačev telefon (385…)
                gb     TEXT,             -- kamion o kojem smo pitali
                vozac  TEXT,             -- ime vozača kojeg smo pitali
                stanje TEXT,             -- 'pitano' | 'ceka_gb'
                ts     REAL              -- kad smo pitali
            )
        """)


def _stanje_map():
    with _db() as c:
        rows = c.execute(
            "SELECT gb, motor, off_od_ts, zadnja_obav_ts FROM ignition_state"
        ).fetchall()
    return {r["gb"]: r for r in rows}


def _spremi_stanje(gb, motor, off_od_ts, zadnja_obav_ts):
    with _db() as c:
        c.execute(
            "INSERT INTO ignition_state (gb, motor, off_od_ts, zadnja_obav_ts) "
            "VALUES (?,?,?,?) ON CONFLICT(gb) DO UPDATE SET "
            "motor=excluded.motor, off_od_ts=excluded.off_od_ts, "
            "zadnja_obav_ts=excluded.zadnja_obav_ts",
            (gb, motor, off_od_ts, zadnja_obav_ts))


def _postavi_upit(broj, gb, vozac):
    with _db() as c:
        c.execute(
            "INSERT INTO ignition_upit (broj, gb, vozac, stanje, ts) "
            "VALUES (?,?,?,?,?) ON CONFLICT(broj) DO UPDATE SET "
            "gb=excluded.gb, vozac=excluded.vozac, stanje=excluded.stanje, "
            "ts=excluded.ts",
            (broj, gb, vozac, "pitano", time.time()))


def _dohvati_upit(broj):
    with _db() as c:
        r = c.execute(
            "SELECT broj, gb, vozac, stanje, ts FROM ignition_upit WHERE broj=?",
            (broj,)).fetchone()
    if not r:
        return None
    if time.time() - (r["ts"] or 0) > _upit_valjan_s():
        _obrisi_upit(broj)   # istekao
        return None
    return r


def _upit_stanje(broj, stanje):
    with _db() as c:
        c.execute("UPDATE ignition_upit SET stanje=? WHERE broj=?", (stanje, broj))


def _obrisi_upit(broj):
    with _db() as c:
        c.execute("DELETE FROM ignition_upit WHERE broj=?", (broj,))


# ==================== MAPIRANJE IMENA → TELEFON ====================

def _norm_ime(s):
    """Normaliziraj ime za usporedbu: bez dijakritike, mala slova, jedan razmak."""
    s = unicodedata.normalize("NFKD", str(s or ""))
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return " ".join(s.lower().split())


def _telefon_za_ime(ime):
    """Nađi vozačev WhatsApp broj iz WHATSAPP_DRIVERS po imenu (bez dijakritike).
    Vrati broj (385…) ili None."""
    cilj = _norm_ime(ime)
    if not cilj:
        return None
    for broj, (dime, _gb) in whatsapp_racuni._drivers_map().items():
        if dime and _norm_ime(dime) == cilj:
            return broj
    return None


def _fmt_gb(gb):
    g = str(gb or "").strip()
    if not g:
        return g
    return g if g.upper().startswith("GB") else f"GB{g}"


# ==================== SCHEDULER (praćenje paljenja) ====================

_zadnji_poll = 0.0


def tick():
    """Pozvati često (npr. iz check_reminders svakih 10 s). Sam odlučuje je li
    vrijeme za novu provjeru pozicija; NE blokira — teški dio ide u nit."""
    global _zadnji_poll
    if not _ukljuceno():
        return
    now = time.time()
    if now - _zadnji_poll < _poll_sec():
        return
    _zadnji_poll = now
    import threading
    threading.Thread(target=obradi_ciklus, daemon=True).start()


def obradi_ciklus():
    """Jedan prolaz: dohvati pozicije, otkrij prijelaze ugašeno→upaljeno i
    (uz debounce) pošalji potvrdu zadnjem vozaču. Best-effort; nikad ne baca."""
    if not _ukljuceno():
        return
    try:
        pozicije = mobilisis.all_positions()
    except Exception as e:
        monitoring.warning(f"Paljenje: pozicije nedostupne: {e}", source="wa_paljenje")
        return

    samo = _samo_gb()
    off_prag = _off_prag_s()
    tihi_prag = _tihi_prag_s()
    now = time.time()
    stanja = _stanje_map()

    for p in pozicije:
        gb = p.get("gb")
        motor = p.get("motor")
        if not gb or motor is None:
            continue
        gb = str(gb).strip()
        if samo and (gb.lstrip("0") or gb) not in samo:
            continue

        motor_i = 1 if motor else 0
        prosli = stanja.get(gb)

        # Prvi put viđen kamion → samo zapamti stanje (bez okidanja).
        if prosli is None:
            off_od = None if motor_i else now
            _spremi_stanje(gb, motor_i, off_od, None)
            continue

        prev_motor = prosli["motor"]
        off_od = prosli["off_od_ts"]
        zadnja_obav = prosli["zadnja_obav_ts"]

        if motor_i == 0:
            # Ugašeno: zapamti otkad (ako je upravo ugašen).
            if prev_motor != 0 or off_od is None:
                off_od = now
            _spremi_stanje(gb, 0, off_od, zadnja_obav)
            continue

        # Motor UPALJEN.
        if prev_motor == 1:
            # I dalje upaljen — ništa novo.
            _spremi_stanje(gb, 1, off_od, zadnja_obav)
            continue

        # PRIJELAZ ugašeno → upaljeno.
        bio_ugasen = (now - off_od) if off_od else 0
        tiho_ok = (zadnja_obav is None) or (now - zadnja_obav >= tihi_prag)
        smjena_ok = bio_ugasen >= off_prag

        if smjena_ok and tiho_ok:
            poslano = _posalji_potvrdu(gb)
            _spremi_stanje(gb, 1, None, now if poslano else zadnja_obav)
        else:
            _log(f"GB{gb} paljenje preskočeno (ugašen {int(bio_ugasen/60)} min, "
                 f"tiho_ok={tiho_ok}).")
            _spremi_stanje(gb, 1, None, zadnja_obav)


def _posalji_potvrdu(gb):
    """Nađi zadnjeg vozača za GB, mapiraj na telefon i pošalji predložak.
    Vrati True ako je poruka poslana."""
    odg = _flota_get("/api/flota/zadnji-vozac", {"gb": gb}) or {}
    vozac = odg.get("vozac")
    if not vozac:
        _log(f"GB{gb}: nema zadnjeg vozača (Flota OS) — preskačem.")
        return False
    broj = _telefon_za_ime(vozac)
    if not broj:
        _log(f"GB{gb}: vozač '{vozac}' nema WhatsApp broj (WHATSAPP_DRIVERS) — preskačem.")
        monitoring.warning(
            f"Paljenje GB{gb}: vozač '{vozac}' nije u WHATSAPP_DRIVERS",
            source="wa_paljenje")
        return False

    ime_kratko = vozac.split()[0] if vozac.split() else vozac
    res = whatsapp.send_template(
        broj, "potvrda_vozila", "hr",
        components=[{"type": "body", "parameters": [
            {"type": "text", "text": ime_kratko},
            {"type": "text", "text": _fmt_gb(gb)},
        ]}])
    if res.get("ok"):
        _postavi_upit(broj, gb, vozac)
        _log(f"GB{gb}: poslana potvrda vozaču {vozac} ({broj}).")
        return True
    _log(f"GB{gb}: slanje potvrde nije uspjelo: {res.get('data')}")
    return False


# ==================== OBRADA ODGOVORA VOZAČA ====================

_DA = {"da", "da vozim", "da, vozim", "vozim", "✅"}
_NE = {"ne", "ne vozim", "nisam", "❌"}
_ODUSTANI = {"-", "ne danas", "ne vozim danas", "nijedan", "nista", "ništa"}


def _parse_gb(tekst):
    """Ako tekst izgleda kao broj kamiona (npr. '401', 'GB 401', 'gb401') →
    vrati normaliziran GB (znamenke), inače None."""
    t = str(tekst or "").strip().lower()
    if t.startswith("gb"):
        t = t[2:]
    t = t.strip().lstrip("-").strip()
    digits = "".join(ch for ch in t if ch.isdigit())
    # cijeli ostatak (bez razmaka) mora biti znamenke, da ne uhvatimo npr. „ok"
    if digits and t.replace(" ", "") == digits:
        return digits
    return None


def obradi_odgovor(frm, ime, msg):
    """Ako za ovaj broj postoji otvoreni upit o paljenju, obradi odgovor i vrati
    True (poruka je „potrošena"). Inače vrati False (neka ide dalje na račune).

    Slike NIKAD ne hvatamo (to je račun) — vraćamo False."""
    if _db is None:
        return False
    try:
        upit = _dohvati_upit(frm)
    except Exception as e:
        monitoring.warning(f"Paljenje: čitanje upita: {e}", source="wa_paljenje")
        return False
    if not upit:
        return False

    tip = msg.get("type")
    # Tekst iz gumba predloška dolazi kao type 'button'; interaktivni kao
    # 'interactive'; obični tekst kao 'text'. Slike/dokumenti → nije odgovor.
    if tip == "button":
        tekst = (msg.get("button") or {}).get("text", "")
    elif tip == "interactive":
        inter = msg.get("interactive") or {}
        tekst = ((inter.get("button_reply") or {}).get("title")
                 or (inter.get("button_reply") or {}).get("id")
                 or (inter.get("list_reply") or {}).get("title") or "")
    elif tip == "text":
        tekst = (msg.get("text") or {}).get("body", "")
    else:
        return False   # slika/audio/…: ne diramo (ide na račune)

    try:
        _rijesi(frm, upit, tekst)
    except Exception as e:
        monitoring.error("Paljenje: obrada odgovora", source="wa_paljenje", exc=e)
    return True


def _rijesi(frm, upit, tekst):
    gb = upit["gb"]
    vozac = upit["vozac"]
    stanje = upit["stanje"]
    low = " ".join(str(tekst or "").lower().split())
    novi_gb = _parse_gb(tekst)

    # 1) Vozač je upisao broj DRUGOG kamiona → ispravak.
    if novi_gb and novi_gb.lstrip("0") != str(gb).lstrip("0"):
        if stanje == "pitano":
            _flota_zapisi(gb, vozac, False)      # nije na kamionu o kojem smo pitali
        _flota_zapisi(novi_gb, vozac, True)      # vozi ovaj
        _obrisi_upit(frm)
        whatsapp.send_text(
            frm, f"✅ Zabilježeno: voziš kamion {_fmt_gb(novi_gb)}. Hvala!")
        return

    # 2) „Da, vozim" (ili isti GB) → potvrda.
    if low in _DA or (novi_gb and novi_gb.lstrip("0") == str(gb).lstrip("0")):
        _flota_zapisi(gb, vozac, True)
        _obrisi_upit(frm)
        whatsapp.send_text(
            frm, f"✅ Super, hvala! Zabilježeno da voziš kamion {_fmt_gb(gb)}.")
        return

    # 3) „Ne vozim" → zapiši da nije, pa pitaj koji kamion vozi.
    if low in _NE:
        _flota_zapisi(gb, vozac, False)
        _upit_stanje(frm, "ceka_gb")
        whatsapp.send_text(
            frm, "U redu. Koji kamion voziš danas? Upiši broj (npr. 401), "
                 "ili napiši „-” ako danas ne voziš.")
        return

    # 4) Nakon „Ne vozim" — odustajanje (ne vozi ništa danas).
    if stanje == "ceka_gb" and low in _ODUSTANI:
        _obrisi_upit(frm)
        whatsapp.send_text(frm, "U redu, hvala. Ugodan dan! 👋")
        return

    # 5) Neprepoznato dok upit stoji → blagi podsjetnik.
    if stanje == "ceka_gb":
        whatsapp.send_text(
            frm, "Upiši broj kamiona koji voziš (npr. 401), ili „-” ako danas ne voziš.")
    else:
        whatsapp.send_text(
            frm, f"Voziš li danas kamion {_fmt_gb(gb)}? Napiši „da” ili „ne”, "
                 "ili upiši broj kamiona koji voziš.")
