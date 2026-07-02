import os
from datetime import datetime, timedelta
import time
import threading
import re
import telebot
import keep_alive
from zoneinfo import ZoneInfo
import logging
import requests
from openai import OpenAI

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

keep_alive

os.environ["OPENAI_API_KEY"] = os.getenv("OPENAI_API_KEY")

TELEGRAM_TOKEN = "8968996549:AAE5YFAnUcnWd-esCwYyLzFKgAObJfFVuZU"
FLY_APP_NAME = "bravel-agent"

client = OpenAI()
bot = telebot.TeleBot(TELEGRAM_TOKEN)

ALLOWED_USERS = [5191857104, 7599693099]

print("Bravel Agent - Podsjetnici sa datumima")

reminders = []

def parse_time(text):
    """Poboljšani parser za datum + vrijeme"""
    text = text.lower()
    now = datetime.now(ZoneInfo("Europe/Zagreb"))
    
    # 1. Za X minuta
    match = re.search(r'za (\d+) (minut|min)', text)
    if match:
        return now + timedelta(minutes=int(match.group(1)))
    
    # 2. Kombinacija: datum + vrijeme (npr. 5.7. u 14:30, 15.8 u 9:00)
    match = re.search(r'(\d{1,2})\.(\d{1,2})\.?\s*(?:u)?\s*(\d{1,2})[:.]?(\d{2})?', text)
    if match:
        day = int(match.group(1))
        month = int(match.group(2))
        hour = int(match.group(3)) if match.group(3) else 9
        minute = int(match.group(4)) if match.group(4) else 0
        
        target = now.replace(day=day, month=month, hour=hour, minute=minute, second=0, microsecond=0)
        
        # Ako je datum već prošao, stavi sljedeću godinu
        if target <= now:
            target = target.replace(year=target.year + 1)
        return target
    
    # 3. Samo vrijeme (u 14:30, u 14)
    match = re.search(r'u? (\d{1,2})[:.]?(\d{2})?', text)
    if match:
        hour = int(match.group(1))
        minute = int(match.group(2)) if match.group(2) else 0
        target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if target <= now:
            target += timedelta(days=1)
        return target
    
    # 4. Samo datum (5.7., 15.8.)
    match = re.search(r'(\d{1,2})\.(\d{1,2})\.', text)
    if match:
        day = int(match.group(1))
        month = int(match.group(2))
        target = now.replace(day=day, month=month, hour=9, minute=0, second=0, microsecond=0)
        if target <= now:
            target = target.replace(year=target.year + 1)
        return target
    
    if "sutra" in text:
        return now + timedelta(days=1)
    
    return None

def check_reminders():
    while True:
        now = datetime.now(ZoneInfo("Europe/Zagreb"))
        
        for r in reminders[:]:
            if r['time'] <= now:
                delay_minutes = int((now - r['time']).total_seconds() / 60)
                
                if delay_minutes > 3:
                    msg = f"🚨 **ZAKAŠNJELI PODSJETNIK** ({delay_minutes} min)\n\n{r['text']}"
                    try:
                        bot.send_message(r['chat_id'], msg, parse_mode='Markdown')
                        time.sleep(2)
                        bot.send_message(r['chat_id'], "🚨 **PAŽNJA!** Ovo je zakašnjeli podsjetnik!", parse_mode='Markdown')
                    except:
                        pass
                else:
                    msg = f"🛎️ **PODSJETNIK**\n\n{r['text']}\n⏰ **{r['time'].strftime('%H:%M')}**"
                    try:
                        bot.send_message(r['chat_id'], msg, parse_mode='Markdown')
                    except:
                        pass
                
                reminders.remove(r)
        
        time.sleep(3)

threading.Thread(target=check_reminders, daemon=True).start()

@bot.message_handler(func=lambda message: True)
def handle_message(message):
    if message.chat.id not in ALLOWED_USERS:
        bot.reply_to(message, "Žao mi je, ovaj bot je samo za ovlaštene korisnike.")
        return
    
    text = message.text
    chat_id = message.chat.id
    
    try:
        if "podsjetnici" in text.lower() or "lista" in text.lower():
            if not reminders:
                bot.reply_to(message, "Nemaš aktivnih podsjetnika.")
            else:
                msg = "📋 Tvoji aktivni podsjetnici:\n\n"
                now = datetime.now(ZoneInfo("Europe/Zagreb"))
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
                bot.reply_to(message, f"✅ Podsjetnik postavljen!\nDatum: {reminder_time.strftime('%d.%m.%Y')}\nVrijeme: {reminder_time.strftime('%H:%M')}")
            else:
                # Ako parser ne uspije, koristi OpenAI
                response = client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[{"role": "user", "content": f"Ti si pomoćnik za logističku firmu Bravel. Odgovori prijateljski na hrvatskom: {text}"}],
                    temperature=0.7
                )
                bot.reply_to(message, response.choices[0].message.content)
                
    except Exception as e:
        logger.error(f"Greška: {e}")
        bot.reply_to(message, "Došlo je do greške. Pokušaj ponovo.")

print("Bot je aktivan sa podrškom za datume.")
bot.infinity_polling()
