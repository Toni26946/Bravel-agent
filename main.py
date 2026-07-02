import os
from datetime import datetime, timedelta
import time
import threading
import re
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

print("Bravel Agent - Popravljena lista podsjetnika")

reminders = []      # jednokratni
recurring = []      # ponavljajući

def get_current_datetime():
    return datetime.now(ZoneInfo("Europe/Zagreb"))

def get_time_left(target_time):
    """Vraća 'za x min' ili 'za x sati'"""
    now = get_current_datetime()
    delta = target_time - now
    minutes = int(delta.total_seconds() / 60)
    
    if minutes <= 0:
        return "uskoro"
    elif minutes < 60:
        return f"za {minutes} min"
    else:
        hours = minutes // 60
        return f"za {hours} sati"

def parse_time(text):
    text = text.lower()
    now = get_current_datetime()
    
    # Ponavljajući
    if any(x in text for x in ["svaki dan", "svakodnevno", "every day"]):
        match = re.search(r'(?:u|at|oko) (\d{1,2})[:.]?(\d{2})?', text)
        if match:
            return (int(match.group(1)), int(match.group(2) or 0)), "daily"
    
    # Svaki dan u tjednu
    days_map = {"ponedjeljak":0,"utorak":1,"srijeda":2,"četvrtak":3,"petak":4,"subota":5,"nedjelja":6,
                "monday":0,"tuesday":1,"wednesday":2,"thursday":3,"friday":4,"saturday":5,"sunday":6}
    for day_name, day_num in days_map.items():
        if day_name in text:
            match = re.search(r'(?:u|at|oko) (\d{1,2})[:.]?(\d{2})?', text)
            if match:
                return (day_num, int(match.group(1)), int(match.group(2) or 0)), "weekly"
    
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

# ==================== BRISANJE ====================
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

            # Jednokratni
            for r in reminders:
                btn = types.InlineKeyboardButton("🗑 Izbriši", callback_data=f"delete_{count}")
                markup.add(btn)
                time_left = get_time_left(r['time'])
                msg += f"{count+1}. {r['text']}\n   ⏰ {r['time'].strftime('%d.%m.%Y %H:%M')} ({time_left})\n"
                count += 1

            # Ponavljajući
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

        # Parsiranje
        result = parse_time(text)
        if result and result[0] is not None:
            data, rtype = result
            if rtype == "daily" or rtype == "weekly":
                recurring.append({**data, 'text': text, 'chat_id': chat_id})
                bot.reply_to(message, f"✅ **Ponavljajući podsjetnik postavljen!**\n\n{text}")
            else:
                reminders.append({'text': text, 'time': data, 'chat_id': chat_id})
                bot.reply_to(message, f"""✅ **Podsjetnik postavljen!**

{text}
Datum: {data.strftime('%d.%m.%Y')}
Vrijeme: {data.strftime('%H:%M')}""")
            return

        # OpenAI
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

print("Bot je aktivan sa popravljenom listom i vremenskim prikazom.")
bot.infinity_polling()
