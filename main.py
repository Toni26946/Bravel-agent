import os
from datetime import datetime, timedelta
import time
import threading
import re
import telebot
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

print("Bravel Agent - Popravljen prioritet parsera")

reminders = []
recurring = []

def get_current_datetime():
    return datetime.now(ZoneInfo("Europe/Zagreb"))

def parse_time(text):
    text = text.lower()
    now = get_current_datetime()
    
    # === NAJVIŠI PRIORITET - detekcija podsjetnika ===
    reminder_keywords = ["podsjeti me", "postavi podsjetnik", "set reminder", "remind me", "sutra u", "svaki dan u", "u ", "za ", "za sutra"]
    
    if any(keyword in text for keyword in reminder_keywords):
        
        # Ponavljajući
        if "svaki dan" in text or "svakodnevno" in text:
            match = re.search(r'(?:u|at) (\d{1,2})[:.]?(\d{2})?', text)
            if match:
                return (int(match.group(1)), int(match.group(2) or 0)), "daily"
        
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
        
        # Općenito vrijeme
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

@bot.message_handler(func=lambda message: True)
def handle_message(message):
    if message.chat.id not in ALLOWED_USERS:
        return
    
    text = message.text.strip()
    chat_id = message.chat.id

    try:
        if "podsjetnici" in text.lower() or "lista" in text.lower():
            # ... (lista kod - možeš ostaviti iz prethodne verzije)
            bot.reply_to(message, "Lista podsjetnika u razvoju...")
            return

        if "status" in text.lower():
            bot.reply_to(message, "✅ Bot je aktivan i radi 24/7.")
            return

        # Pokušaj parsirati kao podsjetnik
        result = parse_time(text)
        if result and result[0] is not None:
            data, rtype = result
            if rtype == "daily":
                hour, minute = data
                recurring.append({'text': text, 'hour': hour, 'minute': minute, 'chat_id': chat_id})
                bot.reply_to(message, f"✅ **Ponavljajući podsjetnik postavljen!**\n\n{text}")
            else:
                reminders.append({'text': text, 'time': data, 'chat_id': chat_id})
                bot.reply_to(message, f"✅ **Podsjetnik postavljen!**\n\n{text}")
            return

        # Ako nije podsjetnik → OpenAI
        current_time = get_current_datetime()
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": f"Trenutni datum i vrijeme: {current_time.strftime('%d.%m.%Y %H:%M')}. Odgovori prijateljski na hrvatskom jeziku."},
                {"role": "user", "content": text}
            ],
            temperature=0.7
        )
        bot.reply_to(message, response.choices[0].message.content)

    except Exception as e:
        logger.error(f"Greška: {e}")
        bot.reply_to(message, "Došlo je do greške. Pokušaj ponovo.")

print("Bot je aktivan sa popravljenim prioritetom za podsjetnike.")
bot.infinity_polling()
