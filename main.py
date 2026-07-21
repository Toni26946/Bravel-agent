# ============================================================
#  BRAVEL AGENT - Telegram bot
#  - SQLite persistencija na Fly Volume (/data/bot.db)
#  - Podsjetnici: jednokratni, dnevni, tjedni, svaka N dana,
#    svaki N. tjedan, mjesecni
#  - Odgoda podsjetnika gumbima (+15 min, +1 h, +3 h, sutra)
#  - AI razgovor (Claude) s pamcenjem konteksta po korisniku
# ============================================================

import os
import re
import time
import json
import sqlite3
import calendar
import threading
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import telebot
import anthropic
import requests

import monitoring  # slanje gresaka/logova zasebnom monitoring botu (no-op ako nije konfiguriran)
import racuni      # obrada fotki racuna + upis u Excel na SharePointu
import backup      # dnevni backup bot.db na SharePoint
import mobilisis   # GPS pozicije vozila (Mobilisis Fleet) za /gdje
import whatsapp    # WhatsApp Cloud API (registracija broja, slanje) — admin komande
import whatsapp_racuni  # Faza 1: obrada računa/primki preko WhatsAppa (zaposlenici)
import whatsapp_meni  # WhatsApp izbornik/upravljačka ploča za vozače/radnike
import whatsapp_podsjetnici  # automatski tjedni podsjetnici vozačima (predlošci)
import benzinske   # registar benzinskih lanaca + praćenje cijena goriva
import podrska     # živi chat (podrška) za internu Flotu OS
import web_api     # lagani HTTP server (GET /api/pozicije, /zdrav)

# ==================== KONFIGURACIJA ====================

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
bot = telebot.TeleBot(TELEGRAM_TOKEN)

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

# Whitelist: prvo pokusaj iz env varijable ALLOWED_USERS="123,456",
# ako je nema koristi hardkodiranu listu. Novog radnika dodajes sa:
#   fly secrets set ALLOWED_USERS=5191857104,7599693099,NOVI_ID
_env_users = os.getenv("ALLOWED_USERS", "")
if _env_users.strip():
    ALLOWED_USERS = [int(x) for x in _env_users.split(",") if x.strip()]
else:
    ALLOWED_USERS = [5191857104, 7599693099]

DB_FILE = "/data/bot.db" if os.path.isdir("/data") else "bot.db"

TZ = ZoneInfo("Europe/Zagreb")

HISTORY_LIMIT = 20  # zadnjih 20 poruka (10 izmjena) AI povijesti po korisniku
history = {}
history_lock = threading.Lock()

DAY_NAMES_SHORT = ["Pon", "Uto", "Sri", "Čet", "Pet", "Sub", "Ned"]
DAY_NAMES_INSTR = ["ponedjeljkom", "utorkom", "srijedom", "četvrtkom",
                   "petkom", "subotom", "nedjeljom"]


def get_now():
    return datetime.now(TZ)


# ==================== BAZA (SQLite) ====================
# Konekcija po operaciji + WAL mode = thread-safe bez rucnih lockova.

