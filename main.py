import os
from datetime import datetime, timedelta
import time
import threading
import re
import telebot
from keep_alive import keep_alive
from zoneinfo import ZoneInfo

keep_alive()

os.environ["OPENAI_API_KEY"] = "sk-tvoj-kljuc-ovdje"

TELEGRAM_TOKEN = "8968996549:AAE5YFAnUcnWd-esCwYyLzFKgAObJfFVuZU"

ALLOWED_USERS = [5191857104, 7599693099]

bot = telebot.TeleBot(TELEGRAM_TOKEN)

print("Bravel Agent - Točan prikaz vremena")

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
        time.sleep(5)

threading.Thread(target=check_reminders, daemon=True).start()

@bot.message_handler(func=lambda message: True)
def handle_message(message):
    if message.chat.id not in ALLOWED_USERS:
        bot.reply_to(message, "Žao mi je, ovaj bot je samo za ovlaštene korisnike.")
        return
    
    text = message.text.lower()
    chat_id = message.chat.id
    if "podsjetnici" in text or "lista" in text:
        if not reminders:
            bot.reply_to(message, "Nemaš aktivnih podsjetnika.")
        else:
            msg = "📋 Tvoji aktivni podsjetnici:\n"
            for i, r in enumerate(reminders, 1):
                msg += f"{i}. {r['text']} (u {r['time'].strftime('%H:%M')})\n"
            bot.reply_to(message, msg)
    elif "podsjeti me" in text:
        reminder_time = parse_time(text)
        reminders.append({
            'text': message.text,
            'time': reminder_time,
            'chat_id': chat_id
        })
        bot.reply_to(message, f"✅ Podsjetnik postavljen! Aktivira se u {reminder_time.strftime('%H:%M')}")
    else:
        bot.reply_to(message, "✅ Razumio sam.")

print("Bot je aktivan.")
bot.infinity_polling()
    if "status" in text or "kakav je status" in text:
        bot.reply_to(message, "✅ Bot je aktivan i radi 24/7.")
        if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:bot", host="0.0.0.0", port=8080)
