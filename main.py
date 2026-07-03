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

print("Bravel Agent - SQLite verzija")

# ==================== SQLITE FUNKCIJE ====================
def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    
    c.execute('''CREATE TABLE IF NOT EXISTS reminders (
                    id INTEGER PRIMARY KEY,
                    text TEXT,
                    time TEXT,
                    chat_id INTEGER
                )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS recurring (
                    id INTEGER PRIMARY KEY,
                    text TEXT,
                    type TEXT,
                    weekday INTEGER,
                    hour INTEGER,
                    minute INTEGER,
                    chat_id INTEGER
                )''')
    
    conn.commit()
    conn.close()

def save_reminder(text, time_obj, chat_id):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("INSERT INTO reminders (text, time, chat_id) VALUES (?, ?, ?)", 
              (text, time_obj.isoformat(), chat_id))
    conn.commit()
    conn.close()

def save_recurring(text, rtype, chat_id, weekday=None, hour=None, minute=None):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("INSERT INTO recurring (text, type, weekday, hour, minute, chat_id) VALUES (?, ?, ?, ?, ?, ?)",
              (text, rtype, weekday, hour, minute, chat_id))
    conn.commit()
    conn.close()

def load_data():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    
    c.execute("SELECT * FROM reminders")
    reminders_list = []
    for row in c.fetchall():
        reminders_list.append({
            'id': row[0],
            'text': row[1],
            'time': datetime.fromisoformat(row[2]),
            'chat_id': row[3]
        })
    
    c.execute("SELECT * FROM recurring")
    recurring_list = []
    for row in c.fetchall():
        recurring_list.append({
            'id': row[0],
            'text': row[1],
            'type': row[2],
            'weekday': row[3],
            'hour': row[4],
            'minute': row[5],
            'chat_id': row[6]
        })
    
    conn.close()
    return reminders_list, recurring_list
    
init_db()
reminders, recurring = load_data()

def get_current_datetime():
    return datetime.now(ZoneInfo("Europe/Zagreb"))

def get_time_left(target):
    now = get_current_datetime()
    minutes = int((target - now).total_seconds() / 60)
    if minutes <= 0:
        return "uskoro"
    elif minutes < 60:
        return f"za {minutes} min"
    else:
        return f"za {minutes//60} sati"

def parse_time(text):
    text = text.lower()
    now = get_current_datetime()
    
    # ==================== PONAVLJAJUĆI ====================
    if any(x in text for x in ["svaki dan", "svakodnevno", "every day"]):
        match = re.search(r'(?:u|at|oko) (\d{1,2})[:.]?(\d{2})?', text)
        if match:
            return (int(match.group(1)), int(match.group(2) or 0)), "daily"
    
    # Svaki dan u tjednu
    days_map = {
        "ponedjeljak": 0, "utorak": 1, "srijeda": 2, "četvrtak": 3, "petak": 4,
        "subota": 5, "nedjelja": 6
    }
    for day_name, day_num in days_map.items():
        if day_name in text:
            match = re.search(r'(?:u|at|oko) (\d{1,2})[:.]?(\d{2})?', text)
            if match:
                return {"type": "weekly", "weekday": day_num, "hour": int(match.group(1)), "minute": int(match.group(2) or 0)}, "weekly"
    
    # Jednokratni
    match = re.search(r'za (\d+) (minut|min)', text)
    if match:
        return now + timedelta(minutes=int(match.group(1))), "once"
    
    if "sutra" in text:
        match = re.search(r'sutra.*u? (\d{1,2})[:.]?(\d{2})?', text)
        if match:
            hour = int(match.group(1))
            minute = int(match.group(2)) if match.group(2) else 0
            target = now + timedelta(days=1)
            target = target.replace(hour=hour, minute=minute, second=0, microsecond=0)
            return target, "once"
    
    match = re.search(r'(\d{1,2})\.(\d{1,2})\.?\s*(?:u|at|oko)?\s*(\d{1,2})[:.]?(\d{2})?', text)
    if match:
        day = int(match.group(1))
        month = int(match.group(2))
        hour = int(match.group(3))
        minute = int(match.group(4)) if match.group(4) else 0
        target = now.replace(day=day, month=month, hour=hour, minute=minute, second=0, microsecond=0)
        if target <= now:
            target = target.replace(year=target.year + 1)
        return target, "once"
    
    match = re.search(r'u? (\d{1,2})[:.]?(\d{2})?', text)
    if match:
        hour = int(match.group(1))
        minute = int(match.group(2)) if match.group(2) else 0
        target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if target <= now:
            target += timedelta(days=1)
        return target, "once"
    
    return None, None