def db():
    conn = sqlite3.connect(DB_FILE, timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS reminders (
                id      INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                text    TEXT    NOT NULL,
                time_ts REAL    NOT NULL,   -- unix timestamp, pouzdan za usporedbu
                fired   INTEGER DEFAULT 0   -- 1 = poslan (ceka eventualnu odgodu)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS recurring (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id    INTEGER NOT NULL,
                text       TEXT    NOT NULL,
                rtype      TEXT    NOT NULL,     -- 'daily' / 'weekly' / 'monthly'
                weekday    INTEGER,               -- 0=pon..6=ned (weekly)
                hour       INTEGER NOT NULL,
                minute     INTEGER NOT NULL,
                interval_n INTEGER DEFAULT 1,     -- svaka N dana / svaki N. tjedan
                anchor_ts  REAL,                  -- datum prvog okidanja (za interval)
                monthday   INTEGER,               -- dan u mjesecu (monthly)
                last_fired TEXT                   -- 'YYYY-MM-DD HH:MM' zadnjeg okidanja
            )
        """)
        # Dnevni log za izvjestaj: zabiljeske rada (kind='note') i poruke AI
        # razgovora (kind='user'/'assistant'). 'day' je datum u Europe/Zagreb
        # radi jednostavnog upita "sve od danas".
        conn.execute("""
            CREATE TABLE IF NOT EXISTS daily_log (
                id      INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                day     TEXT    NOT NULL,   -- 'YYYY-MM-DD' (Europe/Zagreb)
                ts      REAL    NOT NULL,   -- unix timestamp (za poredak)
                kind    TEXT    NOT NULL,   -- 'note' | 'user' | 'assistant'
                text    TEXT    NOT NULL
            )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_daily_log_lookup "
            "ON daily_log (chat_id, day)"
        )
    # Migracija starije baze (dodavanje stupaca ako ne postoje)
    with db() as conn:
        for stmt in [
            "ALTER TABLE reminders ADD COLUMN fired INTEGER DEFAULT 0",
            "ALTER TABLE recurring ADD COLUMN interval_n INTEGER DEFAULT 1",
            "ALTER TABLE recurring ADD COLUMN anchor_ts REAL",
            "ALTER TABLE recurring ADD COLUMN monthday INTEGER",
        ]:
            try:
                conn.execute(stmt)
            except sqlite3.OperationalError:
                pass  # stupac vec postoji
    print(f"Baza spremna: {DB_FILE}")


def add_reminder(chat_id, text, dt):
    with db() as conn:
        conn.execute(
            "INSERT INTO reminders (chat_id, text, time_ts) VALUES (?, ?, ?)",
            (chat_id, text, dt.timestamp())
        )


def first_occurrence(rtype, hour, minute, weekday=None):
    """Prvi datum/vrijeme kada ponavljajuci podsjetnik treba okinuti."""
    now = get_now()
    t = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if rtype == "daily":
        if t <= now:
            t += timedelta(days=1)
    elif rtype == "weekly":
        t += timedelta(days=(weekday - now.weekday()) % 7)
        if t <= now:
            t += timedelta(days=7)
    return t


def add_recurring(chat_id, text, rtype, hour, minute,
                  weekday=None, interval=1, monthday=None):
    anchor_ts = None
    if rtype in ("daily", "weekly"):
        first = first_occurrence(rtype, hour, minute, weekday)
        # anchor = ponoc dana prvog okidanja (za racunanje intervala)
        anchor_ts = first.replace(hour=0, minute=0).timestamp()
    with db() as conn:
        conn.execute(
            "INSERT INTO recurring (chat_id, text, rtype, weekday, hour, minute, "
            "interval_n, anchor_ts, monthday) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (chat_id, text, rtype, weekday, hour, minute, interval, anchor_ts, monthday)
        )


def get_user_items(chat_id):
    """Vraca (jednokratni, ponavljajuci) za korisnika, deterministicki poredano."""
    with db() as conn:
        once = conn.execute(
            "SELECT * FROM reminders WHERE chat_id = ? AND fired = 0 "
            "ORDER BY time_ts, id",
            (chat_id,)
        ).fetchall()
        rec = conn.execute(
            "SELECT * FROM recurring WHERE chat_id = ? ORDER BY id",
            (chat_id,)
        ).fetchall()
    return once, rec


# ==================== DNEVNI LOG ====================
# Broj dana koliko cuvamo zapise; stariji se brisu kod izrade izvjestaja.
RETENTION_DAYS = 30


def _log(chat_id, kind, text):
    now = get_now()
    with db() as conn:
        conn.execute(
            "INSERT INTO daily_log (chat_id, day, ts, kind, text) VALUES (?, ?, ?, ?, ?)",
            (chat_id, now.strftime('%Y-%m-%d'), now.timestamp(), kind, text)
        )


def log_note(chat_id, text):
    _log(chat_id, "note", text)


def log_chat(chat_id, role, text):
    # role je 'user' ili 'assistant'
    _log(chat_id, role, text)


def get_today_log(chat_id):
    today = get_now().strftime('%Y-%m-%d')
    with db() as conn:
        return conn.execute(
            "SELECT kind, text, ts FROM daily_log WHERE chat_id = ? AND day = ? "
            "ORDER BY ts, id",
            (chat_id, today)
        ).fetchall()


def cleanup_old_logs():
    cutoff = get_now().timestamp() - RETENTION_DAYS * 86400
    with db() as conn:
        conn.execute("DELETE FROM daily_log WHERE ts < ?", (cutoff,))


# ==================== PARSIRANJE VREMENA ====================

def _make_description(original, spans):
    """Izbaci vremenske dijelove (spans) iz teksta i vrati cisti opis."""
    spans = sorted(spans)
    parts, prev = [], 0
    for s, e in spans:
        if s < prev:
            prev = max(prev, e)  # preklapajuci span - prosiri brisanje
            continue
        parts.append(original[prev:s])
        prev = e
    parts.append(original[prev:])
    desc = re.sub(r'\s+', ' ', ''.join(parts)).strip(' ,.;:-–—')
    # makni uvodne fraze tipa "podsjeti me (da)" iz opisa
    desc = re.sub(r'^(podsjeti\s+me\s+(da\s+)?|podsjetnik[:,]?\s*)', '', desc,
                  flags=re.IGNORECASE).strip(' ,.;:-–—')
    if not desc:
        return "Podsjetnik"
    return desc[0].upper() + desc[1:]


TIME_RE = r'(?:u|at|oko)\s*(\d{1,2})[:.]?(\d{2})?'

ORDINALS = {"drug": 2, "treć": 3, "četvrt": 4, "pet": 5, "šest": 6}

WEEKDAYS = [("ponedjeljak", 0), ("utorak", 1), ("srijeda", 2), ("četvrtak", 3),
            ("petak", 4), ("subota", 5), ("nedjelja", 6),
            ("pon", 0), ("uto", 1), ("sri", 2), ("čet", 3),
            ("pet", 4), ("sub", 5), ("ned", 6)]


def _find_weekday(low):
    """Nadji dan u tjednu u tekstu. Vraca (weekday, span) ili (None, None).
    \\b granice: 'pon' ne matcha 'ponuda', 'pet' ne matcha 'petsto'.
    Duzi nazivi prvi da 'ponedjeljak' ne bude prepoznat kao 'pon'."""
    for name, wd in WEEKDAYS:
        m = re.search(r'\b' + name + r'\b', low)
        if m:
            return wd, m.span()
    return None, None


def _interval_from(numstr, wordstr):
    if numstr:
        return int(numstr)
    if wordstr:
        for prefix, val in ORDINALS.items():
            if wordstr.startswith(prefix):
                return val
    return 1


def parse_time(text):
    """Vraca (rezultat, tip, opis).
    tip: 'once' (rezultat=datetime) / 'daily'/'weekly'/'monthly' (rezultat=dict) / None"""
    original = text.strip()
    low = original.lower()
    now = get_now()

    # 1. Konkretan datum: "7.7. u 10:30", ali i razdvojeno: "8.7. za tenis u 16"
    #    (?!\w) sprjecava da "12.5mm" bude prepoznat kao datum
    dm = re.search(r'\b(\d{1,2})[\./](\d{1,2})(?:[\./](\d{2,4}))?\.?(?!\w)', low)
    if dm:
        day, month = int(dm.group(1)), int(dm.group(2))
        year = int(dm.group(3)) if dm.group(3) else now.year
        if year < 100:
            year += 2000
        if 1 <= day <= 31 and 1 <= month <= 12:
            # vrijeme moze biti bilo gdje u poruci, samo ne unutar samog datuma
            tm = None
            for cand in re.finditer(TIME_RE, low):
                if cand.start() >= dm.end() or cand.end() <= dm.start():
                    tm = cand
                    break
            if tm:
                hour, minute = int(tm.group(1)), int(tm.group(2) or 0)
                try:
                    target = datetime(year, month, day, hour, minute, tzinfo=TZ)
                    if target < now:
                        target = target.replace(year=target.year + 1)
                    return target, "once", _make_description(original, [dm.span(), tm.span()])
                except Exception:
                    pass

    # 2. Mjesecno: "svaki mjesec 15. u 9" / "svakog 15. u mjesecu u 9"
    #    / "zadnji dan u mjesecu u 20"
    zm = re.search(r'zadnj\w+\s+dan\w*', low)
    mk = (re.search(r'svak\w*\s+mjesec\w*', low)
          or re.search(r'\bu\s+mjesecu\b', low)
          or (zm and re.search(r'\bmjesec\w*', low)))
    if mk:
        tm = re.search(TIME_RE, low)
        if tm:
            spans = [mk.span(), tm.span()]
            sk = re.search(r'\bsvak\w*\b', low)
            if sk and sk.span() != mk.span():
                spans.append(sk.span())
            if zm:
                monthday = 32  # 32 = zadnji dan u mjesecu (sentinel)
                spans.append(zm.span())
            else:
                dmm = re.search(r'\b(\d{1,2})\.(?!\d)', low)
                if dmm:
                    monthday = int(dmm.group(1))
                    spans.append(dmm.span())
                else:
                    monthday = now.day
            if 1 <= monthday <= 32:
                payload = {"monthday": monthday,
                           "hour": int(tm.group(1)), "minute": int(tm.group(2) or 0)}
                return payload, "monthly", _make_description(original, spans)

    # 3. Svaki N. tjedan / svaki drugi tjedan / svaki tjedan (+ opcionalni dan)
    wk = re.search(r'svak\w*\s+(?:(\d+)\.?\s*|([a-zčćšđž]+)\s+)?tjed\w*', low)
    if wk:
        tm = re.search(TIME_RE, low)
        if tm:
            interval = _interval_from(wk.group(1), wk.group(2))
            wd, wd_span = _find_weekday(low)
            spans = [wk.span(), tm.span()]
            if wd_span:
                spans.append(wd_span)
            if wd is None:
                wd = now.weekday()  # nije naveden dan -> danasnji dan u tjednu
            payload = {"weekday": wd, "interval": interval,
                       "hour": int(tm.group(1)), "minute": int(tm.group(2) or 0)}
            return payload, "weekly", _make_description(original, spans)

    # 4. Svaka N dana / svaki drugi dan
    dk = re.search(r'svak\w*\s+(?:(\d+)\.?\s*|([a-zčćšđž]+)\s+)dan\w*', low)
    if dk:
        tm = re.search(TIME_RE, low)
        if tm:
            interval = _interval_from(dk.group(1), dk.group(2))
            payload = {"interval": interval,
                       "hour": int(tm.group(1)), "minute": int(tm.group(2) or 0)}
            return payload, "daily", _make_description(original, [dk.span(), tm.span()])

    # 5. Svaki dan
    for kw in ["svaki dan", "svakodnevno", "daily"]:
        kw_pos = low.find(kw)
        if kw_pos != -1:
            tm = re.search(TIME_RE, low)
            if tm:
                payload = {"interval": 1,
                           "hour": int(tm.group(1)), "minute": int(tm.group(2) or 0)}
                desc = _make_description(original, [(kw_pos, kw_pos + len(kw)), tm.span()])
                return payload, "daily", desc

    # 6. Odredjeni dan u tjednu (svaki tjedan): "petak u 14 sastanak"
    wd, wd_span = _find_weekday(low)
    if wd is not None:
        tm = re.search(TIME_RE, low)
        if tm:
            payload = {"weekday": wd, "interval": 1,
                       "hour": int(tm.group(1)), "minute": int(tm.group(2) or 0)}
            return payload, "weekly", _make_description(original, [wd_span, tm.span()])

    # 7. Relativni - prekosutra PRIJE jer sadrzi "sutra"
    for kw, offset in [("prekosutra", 2), ("sutra", 1)]:
        kw_pos = low.find(kw)
        if kw_pos != -1:
            tm = re.search(TIME_RE, low)
            if tm:
                h, mi = int(tm.group(1)), int(tm.group(2) or 0)
                target = (now + timedelta(days=offset)).replace(
                    hour=h, minute=mi, second=0, microsecond=0)
                desc = _make_description(original, [(kw_pos, kw_pos + len(kw)), tm.span()])
                return target, "once", desc

    # 8. Za X minuta/sati - [a-zć]* hvata cijelu rijec (sata, sati, minuta...)
    m = re.search(r'za (\d+)\s*(minut[a-zć]*|min|sat[a-zć]*|h)\b', low)
    if m:
        num, unit = int(m.group(1)), m.group(2)
        delta = timedelta(hours=num) if ("sat" in unit or "h" in unit) else timedelta(minutes=num)
        return now + delta, "once", _make_description(original, [m.span()])

    # 9. Samo vrijeme: "U 11:35 idem na trening" -> danas (ili sutra ako je proslo)
    m = re.search(r'\bu\s*(\d{1,2})(?:[:.](\d{2}))?\b', low)
    if m:
        h, mi = int(m.group(1)), int(m.group(2) or 0)
        if 0 <= h <= 23 and 0 <= mi <= 59:
            target = now.replace(hour=h, minute=mi, second=0, microsecond=0)
            if target <= now:
                target += timedelta(days=1)
            return target, "once", _make_description(original, [m.span()])

    return None, None, None


# ==================== OPISI PONAVLJANJA ====================

def recurring_label(r):
    """Ljudski citljiv opis rasporeda ponavljajuceg podsjetnika iz retka baze."""
    hhmm = f"{r['hour']:02d}:{r['minute']:02d}"
    n = r["interval_n"] or 1
    if r["rtype"] == "daily":
        return f"Svaki dan u {hhmm}" if n == 1 else f"Svaka {n} dana u {hhmm}"
    if r["rtype"] == "weekly":
        day = DAY_NAMES_SHORT[r["weekday"] or 0]
        return f"{day} u {hhmm}" if n == 1 else f"Svaki {n}. tjedan, {day} u {hhmm}"
    if r["rtype"] == "monthly":
        if (r["monthday"] or 1) >= 32:
            return f"Zadnji dan u mjesecu u {hhmm}"
        return f"Svaki mjesec {r['monthday']}. u {hhmm}"
    return hhmm


# ==================== SLANJE PORUKA ====================
# Bez parse_mode: korisnikov tekst s * ili _ ne smije srusiti slanje.

def safe_send(chat_id, text, markup=None):
    try:
        bot.send_message(chat_id, text, reply_markup=markup)
        return True
    except Exception as e:
        print(f"Greska pri slanju poruke ({chat_id}): {e}")
        monitoring.warning(f"Slanje poruke nije uspjelo ({chat_id}): {e}", source="safe_send")
        return False


def send_msg(chat_id, text, markup=None):
    """Kao safe_send, ali vrati message objekt (ili None) — treba za mapiranje
    reply-a (živi chat podrške) na message_id."""
    try:
        return bot.send_message(chat_id, text, reply_markup=markup)
    except Exception as e:
        monitoring.warning(f"Slanje poruke nije uspjelo ({chat_id}): {e}", source="send_msg")
        return None


# ==================== ŽIVI CHAT (PODRŠKA) — AI ASISTENT ====================
# Dispečeri na Floti OS razgovaraju s AI-jem (Claude). Dolazna poruka -> AI
# generira odgovor -> natrag korisniku preko WebSocketa (podrska.posalji_klijentu).
# Povijest po sesiji (za kontekst razgovora) drži se u RAM-u; briše se kad se
# sesija zatvori. Vlasnici NE moraju odgovarati; /podrska ostaje kao admin uvid
# (popis) i ručno ubacivanje poruke (override) ako baš treba ljudski upad.
PODRSKA_SYSTEM_PROMPT = (
    "Ti si stručna podrška za web-aplikaciju Flota OS (Jarvis) tvrtke Bravel d.o.o. — "
    "sustav za upravljanje flotom kamiona. Razgovaraš s internim korisnicima (dispečeri, ured).\n\n"
    "ŠTO FLOTA OS IMA (ekrani/funkcije):\n"
    "• Živa karta — trenutne GPS pozicije vozila (Mobilisis); klik na vozilo daje brzinu, "
    "status motora i vrijeme; ruta/putanja vozila za zadnjih N sati.\n"
    "• Planirane rute i Ture — dnevni nalozi i slaganje u ture; Optimalne ture / Optimizator "
    "grupira naloge da se smanji prazan hod (VRP).\n"
    "• Profitabilnost / Isplativost — marža po ruti/turi (km × stope: gorivo, cestarina, puni "
    "trošak €/km, korekcija praznog hoda).\n"
    "• Gorivo i Potrošnja — točenja i l/100km po vozilu/vozaču; Prihod — dnevni prihod iz naloga.\n"
    "• Usporedba vozača, Troškovi, Status vozila (aktivno/pasivno/prodano), Benzinske i cijene goriva.\n\n"
    "ALATI za ŽIVE podatke (KORISTI ih, ne nagađaj brojke): cijene_goriva (cijene po lancu), "
    "pozicija_vozila (GPS po registraciji/GB), prihod (pregled po mjesecu ILI po vozaču za dan "
    "YYYY-MM-DD), profitabilnost (marža/prihod/trošak/dobit po kamionu, zadnji dan), ture "
    "(trenutna tura po kamionu), potrosnja (litre i € goriva po mjesecu/režimu), status_vozila "
    "(koliko vozila je aktivno/pasivno/prodano + popis). Ako alat vrati grešku/nekonfigurirano, "
    "reci to iskreno i po potrebi uputi korisnika na odgovarajući ekran u aplikaciji.\n\n"
    "STIL: odgovaraj KRATKO, jasno i na hrvatskom, konkretnim koracima. Ne izmišljaj funkcije ni "
    "podatke. Ako alat vrati grešku/nedostupno, reci to iskreno. Za ljudsku intervenciju ili ovlasti "
    "uputi da proslijede vlasnicima (Toni/ured).\n\n"
    "NIKAD NE IZMIŠLJAJ pojedinačne podatke (registracije, modele, GB brojeve, iznose) kojih NEMA u "
    "rezultatu alata. Koristi TOČNO ono što alat vrati. Ako je popis dug ili je u rezultatu naznaka da "
    "je skraćen/nepotpun (npr. 'napomena_popis'), reci to i ponudi filtriranje (po statusu, GB-u ili "
    "registraciji) umjesto da nabrajaš izmišljene stavke.\n\n"
    "FORMAT: odgovaraj u ČISTOM TEKSTU — chat prikazuje običan tekst pa se Markdown NE renderira. "
    "NE koristi zvjezdice za podebljano (**), NE koristi Markdown tablice (retke s |), ni # naslove. "
    "Za popise koristi jednostavne retke s crticom (-) ili emoji. Brojke piši u tekstu "
    "(npr. 'EU: 611 naloga, 512.316,74 €'), ne u tablici."
)

# Anthropic tool-use: alati kojima podrška ČITA žive podatke (bravel-agent ih servira).
PODRSKA_TOOLS = [
    {
        "name": "cijene_goriva",
        "description": ("Trenutne cijene goriva po lancu (Adria Oil, Tifon, Shell, Petrol, "
                        "Brebrić) sa smjerom promjene. Koristi za pitanja o cijenama goriva, "
                        "najjeftinijem gorivu ili usporedbi lanaca."),
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "pozicija_vozila",
        "description": ("Trenutna GPS lokacija jednog vozila po registraciji (npr. ZG1234AB) ILI "
                        "garažnom broju (GB). Vraća koordinate, brzinu, status motora i vrijeme. "
                        "Koristi kad korisnik pita gdje je neki kamion."),
        "input_schema": {
            "type": "object",
            "properties": {"vozilo": {"type": "string",
                           "description": "registracija ili garažni broj (GB) vozila"}},
            "required": ["vozilo"],
        },
    },
    {
        "name": "prihod",
        "description": ("Prihod flote iz Flota OS-a. Bez datuma: pregled (broj naloga i prihod "
                        "po mjesecu/režimu). S datumom (YYYY-MM-DD): prihod po vozaču za taj dan. "
                        "Koristi za pitanja o prihodu/zaradi po danu ili mjesecu."),
        "input_schema": {
            "type": "object",
            "properties": {"datum": {"type": "string",
                           "description": "opcionalno, YYYY-MM-DD za dnevni prihod po vozaču"}},
            "required": [],
        },
    },
    {
        "name": "profitabilnost",
        "description": ("Isplativost po kamionu (GB) iz zadnjeg radnog dana: marža, prihod, "
                        "trošak, dobit. Koristi za pitanja o profitabilnosti/marži vozila."),
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "ture",
        "description": ("Trenutna tura po kamionu (GB) iz Flota OS-a — tekuća tura vozača s "
                        "odredištem. Koristi za pitanja o trenutnim turama/gdje ide koji kamion."),
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "potrosnja",
        "description": ("Potrošnja goriva iz Flota OS-a — litre i € po mjesecu i režimu "
                        "(Bravel / Bravel Logs). Koristi za pitanja o potrošnji goriva, "
                        "litrama ili trošku goriva po razdoblju."),
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "status_vozila",
        "description": ("Status flote iz Flota OS-a — ukupan broj vozila i razdioba po statusu "
                        "(aktivno/pasivno/prodano) + popis {gb, status, model, reg}. Koristi za "
                        "pitanja koliko vozila je aktivno, koji su pasivni/prodani i sl."),
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
]
_podrska_hist = {}          # session_id -> [{"role","content"}]
_podrska_hist_lock = threading.Lock()
_PODRSKA_HIST_LIMIT = 20    # zadnjih 20 poruka (10 izmjena) po sesiji


def _podrska_cijene_kompaktno():
    """Kompaktan sažetak cijena (bez lokacija postaja) za AI alat."""
    out = []
    for l in benzinske.trenutno():
        if l.get("goriva"):
            g = {x["gorivo"]: {"cijena": x["cijena"], "smjer": x.get("smjer")}
                 for x in l["goriva"]}
            out.append({"lanac": l["naziv"], "goriva": g})
        elif l.get("tip") == "kartica":
            out.append({"lanac": l["naziv"], "napomena": "kartična mreža — nema javne cijene"})
    return out


# Flota OS API (prihod/profitabilnost/ture) — servisni pristup preko X-Service-Key
# (ista tajna kao SERVICE_KEY na flota-os backendu; ključ NIKAD ne ide korisniku).
_FLOTA_OS_API = os.getenv("FLOTA_OS_API_URL", "https://bravel-flota-os-api.fly.dev").rstrip("/")
_FLOTA_OS_SERVICE_KEY = os.getenv("FLOTA_OS_SERVICE_KEY", "").strip()


def _flota_os_get(path, params=None):
    """GET na flota-os backend sa servisnim ključem. Vrati JSON ili {greska}."""
    if not _FLOTA_OS_SERVICE_KEY:
        return {"greska": "Flota OS servisni pristup nije konfiguriran (FLOTA_OS_SERVICE_KEY)."}
    try:
        r = requests.get(f"{_FLOTA_OS_API}{path}", params=params,
                         headers={"X-Service-Key": _FLOTA_OS_SERVICE_KEY}, timeout=25)
        if r.status_code == 401:
            return {"greska": "servisni ključ odbijen (provjeri da je isti na obje strane)"}
        if r.status_code != 200:
            return {"greska": f"Flota OS HTTP {r.status_code}"}
        return r.json()
    except Exception as e:
        return {"greska": f"Flota OS nedostupan: {e}"}


def _podrska_alat(naziv, ulaz):
    """Izvrši alat koji je AI zatražio. Vrati JSON-spreman rezultat."""
    ulaz = ulaz or {}
    try:
        if naziv == "cijene_goriva":
            return {"cijene": _podrska_cijene_kompaktno()}
        if naziv == "pozicija_vozila":
            return mobilisis.lookup(ulaz.get("vozilo", ""))
        if naziv == "prihod":
            datum = (ulaz.get("datum") or "").strip()
            if datum:
                return _flota_os_get("/api/prihod/dan", params={"datum": datum})
            return _flota_os_get("/api/prihod/pregled")
        if naziv == "profitabilnost":
            return _flota_os_get("/api/flota/profitabilnost")
        if naziv == "ture":
            return _flota_os_get("/api/flota/ture")
        if naziv == "potrosnja":
            return _flota_os_get("/api/gorivo/pregled")
        if naziv == "status_vozila":
            d = _flota_os_get("/api/flota/status")
            # Flota zna imati stotine vozila; cijeli popis ne stane u rezultat
            # alata (rezanje -> model bi izmišljao registracije). Aktivnih je
            # najviše i nitko ih ne nabraja pojedinačno, pa u POPISU šaljemo samo
            # NE-aktivna vozila; ukupni broj po statusu ostaje u 'po_statusu'.
            if isinstance(d, dict) and isinstance(d.get("vozila"), list):
                akt = {"aktivno", "aktivan"}
                neaktivna = [v for v in d["vozila"]
                             if (v.get("status") or "").strip().lower() not in akt]
                broj_akt = d.get("po_statusu", {}).get("Aktivno", 0)
                d = {**d, "vozila": neaktivna,
                     "napomena_popis": (f"'vozila' sadrži SAMO ne-aktivna vozila "
                                        f"({len(neaktivna)}); aktivnih je {broj_akt} i "
                                        f"NISU u popisu. Ne izmišljaj pojedinačna aktivna vozila.")}
            return d
        return {"greska": f"nepoznat alat: {naziv}"}
    except Exception as e:
        return {"greska": str(e)}


def _ocisti_markdown(text):
    """Chat prikazuje ČIST tekst — Markdown se ne renderira, pa se ** i # vide
    doslovno. Model (haiku) povremeno svejedno ubaci Markdown; ovo ga uklanja
    kao zadnju liniju obrane (neovisno o promptu). Zadržava čitljive retke."""
    if not text:
        return text
    t = re.sub(r"\*\*(.+?)\*\*", r"\1", text)       # **podebljano** -> podebljano
    t = re.sub(r"__(.+?)__", r"\1", t)               # __podebljano__ -> podebljano
    t = re.sub(r"(?m)^\s{0,3}#{1,6}\s*", "", t)      # # naslovi -> obican redak
    t = re.sub(r"(?m)^\s*\|.*\|\s*$", "", t)         # retci Markdown tablice -> makni
    t = re.sub(r"(?m)^\s*[-*]{3,}\s*$", "", t)       # --- / *** razdjelnici -> makni
    t = re.sub(r"\n{3,}", "\n\n", t)                 # ne ostavljaj 3+ praznih redaka
    return t.strip()


def _podrska_ai_odgovori(session_id, ime, tekst):
    """Callback iz podrska (aiohttp executor thread): AI (s alatima za žive
    podatke) generira odgovor i šalje ga natrag u chat. Povijest po sesiji."""
    try:
        with _podrska_hist_lock:
            hist = list(_podrska_hist.get(session_id, []))
        messages = hist + [{"role": "user", "content": tekst}]

        odg = ""
        for _ in range(5):  # agentic petlja: dopusti nekoliko poziva alata
            resp = client.messages.create(
                model="claude-haiku-4-5",
                max_tokens=1024,
                system=PODRSKA_SYSTEM_PROMPT,
                tools=PODRSKA_TOOLS,
                messages=messages,
                temperature=0.3,
            )
            if resp.stop_reason == "tool_use":
                messages.append({"role": "assistant", "content": resp.content})
                rezultati = []
                for blok in resp.content:
                    if getattr(blok, "type", None) == "tool_use":
                        rez = _podrska_alat(blok.name, blok.input or {})
                        rezultati.append({
                            "type": "tool_result",
                            "tool_use_id": blok.id,
                            "content": json.dumps(rez, ensure_ascii=False)[:12000],
                        })
                messages.append({"role": "user", "content": rezultati})
                continue
            odg = "".join(b.text for b in resp.content
                          if getattr(b, "type", None) == "text").strip()
            break
        else:
            # Petlja iscrpljena a model još traži alate -> još jedan poziv BEZ alata,
            # da bude prisiljen dati tekstualni odgovor iz već prikupljenih podataka
            # (umjesto da korisnik dobije prazan/generički fallback).
            resp = client.messages.create(
                model="claude-haiku-4-5", max_tokens=1024,
                system=PODRSKA_SYSTEM_PROMPT, messages=messages, temperature=0.3,
            )
            odg = "".join(b.text for b in resp.content
                          if getattr(b, "type", None) == "text").strip()

        if not odg:
            odg = "Možete li malo pojasniti pitanje? Rado ću pomoći oko Flote OS."
        odg = _ocisti_markdown(odg)   # chat ne renderira Markdown -> makni ** __ # | itd.
        with _podrska_hist_lock:
            h = _podrska_hist.setdefault(session_id, [])
            h.append({"role": "user", "content": tekst})
            h.append({"role": "assistant", "content": odg})
            _podrska_hist[session_id] = h[-_PODRSKA_HIST_LIMIT:]
        podrska.posalji_klijentu(session_id, odg, od="Podrška")
    except Exception as e:
        monitoring.error("Podrška AI odgovor nije uspio", source="podrska", exc=e)
        podrska.posalji_klijentu(
            session_id,
            "Ispričavam se, trenutno ne mogu odgovoriti. Pokušajte ponovno za koji trenutak.",
            od="Podrška")


def _podrska_zatvori(session_id):
    """Sesija zatvorena -> oslobodi povijest razgovora."""
    with _podrska_hist_lock:
        _podrska_hist.pop(session_id, None)


def _podrska_worker(chat_id, arg):
    """Komanda /podrska (admin uvid; na podršku odgovara AI):
      /podrska                 -> popis aktivnih chat sesija
      /podrska <id> <tekst>    -> ručno ubaci poruku korisniku (ljudski override)."""
    try:
        arg = (arg or "").strip()
        if not arg:
            sesije = podrska.aktivne()
            if not sesije:
                safe_send(chat_id, "💬 Nema aktivnih chat sesija podrške.")
                return
            linije = ["💬 Aktivne sesije podrške (odgovara AI):"]
            for s in sesije:
                zadnja = f" — „{s['zadnja']}”" if s.get("zadnja") else ""
                linije.append(f"• #{s['id']} · {s['ime']}{zadnja}")
            linije.append("\nRučni upad (override): /podrska <id> <poruka>")
            safe_send(chat_id, "\n".join(linije))
            return
        parts = arg.split(maxsplit=1)
        sid = parts[0]
        tekst = parts[1].strip() if len(parts) > 1 else ""
        if not tekst:
            safe_send(chat_id, f"Napiši poruku: /podrska {sid} <poruka>")
            return
        if podrska.posalji_klijentu(sid, tekst):
            safe_send(chat_id, f"✅ Poslano korisniku (#{sid}).")
        else:
            safe_send(chat_id, f"⚠️ Sesija #{sid} više nije aktivna (korisnik je zatvorio chat).")
    except Exception as e:
        monitoring.error("Greška u /podrska", source="podrska", exc=e)
        safe_send(chat_id, f"❌ Greška: {e}")


def handle_podrska(message):
    parts = message.text.split(maxsplit=1)
    arg = parts[1] if len(parts) > 1 else ""
    threading.Thread(target=_podrska_worker, args=(message.chat.id, arg),
                     daemon=True).start()


def snooze_markup(reminder_id):
    """Gumbi za odgodu ispod okinutog podsjetnika."""
    mk = telebot.types.InlineKeyboardMarkup()
    mk.row(
        telebot.types.InlineKeyboardButton("+15 min", callback_data=f"snz_{reminder_id}_15"),
        telebot.types.InlineKeyboardButton("+1 h", callback_data=f"snz_{reminder_id}_60"),
        telebot.types.InlineKeyboardButton("+3 h", callback_data=f"snz_{reminder_id}_180"),
    )
    mk.row(
        telebot.types.InlineKeyboardButton("📅 Sutra", callback_data=f"snz_{reminder_id}_1440"),
        telebot.types.InlineKeyboardButton("✅ Gotovo", callback_data=f"snz_{reminder_id}_done"),
    )
    return mk


# ==================== PROVJERA PODSJETNIKA (thread) ====================

def _interval_due(r, today):
    """Provjera intervala za daily/weekly s N>1 (anchor = datum prvog okidanja)."""
    n = r["interval_n"] or 1
    if n <= 1 or not r["anchor_ts"]:
        return True
    anchor = datetime.fromtimestamp(r["anchor_ts"], TZ).date()
    days = (today - anchor).days
    if days < 0:
        return False
    if r["rtype"] == "daily":
        return days % n == 0
    return (days // 7) % n == 0  # weekly


def _job_fire_once(name, fired_key):
    """True samo prvi put za dani (name, fired_key) — perzistentni guard u bazi
    da se scheduled job ne okine dvaput (npr. kod restarta u istoj minuti)."""
    with db() as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS jobs "
                     "(name TEXT PRIMARY KEY, last_fired TEXT)")
        row = conn.execute("SELECT last_fired FROM jobs WHERE name = ?", (name,)).fetchone()
        if row and row[0] == fired_key:
            return False
        conn.execute("INSERT INTO jobs (name, last_fired) VALUES (?, ?) "
                     "ON CONFLICT(name) DO UPDATE SET last_fired = excluded.last_fired",
                     (name, fired_key))
    return True


def _wa_auto_podsjetnici():
    """Pozvano iz rasporeda: pošalji tjedne podsjetnike i javi sažetak vlasnicima."""
    try:
        sazetak = whatsapp_podsjetnici.posalji_tjedne()
        for uid in ALLOWED_USERS:
            safe_send(uid, sazetak)
    except Exception as e:
        monitoring.error("WhatsApp auto podsjetnici pali", source="wa_podsjetnici", exc=e)


def _benzinske_warm():
    """Zagrij keš lokacija postaja (OSM) na startu — best-effort."""
    try:
        benzinske.dohvati_postaje()
    except Exception as e:
        monitoring.warning(f"Benzinske postaje (OSM) warm: {e}", source="benzinske")


def _benzinske_auto():
    """Pozvano iz rasporeda: osvježi cijene goriva (evidencija) i, ako je bilo
    promjena, javi kratki sažetak vlasnicima. Best-effort — nikad ne ruši petlju."""
    try:
        # Osvjezi i lokacije postaja (OSM) — dohvati_postaje ima tjedni TTL,
        # pa se stvarni Overpass poziv dogodi najvise jednom tjedno.
        try:
            benzinske.dohvati_postaje()
        except Exception as e:
            monitoring.warning(f"Benzinske postaje (OSM) osvježavanje: {e}",
                               source="benzinske")
        sazetak, promjena = benzinske.osvjezi_sve()
        if promjena > 0:
            for uid in ALLOWED_USERS:
                safe_send(uid, sazetak)
    except Exception as e:
        monitoring.error("Benzinske auto osvježavanje palo", source="benzinske", exc=e)


# ==================== ZDRAVLJE VANJSKIH OVISNOSTI ====================
# Heartbeat javlja samo da je PROCES bota živ. Ovo aktivno provjerava jesu li
# vanjske ovisnosti (Mobilisis GPS, Flota OS API) stvarno dostupne — bot zna
# biti živ a karta prazna jer Mobilisis ne odgovara. Alarmira SAMO na prijelaz
# radi→pao (jednom), i javi oporavak. Sve best-effort; ne smije rušiti scheduler.
_health_stanje = {}          # naziv ovisnosti -> "ok" | "down"
_health_zadnji_ts = 0.0      # unix vrijeme zadnje provjere
HEALTH_INTERVAL = int(os.getenv("HEALTH_INTERVAL", "300"))   # koliko često (s), default 5 min


def _health_mobilisis():
    """(ok, poruka). Ako Mobilisis nije konfiguriran -> ne alarmiraj (namjerno isključen)."""
    if not mobilisis.is_configured():
        return True, "nije konfiguriran (preskačem)"
    poz = mobilisis.get_positions()
    if isinstance(poz, list):
        return True, f"{len(poz)} pozicija"
    return False, "neočekivan odgovor (nije lista)"


def _health_flota_os():
    """(ok, poruka). Ako servisni pristup nije postavljen -> ne alarmiraj."""
    if not _FLOTA_OS_SERVICE_KEY:
        return True, "servisni pristup nije konfiguriran (preskačem)"
    r = requests.get(f"{_FLOTA_OS_API}/health", timeout=15)
    if r.status_code == 200:
        return True, "200 OK"
    return False, f"HTTP {r.status_code}"


_HEALTH_PROVJERE = [
    ("Mobilisis (GPS pozicije)", _health_mobilisis),
    ("Flota OS API", _health_flota_os),
]


def provjeri_zdravlje():
    """Provjeri sve ovisnosti. Vrati listu (naziv, ok, poruka). Uz to alarmira
    admina na prijelaz radi->pao i javi oporavak (preko monitoringa)."""
    rezultati = []
    for naziv, fn in _HEALTH_PROVJERE:
        try:
            ok, poruka = fn()
            ok = bool(ok)
        except Exception as e:
            ok, poruka = False, str(e)
        rezultati.append((naziv, ok, poruka))
        prije = _health_stanje.get(naziv)
        if not ok and prije != "down":
            monitoring.error(f"Ovisnost PALA: {naziv} — {poruka}", source="health")
            _health_stanje[naziv] = "down"
        elif ok and prije == "down":
            monitoring.info(f"Ovisnost se oporavila: {naziv} — {poruka}", source="health")
            _health_stanje[naziv] = "ok"
        elif ok:
            _health_stanje[naziv] = "ok"
    return rezultati


def check_reminders():
    while True:
        # Cijeli ciklus u try/except - thread ne smije umrijeti.
        try:
            now = get_now()
            now_ts = now.timestamp()
            fired_key = now.strftime('%Y-%m-%d %H:%M')
            today = now.date()

            # --- jednokratni ---
            with db() as conn:
                due = conn.execute(
                    "SELECT * FROM reminders WHERE fired = 0 AND time_ts <= ?",
                    (now_ts,)
                ).fetchall()

            for r in due:
                # Oznaci kao poslan PRIJE slanja (da ne spama kod greske),
                # red ostaje u bazi zbog gumba za odgodu.
                with db() as conn:
                    conn.execute("UPDATE reminders SET fired = 1 WHERE id = ?", (r["id"],))
                safe_send(r["chat_id"], f"🔔 PODSJETNIK\n\n{r['text']}",
                          markup=snooze_markup(r["id"]))

            # --- ponavljajuci ---
            with db() as conn:
                rec = conn.execute("SELECT * FROM recurring").fetchall()

            for r in rec:
                if r["last_fired"] == fired_key:
                    continue  # vec okinuo ovu minutu

                if r["hour"] != now.hour or r["minute"] != now.minute:
                    continue

                should_fire = False
                if r["rtype"] == "daily":
                    should_fire = _interval_due(r, today)
                elif r["rtype"] == "weekly" and r["weekday"] == now.weekday():
                    should_fire = _interval_due(r, today)
                elif r["rtype"] == "monthly":
                    last_day = calendar.monthrange(now.year, now.month)[1]
                    md = r["monthday"] or 1
                    # 32 = zadnji dan; 31. u kracem mjesecu okida na zadnji dan
                    effective = last_day if md >= 32 else min(md, last_day)
                    should_fire = (now.day == effective)

                if should_fire:
                    with db() as conn:
                        conn.execute("UPDATE recurring SET last_fired = ? WHERE id = ?",
                                     (fired_key, r["id"]))
                    safe_send(r["chat_id"],
                              f"🔄 PODSJETNIK ({recurring_label(r)})\n\n{r['text']}")

            # --- tjedni WhatsApp podsjetnik vozacima (best-effort, gura predloske) ---
            # Okida se samo ako je ukljucen prekidac; raspored: DAN/SAT/MIN (env).
            if os.getenv("WHATSAPP_PODSJETNICI_ON", "").strip() == "1":
                try:
                    wd = int(os.getenv("WHATSAPP_PODSJETNIK_DAN", "4"))   # 4 = petak
                    hh = int(os.getenv("WHATSAPP_PODSJETNIK_SAT", "15"))
                    mm = int(os.getenv("WHATSAPP_PODSJETNIK_MIN", "0"))
                    if (now.weekday() == wd and now.hour == hh and now.minute == mm
                            and _job_fire_once("wa_podsjetnici", fired_key)):
                        threading.Thread(target=_wa_auto_podsjetnici, daemon=True).start()
                except Exception as e:
                    monitoring.warning(f"WhatsApp podsjetnik raspored: {e}",
                                       source="wa_podsjetnici")

            # --- benzinske: periodicko osvjezavanje cijena (best-effort) ---
            # Okida se samo ako je ukljucen prekidac BENZINSKE_ON=1, u satima iz
            # BENZINSKE_SATI (default "7,13,19"), u minuti 5. _job_fire_once cuva
            # od dvostrukog okidanja kod restarta u istoj minuti.
            if os.getenv("BENZINSKE_ON", "").strip() == "1" and now.minute == 5:
                try:
                    sati = [int(x) for x in os.getenv("BENZINSKE_SATI", "7,13,19")
                            .split(",") if x.strip().isdigit()]
                    if now.hour in sati and _job_fire_once(
                            f"benzinske_{now.hour}", fired_key):
                        threading.Thread(target=_benzinske_auto, daemon=True).start()
                except Exception as e:
                    monitoring.warning(f"Benzinske raspored: {e}", source="benzinske")

            # --- zdravlje vanjskih ovisnosti (Mobilisis, Flota OS) svakih HEALTH_INTERVAL s ---
            global _health_zadnji_ts
            if now_ts - _health_zadnji_ts >= HEALTH_INTERVAL:
                _health_zadnji_ts = now_ts
                try:
                    provjeri_zdravlje()
                except Exception as e:
                    monitoring.warning(f"Health provjera: {e}", source="health")

            # --- radnički WhatsApp podsjetnici (dospjeli) ---
            try:
                whatsapp_meni.posalji_dospjele()
            except Exception as e:
                monitoring.warning(f"WA podsjetnici isporuka: {e}", source="wa_meni")

            # --- ciscenje: poslani jednokratni stariji od 2 dana ---
            with db() as conn:
                conn.execute("DELETE FROM reminders WHERE fired = 1 AND time_ts < ?",
                             (now_ts - 172800,))

        except Exception as e:
            print(f"Greska u check_reminders petlji: {e}")
            monitoring.error("Greska u check_reminders petlji", source="check_reminders", exc=e)

        time.sleep(10)


# ==================== ODGODA (snooze gumbi) ====================

@bot.callback_query_handler(func=lambda c: c.data.startswith("snz_"))
def snooze_callback(c):
    if c.from_user.id not in ALLOWED_USERS:
        bot.answer_callback_query(c.id)
        return

    try:
        _, rid, val = c.data.split("_")
        rid = int(rid)

        with db() as conn:
            row = conn.execute(
                "SELECT * FROM reminders WHERE id = ? AND chat_id = ?",
                (rid, c.message.chat.id)
            ).fetchone()

        if not row:
            bot.answer_callback_query(c.id, "Taj podsjetnik više ne postoji.")
            return

        if val == "done":
            with db() as conn:
                conn.execute("DELETE FROM reminders WHERE id = ?", (rid,))
            bot.answer_callback_query(c.id, "✅ Označeno kao gotovo")
            try:
                bot.edit_message_text(f"✅ GOTOVO\n\n{row['text']}",
                                      c.message.chat.id, c.message.message_id)
            except Exception:
                pass
            return

        minutes = int(val)
        now_ts = get_now().timestamp()
        if minutes == 1440:
            # "Sutra" = izvorno vrijeme + 24h (isti sat kao original)
            new_ts = row["time_ts"] + 86400
            while new_ts <= now_ts:
                new_ts += 86400
        else:
            new_ts = now_ts + minutes * 60

        with db() as conn:
            conn.execute("UPDATE reminders SET time_ts = ?, fired = 0 WHERE id = ?",
                         (new_ts, rid))

        new_dt = datetime.fromtimestamp(new_ts, TZ)
        bot.answer_callback_query(c.id, f"⏰ Pomaknuto na {new_dt.strftime('%d.%m. %H:%M')}")
        try:
            bot.edit_message_text(
                f"🔔 PODSJETNIK\n\n{row['text']}\n\n"
                f"⏰ Pomaknuto na {new_dt.strftime('%d.%m.%Y. u %H:%M')}",
                c.message.chat.id, c.message.message_id)
        except Exception:
            pass

    except Exception as e:
        print(f"Greska u snooze_callback: {e}")
        monitoring.error("Greska u snooze_callback", source="snooze_callback", exc=e)
        bot.answer_callback_query(c.id, "Greška pri odgodi.")


# ==================== PRIKAZ I BRISANJE ====================

def _short(text, n=25):
    return text if len(text) <= n else text[:n - 1] + "…"


def build_reminders_view(chat_id):
    """Sastavlja tekst liste i gumbe za brisanje.
    Vraca (tekst, markup) - markup je None ako nema podsjetnika."""
    once, rec = get_user_items(chat_id)

    if not once and not rec:
        return "Trenutno nemaš aktivnih podsjetnika.", None

    lines = ["📋 Tvoji podsjetnici:", ""]
    markup = telebot.types.InlineKeyboardMarkup()

    if once:
        lines.append("Jednokratni:")
        for r in once:
            dt = datetime.fromtimestamp(r["time_ts"], TZ)
            lines.append(f"• {dt.strftime('%d.%m.%Y. u %H:%M')} → {r['text']}")
            markup.add(telebot.types.InlineKeyboardButton(
                f"🗑⏰ {dt.strftime('%d.%m. %H:%M')} — {_short(r['text'])}",
                callback_data=f"del_o_{r['id']}"
            ))
        lines.append("")

    if rec:
        lines.append("Ponavljajući:")
        for r in rec:
            label = recurring_label(r)
            lines.append(f"• 🔄 {label} → {r['text']}")
            markup.add(telebot.types.InlineKeyboardButton(
                f"🗑🔄 {label} — {_short(r['text'])}",
                callback_data=f"del_r_{r['id']}"
            ))

    lines.append("")
    lines.append("Za brisanje klikni gumb ispod 👇")
    return "\n".join(lines), markup


def show_reminders(message):
    text, markup = build_reminders_view(message.chat.id)
    bot.reply_to(message, text, reply_markup=markup)


@bot.callback_query_handler(func=lambda c: c.data.startswith("del_"))
def delete_callback(c):
    # Odmah zaustavi "ucitavanje" na gumbu
    try:
        bot.answer_callback_query(c.id)
    except Exception:
        pass

    if c.from_user.id not in ALLOWED_USERS:
        return

    try:
        _, kind, rid = c.data.split("_")
        rid = int(rid)
        table = "reminders" if kind == "o" else "recurring"
        print(f"[DELETE] zahtjev: table={table}, id={rid}, chat={c.message.chat.id}")

        conn = db()
        try:
            row = conn.execute(
                f"SELECT text FROM {table} WHERE id = ? AND chat_id = ?",
                (rid, c.message.chat.id)
            ).fetchone()
            if row:
                cur = conn.execute(f"DELETE FROM {table} WHERE id = ?", (rid,))
                conn.commit()
                print(f"[DELETE] obrisano redaka: {cur.rowcount}, tekst: {row['text']}")
            else:
                print(f"[DELETE] nije pronadjen: table={table}, id={rid}, chat={c.message.chat.id}")
        finally:
            conn.close()

        if row:
            bot.answer_callback_query(c.id, f"🗑 Obrisano: {_short(row['text'])}")
        else:
            bot.answer_callback_query(c.id, "Taj podsjetnik više ne postoji.")

        # Osvjezi poruku s novom listom
        text, markup = build_reminders_view(c.message.chat.id)
        try:
            bot.edit_message_text(text, c.message.chat.id, c.message.message_id,
                                  reply_markup=markup)
        except Exception as e:
            print(f"[DELETE] edit poruke nije uspio (vjerojatno nebitno): {e}")

    except Exception as e:
        print(f"[DELETE] GRESKA: {e}")
        monitoring.error("Greska u delete_callback", source="delete_callback", exc=e)

# ==================== AI RAZGOVOR ====================

SYSTEM_PROMPT = (
    "Ti si koristan asistent tvrtke Bravel. Odgovaraj kratko, jasno i na hrvatskom, "
    "osim ako te korisnik izričito pita na drugom jeziku."
)


def get_ai_response(chat_id, text):
    try:
        with history_lock:
            user_history = list(history.get(chat_id, []))

        messages = (
            user_history
            + [{"role": "user", "content": text}]
        )

        response = client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            messages=messages,
            temperature=0.7,
        )
        answer = response.content[0].text

        with history_lock:
            h = history.setdefault(chat_id, [])
            h.append({"role": "user", "content": text})
            h.append({"role": "assistant", "content": answer})
            history[chat_id] = h[-HISTORY_LIMIT:]

        # Trajno spremi izmjenu za dnevni izvjestaj (RAM povijest se gubi kod restarta)
        log_chat(chat_id, "user", text)
        log_chat(chat_id, "assistant", answer)

        return answer
    except Exception as e:
        print(f"Claude greska: {e}")
        monitoring.error("Claude API greska (get_ai_response)", source="claude", exc=e)
        return "Žao mi je, imao sam problem s odgovorom. Pokušaj ponovno."


# ==================== DNEVNI IZVJESTAJ ====================

# Okidaci koji traze izvjestaj. Drzimo ih kratkima da lako matchaju.
REPORT_TRIGGERS = [
    "gotovi za danas", "gotov za danas", "gotova za danas", "gotovo za danas",
    "gotovi smo za danas", "kraj dana", "gotov sam za danas",
    "dnevni izvještaj", "dnevni izvjestaj",
    "izvještaj za danas", "izvjestaj za danas",
]

# Prefiksi kojima korisnik rucno biljezi rad, npr. "zabilježi obavljena dostava".
_NOTE_RE = re.compile(r'^\s*(zabilje[žz]i|bilje[šs]ka|zapi[šs]i)\b\s*[:,\-]?\s*(.+)',
                      re.IGNORECASE | re.DOTALL)


def is_report_trigger(lower):
    return any(t in lower for t in REPORT_TRIGGERS)


def extract_note(text):
    """Vraca tekst zabiljeske ako poruka pocinje prepoznatim prefiksom, inace None."""
    m = _NOTE_RE.match(text)
    if m:
        return m.group(2).strip()
    return None


def summarize_day(messages):
    """messages: lista (role, text). Vraca uredan AI sazetak ili None ako AI padne."""
    convo = "\n".join(
        f"{'Radnik' if role == 'user' else 'Bot'}: {t}" for role, t in messages
    )
    try:
        resp = client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=1024,
            system=(
                "Na temelju razgovora radnika s botom napiši kratak, uredan sažetak "
                "što je radnik danas radio, dogovorio ili planirao. Piši na hrvatskom, "
                "u natuknicama koje počinju s '- '. Bez uvoda i zaključka. "
                "Ako iz razgovora nema konkretnog posla, napiši samo '- nema konkretnih zadataka'."
            ),
            messages=[
                {"role": "user", "content": convo},
            ],
            temperature=0.4,
        )
        return resp.content[0].text.strip()
    except Exception as e:
        print(f"Claude sazetak greska: {e}")
        monitoring.warning(f"Claude sazetak (summarize_day) nije uspio: {e}", source="claude")
        return None


