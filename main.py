import os
from datetime import datetime, timedelta
import time
import threading
import re
import telebot
import keep_alive
from zoneinfo import ZoneInfo
from openai import OpenAI

keep_alive.keep_alive()

# ==================== CONFIG ====================
TELEGRAM_TOKEN = "8968996549:AAE5YFAnUcnWd-esCwYyLzFKgAObJfFVuZU"
bot = telebot.TeleBot(TELEGRAM_TOKEN)

ALLOWED_USERS = [5191857104, 7599693099]

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

reminders = []      # jednokratni
recurring = []      # ponavljajući

def get_now():
    return datetime.now(ZoneInfo("Europe/Zagreb"))

# ==================== OPENAI PARSING ====================
def parse_with_openai(text):
    prompt = f"""
    Ti si asistent za postavljanje podsjetnika.
    Trenutno vrijeme: {get_now().strftime('%d.%m.%Y. %H:%M')}
    
    Korisnik je rekao: "{text}"
    
    Vrati samo JSON sa:
    - "type": "once" ili "daily" ili "weekly"
    - "time": ISO format datuma/vremena (ako je once) ili null
    - "hour": broj (za daily/weekly)
    - "minute": broj
    - "weekday": broj 0-6 (za weekly, None ako nije)
    - "text": originalni tekst podsjetnika
    
    Ako ne razumiješ, vrati null.
    """

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3
        )
        import json
        result = json.loads(response.choices[0].message.content.strip())
        return result
    except:
        return None

# ==================== CHECK REMINDERS (isto kao prije) ====================
def check_reminders():
    global reminders, recurring
    while True:
        now = get_now()
        print(f"[{now.strftime('%H:%M:%S')}] Provjera...")

        for r in reminders[:]:
            if r['time'] <= now:
                bot.send_message(r['chat_id'], f"🔔 **PODSJETNIK**\n\n{r['text']}")
                reminders.remove(r)

        for r in recurring:
            if r['rtype'] == "daily" and r['hour'] == now.hour and r['minute'] == now.minute:
                bot.send_message(r['chat_id'], f"🔄 **DNEVNI PODSJETNIK**\n\n{r['text']}")
            elif r['rtype'] == "weekly" and r.get('weekday') == now.weekday() and r['hour'] == now.hour and r['minute'] == now.minute:
                bot.send_message(r['chat_id'], f"🔄 **TJEDNI PODSJETNIK**\n\n{r['text']}")

        time.sleep(10)

# ==================== HANDLER ====================
@bot.message_handler(func=lambda m: True)
def handle(message):
    if message.chat.id not in ALLOWED_USERS:
        return

    text = message.text.strip()
    
    # Prvo probaj OpenAI
    ai_result = parse_with_openai(text)
    
    if ai_result and ai_result != "null":
        try:
            if ai_result['type'] == "once":
                remind_time = datetime.fromisoformat(ai_result['time'].replace('Z', '+00:00'))
                reminders.append({'text': ai_result['text'], 'time': remind_time, 'chat_id': message.chat.id})
                bot.reply_to(message, f"✅ Podsjetnik postavljen za {remind_time.strftime('%d.%m.%Y. %H:%M')}")
            else:
                # daily ili weekly
                rtype = ai_result['type']
                if rtype == "daily":
                    recurring.append({
                        'text': ai_result['text'], 
                        'rtype': 'daily', 
                        'hour': ai_result['hour'], 
                        'minute': ai_result['minute'], 
                        'chat_id': message.chat.id
                    })
                else:
                    recurring.append({
                        'text': ai_result['text'], 
                        'rtype': 'weekly', 
                        'weekday': ai_result['weekday'], 
                        'hour': ai_result['hour'], 
                        'minute': ai_result['minute'], 
                        'chat_id': message.chat.id
                    })
                bot.reply_to(message, f"✅ Ponavljajući podsjetnik postavljen!")
            return
        except:
            pass

    # Ako OpenAI ne uspije, fallback na stari parser
    bot.reply_to(message, "❌ Nisam uspio razumjeti. Pokušaj ponovo ili koristi jednostavan format.")

print("🚀 Bot pokrenut sa OpenAI-om")
bot.delete_webhook(drop_pending_updates=True)
threading.Thread(target=check_reminders, daemon=True).start()
bot.infinity_polling()
