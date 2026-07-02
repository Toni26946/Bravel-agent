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

print("Bravel Agent - Ažurirano (Lista + Više jezika)")

reminders = []      # jednokratni
recurring = []      # ponavljajući

def get_current_datetime():
    return datetime.now(ZoneInfo("Europe/Zagreb"))

def parse_time(text):
    # ... (ista funkcija kao u prethodnoj verziji - možeš kopirati)
    # Za sada ostavljam placeholder
    text = text.lower()
    now = get_current_datetime()
    
    if "svaki dan" in text or "svakodnevno" in text:
        match = re.search(r'(?:u|at) (\d{1,2})[:.]?(\d{2})?', text)
        if match:
            return (int(match.group(1)), int(match.group(2) or 0)), "daily"
    
    # Jednokratni logika...
    return None, None

def check_reminders():
    while True:
        now = get_current_datetime()
        # Jednokratni + Ponavljajući logika (ista kao prije)
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
            msg = "📋 **Tvoji aktivni podsjetnici:**\n\n"
            
            if reminders or recurring:
                if reminders:
                    msg += "**Jednokratni podsjetnici:**\n"
                    for r in reminders:
                        msg += f"• {r['text']}\n"
                if recurring:
                    msg += "\n**Ponavljajući podsjetnici:**\n"
                    for r in recurring:
                        if r.get('type') == "daily":
                            msg += f"• {r['text']} (svaki dan u {r['hour']:02d}:{r['minute']:02d})\n"
            else:
                msg += "Trenutno nemaš aktivnih podsjetnika."
            
            bot.reply_to(message, msg)
            return

        if "status" in text.lower():
            bot.reply_to(message, "✅ Bot je aktivan i radi 24/7.")
            return

        # Parsiranje podsjetnika...
        result = parse_time(text)
        if result and result[0] is not None:
            # ... logika za spremanje podsjetnika
            bot.reply_to(message, "✅ Podsjetnik postavljen!")
            return

        # OpenAI - podrška za više jezika
        current_time = get_current_datetime()
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": f"""Ti si koristan pomoćnik za logističku firmu Bravel. 
Trenutni datum i vrijeme: {current_time.strftime('%d.%m.%Y %H:%M')}.
Odgovaraj na jeziku na kojem ti se korisnik obraća (hrvatski, engleski, njemački, talijanski...). 
Budi prijateljski i koristan."""},
                {"role": "user", "content": text}
            ],
            temperature=0.7
        )
        bot.reply_to(message, response.choices[0].message.content)

    except Exception as e:
        logger.error(f"Greška: {e}")
        bot.reply_to(message, "Došlo je do greške. Pokušaj ponovo.")

print("Bot je aktivan.")
bot.infinity_polling()