def build_daily_report(chat_id):
    cleanup_old_logs()
    rows = get_today_log(chat_id)
    notes = [r["text"] for r in rows if r["kind"] == "note"]
    convo = [(r["kind"], r["text"]) for r in rows if r["kind"] in ("user", "assistant")]

    if not notes and not convo:
        return (
            "📊 Danas još nema zabilježenih aktivnosti.\n\n"
            "Rad možeš zabilježiti porukom, npr:\n"
            "„zabilježi obavljena dostava Zagreb“."
        )

    today_str = get_now().strftime('%d.%m.%Y.')
    lines = [f"📊 DNEVNI IZVJEŠTAJ — {today_str}", ""]

    if notes:
        lines.append(f"📝 Zabilješke ({len(notes)}):")
        for i, n in enumerate(notes, 1):
            lines.append(f"{i}. {n}")
        lines.append("")

    if convo:
        summary = summarize_day(convo)
        if summary:
            lines.append("💬 Sažetak dana:")
            lines.append(summary)
            lines.append("")

    lines.append("Ugodan odmor! 👋")
    return "\n".join(lines).strip()


def send_daily_report(message):
    report = build_daily_report(message.chat.id)
    safe_send(message.chat.id, report)


# ==================== /gdje — GPS lokacija vozila (Mobilisis) ====================

