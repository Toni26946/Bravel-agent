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

print("Bravel Agent - Pametni podsjetnici")

reminders = []

def parse_time(text):
    # Stara funkcija za jednostavne slučajeve
    text = text.lower()
    now = datetime.now(ZoneInfo("Europe/Zagreb"))
    
    match = re.search(r'za (\d+) (minut|min)', text)
    if match:
        return now + timedelta(minutes=int(match.group(1)))
    
    match = re.search(r'u? (\d{1,2}):(\d{2})', text)
    if match:
        hour = int(match.group(1))
        minute = int(match.group(2))
        target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if target <= now:
            target += timedelta(days=1)
        return target
    
    if "sutra" in text:
        return now + timedelta(days=1)
    
    return None

def get_openai_reminder(text):
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Ti si asistent koji iz poruke izvlači vrijeme za podsjetnik. Vrati samo vrijeme u formatu YYYY-MM-DD HH:MM i tekst podsjetnika. Ako ne možeš odrediti vrijeme, vrati 'NONE'."},
                {"role": "user", "content": f"Poruka: {text}"}
            ],
            temperature=0.3
        )
        return response.choices[0].message.content.strip()
    except:
        return "NONE"

def check_reminders():
    while True:
        now = datetime.now(ZoneInfo("Europe/Zagreb"))
        for r in reminders[:]:
            if r['time'] <= now:
                delay = int((now - r['time']).total_seconds() / 60)
                if delay > 5:
                    msg = f"⚠️ **ZAKAŠNJELI PODSJETNIK** ({delay} min): {r['text']}"
                else:
                    msg = f"🛎️ PODSJETNIK: {r['text']}"
                try:
                    bot.send_message(r['chat_id'], msg)
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
                    if delay > 0:
                        time_str = f"za {delay} min"
                    else:
                        time_str = "uskoro"
                    msg += f"{i}. {r['text']} → {r['time'].strftime('%H:%M')} ({time_str})\n"
                bot.reply_to(message, msg)
                
        elif any(word in text.lower() for word in ["podsjeti", "sastanak", "meeting", "ručak", "nazovem", "provjerim", "idi", "u 1", "u 2", "u 3", "u 4", "u 5", "u 6", "u 7", "u 8", "u 9", "u 10", "u 11", "u 12", "u 13", "u 14", "u 15", "u 16", "u 17", "u 18", "u 19", "u 20", "u 21", "u 22", "u 23"]):
            # Pametni način - koristi OpenAI
            openai_result = get_openai_reminder(text)
            if "NONE" not in openai_result.upper():
                # Za sada koristimo staru parse funkciju, ali ćemo kasnije poboljšati
                reminder_time = parse_time(text)
                if reminder_time:
                    reminders.append({
                        'text': text,
                        'time': reminder_time,
                        'chat_id': chat_id
                    })
                    bot.reply_to(message, f"✅ Pametni podsjetnik postavljen! Aktivira se u {reminder_time.strftime('%H:%M')}")
                else:
                    bot.reply_to(message, "✅ Razumio sam da želiš podsjetnik, ali nisam siguran kada. Možeš li reći npr. 'u 14:30' ili 'za 30 minuta'?")
            else:
                bot.reply_to(message, "✅ Razumio sam, ali nisam siguran kada želiš podsjetnik. Možeš li biti malo precizniji?")
        elif "status" in text.lower():
            bot.reply_to(message, "✅ Bot je aktivan i radi 24/7.")
        else:
            response = get_openai_response(f"Ti si pomoćnik za logističku firmu Bravel. Odgovori na hrvatskom, prijateljski: {text}")
            bot.reply_to(message, response)
    except Exception as e:
        bot.reply_to(message, "Došlo je do greške. Pokušaj ponovo.")

def get_openai_response(prompt):
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7
        )
        return response.choices[0].message.content
    except:
        return "Došlo je do greške sa OpenAI."

print("Bot je aktivan sa pametnim podsjetnicima.")
bot.infinity_polling()
