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

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

keep_alive  # <--- ovo treba biti keep_alive() ako ima funkciju

os.environ["OPENAI_API_KEY"] = "sk-projp2UUzbVeQ95H-KSeAJAPD95Gr9wwUUOSLLIR6Pm98NxZUQ6Fs3UJFpVqPOERQeHo9Sx7shwT3BibkFlyyE_xikr$e wArm8aOq_7CKAPwHQvnqtdtMhHdM4m5PSnEq3vFPJnrclXTTwTormppOj_88BLcQA"

TELEGRAM_TOKEN = "8968996549:AAE5YFAnUcnWd-esCwYyLzFKgAObJfFVuZU"

FLY_TOKEN = "FlyV1 fm2_lJPECAAAAAAAFcOExBAO8atbztkL/8yVe9AaeOT6wrVodHRwczovL2FwaS5mbHkuaW8vdjGWAJLOABrDcB8Lk7lodHRwczovL2FwaS5mbHkuaW8vYWFhL3YxxDz6awbFM9Uq6QSd1T8C9TWMk/DmqmzRTxZk2VVXa3NEvwY3t6S18XJSzSTbfOsrC7qH4tk1WJNSW+UCsMLETjlRewRs/2apeuRG2+l5NdWMldgzPJ0FaQyLoL7dil7FHDF4jLsSSJwa13uytD+5BuEzFAFAbCtBI0FeR8IB9dkoqen/XgcxUH5bLExleA2SlAORgc4BOur5HwWRgqdidWlsZGVyH6J3Zx8BxCCQHq06lJdU3/o3GupGVorN6ew08GUHdrWmC6tot+hs8Q==,fm2_lJPETjlRewRs/2apeuRG2+l5NdWMldgzPJ0FaQyLoL7dil7FHDF4jLsSSJwa13uytD+5BuEzFAFAbCtBI0FeR8IB9dkoqen/XgcxUH5bLExleMQQo8nnjSx4yHfrU4uKG/gOssO5aHR0cHM6Ly9hcGkuZmx5LmlvL2FhYS92MZgEks5qRP+8zwAAAAEmPR3aF84AGZ+1CpHOABmftQzEEPSlj/z2Kqro/ukfZarVgojEIHa9Lq7ch7ZgXBP7h92oFTd5Vy13jhH7ggemTbATgqzy"

FLY_APP_NAME = "bravel-agent"

client = OpenAI()

bot = telebot.TeleBot(TELEGRAM_TOKEN)

print("Bravel Agent - Sa OpenAI")

reminders = []

def parse_time(text):
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
    
    match = re.search(r'(\d{1,2})\.(\d{1,2})\.', text)
    if match:
        day = int(match.group(1))
        month = int(match.group(2))
        target = now.replace(day=day, month=month, hour=9, minute=0, second=0)
        if target <= now:
            target = target.replace(year=target.year + 1 if target.month < now.month else target.year)
        return target
    
    if "sutra" in text:
        return now + timedelta(days=1)
    
    return now + timedelta(minutes=5)

def check_reminders():
    while True:
        now = datetime.now(ZoneInfo("Europe/Zagreb"))
        for r in reminders[:]:
            if r['time'] <= now:
                msg = f"🛎️ PODSJETNIK: {r['text']}"
                print(msg)
                try:
                    bot.send_message(r['chat_id'], msg)
                except:
                    pass
                reminders.remove(r)
        time.sleep(3)

def check_fly_status():
    while True:
        try:
            response = requests.get(
                f"https://api.fly.io/apps/{FLY_APP_NAME}/machines",
                headers={"Authorization": f"Bearer {FLY_TOKEN}"}
            )
            if response.status_code != 200:
                bot.send_message(5191857104, "⚠️ UPOZORENJE: Fly.io mašina je pala ili ima problem!")
        except Exception as e:
            bot.send_message(5191857104, f"⚠️ Greška pri provjeri Fly.io: {e}")
        time.sleep(300)

def get_openai_response(prompt):
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7
        )
        return response.choices[0].message.content
    except Exception as e:
        logger.error(f"OpenAI greška: {e}")
        return "Došlo je do greške sa OpenAI. Pokušaj ponovo kasnije."

threading.Thread(target=check_reminders, daemon=True).start()
threading.Thread(target=check_fly_status, daemon=True).start()

@bot.message_handler(func=lambda message: True)
def handle_message(message):
    if message.chat.id not in ALLOWED_USERS:
        bot.reply_to(message, "Žao mi je, ovaj bot je samo za ovlaštene korisnike.")
        return
    
    text = message.text
    chat_id = message.chat.id
    
    try:
        logger.info(f"Poruka od {chat_id}: {text}")
        
        if "podsjetnici" in text.lower() or "lista" in text.lower():
            if not reminders:
                bot.reply_to(message, "Nemaš aktivnih podsjetnika.")
            else:
                msg = "📋 Tvoji aktivni podsjetnici:\n"
                for i, r in enumerate(reminders, 1):
                    msg += f"{i}. {r['text']} (u {r['time'].strftime('%H:%M')})\n"
                bot.reply_to(message, msg)
        elif "podsjeti me" in text.lower():
            reminder_time = parse_time(text)
            reminders.append({
                'text': text,
                'time': reminder_time,
                'chat_id': chat_id
            })
            bot.reply_to(message, f"✅ Podsjetnik postavljen! Aktivira se u {reminder_time.strftime('%H:%M')}")
        elif "status" in text.lower():
            bot.reply_to(message, "✅ Bot je aktivan i radi 24/7.")
        else:
            response = get_openai_response(f"Ti si pomoćnik za logističku firmu Bravel. Odgovori korisniku na hrvatskom jeziku, prijateljski i korisno: {text}")
            bot.reply_to(message, response)
    except Exception as e:
        logger.error(f"Greška: {e}")
        bot.reply_to(message, "Došlo je do greške. Pokušaj ponovo.")

print("Bot je aktivan sa OpenAI.")
bot.infinity_polling()
