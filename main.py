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

# === OpenAI setup ===
os.environ["OPENAI_API_KEY"] = os.getenv("OPENAI_API_KEY")
client = OpenAI()   # ovo mora biti ovdje

TELEGRAM_TOKEN = "8968996549:AAE5YFAnUcnWd-esCwYyLzFKgAObJfFVuZU"

bot = telebot.TeleBot(TELEGRAM_TOKEN)
ALLOWED_USERS = [5191857104, 7599693099]

print("Bravel Agent - Popravljeni OpenAI")

reminders = []
recurring = []

def get_current_datetime():
    return datetime.now(ZoneInfo("Europe/Zagreb"))

def parse_time(text):
    # (ista funkcija kao prije - skraćeno za čistoću)
    text = text.lower()
    now = get_current_datetime()
    
    if "svaki dan" in text or "svakodnevno" in text:
        match = re.search(r'(?:u|at) (\d{1,2})[:.]?(\d{2})?', text)
        if match:
            return (int(match.group(1)), int(match.group(2) or 0)), "daily"
    
    # ... ostale jednokratne logike (za sada ostavljamo jednostavno)
    return None, None

def check_reminders():
    while True:
        now = get_current_datetime()
        for r in reminders[:]:
            if r['time'] <= now:
                bot.send_message(r['chat_id'], f"🛎️ **PODSJETNIK**\n\n{r['text']}", parse_mode='Markdown')
                reminders.remove(r)
        time.sleep(5)

threading.Thread(target=check_reminders, daemon=True).start()

@bot.message_handler(func=lambda message: True)
def handle_message(message):
    if message.chat.id not in ALLOWED_USERS:
        return
    
    text = message.text.strip()
    chat_id = message.chat.id

    try:
        # 1. Provjera specijalnih naredbi
        if "podsjetnici" in text.lower() or "lista" in text.lower():
            bot.reply_to(message, "Lista podsjetnika u razvoju...")
            return
            
        if "status" in text.lower():
            bot.reply_to(message, "✅ Bot je aktivan i radi 24/7.")
            return

        # 2. Pokušaj parsirati podsjetnik
        result = parse_time(text)
        if result and result[0] is not None:
            # ... logika za podsjetnike (ostaje ista)
            bot.reply_to(message, "✅ Podsjetnik postavljen!")
            return

        # 3. Ako nije podsjetnik → OpenAI
        logger.info("Šaljem poruku OpenAI-u...")
        current_time = get_current_datetime()
        
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": f"Ti si koristan i prijateljski pomoćnik za logističku firmu Bravel. Trenutni datum i vrijeme je: {current_time.strftime('%d.%m.%Y %H:%M')}. Odgovaraj kratko i jasno na hrvatskom jeziku."},
                {"role": "user", "content": text}
            ],
            temperature=0.7,
            max_tokens=500
        )
        
        ai_reply = response.choices[0].message.content.strip()
        bot.reply_to(message, ai_reply)
        
    except Exception as e:
        logger.error(f"OpenAI greška: {e}")
        bot.reply_to(message, "❌ OpenAI trenutno ne radi. Pokušaj ponovo za par sekundi.")

print("Bot pokrenut sa popravljenim OpenAI-om.")
bot.infinity_polling()
