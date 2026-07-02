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

print("Bravel Agent - Popravljen datum + zelena kvačica")

reminders = []

def get_current_datetime():
    return datetime.now(ZoneInfo("Europe/Zagreb"))

def parse_time(text):
    text = text.lower()
    now = get_current_datetime()
    
    match = re.search(r'za (\d+) (minut|min)', text)
    if match:
        return now + timedelta(minutes=int(match.group(1)))
    
    if "sutra" in text:
        match = re.search(r'sutra.*u? (\d{1,2})[:.]?(\d{2})?', text)
        if match:
            hour = int(match.group(1))
            minute = int(match.group(2)) if match.group(2) else 0
            target = now + timedelta(days=1)
            target = target.replace(hour=hour, minute=minute, second=0, microsecond=0)
            return target
        return now + timedelta(days=1)
    
    match = re.search(r'(\d{1,2})\.(\d{1,2})\.?\s*(?:u)?\s*(\d{1,2})[:.]?(\d{2})?', text)
    if match:
        day = int(match.group(1))
        month = int(match.group(2))
        hour = int(match.group(3)) if match.group(3) else 9
        minute = int(match.group(4)) if match.group(4) else 0
        target = now.replace(day=day, month=month, hour=hour, minute=minute, second=0, microsecond=0)
        if target <= now:
            target = target.replace(year=target.year + 1)
        return target
    
    match = re.search(r'u? (\d{1,2})[:.]?(\d{2})?', text)
    if match:
        hour = int(match.group(1))
        minute = int(match.group(2)) if match.group(2) else 0
        target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if target <= now:
            target += timedelta(days=1)
        return target
    
    return None

def check_reminders():
    while True:
        now = get_current_datetime()
        for r in reminders[:]:
            if r['time'] <= now:
                delay_minutes = int((now - r['time']).total_seconds() / 60)
                if delay_minutes > 3:
                    bot.send_message(r['chat_id'], f"🚨 **ZAKAŠNJELI PODSJETNIK** ({delay_minutes} min)\n\n{r['text']}", parse_mode='Markdown')
                else:
                    bot.send_message(r['chat_id'], f"🛎️ **PODSJETNIK**\n\n{r['text']}\n⏰ **{r['time'].strftime('%H:%M')}**", parse_mode='Markdown')
                reminders.remove(r)
        time.sleep(3)

threading.Thread(target=check_reminders, daemon=True).start()

@bot.message_handler(func=lambda message: True)
def handle_message(message):
    if message.chat.id not in ALLOWED_USERS:
        return
    
    text = message.text
    chat_id = message.chat.id
    
    if "podsjetnici" in text.lower() or "lista" in text.lower():
        if not reminders:
            bot.reply_to(message, "Nemaš aktivnih podsjetnika.")
        else:
            msg = "📋 Tvoji aktivni podsjetnici:\n\n"
            now = get_current_datetime()
            for i, r in enumerate(reminders, 1):
                delay = int((r['time'] - now).total_seconds() / 60)
                time_str = f"za {delay} min" if delay > 0 else "uskoro"
                msg += f"{i}. {r['text']} → {r['time'].strftime('%d.%m. %H:%M')} ({time_str})\n"
            bot.reply_to(message, msg)
            
    elif "status" in text.lower():
        bot.reply_to(message, "✅ Bot je aktivan i radi 24/7.")
        
    else:
        reminder_time = parse_time(text)
        
        if reminder_time:
            reminders.append({
                'text': text,
                'time': reminder_time,
                'chat_id': chat_id
            })
            bot.reply_to(message, f"""✅ **Podsjetnik postavljen!**

Opis: {text}
Datum: {reminder_time.strftime('%d.%m.%Y')}
Vrijeme: {reminder_time.strftime('%H:%M')}""")
        else:
            # Popravljeni OpenAI dio sa točnim datumom
            current_time = get_current_datetime()
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": f"Ti si pomoćnik za logističku firmu Bravel. Trenutni datum i vrijeme je: {current_time.strftime('%d.%m.%Y %H:%M')} (Europe/Zagreb). Odgovori prijateljski i točno na hrvatskom jeziku."},
                    {"role": "user", "content": text}
                ],
                temperature=0.7
            )
            bot.reply_to(message, response.choices[0].message.content)

print("Bot je aktivan sa popravljenim datumom.")
bot.infinity_polling()
