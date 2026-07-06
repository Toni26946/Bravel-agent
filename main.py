# ============================================================
#  BRAVEL AGENT - Telegram bot
#  - SQLite persistencija na Fly Volume (/data/bot.db)
#  - Podsjetnici (jednokratni, dnevni, tjedni)
#  - AI razgovor (OpenAI) s pamcenjem konteksta po korisniku
#  - Bez keep_alive (nepotreban na fly.io)
# ============================================================

import os
import re
import time
import sqlite3
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

# Na fly.io je volume mountan na /data. Za lokalno testiranje
# (bez /data mape) baza se sprema u trenutni direktorij.
DB_FILE = "/data/bot.db" if os.path.isdir("/data") else "bot.db"

TZ = ZoneInfo("Europe/Zagreb")

# Povijest AI razgovora po korisniku (u RAM-u, resetira se kod restarta).
# Kljuc: chat_id, vrijednost: lista {"role": ..., "content": ...}
HISTORY_LIMIT = 20  # zadnjih 20 poruka (10 izmjena) po korisniku
history = {}
history_lock = threading.Lock()


def get_now():
    return datetime.now(TZ)


# ==================== BAZA (SQLite) ====================
# Svaka operacija otvara svoju konekciju ("konekcija po operaciji").
# To je thread-safe i za ovaj obujam sasvim dovoljno brzo.
# WAL mode omogucuje da jedan thread cita dok drugi pise.

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
                time_ts REAL    NOT NULL   -- unix timestamp (UTC), pouzdan za usporedbu
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS recurring (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id    INTEGER NOT NULL,
                text       TEXT    NOT NULL,
                rtype      TEXT    NOT NULL,          -- 'daily' ili 'weekly'
                weekday    INTEGER,                    -- 0=pon ... 6=ned (samo weekly)
                hour       INTEGER NOT NULL,
                minute     INTEGER NOT NULL,
                last_fired TEXT                        -- 'YYYY-MM-DD HH:MM' zadnjeg okidanja
            )
        """)
    print(f"Baza spremna: {DB_FILE}")


def add_reminder(chat_id, text, dt):
    with db() as conn:
        conn.execute(
            "INSERT INTO reminders (chat_id, text, time_ts) VALUES (?, ?, ?)",
            (chat_id, text, dt.timestamp())
        )


def add_recurring(chat_id, text, rtype, hour, minute, weekday=None):
    with db() as conn:
        conn.execute(
            "INSERT INTO recurring (chat_id, text, rtype, weekday, hour, minute) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (chat_id, text, rtype, weekday, hour, minute)
        )


def get_user_items(chat_id):
    """Vraca (jednokratni, ponavljajuci) za jednog korisnika,
    deterministicki poredano - isti poredak koristi i /lista i /obrisi."""
    with db() as conn:
        once = conn.execute(
            "SELECT * FROM reminders WHERE chat_id = ? ORDER BY time_ts, id",
            (chat_id,)
        ).fetchall()
        rec = conn.execute(
            "SELECT * FROM recurring WHERE chat_id = ? ORDER BY id",
            (chat_id,)
        ).fetchall()
    return once, rec


# ==================== PARSIRANJE VREMENA ====================

def _make_description(original, spans):
    """Iz originalnog teksta izbaci dijelove koji opisuju vrijeme (spans)
    i vrati ocisceni opis podsjetnika, s velikim pocetnim slovom."""
    spans = sorted(spans)
    parts, prev = [], 0
    for s, e in spans:
        parts.append(original[prev:s])
        prev = e
    parts.append(original[prev:])
    desc = re.sub(r'\s+', ' ', ''.join(parts)).strip(' ,.;:-–—')
    if not desc:
        return "Podsjetnik"
    return desc[0].upper() + desc[1:]


TIME_RE = r'(?:u|at|oko)\s*(\d{1,2})[:.]?(\d{2})?'


def parse_time(text):
    """Vraca (rezultat, tip, opis).
    tip: 'once' / 'daily' / 'weekly' / None
    opis: tekst podsjetnika bez vremenskog dijela ("Idem na trening")"""
    original = text.strip()
    low = original.lower()
    now = get_now()

    # 1. Format: 7.7. u 10:30 ili 07.07.2026 u 10:30
    # \.? iza mjeseca/godine dopusta hrvatski nacin pisanja datuma s tockom ("7.7.")
    m = re.search(
        r'(\d{1,2})[\./](\d{1,2})(?:[\./](\d{2,4}))?\.?\s*(?:u|at|oko|za)?\s*(\d{1,2})[:.]?(\d{2})?',
        low
    )
    if m:
        day = int(m.group(1))
        month = int(m.group(2))
        year = int(m.group(3)) if m.group(3) else now.year
        if year < 100:
            year += 2000
        hour = int(m.group(4))
        minute = int(m.group(5) or 0)
        try:
            target = datetime(year, month, day, hour, minute, tzinfo=TZ)
            if target < now:
                target = target.replace(year=target.year + 1)
            return target, "once", _make_description(original, [m.span()])
        except Exception:
            pass

    # 2. Ponavljajuci - svaki dan
    for kw in ["svaki dan", "svakodnevno", "daily"]:
        kw_pos = low.find(kw)
        if kw_pos != -1:
            m = re.search(TIME_RE, low)
            if m:
                desc = _make_description(original, [(kw_pos, kw_pos + len(kw)), m.span()])
                return (int(m.group(1)), int(m.group(2) or 0)), "daily", desc

    # 2b. Ponavljajuci - odredjeni dan u tjednu.
    # \b granice rijeci: "pon" ne matcha "ponuda", "pet" ne matcha "petsto".
    # Duzi nazivi idu prvi da "ponedjeljak" ne bude prepoznat kao "pon".
    days = [("ponedjeljak", 0), ("utorak", 1), ("srijeda", 2), ("četvrtak", 3),
            ("petak", 4), ("subota", 5), ("nedjelja", 6),
            ("pon", 0), ("uto", 1), ("sri", 2), ("čet", 3),
            ("pet", 4), ("sub", 5), ("ned", 6)]
    for name, wd in days:
        dm = re.search(r'\b' + name + r'\b', low)
        if dm:
            m = re.search(TIME_RE, low)
            if m:
                desc = _make_description(original, [dm.span(), m.span()])
                return (wd, int(m.group(1)), int(m.group(2) or 0)), "weekly", desc

    # 3. Relativni - prekosutra PRIJE jer sadrzi "sutra"
    for kw, offset in [("prekosutra", 2), ("sutra", 1)]:
        kw_pos = low.find(kw)
        if kw_pos != -1:
            m = re.search(TIME_RE, low)
            if m:
                h, mi = int(m.group(1)), int(m.group(2) or 0)
                target = (now + timedelta(days=offset)).replace(hour=h, minute=mi, second=0, microsecond=0)
                desc = _make_description(original, [(kw_pos, kw_pos + len(kw)), m.span()])
                return target, "once", desc

    # 4. Za X minuta/sati - [a-zć]* hvata cijelu rijec (sata, sati, minuta, minute...)
    m = re.search(r'za (\d+)\s*(minut[a-zć]*|min|sat[a-zć]*|h)\b', low)
    if m:
        num = int(m.group(1))
        unit = m.group(2)
        delta = timedelta(hours=num) if ("sat" in unit or "h" in unit) else timedelta(minutes=num)
        return now + delta, "once", _make_description(original, [m.span()])

    # 5. Samo vrijeme, bez datuma: "U 11:35 idem na trening" -> danas
    #    (ili sutra ako je vrijeme vec proslo). Trazimo HH:MM s dvotockom/tockom
    #    ili sam sat ("u 14") - provjera ide ZADNJA da ne pregazi gornje formate.
    m = re.search(r'\bu\s*(\d{1,2})(?:[:.](\d{2}))?\b', low)
    if m:
        h = int(m.group(1))
        mi = int(m.group(2) or 0)
        if 0 <= h <= 23 and 0 <= mi <= 59:
            target = now.replace(hour=h, minute=mi, second=0, microsecond=0)
            if target <= now:
                target += timedelta(days=1)
            return target, "once", _make_description(original, [m.span()])

    return None, None, None


# ==================== SLANJE PORUKA ====================
# Bez parse_mode: korisnikov tekst moze sadrzavati * ili _ koji rusi
# Markdown parsiranje pa se poruka uopce ne posalje. Plain text je siguran.

def safe_send(chat_id, text):
    try:
        bot.send_message(chat_id, text)
        return True
    except Exception as e:
        print(f"Greska pri slanju poruke ({chat_id}): {e}")
        return False


# ==================== PROVJERA PODSJETNIKA (thread) ====================

def check_reminders():
    while True:
        # Cijeli ciklus u try/except - ako bilo sto pukne (mreza, baza),
        # thread NE umire nego pokusa opet za 10 sekundi.
        try:
            now = get_now()
            now_ts = now.timestamp()
            fired_key = now.strftime('%Y-%m-%d %H:%M')

            # --- jednokratni ---
            with db() as conn:
                due = conn.execute(
                    "SELECT * FROM reminders WHERE time_ts <= ?", (now_ts,)
                ).fetchall()

            for r in due:
                sent = safe_send(r["chat_id"], f"🔔 PODSJETNIK\n\n{r['text']}")
                # Brisi iz baze i ako slanje nije uspjelo - inace bi
                # neispravan chat_id spamao pokusaje svakih 10 sekundi.
                # (Privremene mrezne greske rjesava telebot-ov vlastiti retry.)
                with db() as conn:
                    conn.execute("DELETE FROM reminders WHERE id = ?", (r["id"],))
                if not sent:
                    print(f"Podsjetnik {r['id']} obrisan iako slanje nije uspjelo: {r['text']}")

            # --- ponavljajuci ---
            with db() as conn:
                rec = conn.execute("SELECT * FROM recurring").fetchall()

            for r in rec:
                # last_fired sprjecava visestruko okidanje unutar iste minute
                if r["last_fired"] == fired_key:
                    continue

                should_fire = False
                if r["rtype"] == "daily" and r["hour"] == now.hour and r["minute"] == now.minute:
                    should_fire = True
                elif (r["rtype"] == "weekly" and r["weekday"] == now.weekday()
                        and r["hour"] == now.hour and r["minute"] == now.minute):
                    should_fire = True

                if should_fire:
                    with db() as conn:
                        conn.execute(
                            "UPDATE recurring SET last_fired = ? WHERE id = ?",
                            (fired_key, r["id"])
                        )
                    label = "DNEVNI" if r["rtype"] == "daily" else "TJEDNI"
                    safe_send(r["chat_id"], f"🔄 {label} PODSJETNIK\n\n{r['text']}")

        except Exception as e:
            print(f"Greska u check_reminders petlji: {e}")

        time.sleep(10)


# ==================== PRIKAZ I BRISANJE ====================

def show_reminders(message):
    once, rec = get_user_items(message.chat.id)

    if not once and not rec:
        bot.reply_to(message, "Trenutno nemaš aktivnih podsjetnika.")
        return

    lines = ["📋 Tvoji podsjetnici:", ""]
    idx = 1

    if once:
        lines.append("Jednokratni:")
        for r in once:
            dt = datetime.fromtimestamp(r["time_ts"], TZ)
            lines.append(f"{idx}. {dt.strftime('%d.%m.%Y. %H:%M')} → {r['text']}")
            idx += 1
        lines.append("")

    if rec:
        lines.append("Ponavljajući:")
        day_names = ["Pon", "Uto", "Sri", "Čet", "Pet", "Sub", "Ned"]
        for r in rec:
            if r["rtype"] == "daily":
                lines.append(f"{idx}. 🔄 Svaki dan u {r['hour']:02d}:{r['minute']:02d} → {r['text']}")
            else:
                wd = day_names[r["weekday"] or 0]
                lines.append(f"{idx}. 🔄 {wd} u {r['hour']:02d}:{r['minute']:02d} → {r['text']}")
            idx += 1

    lines.append("")
    lines.append("Za brisanje: /obrisi BROJ (npr. /obrisi 2)")
    bot.reply_to(message, "\n".join(lines))


def delete_reminder(message):
    m = re.search(r'/obrisi\s+(\d+)', message.text.lower())
    if not m:
        bot.reply_to(message, "Napiši broj podsjetnika, npr. /obrisi 2\nBrojeve vidiš sa /lista")
        return

    num = int(m.group(1))
    once, rec = get_user_items(message.chat.id)  # isti poredak kao /lista
    total = len(once) + len(rec)

    if num < 1 or num > total:
        bot.reply_to(message, f"Ne postoji podsjetnik broj {num}. Provjeri /lista")
        return

    if num <= len(once):
        target = once[num - 1]
        with db() as conn:
            conn.execute("DELETE FROM reminders WHERE id = ?", (target["id"],))
        bot.reply_to(message, f"🗑 Obrisan podsjetnik: {target['text']}")
    else:
        target = rec[num - len(once) - 1]
        with db() as conn:
            conn.execute("DELETE FROM recurring WHERE id = ?", (target["id"],))
        bot.reply_to(message, f"🗑 Obrisan ponavljajući podsjetnik: {target['text']}")


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

        # Spremi izmjenu u povijest i odrezi na zadnjih HISTORY_LIMIT poruka
        with history_lock:
            h = history.setdefault(chat_id, [])
            h.append({"role": "user", "content": text})
            h.append({"role": "assistant", "content": answer})
            history[chat_id] = h[-HISTORY_LIMIT:]

        return answer
    except Exception as e:
        print(f"OpenAI greska: {e}")
        return "Žao mi je, imao sam problem s odgovorom. Pokušaj ponovno."


# ==================== HANDLERS ====================

@bot.message_handler(commands=['start', 'lista', 'list', 'podsjetnici', 'podsjetnik', 'obrisi', 'reset'])
def command_handler(message):
    if message.chat.id not in ALLOWED_USERS:
        return

    cmd = message.text.lower().strip()

    if cmd.startswith('/start'):
        bot.reply_to(
            message,
            "✅ Bot je aktivan!\n\n"
            "Podsjetnik postaviš običnom porukom, npr:\n"
            "• sutra u 10 nazovi klijenta\n"
            "• svaki dan u 7:30 provjeri kamione\n"
            "• petak u 14 sastanak\n\n"
            "Naredbe:\n"
            "/lista – pregled podsjetnika\n"
            "/obrisi BROJ – brisanje podsjetnika\n"
            "/reset – obriši povijest AI razgovora\n\n"
            "Sve ostalo što napišeš ide AI asistentu."
        )
        return

    if cmd.startswith('/obrisi'):
        delete_reminder(message)
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

    # 1. Kljucne rijeci za pregled podsjetnika
    list_keywords = ["lista", "podsjetnici", "moji podsjetnici",
                     "pokaži podsjetnike", "pregled podsjetnika"]
    if any(k == lower or k in lower for k in list_keywords) and len(lower) < 30:
        show_reminders(message)
        return

    # 2. Pokusaj prepoznati kao podsjetnik
    result, rtype, desc = parse_time(text)
    if result is not None:
        if rtype == "once":
            add_reminder(message.chat.id, desc, result)
            bot.reply_to(
                message,
                f"✅ Podsjetnik postavljen za {result.strftime('%d.%m.%Y. %H:%M')}\n📝 {desc}"
            )
        elif rtype == "daily":
            hour, minute = result
            add_recurring(message.chat.id, desc, "daily", hour, minute)
            bot.reply_to(
                message,
                f"✅ Dnevni podsjetnik postavljen ({hour:02d}:{minute:02d})\n📝 {desc}"
            )
        else:  # weekly
            weekday, hour, minute = result
            day_names = ["ponedjeljak", "utorak", "srijedu", "četvrtak", "petak", "subotu", "nedjelju"]
            add_recurring(message.chat.id, desc, "weekly", hour, minute, weekday)
            bot.reply_to(
                message,
                f"✅ Tjedni podsjetnik postavljen (svaki {day_names[weekday]} u {hour:02d}:{minute:02d})\n📝 {desc}"
            )
        return

    # 3. Sve ostalo -> AI razgovor
    response = get_ai_response(message.chat.id, text)
    bot.reply_to(message, response)


# ==================== START ====================

if __name__ == "__main__":
    print("🚀 Bot se pokreće...")
    init_db()
    bot.delete_webhook(drop_pending_updates=True)
    threading.Thread(target=check_reminders, daemon=True).start()
    print("✅ Bot pokrenut, slušam poruke")
    bot.infinity_polling()
