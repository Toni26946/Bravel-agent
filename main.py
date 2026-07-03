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
import logging
from openai import OpenAI

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

keep_alive

os.environ["OPENAI_API_KEY"] = os.getenv("OPENAI_API_KEY")
client = OpenAI()

TELEGRAM_TOKEN = "8968996549:AAE5YFAnUcnWd-esCwYyLzFKgAObJfFVuZU"
bot = telebot.TeleBot(TELEGRAM_TOKEN)

ALLOWED_USERS = [5191857104, 7599693099]

DB_FILE = "bravel.db"

# ==================== SQLITE ====================
def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS reminders (
                    id INTEGER PRIMARY KEY, text TEXT, time TEXT, chat_id INTEGER)''')
    c.execute('''CREATE TABLE IF NOT EXISTS recurring (
                    id INTEGER PRIMARY KEY, text TEXT, type TEXT, 
                    weekday INTEGER, hour INTEGER, minute INTEGER, chat_id INTEGER)''')
    conn.commit()
    conn.close()

def save_recurring(text, rtype, chat_id, data):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    if rtype == "daily":
        hour, minute = data
        c.execute("INSERT INTO recurring (text, type, hour, minute, chat_id) VALUES (?,?,?,?,?)",
                  (text, rtype, hour, minute, chat_id))
    else:  # weekly
        weekday, hour, minute = data
        c.execute("INSERT INTO recurring (text, type, weekday, hour, minute, chat_id) VALUES (?,?,?,?,?,?)",
                  (text, rtype, weekday, hour, minute, chat_id))
    conn.commit()
    conn.close()

def load_data():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT * FROM reminders")
    reminders = [dict(zip([col[0] for col in c.description], row)) for row in c.fetchall()]
    for r in reminders:
        r['time'] = datetime.fromisoformat(r['time'])
    
    c.execute("SELECT * FROM recurring")
    recurring = [dict(zip([col[0] for col in c.description], row)) for row in c.fetchall()]
    conn.close()
    return reminders, recurring

init_db()
reminders, recurring = load_data()

def get_current_datetime():
    return datetime.now(ZoneInfo("Europe/Zagreb"))

def parse_time(text):
    text = text.lower().strip()
    now = get_current_datetime()
    
    # PONAVLJAJUĆI - poboljšano
    if any(word in text for word in ["svaki dan", "svakodnevno", "every day"]):
        match = re.search(r'(?:u|at|oko)\s*(\d{1,2})[:.]?(\d{2})?', text)
        if match:
            return (int(match.group(1)), int(match.group(2) or 0)), "daily"
    
    days_map = {"ponedjeljak":0, "utorak":1, "srijeda":2, "četvrtak":3, "petak":4, "subota":5, "nedjelja":6,
                "petkom":4, "pon":0, "uto":1, "sri":2, "čet":3, "pet":4}
    for day_name, num in days_map.items():
        if day_name in text:
            match = re.search(r'(?:u|at|oko)\s*(\d{1,2})[:.]?(\d{2})?', text)
            if match:
                return (num, int(match.group(1)), int(match.group(2) or 0)), "weekly"
    
    # Jednokratni (ostavljeno isto)
    match = re.search(r'za (\d+) (minut|min)', text)
    if match:
        return now + timedelta(minutes=int(match.group(1))), "once"
    
    # ... (ostali jednokratni dio možeš ostaviti)

    return None, None

def check_reminders():
    while True:
        now = get_current_datetime()
        print(f"🔍 Provjera u {now.strftime('%H:%M')} | Ponavljajućih: {len(recurring)}")
        
        for r in recurring:
            if r['type'] == "daily" and r['hour'] == now.hour and r['minute'] == now.minute:
                bot.send_message(r['chat_id'], f"🔄 **PONAVLJAJUĆI PODSJETNIK**\n\n{r['text']}", parse_mode='Markdown')
            elif r['type'] == "weekly" and r.get('weekday') == now.weekday() and r['hour'] == now.hour and r['minute'] == now.minute:
                bot.send_message(r['chat_id'], f"🔄 **PONAVLJAJUĆI PODSJETNIK**\n\n{r['text']}", parse_mode='Markdown')
        
        time.sleep(10)  # provjera svakih 10 sekundi

threading.Thread(target=check_reminders, daemon=True).start()

# ... (ostatak koda - handle_message, callback itd. ostaje isti kao prije)

@bot.message_handler(func=lambda message: True)
def handle_message(message):
    if message.chat.id not in ALLOWED_USERS:
        return
    text = message.text.strip()
    chat_id = message.chat.id

    try:
        if "podsjetnici" in text.lower() or "lista" in text.lower():
            # ... tvoj stari kod za listu
            pass

        result = parse_time(text)
        if result and result[0] is not None:
            data, rtype = result
            if rtype in ["daily", "weekly"]:
                recurring.append({**data, 'text': text, 'chat_id': chat_id, 'type': rtype})
                save_recurring(text, rtype, chat_id, data)
                bot.reply_to(message, f"✅ **Ponavljajući podsjetnik postavljen!**\n\n{text}\nPonavlja se: {'svaki dan' if rtype=='daily' else 'svaki tjedan'}")
            else:
                # jednokratni...
                pass
            return

        # OpenAI dio...
        
    except Exception as e:
        bot.reply_to(message, f"Greška: {e}")

print("Bot pokrenut - ponavljajući popravljen")
bot.infinity_polling()
