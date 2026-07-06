import os
from datetime import datetime, timedelta
import time
import threading
import re
import sqlite3
import telebot
from telebot import types
import keep_alive
from zoneinfo import ZoneInfo

keep_alive.keep_alive()

TELEGRAM_TOKEN = "8968996549:AAE5YFAnUcnWd-esCwYyLzFKgAObJfFVuZU"
bot = telebot.TeleBot(TELEGRAM_TOKEN)

ALLOWED_USERS = [5191857104, 7599693099]

DB_FILE = "bravel.db"

# ==================== DATABASE ====================
def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS reminders (
                    id INTEGER PRIMARY KEY, 
                    text TEXT, 
                    remind_time TEXT, 
                    chat_id INTEGER)''')
    c.execute('''CREATE TABLE IF NOT EXISTS recurring (
                    id INTEGER PRIMARY KEY, 
                    text TEXT, 
                    rtype TEXT, 
                    weekday INTEGER, 
                    hour INTEGER, 
                    minute INTEGER, 
                    chat_id INTEGER)''')
    conn.commit()
    conn.close()

def save_reminder(text, remind_time, chat_id):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("INSERT INTO reminders (text, remind_time, chat_id) VALUES (?,?,?)",
              (text, remind_time.isoformat(), chat_id))
    conn.commit()
    conn.close()

def save_recurring(text, rtype, chat_id, data):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    if rtype == "daily":
        hour, minute = data
        c.execute("INSERT INTO recurring (text, rtype, hour, minute, chat_id) VALUES (?,?,?,?,?)",
                  (text, rtype, hour, minute, chat_id))
    else:  # weekly
        weekday, hour, minute = data
        c.execute("INSERT INTO recurring (text, rtype, weekday, hour, minute, chat_id) VALUES (?,?,?,?,?,?)",
                  (text, rtype, weekday, hour, minute, chat_id))
    conn.commit()
    conn.close()

def load_reminders():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT * FROM reminders")
    reminders = []
    for row in c.fetchall():
        reminders.append({
            'id': row[0],
            'text': row[1],
            'time': datetime.fromisoformat(row[2]),
            'chat_id': row[3]
        })
    c.execute("SELECT * FROM recurring")
    recurring = [dict(zip([col[0] for col in c.description], row)) for row in c.fetchall()]
    conn.close()
    return reminders, recurring

init_db()
reminders, recurring = load_reminders()

def get_now():
    return datetime.now(ZoneInfo("Europe/Zagreb"))

# ==================== PARSE TIME ====================
def parse_time(text):
    text = text.lower().strip()
    now = get_now()

    # === PONAVLJAJUĆI ===
    if any(x in text for x in ["svaki dan", "svakodnevno", "daily"]):
        m = re.search(r'(?:u|at|oko)\s*(\d{1,2})[:.]?(\d{2})?', text)
        if m:
            return (int(m.group(1)), int(m.group(2) or 0)), "daily"

    days = {"ponedjeljak":0,"pon":0,"utorak":1,"uto":1,"srijeda":2,"sri":2,"četvrtak":3,"čet":3,
            "petak":4,"pet":4,"subota":5,"sub":5,"nedjelja":6,"ned":6}
    for name, wd in days.items():
        if name in text:
            m = re.search(r'(?:u|at|oko)\s*(\d{1,2})[:.]?(\d{2})?', text)
            if m:
                return (wd, int(m.group(1)), int(m.group(2) or 0)), "weekly"

    # === JEDNOKRATNI ===
    # Datum + vrijeme: 5.7. u 18:30
    m = re.search(r'(\d{1,2})[\./](\d{1,2})(?:[\./](\d{2,4}))?\s*(?:u|at|oko)?\s*(\d{1,2})[:.]?(\d{2})?', text)
    if m:
        d, mo, y, h, mi = m.groups()
        year = int(y) if y else now.year
        if year < 100: year += 2000
        target = datetime(year, int(mo), int(d), int(h), int(mi or 0), tzinfo=ZoneInfo("Europe/Zagreb"))
        if target < now:
            target = target.replace(year=target.year + 1)
        return target, "once"

    # Sutra / prekosutra
    if "sutra" in text:
        m = re.search(r'(?:u|at|oko)\s*(\d{1,2})[:.]?(\d{2})?', text)
        if m:
            h = int(m.group(1))
            mi = int(m.group(2) or 0)
            return (now + timedelta(days=1)).replace(hour=h, minute=mi, second=0, microsecond=0), "once"

    if "prekosutra" in text:
        m = re.search(r'(?:u|at|oko)\s*(\d{1,2})[:.]?(\d{2})?', text)
        if m:
            h = int(m.group(1))
            mi = int(m.group(2) or 0)
            return (now + timedelta(days=2)).replace(hour=h, minute=mi, second=0, microsecond=0), "once"

    # Za X minuta/sati
    m = re.search(r'za (\d+)\s*(min|sat|h)', text)
    if m:
        num = int(m.group(1))
        if "sat" in m.group(2) or "h" in m.group(2):
            return now + timedelta(hours=num), "once"
        return now + timedelta(minutes=num), "once"

    return None, None

# ==================== CHECK REMINDERS ====================
def check_reminders():
    global reminders, recurring
    while True:
        now = get_now()
        print(f"[{now.strftime('%H:%M:%S')}] Provjera podsjetnika...")

        # Jednokratni
        for r in reminders[:]:
            if r['time'] <= now:
                try:
                    bot.send_message(r['chat_id'], f"🔔 **PODSJETNIK**\n\n{r['text']}", parse_mode='Markdown')
                    # Obriši nakon slanja
                    conn = sqlite3.connect(DB_FILE)
                    conn.execute("DELETE FROM reminders WHERE id=?", (r['id'],))
                    conn.commit()
                    conn.close()
                    reminders.remove(r)
                except:
                    pass

        # Ponavljajući
        for r in recurring:
            if r['rtype'] == "daily" and r['hour'] == now.hour and r['minute'] == now.minute:
                bot.send_message(r['chat_id'], f"🔄 **DNEVNI PODSJETNIK**\n\n{r['text']}", parse_mode='Markdown')
            elif r['rtype'] == "weekly" and r.get('weekday') == now.weekday() and r['hour'] == now.hour and r['minute'] == now.minute:
                bot.send_message(r['chat_id'], f"🔄 **TJEDNI PODSJETNIK**\n\n{r['text']}", parse_mode='Markdown')

        time.sleep(10)

# ==================== BOT HANDLERS ====================
@bot.message_handler(commands=['start'])
def start(message):
    if message.chat.id not in ALLOWED_USERS:
        bot.reply_to(message, "Nemaš pristup.")
        return
    bot.reply_to(message, "✅ Bot je spreman!\n\nPošalji podsjetnik npr.:\n- `svaki dan u 8:00 popij tabletu`\n- `5.7. u 18:30 trening`\n- `sutra u 9:00`")

@bot.message_handler(func=lambda m: True)
def handle_all(message):
    if message.chat.id not in ALLOWED_USERS:
        return
    
    result, rtype = parse_time(message.text)
    
    if result:
        if rtype == "once":
            save_reminder(message.text, result, message.chat.id)
            bot.reply_to(message, f"✅ Jednokratni podsjetnik postavljen za:\n{result.strftime('%d.%m.%Y. %H:%M')}")
        else:
            save_recurring(message.text, rtype, message.chat.id, result)
            bot.reply_to(message, f"✅ **Ponavljajući podsjetnik spreman!**\n\n{message.text}")
    else:
        bot.reply_to(message, "❌ Nisam razumio vrijeme. Pokušaj ponovo.")

# ==================== START ====================
print("🚀 Bot pokrenut...")
threading.Thread(target=check_reminders, daemon=True).start()
bot.infinity_polling()
