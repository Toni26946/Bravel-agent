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

print("Bravel Agent - Podsjetnici sa čistim opisom")

reminders = []

def parse_time(text):
    text = text.lower()
    now = datetime.now(ZoneInfo("Europe/Zagreb"))
    
    # Sutra + vrijeme
    if "sutra" in text:
        match = re.search(r'sutra.*u? (\d{1,2})[:.]?(\d{2})?', text)
        if match:
            hour = int(match.group(1))
            minute = int(match.group(2)) if match.group(2) else 0
            target = now + timedelta(days=1)
            target = target.replace(hour=hour, minute=minute, second=0, microsecond=0)
            return target
        return now + timedelta(days=1)
    
    # Datum + vrijeme (5.7. u 14:30)
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
    
    # Samo vrijeme
    match = re.search(r'u? (\d{1,2})[:.]?(\d{2})?', text)
    if match:
        hour = int(match.group(1))
        minute = int(match.group(2)) if match.group(2) else 0
        target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if target <= now:
            target += timedelta(days=1)
        return target
    
    return None

def extract_description(text):
    """Izvlači čisti opis iz poruke (bez vremena)"""
    # Uklanja uobičajene fraze za vrijeme
    desc = re.sub(r'sutra u \d{1,2}[:.]?\d{2}?', '', text, flags=re.IGNORECASE)
    desc = re.sub(r'u \d{1,2}[:.]?\d{2}?', '', desc, flags=re.IGNORECASE)
    desc = re.sub(r'\d{1,2}\.\d{1,2}\.?\s*u?\s*\d{1,2}[:.]?\d{2}?', '', desc, flags=re.IGNORECASE)
    desc = desc.strip().strip(' ,.-')
    return desc if desc else text

def check_reminders():
    while True:
        now = datetime.now(ZoneInfo("Europe/Zagreb"))
        for r in reminders[:]:
            if r['time'] <= now:
                delay_minutes = int((now - r['time']).total_seconds() / 60)
                if delay_minutes > 3:
                    msg = f"🚨 **ZAKAŠNJELI PODSJETNIK** ({delay_minutes} min)\n\n{r['text']}"
                    bot.send_message(r['chat_id'], msg, parse_mode='Markdown')
                else:
                    msg = f"🛎️ **PODSJETNIK**\n\n{r['description']}\n⏰ **{r['time'].strftime('%H:%M')}**"
                    bot.send_message(r['chat_id'], msg, parse_mode='Markdown')
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
        # ... (ista logika kao prije)
        if not reminders:
            bot.reply_to(message, "Nemaš aktivnih podsjetnika.")
        else:
            msg = "📋 Tvoji aktivni podsjetnici:\n\n"
            now = datetime.now(ZoneInfo("Europe/Zagreb"))
            for i, r in enumerate(reminders, 1):
                delay = int((r['time'] - now).total_seconds() / 60)
                time_str = f"za {delay} min" if delay > 0 else "uskoro"
                msg += f"{i}. {r['description']} → {r['time'].strftime('%d.%m. %H:%M')} ({time_str})\n"
            bot.reply_to(message, msg)
            
    elif "status" in text.lower():
        bot.reply_to(message, "✅ Bot je aktivan i radi 24/7.")
        
    else:
        reminder_time = parse_time(text)
        
        if reminder_time:
            description = extract_description(text)
            reminders.append({
                'text': text,
                'description': description,
                'time': reminder_time,
                'chat_id': chat_id
            })
            bot.reply_to(message, f"✅ **Podsjetnik postavljen!**\n\n**Opis:** {description}\n**Vrijeme:** {reminder_time.strftime('%d.%m.%Y %H:%M')}")
        else:
            # OpenAI odgovor
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": f"Ti si pomoćnik za logističku firmu Bravel. Odgovori prijateljski na hrvatskom: {text}"}],
                temperature=0.7
            )
            bot.reply_to(message, response.choices[0].message.content)

print("Bot je aktivan sa čistim opisom podsjetnika.")
bot.infinity_polling()