def _coord(x):
    """Koordinata kao string s TOCKOM (bez lokalizacije), 6 decimala."""
    return f"{float(x):.6f}"


def _ignition_on(v):
    """Je li motor upaljen (ignitionState raznih oblika)."""
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return v != 0
    return str(v).strip().lower() in ("1", "true", "on", "yes", "upaljen",
                                      "ignition_on", "ignitionon")


def _format_gdje(res, query):
    st = res.get("status")
    if st == "empty":
        return "Napiši GB broj ili registraciju, npr:\n/gdje 12   ili   /gdje ZG5267KM"
    if st == "error":
        return f"❌ {res.get('message', 'Greška pri dohvatu lokacije.')}"
    if st == "not_found":
        sug = res.get("suggestions") or []
        txt = f"❓ Ništa nije nađeno za „{query}”."
        if sug:
            txt += "\nJesi li mislio:\n" + "\n".join(f"• {s}" for s in sug)
        return txt
    if st == "no_device":
        return (f"🚛 {res.get('reg')} (GB {res.get('gb') or '?'})\n"
                "⚠️ Ovo vozilo nema GPS uređaj (nije u Mobilisisu).")
    if st == "no_position":
        return (f"🚛 {res.get('reg')} (GB {res.get('gb') or '?'})\n"
                "⚠️ Nema trenutne GPS pozicije za ovo vozilo.")

    # status ok
    pos = res["pos"]
    lat_s, lon_s = _coord(pos["lat"]), _coord(pos["lon"])
    dt = mobilisis.parse_utc(pos.get("dateTime"))
    if dt:
        loc = dt.astimezone(TZ)
        when = f"{loc.day}.{loc.month}.{loc.year} {loc:%H:%M}"
    else:
        when = "?"
    speed = pos.get("speed")
    kretanje = f"vozi {round(speed)} km/h" if (speed and speed > 0.5) else "stoji"
    motor = "upaljen" if _ignition_on(pos.get("ignition")) else "ugašen"
    odo = pos.get("odometer")
    odo_s = str(round(odo)) if isinstance(odo, (int, float)) else "?"
    return (
        f"🚛 {res['reg']} (GB {res.get('gb') or '?'})\n"
        f"📍 Google Maps: https://maps.google.com/?q={lat_s},{lon_s}\n"
        f"🕐 {when}\n"
        f"⚡ {kretanje}, motor {motor}\n"
        f"🛣 Odometar: {odo_s} km"
    )


