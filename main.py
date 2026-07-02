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

print("Bravel Agent - Jednostavni ponavljajući podsjetnici")

reminders = []           # jednokratni
recurring = []           # ponavljajući (svaki dan)

def get_current_datetime():
    return datetime.now(ZoneInfo("Europe/Zagreb"))

def parse_time(text):
    text = text.lower()
    now = get_current_datetime()
    
    # 1. Ponavljajući - svaki dan u HH:MM
    if "svaki dan" in text or "svakodnevno" in text:
        match = re.search(r'(?:u|at) (\d{1,2})[:.]?(\d{2})?', text)
        if match:
            hour = int(match.group(1))
            minute = int(match.group(2)) if match.group(2) else 0
            return (hour, minute), "daily"
    
    # 2. Jednokratni (stara logika)
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
    
    # ostale jednokratne...
    match = re.search(r'u? (\d{1,2})[:.]?(\d{2})?', text)
    if match:
        hour = int(match.group(1))
        minute = int(match.group(2)) if match.group(2) else 0
        target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if target <= now:
            target += timedelta(days=1)
        return target, "once"
    
    return None, "once"

def check_reminders():
    while True:
        now = get_current_datetime()
        
        # Jednokratni podsjetnici
        for r in reminders[:]:
            if r['time'] <= now:
                bot.send_message(r['chat_id'], f"🛎️ **PODSJETNIK**\n\n{r['text']}", parse_mode='Markdown')
                reminders.remove(r)
        
        # Ponavljajući podsjetnici (svaki dan)
        for r in recurring[:]:
            if r['hour'] == now.hour and r['minute'] == now.minute:
                bot.send_message(r['chat_id'], f"🔄 **PONAVLJAJUĆI PODSJETNIK**\n\n{r['text']}", parse_mode='Markdown')
        
        time.sleep(5)  # provjera svakih 5 sekundi

threading.Thread(target=check_reminders, daemon=True).start()

@bot.message_handler(func=lambda message: True)
def handle_message(message):
    if message.chat.id not in ALLOWED_USERS:
        return
    
    text = message.text
    chat_id = message.chat.id
    
    if "podsjetnici" in text.lower() or "lista" in text.lower():
        bot.reply_to(message, "Lista podsjetnika još nije ažurirana za ponavljajuće. U razvoju.")
        
    elif "status" in text.lower():
        bot.reply_to(message, "✅ Bot je aktivan i radi 24/7.")
        
    else:
        result = parse_time(text)
        if isinstance(result, tuple) and len(result) == 2:
            reminder_data, reminder_type = result
            
            if reminder_type == "daily":
                hour, minute = reminder_data
                recurring.append({
                    'text': text,
                    'hour': hour,
                    'minute': minute,
                    'chat_id': chat_id
                })
                bot.reply_to(message, f"""✅ **Ponavljajući podsjetnik postavljen!**

Opis: {text}
Ponavljanje: **svaki dan u {hour:02d}:{minute:02d}**""")
            else:
                # jednokratni
                reminders.append({
                    'text': text,
                    'time': reminder_data,
                    'chat_id': chat_id
                })
                bot.reply_to(message, f"""✅ **Podsjetnik postavljen!**

Opis: {text}
Vrijeme: {reminder_data.strftime('%d.%m.%Y %H:%M')}""")
        else:
            # OpenAI
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": f"Ti si pomoćnik za logističku firmu Bravel. Odgovori prijateljski na hrvatskom: {text}"}],
                temperature=0.7
            )
            bot.reply_to(message, response.choices[0].message.content)

print("Bot je aktivan sa jednostavnim ponavljajućim podsjetnicima.")
bot.infinity_polling()
