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

TELEGRAM_TOKEN = "8968996549:AAE5YFAnUcnWd-esCwYyLzFKgAObJfFVuZU"

client = OpenAI()
bot = telebot.TeleBot(TELEGRAM_TOKEN)

ALLOWED_USERS = [5191857104, 7599693099]

print("Bravel Agent - Ponavljajući podsjetnici + Popravljeni OpenAI")

reminders = []      # jednokratni
recurring = []      # ponavljajući (svaki dan)

def get_current_datetime():
    return datetime.now(ZoneInfo("Europe/Zagreb"))

def parse_time(text):
    text = text.lower()
    now = get_current_datetime()
    
    # Ponavljajući - svaki dan
    if "svaki dan" in text or "svakodnevno" in text:
        match = re.search(r'(?:u|at) (\d{1,2})[:.]?(\d{2})?', text)
        if match:
            hour = int(match.group(1))
            minute = int(match.group(2)) if match.group(2) else 0
            return (hour, minute), "daily"
    
    # Jednokratni podsjetnici
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
        return now + timedelta(days=1), "once"
    
    # Datum + vrijeme
    match = re.search(r'(\d{1,2})\.(\d{1,2})\.?\s*(?:u)?\s*(\d{1,2})[:.]?(\d{2})?', text)
    if match:
        day = int(match.group(1))
        month = int(match.group(2))
        hour = int(match.group(3)) if match.group(3) else 9
        minute = int(match.group(4)) if match.group(4) else 0
        target = now.replace(day=day, month=month, hour=hour, minute=minute, second=0, microsecond=0)
        if target <= now:
            target = target.replace(year=target.year + 1)
        return target, "once"
    
    # Samo vrijeme
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
        
        # Jednokratni
        for r in reminders[:]:
            if r['time'] <= now:
                bot.send_message(r['chat_id'], f"🛎️ **PODSJETNIK**\n\n{r['text']}", parse_mode='Markdown')
                reminders.remove(r)
        
        # Ponavljajući
        for r in recurring:
            if r['hour'] == now.hour and r['minute'] == now.minute:
                bot.send_message(r['chat_id'], f"🔄 **PONAVLJAJUĆI PODSJETNIK**\n\n{r['text']}", parse_mode='Markdown')
        
        time.sleep(5)

threading.Thread(target=check_reminders, daemon=True).start()

@bot.message_handler(func=lambda message: True)
def handle_message(message):
    if message.chat.id not in ALLOWED_USERS:
        return
    
    text = message.text
    chat_id = message.chat.id
    
    try:
        if "podsjetnici" in text.lower() or "lista" in text.lower():
            response_text = "📋 **Tvoji podsjetnici:**\n\n"
            if reminders or recurring:
                # Jednokratni
                if reminders:
                    response_text += "**Jednokratni:**\n"
                    for r in reminders:
                        response_text += f"• {r['text']}\n"
                # Ponavljajući
                if recurring:
                    response_text += "\n**Ponavljajući (svaki dan):**\n"
                    for r in recurring:
                        response_text += f"• {r['text']} (u {r['hour']:02d}:{r['minute']:02d})\n"
            else:
                response_text += "Nemaš aktivnih podsjetnika."
            bot.reply_to(message, response_text)
            
        elif "status" in text.lower():
            bot.reply_to(message, "✅ Bot je aktivan i radi 24/7.")
            
        else:
            # Pokušaj parsirati podsjetnik
            result = parse_time(text)
            if result and result[0] is not None:
                data, rtype = result
                
                if rtype == "daily":
                    hour, minute = data
                    recurring.append({
                        'text': text,
                        'hour': hour,
                        'minute': minute,
                        'chat_id': chat_id
                    })
                    bot.reply_to(message, f"""✅ **Ponavljajući podsjetnik postavljen!**

Opis: {text}
Ponavljanje: Svaki dan u {hour:02d}:{minute:02d}""")
                else:
                    reminders.append({
                        'text': text,
                        'time': data,
                        'chat_id': chat_id
                    })
                    bot.reply_to(message, f"""✅ **Podsjetnik postavljen!**

Opis: {text}
Vrijeme: {data.strftime('%d.%m.%Y %H:%M')}""")
            else:
                # Ako nije podsjetnik → OpenAI
                current_time = get_current_datetime()
                response = client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[
                        {"role": "system", "content": f"Ti si koristan pomoćnik za logističku firmu Bravel. Trenutni datum i vrijeme je: {current_time.strftime('%d.%m.%Y %H:%M')}. Odgovori prijateljski i točno na hrvatskom jeziku."},
                        {"role": "user", "content": text}
                    ],
                    temperature=0.7
                )
                bot.reply_to(message, response.choices[0].message.content)
                
    except Exception as e:
        logger.error(f"Greška: {e}")
        bot.reply_to(message, "Došlo je do greške. Pokušaj ponovo.")

print("Bot je aktivan sa ponavljajućim podsjetnicima + OpenAI.")
bot.infinity_polling()