def _gdje_worker(chat_id, query):
    try:
        res = mobilisis.lookup(query)
        safe_send(chat_id, _format_gdje(res, query))
    except Exception as e:
        print(f"[gdje] GRESKA: {e}")
        monitoring.error("Greska u /gdje", source="gdje", exc=e)
        safe_send(chat_id, "❌ Greška pri dohvatu lokacije. Pokušaj ponovno.")


def handle_gdje(message):
    parts = message.text.split(maxsplit=1)
    query = parts[1].strip() if len(parts) > 1 else ""
    if not query:
        bot.reply_to(message,
                     "Napiši GB broj ili registraciju, npr:\n"
                     "/gdje 12   ili   /gdje ZG5267KM")
        return
    # Mrezni pozivi (Mobilisis + Excel) -> u thread da ne blokira polling.
    bot.reply_to(message, "🔎 Tražim lokaciju…")
    threading.Thread(target=_gdje_worker, args=(message.chat.id, query),
                     daemon=True).start()


# ==================== WhatsApp admin komande (samo vlasnik) ====================

def _wa_register_worker(chat_id, pin):
    try:
        res = whatsapp.register(pin)
        if res["ok"]:
            safe_send(chat_id, "✅ Broj je REGISTRIRAN na Cloud API.\n"
                               "Možemo dalje na slanje (test predloška).")
        else:
            safe_send(chat_id,
                      "❌ Registracija nije uspjela.\n\n"
                      f"{whatsapp.opisi_gresku(res)}\n\n"
                      f"Sirovi odgovor:\n{res['data']}"[:3800])
    except whatsapp.WhatsAppError as e:
        safe_send(chat_id, f"⚠️ {e}")
    except Exception as e:
        monitoring.error("Greska u /wa_register", source="wa_register", exc=e)
        safe_send(chat_id, f"❌ Greška pri registraciji: {e}")