def check_reminders():
    while True:
        now = get_current_datetime()
        
        for r in reminders[:]:
            if r['time'] <= now:
                bot.send_message(r['chat_id'], f"🛎️ **PODSJETNIK**\n\n{r['text']}", parse_mode='Markdown')
                reminders.remove(r)
        
        for r in recurring:
            if (r['type'] == "daily" and r['hour'] == now.hour and r['minute'] == now.minute) or \
               (r['type'] == "weekly" and r['weekday'] == now.weekday() and r['hour'] == now.hour and r['minute'] == now.minute):
                bot.send_message(r['chat_id'], f"🔄 **PONAVLJAJUĆI PODSJETNIK**\n\n{r['text']}", parse_mode='Markdown')
        
        time.sleep(5)

threading.Thread(target=check_reminders, daemon=True).start()

# Brisanje
@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    try:
        if call.data.startswith("delete_"):
            index = int(call.data.split("_")[1])
            all_rem = reminders + recurring
            if 0 <= index < len(all_rem):
                deleted = all_rem[index]
                if deleted in reminders:
                    reminders.remove(deleted)
                else:
                    recurring.remove(deleted)
                bot.answer_callback_query(call.id, "✅ Izbrisano!")
                bot.edit_message_text("✅ Podsjetnik je izbrisan.", call.message.chat.id, call.message.message_id)
    except:
        pass

@bot.message_handler(func=lambda message: True)
def handle_message(message):
    if message.chat.id not in ALLOWED_USERS:
        return
    
    text = message.text.strip()
    chat_id = message.chat.id

    try:
        if "podsjetnici" in text.lower() or "lista" in text.lower():
            if not reminders and not recurring:
                bot.reply_to(message, "Nemaš aktivnih podsjetnika.")
                return

            msg = "📋 **Tvoji aktivni podsjetnici:**\n\n"
            markup = types.InlineKeyboardMarkup(row_width=1)
            count = 0

            if reminders:
                msg += "**📌 Jednokratni podsjetnici:**\n"
                for r in reminders:
                    btn = types.InlineKeyboardButton("🗑 Izbriši", callback_data=f"delete_{count}")
                    markup.add(btn)
                    msg += f"{count+1}. {r['text']}\n   ⏰ {r['time'].strftime('%d.%m.%Y %H:%M')}\n"
                    count += 1

            if recurring:
                msg += "\n**🔄 Ponavljajući podsjetnici:**\n"
                for r in recurring:
                    btn = types.InlineKeyboardButton("🗑 Izbriši", callback_data=f"delete_{count}")
                    markup.add(btn)
                    if r['type'] == "daily":
                        msg += f"{count+1}. {r['text']} (🔄 svaki dan u {r['hour']:02d}:{r['minute']:02d})\n"
                    else:
                        days = ["Ponedjeljak","Utorak","Srijeda","Četvrtak","Petak","Subota","Nedjelja"]
                        msg += f"{count+1}. {r['text']} (🔄 svaki {days[r['weekday']]} u {r['hour']:02d}:{r['minute']:02d})\n"
                    count += 1

            bot.reply_to(message, msg, reply_markup=markup)
            return

        if "status" in text.lower():
            bot.reply_to(message, "✅ Bot je aktivan i radi 24/7.")
            return

        result = parse_time(text)
        if result and result[0] is not None:
            data, rtype = result
            if rtype in ["daily", "weekly"]:
                if isinstance(data, dict):
                    recurring.append({**data, 'text': text, 'chat_id': chat_id})
                else:
                    hour, minute = data
                    recurring.append({"type": "daily", "hour": hour, "minute": minute, 'text': text, 'chat_id': chat_id})
                bot.reply_to(message, f"✅ **Ponavljajući podsjetnik postavljen!**\n\n{text}")
            else:
                reminders.append({'text': text, 'time': data, 'chat_id': chat_id})
                bot.reply_to(message, f"""✅ **Podsjetnik postavljen!**

{text}
Datum: {data.strftime('%d.%m.%Y')}
Vrijeme: {data.strftime('%H:%M')}""")
            return

        # OpenAI
        if client:
            current_time = get_current_datetime()
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "system", "content": "Odgovaraj na istom jeziku na kojem ti je korisnik postavio pitanje."},
                          {"role": "user", "content": text}],
                temperature=0.7
            )
            bot.reply_to(message, response.choices[0].message.content)

    except Exception as e:
        logger.error(f"Greška: {e}")
        bot.reply_to(message, "Došlo je do greške. Pokušaj ponovo.")

print("Bot je aktivan sa SQLite bazom.")
bot.infinity_polling()
