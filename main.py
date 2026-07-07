# ============================================================
#  BRAVEL AGENT - Telegram bot
#  - SQLite persistencija na Fly Volume (/data/bot.db)
#  - Podsjetnici: jednokratni, dnevni, tjedni, svaka N dana,
#    svaki N. tjedan, mjesecni
#  - Odgoda podsjetnika gumbima (+15 min, +1 h, +3 h, sutra)
#  - AI razgovor (OpenAI) s pamcenjem konteksta po korisniku
# ============================================================

import os
import re
import time
import sqlite3
import calendar
import threading
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import telebot
from openai import OpenAI

# ==================== KONFIGURACIJA ====================

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
bot = telebot.TeleBot(TELEGRAM_TOKEN)

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

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
        return False


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

            # --- ciscenje: poslani jednokratni stariji od 2 dana ---
            with db() as conn:
                conn.execute("DELETE FROM reminders WHERE fired = 1 AND time_ts < ?",
                             (now_ts - 172800,))

        except Exception as e:
            print(f"Greska u check_reminders petlji: {e}")

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
            [{"role": "system", "content": SYSTEM_PROMPT}]
            + user_history
            + [{"role": "user", "content": text}]
        )

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            temperature=0.7,
        )
        answer = response.choices[0].message.content

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
        print(f"OpenAI greska: {e}")
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
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": (
                    "Na temelju razgovora radnika s botom napiši kratak, uredan sažetak "
                    "što je radnik danas radio, dogovorio ili planirao. Piši na hrvatskom, "
                    "u natuknicama koje počinju s '- '. Bez uvoda i zaključka. "
                    "Ako iz razgovora nema konkretnog posla, napiši samo '- nema konkretnih zadataka'."
                )},
                {"role": "user", "content": convo},
            ],
            temperature=0.4,
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        print(f"OpenAI sazetak greska: {e}")
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


# ==================== HANDLERS ====================

@bot.message_handler(commands=['start', 'lista', 'list', 'podsjetnici', 'podsjetnik',
                               'reset', 'izvjestaj'])
def command_handler(message):
    if message.chat.id not in ALLOWED_USERS:
        return

    cmd = message.text.lower().strip()

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
            "Naredbe:\n"
            "/lista – pregled podsjetnika (brisanje gumbom)\n"
            "/izvjestaj – dnevni izvještaj\n"
            "/reset – obriši povijest AI razgovora\n\n"
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


@bot.message_handler(func=lambda m: True)
def handle(message):
    if message.chat.id not in ALLOWED_USERS:
        return

    text = message.text.strip()
    lower = text.lower()

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
    init_db()
    bot.delete_webhook(drop_pending_updates=True)
    threading.Thread(target=check_reminders, daemon=True).start()
    print("✅ Bot pokrenut, slušam poruke")
    bot.infinity_polling(allowed_updates=["message", "callback_query"])