def handle_wa_register(message):
    parts = message.text.split(maxsplit=1)
    pin = parts[1].strip() if len(parts) > 1 else ""
    if not (pin.isdigit() and len(pin) == 6):
        bot.reply_to(message, "Upiši 6-znamenkasti PIN, npr:\n/wa_register 123456")
        return
    bot.reply_to(message, "⏳ Šaljem registraciju na Metu…")
    threading.Thread(target=_wa_register_worker, args=(message.chat.id, pin),
                     daemon=True).start()


def _wa_test_worker(chat_id, broj):
    try:
        res = whatsapp.send_template(broj, "hello_world", "en_US")
        if res["ok"]:
            safe_send(chat_id, f"✅ Poslano na {broj} (hello_world). Provjeri WhatsApp.")
        else:
            safe_send(chat_id,
                      "❌ Slanje nije uspjelo.\n\n"
                      f"{whatsapp.opisi_gresku(res)}\n\n"
                      f"Sirovi odgovor:\n{res['data']}"[:3800])
    except whatsapp.WhatsAppError as e:
        safe_send(chat_id, f"⚠️ {e}")
    except Exception as e:
        monitoring.error("Greska u /wa_test", source="wa_test", exc=e)
        safe_send(chat_id, f"❌ Greška pri slanju: {e}")


def _wa_broj(s):
    """Normaliziraj broj u međunarodni oblik bez +: 0994396448 -> 385994396448."""
    b = s.strip().replace("+", "").replace(" ", "").replace("-", "").replace("/", "")
    if b.startswith("00"):
        b = b[2:]
    elif b.startswith("0"):
        b = "385" + b[1:]
    return b


def handle_wa_test(message):
    parts = message.text.split(maxsplit=1)
    broj = _wa_broj(parts[1]) if len(parts) > 1 else ""
    if not broj.isdigit():
        bot.reply_to(message, "Upiši broj primatelja, npr:\n"
                              "/wa_test 0994396448   ili   /wa_test 385994396448")
        return
    bot.reply_to(message, "⏳ Šaljem test predložak (hello_world)…")
    threading.Thread(target=_wa_test_worker, args=(message.chat.id, broj),
                     daemon=True).start()


def _wa_token_worker(chat_id):
    try:
        res = whatsapp.debug_token()
        if not res["ok"]:
            safe_send(chat_id,
                      "❌ Ne mogu provjeriti token.\n\n"
                      f"{whatsapp.opisi_gresku(res)}\n\n"
                      f"Sirovi odgovor:\n{res['data']}"[:3800])
            return
        d = (res.get("data") or {}).get("data") or {}
        exp = d.get("expires_at")
        dexp = d.get("data_access_expires_at")

        def _fmt(ts):
            if ts in (0, None):
                return "NIKAD (permanentni ✅)"
            try:
                dt = datetime.fromtimestamp(ts, TZ)
                dana = (dt - datetime.now(TZ)).days
                znak = "⚠️" if dana < 30 else "✅"
                return f"{dt:%d.%m.%Y %H:%M} (za {dana} dana) {znak}"
            except Exception:
                return str(ts)

        scopes = ", ".join(d.get("scopes") or []) or "—"
        poruka = (
            "🔑 WhatsApp token\n"
            f"• Tip: {d.get('type', '?')}\n"
            f"• Valjan sad: {'da ✅' if d.get('is_valid') else 'NE ❌'}\n"
            f"• Istječe: {_fmt(exp)}\n"
            f"• Data-access istječe: {_fmt(dexp)}\n"
            f"• App: {d.get('application') or d.get('app_id') or '?'}\n"
            f"• Dozvole: {scopes}"
        )
        if exp not in (0, None):
            poruka += (
                "\n\n⚠️ Token NIJE permanentan → slanje će pući kad istekne.\n"
                "Riješi: Business Settings → Users → System users → (admin) "
                "Generate token, istek Never, dozvole whatsapp_business_messaging "
                "+ whatsapp_business_management. Pa:\n"
                "fly secrets set WHATSAPP_TOKEN=<token> -a bravel-agent")
        safe_send(chat_id, poruka)
    except whatsapp.WhatsAppError as e:
        safe_send(chat_id, f"⚠️ {e}")
    except Exception as e:
        monitoring.error("Greska u /wa_token", source="wa_token", exc=e)
        safe_send(chat_id, f"❌ Greška pri provjeri tokena: {e}")


def handle_wa_token(message):
    bot.reply_to(message, "⏳ Pitam Metu za status tokena…")
    threading.Thread(target=_wa_token_worker, args=(message.chat.id,),
                     daemon=True).start()


def _wa_predlozak_worker(chat_id, broj, naziv, varovi):
    try:
        comps = None
        if varovi:
            comps = [{"type": "body",
                      "parameters": [{"type": "text", "text": v} for v in varovi]}]
        res = whatsapp.send_template(broj, naziv, "hr", components=comps)
        if res["ok"]:
            safe_send(chat_id, f"✅ Predložak „{naziv}” poslan na {broj}. Provjeri WhatsApp.")
        else:
            safe_send(chat_id,
                      "❌ Slanje predloška nije uspjelo.\n\n"
                      f"{whatsapp.opisi_gresku(res)}\n\n"
                      f"Sirovi odgovor:\n{res['data']}"[:3800])
    except whatsapp.WhatsAppError as e:
        safe_send(chat_id, f"⚠️ {e}")
    except Exception as e:
        monitoring.error("Greska u /wa_predlozak", source="wa_predlozak", exc=e)
        safe_send(chat_id, f"❌ Greška pri slanju predloška: {e}")


def handle_wa_predlozak(message):
    # /wa_predlozak <broj> <naziv> [var1 | var2 | ...]  (varijable odvojene s |)
    parts = message.text.split(maxsplit=3)
    if len(parts) < 3:
        bot.reply_to(message,
                     "Format:\n/wa_predlozak <broj> <naziv> [var1 | var2 | ...]\n"
                     "npr: /wa_predlozak 0994396448 podsjetnik_racun Ivan | ovaj tjedan\n\n"
                     "(šalje ODOBRENI predložak, jezik hr; varijable {{1}},{{2}}… "
                     "odvoji znakom „|”)")
        return
    broj = _wa_broj(parts[1])
    naziv = parts[2].strip()
    varovi = []
    if len(parts) > 3 and parts[3].strip():
        varovi = [v.strip() for v in parts[3].split("|")]
    if not broj.isdigit():
        bot.reply_to(message, "Neispravan broj. Npr: /wa_predlozak 0994396448 "
                              "podsjetnik_racun Ivan | ovaj tjedan")
        return
    bot.reply_to(message, "⏳ Šaljem predložak…")
    threading.Thread(target=_wa_predlozak_worker,
                     args=(message.chat.id, broj, naziv, varovi), daemon=True).start()


_WA_STATUS_EMOJI = {
    "APPROVED": "✅", "PENDING": "🟡", "IN_APPEAL": "🟡",
    "PENDING_DELETION": "🟡", "REJECTED": "🔴", "DISABLED": "🔴",
    "PAUSED": "⏸️", "LIMIT_EXCEEDED": "⚠️",
}


_WA_NASI = {"potvrda_racuna", "podsjetnik_racun", "podsjetnik_voznje", "poruka_dispecera"}


def _wa_predlosci_jedna_waba(waba_id, naziv_wabe):
    """Vrati (linije, odobreni_nasi) za jednu WABA-u."""
    res = whatsapp.list_templates(waba_id)
    glava = f"🏢 {naziv_wabe} ({waba_id})"
    if not res["ok"]:
        return [f"{glava}\n  ❌ {whatsapp.opisi_gresku(res)}"], 0
    stavke = res["data"].get("data") or []
    if not stavke:
        return [f"{glava}\n  — nema predložaka"], 0
    stavke.sort(key=lambda t: (t.get("name") not in _WA_NASI, t.get("name") or ""))
    linije = [f"{glava} — {len(stavke)} predložaka:"]
    for t in stavke:
        naziv = t.get("name", "?")
        st = (t.get("status") or "?").upper()
        emo = _WA_STATUS_EMOJI.get(st, "⚪")
        zvj = "⭐ " if naziv in _WA_NASI else ""
        linije.append(f"  {emo} {zvj}{naziv} — {st} ({t.get('language','')})")
    odobreni = sum(1 for t in stavke if (t.get("status") or "").upper() == "APPROVED"
                   and t.get("name") in _WA_NASI)
    return linije, odobreni


def _wa_predlosci_worker(chat_id, waba_arg=None):
    try:
        if waba_arg:
            wabas = [{"id": waba_arg, "name": "(zadano)"}]
        else:
            wres = whatsapp.list_wabas()
            wabas = wres.get("wabas") or []
            if not wabas:
                # fallback: bar konfigurirani WABA
                wabas = [{"id": whatsapp._waba_id(), "name": "(konfigurirani)"}]
        linije, ukupno_odobreni = ["📋 WhatsApp predlošci po WABA-i:"], 0
        for w in wabas:
            dio, odo = _wa_predlosci_jedna_waba(w.get("id"), w.get("name") or "?")
            linije += [""] + dio
            ukupno_odobreni += odo
        linije.append(f"\n⭐ = naši · Odobrenih naših ukupno: {ukupno_odobreni}/4")
        linije.append("Za slanje predložak mora biti na ISTOJ WABA-i kao broj "
                      f"(WHATSAPP_WABA_ID = {whatsapp._waba_id()}).")
        safe_send(chat_id, "\n".join(linije)[:3900])
    except whatsapp.WhatsAppError as e:
        safe_send(chat_id, f"⚠️ {e}")
    except Exception as e:
        monitoring.error("Greska u /wa_predlosci", source="wa_predlosci", exc=e)
        safe_send(chat_id, f"❌ Greška pri dohvaćanju predložaka: {e}")


