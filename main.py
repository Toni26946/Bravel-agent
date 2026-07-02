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

print("Bravel Agent - Popravljen OpenAI jezik")

reminders = []
recurring = []

def get_current_datetime():
    return datetime.now(ZoneInfo("Europe/Zagreb"))

def parse_time(text):
    text = text.lower()
    now = get_current_datetime()
    
    # Ponavljajući
    if any(x in text for x in ["svaki dan", "svakodnevno"]):
        match = re.search(r'(?:u|at) (\d{1,2})[:.]?(\d{2})?', text)
        if match:
            return (int(match.group(1)), int(match.group(2) or 0)), "daily"
    
    days_map = {
        "ponedjeljak": 0, "utorak": 1, "srijeda": 2, "četvrtak": 3, "petak": 4,
        "subota": 5, "nedjelja": 6, "monday": 0, "tuesday": 1, "wednesday": 2,
        "thursday": 3, "friday": 4, "saturday": 5, "sunday": 6
    }
    
    for day_name, day_num in days_map.items():
        if day_name in text:
            match = re.search(r'(?:u|at) (\d{1,2})[:.]?(\d{2})?', text)
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
    
    match = re.search(r'u? (\d{1,2})[:.]?(\d{2})?', text)
    if match:
        hour = int(match.group(1))
        minute = int(match.group(2)) if match.group(2) else 0
        target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if target <= now:
            target += timedelta(days=1)
        return target, "once"
    
    return None, None

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
            # ... (ista lista kao prije)
            if not reminders and not recurring:
                bot.reply_to(message, "Nemaš aktivnih podsjetnika.")
                return

            msg = "📋 **Tvoji aktivni podsjetnici:**\n\n"
            markup = types.InlineKeyboardMarkup(row_width=1)
            count = 0

            for r in reminders:
                btn = types.InlineKeyboardButton("🗑 Izbriši", callback_data=f"delete_{count}")
                markup.add(btn)
                msg += f"{count+1}. {r['text']}\n"
                count += 1

            for r in recurring:
                btn = types.InlineKeyboardButton("🗑 Izbriši", callback_data=f"delete_{count}")
                markup.add(btn)
                if r.get('type') == "daily":
                    msg += f"{count+1}. {r['text']} (🔄 svaki dan u {r['hour']:02d}:{r['minute']:02d})\n"
                else:
                    days = ["Ponedjeljak","Utorak","Srijeda","Četvrtak","Petak","Subota","Nedjelja"]
                    msg += f"{count+1}. {r['text']} (🔄 svaki {days[r.get('weekday',0)]} u {r['hour']:02d}:{r['minute']:02d})\n"
                count += 1

            bot.reply_to(message, msg, reply_markup=markup)
            return

        if "status" in text.lower():
            bot.reply_to(message, "✅ Bot je aktivan i radi 24/7.")
            return

        # Parsiranje podsjetnika
        result = parse_time(text)
        if result and result[0] is not None:
            data, rtype = result
            if rtype == "daily":
                hour, minute = data
                recurring.append({'text': text, 'hour': hour, 'minute': minute, 'type': 'daily', 'chat_id': chat_id})
                bot.reply_to(message, f"✅ **Ponavljajući podsjetnik postavljen!**\n\n{text}")
            elif rtype == "weekly":
                weekday, hour, minute = data
                recurring.append({'text': text, 'weekday': weekday, 'hour': hour, 'minute': minute, 'type': 'weekly', 'chat_id': chat_id})
                bot.reply_to(message, f"✅ **Ponavljajući podsjetnik postavljen!**\n\n{text}")
            else:
                reminders.append({'text': text, 'time': data, 'chat_id': chat_id})
                bot.reply_to(message, f"✅ **Podsjetnik postavljen!**\n\n{text}")
            return

        # === OPENAI - STROŽA UPUTA ZA JEZIK ===
        current_time = get_current_datetime()
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "VAŽNO: Odgovaraj ISKLJUČIVO na jeziku na kojem ti je korisnik postavio pitanje. Ako je pitanje na hrvatskom - odgovori na hrvatskom. Ako je na engleskom - odgovori na engleskom. Ne miješaj jezike."},
                {"role": "user", "content": text}
            ],
            temperature=0.7
        )
        bot.reply_to(message, response.choices[0].message.content)

    except Exception as e:
        logger.error(f"Greška: {e}")
        bot.reply_to(message, "Došlo je do greške. Pokušaj ponovo.")

print("Bot je aktivan sa strožim jezičnim pravilima.")
bot.infinity_polling()
