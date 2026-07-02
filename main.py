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

print("Bravel Agent - Podsjetnici sa inline tipkama za brisanje")

reminders = []      # jednokratni
recurring = []      # ponavljajući

def get_current_datetime():
    return datetime.now(ZoneInfo("Europe/Zagreb"))

def parse_time(text):
    # ... (ista funkcija kao prije)
    text = text.lower()
    now = get_current_datetime()
    
    if "svaki dan" in text or "svakodnevno" in text:
        match = re.search(r'(?:u|at) (\d{1,2})[:.]?(\d{2})?', text)
        if match:
            return (int(match.group(1)), int(match.group(2) or 0)), "daily"
    
    # Jednokratni (skraćeno)
    match = re.search(r'za (\d+) (minut|min)', text)
    if match:
        return now + timedelta(minutes=int(match.group(1))), "once"
    
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
            if r['hour'] == now.hour and r['minute'] == now.minute:
                bot.send_message(r['chat_id'], f"🔄 **PONAVLJAJUĆI**\n\n{r['text']}", parse_mode='Markdown')
        time.sleep(5)

threading.Thread(target=check_reminders, daemon=True).start()

# === CALLBACK ZA BRISANJE ===
@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    try:
        action, index = call.data.split("_")
        index = int(index)
        
        if action == "delete":
            all_reminders = reminders + recurring
            if 0 <= index < len(all_reminders):
                deleted = all_reminders[index]
                if deleted in reminders:
                    reminders.remove(deleted)
                else:
                    recurring.remove(deleted)
                bot.answer_callback_query(call.id, "✅ Podsjetnik izbrisan.")
                bot.edit_message_text("✅ Podsjetnik je uspješno izbrisan.", call.message.chat.id, call.message.message_id)
            else:
                bot.answer_callback_query(call.id, "❌ Greška.")
    except:
        bot.answer_callback_query(call.id, "❌ Greška pri brisanju.")

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
                btn = types.InlineKeyboardButton(f"🗑 Izbriši", callback_data=f"delete_{count}")
                markup.add(btn)
                msg += f"{count+1}. {r['text']}\n"
                count += 1

            # Ponavljajući
            for r in recurring:
                btn = types.InlineKeyboardButton(f"🗑 Izbriši", callback_data=f"delete_{count}")
                markup.add(btn)
                msg += f"{count+1}. {r['text']} (svaki dan u {r['hour']:02d}:{r['minute']:02d})\n"
                count += 1

            bot.reply_to(message, msg, reply_markup=markup)
            return

        if "status" in text.lower():
            bot.reply_to(message, "✅ Bot je aktivan i radi 24/7.")
            return

        # Parsiranje novog podsjetnika...
        result = parse_time(text)
        if result and result[0] is not None:
            data, rtype = result
            if rtype == "daily":
                hour, minute = data
                recurring.append({'text': text, 'hour': hour, 'minute': minute, 'chat_id': chat_id})
                bot.reply_to(message, f"✅ Ponavljajući podsjetnik postavljen!\n\n{text}")
            else:
                reminders.append({'text': text, 'time': data, 'chat_id': chat_id})
                bot.reply_to(message, f"✅ Podsjetnik postavljen!\n\n{text}")
        else:
            # OpenAI
            current_time = get_current_datetime()
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": f"Trenutni datum i vrijeme: {current_time.strftime('%d.%m.%Y %H:%M')}. Odgovori prijateljski na hrvatskom."},
                    {"role": "user", "content": text}
                ],
                temperature=0.7
            )
            bot.reply_to(message, response.choices[0].message.content)

    except Exception as e:
        logger.error(f"Greška: {e}")
        bot.reply_to(message, "Došlo je do greške. Pokušaj ponovo.")

print("Bot je aktivan sa inline tipkama za brisanje podsjetnika.")
bot.infinity_polling()