# Definicije 4 predloška (UTILITY, hr) — za kreiranje preko Graph API-ja.
# example.body_text = jedan primjer po varijabli (redom {{1}}, {{2}}…).
_WA_PREDLOSCI_DEF = [
    {"name": "potvrda_racuna", "category": "UTILITY", "language": "hr", "components": [
        {"type": "BODY",
         "text": "Bok {{1}}, zaprimili smo tvoj dokument ({{2}}) broj {{3}} "
                 "na iznos {{4}} €. Hvala!",
         "example": {"body_text": [["Ivan", "račun", "123/1/1", "85,40"]]}},
        {"type": "FOOTER", "text": "Bravel d.o.o."}]},
    {"name": "podsjetnik_racun", "category": "UTILITY", "language": "hr", "components": [
        {"type": "BODY",
         "text": "Bok {{1}}, podsjetnik: još nismo primili račune/primke za {{2}}. "
                 "Molimo te da ih fotografiraš i pošalješ na ovaj broj čim budeš u "
                 "mogućnosti. Hvala!",
         "example": {"body_text": [["Ivan", "ovaj tjedan"]]}},
        {"type": "FOOTER", "text": "Bravel d.o.o."}]},
    {"name": "podsjetnik_voznje", "category": "UTILITY", "language": "hr", "components": [
        {"type": "BODY",
         "text": "Bok {{1}}, podsjetnik za vožnju: {{2}}, polazak {{3}}. "
                 "Ako nešto ne odgovara, javi nam na ovaj broj.",
         "example": {"body_text": [["Ivan", "Zagreb - Split", "sutra u 06:00"]]}},
        {"type": "FOOTER", "text": "Bravel d.o.o."}]},
    {"name": "poruka_dispecera", "category": "UTILITY", "language": "hr", "components": [
        {"type": "BODY",
         "text": "Bok {{1}}, nova poruka od dispečera:\n{{2}}\n"
                 "Za pitanja odgovori na ovaj broj.",
         "example": {"body_text": [["Ivan", "Molim te nazovi ured kad staneš."]]}},
        {"type": "FOOTER", "text": "Bravel d.o.o."}]},
    {"name": "podsjetnik_opci", "category": "UTILITY", "language": "hr", "components": [
        {"type": "BODY",
         "text": "🔔 Podsjetnik koji si postavio:\n{{1}}\nHvala i ugodan dan!",
         "example": {"body_text": [["natoči gorivo prije polaska"]]}},
        {"type": "FOOTER", "text": "Bravel d.o.o."}]},
]


def _wa_kreiraj_worker(chat_id, waba_arg=None):
    waba = waba_arg or whatsapp._waba_id()
    linije = [f"🛠️ Kreiram predloške na WABA {waba}:"]
    for d in _WA_PREDLOSCI_DEF:
        try:
            res = whatsapp.create_template(d["name"], d["category"], d["language"],
                                           d["components"], waba_id=waba)
        except whatsapp.WhatsAppError as e:
            linije.append(f"⚠️ {d['name']}: {e}")
            continue
        except Exception as e:
            linije.append(f"❌ {d['name']}: {e}")
            continue
        if res["ok"]:
            st = (res["data"].get("status") or "PENDING")
            linije.append(f"✅ {d['name']} — {st}")
        else:
            err = (res.get("data") or {}).get("error", {}) if isinstance(res.get("data"), dict) else {}
            sub = err.get("error_subcode") if isinstance(err, dict) else None
            if sub == 2388024:   # ime već postoji na WABA-i → nije greška
                linije.append(f"ℹ️ {d['name']} — već postoji")
            else:
                linije.append(f"❌ {d['name']}: {whatsapp.opisi_gresku(res)}")
    linije.append("\nProvjeri s /wa_predlosci — bit će PENDING dok Meta ne odobri.")
    safe_send(chat_id, "\n".join(linije)[:3900])


def handle_wa_kreiraj_predloske(message):
    # /wa_kreiraj_predloske [WABA_ID]  — default WHATSAPP_WABA_ID (Bravel doo)
    parts = message.text.split(maxsplit=1)
    waba_arg = parts[1].strip() if len(parts) > 1 else None
    bot.reply_to(message, "⏳ Kreiram predloške na Meti…")
    threading.Thread(target=_wa_kreiraj_worker, args=(message.chat.id, waba_arg),
                     daemon=True).start()


def handle_wa_predlosci(message):
    # /wa_predlosci [WABA_ID]  — bez argumenta lista sve WABA-e tokena
    parts = message.text.split(maxsplit=1)
    waba_arg = parts[1].strip() if len(parts) > 1 else None
    bot.reply_to(message, "⏳ Pitam Metu za predloške po WABA-ama…")
    threading.Thread(target=_wa_predlosci_worker, args=(message.chat.id, waba_arg),
                     daemon=True).start()


def _wa_podsjetnici_worker(chat_id):
    try:
        # Rucno okidanje radi i kad je automatika iskljucena (force=True).
        sazetak = whatsapp_podsjetnici.posalji_tjedne(force=True)
        safe_send(chat_id, sazetak)
    except Exception as e:
        monitoring.error("Greska u /wa_podsjetnici", source="wa_podsjetnici", exc=e)
        safe_send(chat_id, f"❌ Greška pri slanju podsjetnika: {e}")


def handle_wa_podsjetnici(message):
    bot.reply_to(message, "⏳ Šaljem tjedne podsjetnike vozačima…")
    threading.Thread(target=_wa_podsjetnici_worker, args=(message.chat.id,),
                     daemon=True).start()


def _benzinske_worker(chat_id, arg):
    """Ručna komanda /benzinske:
      /benzinske            -> osvježi sve i prikaži sažetak
      /benzinske stanje     -> zadnje zabilježene cijene iz baze (bez dohvata)
      /benzinske probe URL  -> dijagnostika jednog izvora (dostupnost + uzorak)."""
    try:
        arg = (arg or "").strip()
        if arg.startswith("postaje_debug"):
            term = arg[len("postaje_debug"):].strip()
            safe_send(chat_id, benzinske.debug_postaje(term))
            return
        if arg.startswith("postaje"):
            safe_send(chat_id, benzinske.osvjezi_postaje())
            return
        if arg.startswith("probe_postaje"):
            url = arg[len("probe_postaje"):].strip()
            if not url:
                safe_send(chat_id, "Format: /benzinske probe_postaje <URL pretraživača postaja>")
                return
            r = benzinske.probe_postaje(url)
            if r.get("greska"):
                safe_send(chat_id, f"🔎 probe_postaje {url}\n❌ {r['greska']}")
                return
            parovi_txt = "; ".join(f"{la},{lo}" for la, lo in r.get("prvih_parova", []))
            safe_send(chat_id,
                      f"🔎 probe_postaje {url}\n"
                      f"HTTP {r['status']}, {r['duljina']} znakova\n"
                      f"HR lat brojeva: {r['broj_lat']} · PAROVA (lat,lon): {r.get('broj_parova', 0)}\n"
                      f"prvih parova: {parovi_txt}\n"
                      f"data-izvori: {', '.join(r['izvori']) or '—'}\n\n"
                      f"uzorak:\n{r['uzorak_oko_koord']}"[:3800])
            return
        if arg.startswith("probe"):
            url = arg[len("probe"):].strip()
            if not url:
                safe_send(chat_id, "Format: /benzinske probe <URL>")
                return
            r = benzinske.probe(url)
            if r.get("greska"):
                safe_send(chat_id, f"🔎 probe {url}\n❌ {r['greska']}")
                return
            cijene = ", ".join(f"{g}={c}" for g, c in r["nadjene_cijene"].items()) or "—"
            safe_send(chat_id,
                      f"🔎 probe {url}\n"
                      f"HTTP {r['status']}, {r['duljina']} znakova\n"
                      f"nađene cijene: {cijene}\n\n"
                      f"uzorak:\n{r['uzorak']}"[:3800])
            return
        if arg.startswith("stanje"):
            podaci = benzinske.trenutno()
            linije = []
            for l in podaci:
                if l["goriva"]:
                    dijelovi = ", ".join(
                        f"{g['gorivo']}={g['cijena']:.3f}"
                        + (f" ({'▲' if g['smjer']=='gore' else '▼'}{abs(g['promjena']):.3f})"
                           if g.get("promjena") else "")
                        for g in l["goriva"])
                    linije.append(f"• {l['naziv']}: {dijelovi}")
                else:
                    tip = " (kartica)" if l["tip"] == "kartica" else ""
                    linije.append(f"• {l['naziv']}{tip}: nema zabilježenih cijena")
            safe_send(chat_id, "⛽ Zadnje zabilježene cijene:\n" + "\n".join(linije))
            return
        # default: osvježi sve
        sazetak, _ = benzinske.osvjezi_sve()
        safe_send(chat_id, sazetak[:3900])
    except Exception as e:
        monitoring.error("Greška u /benzinske", source="benzinske", exc=e)
        safe_send(chat_id, f"❌ Greška: {e}")


def _zdravlje_worker(chat_id):
    try:
        rez = provjeri_zdravlje()
        linije = ["🩺 Zdravlje sustava (žive provjere):", ""]
        for naziv, ok, poruka in rez:
            linije.append(f"{'✅' if ok else '❌'} {naziv} — {poruka}")
        linije.append("")
        linije.append("✅ Bot (proces) — živ (vidiš ovu poruku).")
        linije.append("ℹ️ Ovisnosti se automatski provjeravaju u pozadini svakih "
                      f"{HEALTH_INTERVAL // 60} min; pad se javlja na monitor bot.")
        safe_send(chat_id, "\n".join(linije))
    except Exception as e:
        safe_send(chat_id, f"❌ Provjera zdravlja pala: {e}")


def handle_zdravlje(message):
    bot.reply_to(message, "🩺 Provjeravam ovisnosti (Mobilisis, Flota OS)…")
    threading.Thread(target=_zdravlje_worker, args=(message.chat.id,),
                     daemon=True).start()


def handle_benzinske(message):
    parts = message.text.split(maxsplit=1)
    arg = parts[1] if len(parts) > 1 else ""
    if arg.strip().startswith("probe"):
        bot.reply_to(message, "🔎 Provjeravam izvor…")
    elif arg.strip().startswith("stanje"):
        bot.reply_to(message, "⛽ Dohvaćam zadnje cijene…")
    else:
        bot.reply_to(message, "⏳ Osvježavam cijene goriva…")
    threading.Thread(target=_benzinske_worker, args=(message.chat.id, arg),
                     daemon=True).start()


def _wa_send_worker(chat_id, broj, tekst):
    try:
        res = whatsapp.send_text(broj, tekst)
        if res["ok"]:
            safe_send(chat_id, f"✅ Poslano na {broj}. Provjeri WhatsApp.")
        else:
            safe_send(chat_id,
                      "❌ Slanje nije uspjelo.\n\n"
                      f"{whatsapp.opisi_gresku(res)}\n\n"
                      f"Sirovi odgovor:\n{res['data']}"[:3800])
    except whatsapp.WhatsAppError as e:
        safe_send(chat_id, f"⚠️ {e}")
    except Exception as e:
        monitoring.error("Greska u /wa_send", source="wa_send", exc=e)
        safe_send(chat_id, f"❌ Greška pri slanju: {e}")


def handle_wa_send(message):
    # /wa_send <broj> <tekst poruke>
    parts = message.text.split(maxsplit=2)
    if len(parts) < 3:
        bot.reply_to(message, "Format:\n/wa_send <broj> <poruka>\n"
                              "npr: /wa_send 0994396448 Pozdrav iz bota 🚛\n\n"
                              "(obična poruka; radi samo unutar 24 h otkako je "
                              "korisnik zadnji pisao poslovnom broju)")
        return
    broj = _wa_broj(parts[1])
    tekst = parts[2].strip()
    if not broj.isdigit():
        bot.reply_to(message, "Neispravan broj. Npr: /wa_send 0994396448 Pozdrav")
        return
    bot.reply_to(message, "⏳ Šaljem poruku…")
    threading.Thread(target=_wa_send_worker, args=(message.chat.id, broj, tekst),
                     daemon=True).start()


# Dolazna WhatsApp poruka (iz web_api webhooka).
#  - ovlašteni zaposlenik (WHATSAPP_ALLOWED) -> obrada računa/primki na WhatsApp
#  - ostali -> obavijest vlasnicima na Telegram (kao dosad)
def wa_dolazna_poruka(frm, ime, msg):
    try:
        if whatsapp_racuni.is_allowed(frm):
            whatsapp_meni.obradi(frm, ime, msg)   # izbornik + tokovi (računi, kvar, sati…)
            return
    except Exception as e:
        monitoring.error("WhatsApp dispatch nije uspio", source="main", exc=e)
    tip = msg.get("type")
    tekst = (msg.get("text") or {}).get("body", "") if tip == "text" else f"[{tip}]"
    poruka = (f"📱 WhatsApp poruka\n"
              f"od: {ime}" + (f" ({frm})" if ime != frm else "") + "\n\n"
              f"{tekst}")
    for uid in ALLOWED_USERS:
        safe_send(uid, poruka)


# ==================== HANDLERS ====================

@bot.message_handler(commands=['start', 'lista', 'list', 'podsjetnici', 'podsjetnik',
                               'reset', 'izvjestaj', 'backup_sada', 'gdje',
                               'wa_register', 'wa_test', 'wa_send', 'wa_token',
                               'wa_podsjetnici', 'wa_predlosci',
                               'wa_kreiraj_predloske', 'wa_predlozak',
                               'benzinske', 'podrska', 'zdravlje'])
def command_handler(message):
    if message.chat.id not in ALLOWED_USERS:
        return

    cmd = message.text.lower().strip()

    if cmd.startswith('/gdje'):
        handle_gdje(message)
        return

    if cmd.startswith('/zdravlje'):
        handle_zdravlje(message)
        return

    if cmd.startswith('/benzinske'):
        handle_benzinske(message)
        return

    if cmd.startswith('/podrska'):
        handle_podrska(message)
        return

    if cmd.startswith('/wa_kreiraj_predloske'):
        handle_wa_kreiraj_predloske(message)
        return

    if cmd.startswith('/wa_predlozak'):
        handle_wa_predlozak(message)
        return

    if cmd.startswith('/wa_predlosci'):
        handle_wa_predlosci(message)
        return

    if cmd.startswith('/wa_podsjetnici'):
        handle_wa_podsjetnici(message)
        return

    if cmd.startswith('/wa_token'):
        handle_wa_token(message)
        return

    if cmd.startswith('/wa_send'):
        handle_wa_send(message)
        return

    if cmd.startswith('/wa_register'):
        handle_wa_register(message)
        return

    if cmd.startswith('/wa_test'):
        handle_wa_test(message)
        return

    if cmd.startswith('/backup_sada'):
        # Admin test: okini backup odmah (u threadu — ne blokira polling).
        bot.reply_to(message, "⏳ Pokrećem backup baze na SharePoint…")

        def _run_backup_now(chat_id):
            ok, name = backup.run_backup()
            if ok:
                safe_send(chat_id, f"✅ Backup gotov: {name}")
            else:
                safe_send(chat_id, "❌ Backup NIJE uspio — provjeri log / monitor.")

        threading.Thread(target=_run_backup_now, args=(message.chat.id,),
                         daemon=True).start()
        return

    if cmd.startswith('/start'):
        bot.reply_to(
            message,
            "✅ Bot je aktivan!\n\n"
            "Podsjetnik postaviš običnom porukom, npr:\n"
            "• u 14:30 idem na trening\n"
            "• sutra u 10 nazovi klijenta\n"
            "• 15.8. u 9 registracija kamiona\n"
            "• svaki dan u 7:30 provjeri kamione\n"
            "• svaka 2 dana u 8 zalij cvijeće\n"
            "• svaki 2. tjedan pon u 8 sastanak\n"
            "• svaki mjesec 15. u 9 plati leasing\n"
            "• zadnji dan u mjesecu u 20 izvještaj\n\n"
            "Kad podsjetnik stigne, gumbima ga možeš odgoditi "
            "(+15 min, +1 h, +3 h, sutra) ili označiti gotovim.\n\n"
            "Bilježenje rada i izvještaj:\n"
            "• zabilježi obavljena dostava Zagreb – zabilježi što si napravio\n"
            "• „gotovi za danas“ ili /izvjestaj – dnevni izvještaj\n\n"
            "Računi i primke:\n"
            "• pošalji fotografiju računa ili primke – automatski prepoznam "
            "vrstu, izvučem podatke i, nakon tvoje potvrde, upišem ih u Excel "
            "na SharePointu (računi → Racuni_terena, primke → Primke_terena)\n"
            "• višestranična primka: pošalji sve fotke (album ili jednu po "
            "jednu) pa klikni „Obradi dokument” ili napiši /gotovo\n\n"
            "Naredbe:\n"
            "/lista – pregled podsjetnika (brisanje gumbom)\n"
            "/izvjestaj – dnevni izvještaj\n"
            "/reset – obriši povijest AI razgovora\n"
            "/vozac_dodaj <id> <GB> <ime> – dodaj/uredi vozača (admin)\n"
            "/vozac_lista – popis vozača (admin)\n"
            "/backup_sada – ručni backup baze na SharePoint (admin)\n"
            "/gdje <GB ili registracija> – GPS lokacija vozila (Mobilisis)\n"
            "/zdravlje – provjera Mobilisis/Flota OS veza (admin)\n\n"
            "Sve ostalo što napišeš ide AI asistentu."
        )
        return

    if cmd.startswith('/izvjestaj'):
        send_daily_report(message)
        return

    if cmd.startswith('/reset'):
        with history_lock:
            history.pop(message.chat.id, None)
        bot.reply_to(message, "🧹 Povijest razgovora obrisana.")
        return

    if cmd.startswith(('/lista', '/list', '/podsjetnici', '/podsjetnik')):
        show_reminders(message)
        return


# VAZNO: content_types=['text'] — inace bi ovaj "catch-all" handler mogao
# progutati i fotke/dokumente (ovisno o verziji telebota) pa bi photo handler
# u racuni.py nikad ne bio pozvan (telebot izvrsi PRVI handler koji matcha).
@bot.message_handler(func=lambda m: True, content_types=['text'])
def handle(message):
    if message.chat.id not in ALLOWED_USERS:
        return

    # Sigurnosni pojas: ako ipak stigne ne-tekst, ne diraj message.text (None).
    if message.content_type != 'text' or not (message.text or '').strip():
        return

    text = message.text.strip()
    lower = text.lower()

    # 0. Racuni: pending stanja (npr. cekamo GB ili ispravak) i /vozac_*
    #    komande. Ako racuni "pojede" poruku, ne idemo dalje.
    if racuni.handle_text(message):
        return

    # 1. Dnevni izvjestaj ("gotovi za danas" i sl.) - provjeri prvo da ne
    # bude protumaceno kao podsjetnik ili AI poruka.
    if is_report_trigger(lower):
        send_daily_report(message)
        return

    # 2. Rucna zabiljeska rada ("zabilježi ...")
    note = extract_note(text)
    if note is not None:
        if note:
            log_note(message.chat.id, note)
            bot.reply_to(message, f"📝 Zabilježeno: {note}")
        else:
            bot.reply_to(message, "Napiši što da zabilježim, npr:\nzabilježi obavljena dostava Zagreb")
        return

    # 3. Kljucne rijeci za pregled podsjetnika
    list_keywords = ["lista", "podsjetnici", "moji podsjetnici",
                     "pokaži podsjetnike", "pregled podsjetnika"]
    if any(k == lower or k in lower for k in list_keywords) and len(lower) < 30:
        show_reminders(message)
        return

    # 4. Pokusaj prepoznati kao podsjetnik
    result, rtype, desc = parse_time(text)
    if result is not None:
        if rtype == "once":
            add_reminder(message.chat.id, desc, result)
            bot.reply_to(
                message,
                f"✅ Podsjetnik postavljen za {result.strftime('%d.%m.%Y. %H:%M')}\n📝 {desc}"
            )
        elif rtype == "daily":
            add_recurring(message.chat.id, desc, "daily",
                          result["hour"], result["minute"],
                          interval=result["interval"])
            n = result["interval"]
            when = (f"Svaki dan u {result['hour']:02d}:{result['minute']:02d}" if n == 1
                    else f"Svaka {n} dana u {result['hour']:02d}:{result['minute']:02d}")
            bot.reply_to(message, f"✅ Ponavljajući podsjetnik postavljen ({when})\n📝 {desc}")
        elif rtype == "weekly":
            add_recurring(message.chat.id, desc, "weekly",
                          result["hour"], result["minute"],
                          weekday=result["weekday"], interval=result["interval"])
            n = result["interval"]
            day = DAY_NAMES_INSTR[result["weekday"]]
            when = (f"svakim {day} u {result['hour']:02d}:{result['minute']:02d}" if n == 1
                    else f"svaki {n}. tjedan {day} u {result['hour']:02d}:{result['minute']:02d}")
            bot.reply_to(message, f"✅ Ponavljajući podsjetnik postavljen ({when})\n📝 {desc}")
        else:  # monthly
            add_recurring(message.chat.id, desc, "monthly",
                          result["hour"], result["minute"],
                          monthday=result["monthday"])
            hhmm = f"{result['hour']:02d}:{result['minute']:02d}"
            when = ("zadnji dan u mjesecu" if result["monthday"] >= 32
                    else f"svaki mjesec {result['monthday']}.")
            bot.reply_to(message, f"✅ Ponavljajući podsjetnik postavljen ({when} u {hhmm})\n📝 {desc}")
        return

    # 5. Sve ostalo -> AI razgovor
    response = get_ai_response(message.chat.id, text)
    bot.reply_to(message, response)


# ==================== START ====================

if __name__ == "__main__":
    print("🚀 Bot se pokreće...")
    monitoring.install("bravel-agent")  # hvatanje neuhvacenih iznimki -> monitoring bot
    monitoring.start_heartbeat(interval=60)  # 'puls' svakih 60 s -> monitor prati je li bot ziv
    init_db()
    # Modul za racune: injektiraj ovisnosti, kreiraj tablicu vozaca,
    # registriraj photo/document/callback handlere.
    racuni.setup(bot=bot, client=client, db=db,
                 allowed_users=ALLOWED_USERS, tz=TZ, log_note=log_note)
    racuni.init_db()
    racuni.register(bot)

    # WhatsApp izbornik (upravljačka ploča za radnike): ubrizgaj Mobilisis lookup
    # (za „Gdje je vozilo”) i obavijest vlasnicima na Telegram (za „Prijava kvara”,
    # „Evidencija sati”). Kreira tablice wa_sati / wa_podsjetnici.
    def _wa_obavijesti_vlasnike(text):
        for uid in ALLOWED_USERS:
            safe_send(uid, text)

    def _wa_gdje_lookup(query):
        return _format_gdje(mobilisis.lookup(query), query)

    whatsapp_meni.setup(gdje_lookup=_wa_gdje_lookup,
                        obavijesti=_wa_obavijesti_vlasnike)

    # Ispis registriranih handlera (redoslijed = prioritet matchanja u telebotu).
    def _dump_handlers():
        parts = []
        for h in getattr(bot, "message_handlers", []):
            fn = h.get("function")
            name = getattr(fn, "__name__", str(fn))
            filt = h.get("filters", {}) or {}
            parts.append(f"msg:{name}(content_types={filt.get('content_types')},"
                         f"commands={filt.get('commands')})")
        for h in getattr(bot, "callback_query_handlers", []):
            fn = h.get("function")
            parts.append(f"cb:{getattr(fn, '__name__', str(fn))}")
        return " | ".join(parts)

    print(f"[startup] registrirani handleri: {_dump_handlers()}", flush=True)
    monitoring.info(f"Registrirani handleri: {_dump_handlers()}", source="startup")

    # Dnevni backup baze na SharePoint (03:00 Europe/Zagreb, best-effort).
    backup.setup(DB_FILE, TZ)
    backup.start()

    # Registar benzinskih + tablica povijesti cijena (ista baza).
    benzinske.setup(DB_FILE)
    # Zagrij keš lokacija postaja (OSM/Overpass) u pozadini — /api/benzinske
    # ih onda vraća bez čekanja; best-effort, ne blokira start.
    threading.Thread(target=lambda: _benzinske_warm(), daemon=True).start()

    # Lagani HTTP server (aiohttp) u zasebnom threadu — GET /api/pozicije
    # (pozicije vozila iz Mobilisisa) + /zdrav. Ne blokira polling.
    podrska.set_on_zatvoreno(_podrska_zatvori)
    web_api.start(on_incoming=wa_dolazna_poruka, on_support=_podrska_ai_odgovori)

    bot.delete_webhook(drop_pending_updates=True)
    threading.Thread(target=check_reminders, daemon=True).start()
    print("✅ Bot pokrenut, slušam poruke")
    monitoring.info("Bot pokrenut i sluša poruke.", source="startup")
    bot.infinity_polling(allowed_updates=["message", "callback_query"])
