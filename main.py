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

TELEGRAM_TOKEN = "8968996549:AAE5YFAnUcnWd-esCwYyLzFKgAObJfFVuZU"
bot = telebot.TeleBot(TELEGRAM_TOKEN)

ALLOWED_USERS = [5191857104, 7599693099]

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

reminders = []
recurring = []

def get_now():
    return datetime.now(ZoneInfo("Europe/Zagreb"))

# ==================== PODSJETNICI ====================
def parse_time(text):
    text = text.lower().strip()
    now = get_now()

    # === POBOLJŠANO PREPOZNAVANJE DATUMA ===
    
    # 1. Format: 7.7. u 10:30 ili 07.07. u 10:30
    m = re.search(r'(\d{1,2})[\./](\d{1,2})(?:[\./](\d{2,4}))?\s*(?:u|at|oko|za)?\s*(\d{1,2})[:.]?(\d{2})?', text)
    if m:
        day = int(m.group(1))
        month = int(m.group(2))
        year = int(m.group(3)) if m.group(3) else now.year
        if year < 100: year += 2000
        hour = int(m.group(4))
        minute = int(m.group(5) or 0)
        
        try:
            target = datetime(year, month, day, hour, minute, tzinfo=ZoneInfo("Europe/Zagreb"))
            if target < now:
                target = target.replace(year=target.year + 1)
            return target, "once"
        except:
            pass

    # 2. Ponavljajući (svaki dan, petak itd.)
    if any(x in text for x in ["svaki dan", "svakodnevno", "daily"]):
        m = re.search(r'(?:u|at|oko)\s*(\d{1,2})[:.]?(\d{2})?', text)
        if m:
            return (int(m.group(1)), int(m.group(2) or 0)), "daily"

    days = {"ponedjeljak":0,"pon":0,"utorak":1,"uto":1,"srijeda":2,"sri":2,"četvrtak":3,"čet":3,
            "petak":4,"pet":4,"subota":5,"sub":5,"nedjelja":6,"ned":6}
    for name, wd in days.items():
        if name in text:
            m = re.search(r'(?:u|at|oko)\s*(\d{1,2})[:.]?(\d{2})?', text)
            if m:
                return (wd, int(m.group(1)), int(m.group(2) or 0)), "weekly"

    # 3. Relativni (sutra, prekosutra)
    if "sutra" in text:
        m = re.search(r'(?:u|at|oko)\s*(\d{1,2})[:.]?(\d{2})?', text)
        if m:
            h = int(m.group(1))
            mi = int(m.group(2) or 0)
            return (now + timedelta(days=1)).replace(hour=h, minute=mi, second=0, microsecond=0), "once"

    if "prekosutra" in text:
        m = re.search(r'(?:u|at|oko)\s*(\d{1,2})[:.]?(\d{2})?', text)
        if m:
            h = int(m.group(1))
            mi = int(m.group(2) or 0)
            return (now + timedelta(days=2)).replace(hour=h, minute=mi, second=0, microsecond=0), "once"

    # 4. Za X minuta/sati
    m = re.search(r'za (\d+)\s*(minut|min|sat|h)', text)
    if m:
        num = int(m.group(1))
        unit = m.group(2)
        if "sat" in unit or "h" in unit:
            return now + timedelta(hours=num), "once"
        return now + timedelta(minutes=num), "once"

    return None, None

def check_reminders():
    global reminders, recurring
    while True:
        now = get_now()
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

def show_reminders(message):
    print(f"DEBUG: show_reminders pozvan. Jednokratnih: {len(reminders)}, Ponavljajućih: {len(recurring)}")  # debug
    
    if not reminders and not recurring:
        bot.reply_to(message, "Trenutno nemaš aktivnih podsjetnika.")
        return

    text = "📋 **Tvoji podsjetnici:**\n\n"

    if reminders:
        text += "**Jednokratni:**\n"
        for i, r in enumerate(reminders, 1):
            text += f"{i}. {r['time'].strftime('%d.%m.%Y. %H:%M')} → {r['text']}\n"
        text += "\n"

    if recurring:
        text += "**Ponavljajući:**\n"
        for r in recurring:
            if r['rtype'] == "daily":
                text += f"🔄 Svaki dan u {r['hour']:02d}:{r['minute']:02d} → {r['text']}\n"
            else:
                days = ["Pon", "Uto", "Sri", "Čet", "Pet", "Sub", "Ned"]
                text += f"🔄 {days[r.get('weekday', 0)]} u {r['hour']:02d}:{r['minute']:02d} → {r['text']}\n"

    bot.reply_to(message, text, parse_mode='Markdown')

# ==================== HANDLERS ====================
# ==================== HANDLERS ====================
@bot.message_handler(commands=['start', 'lista', 'list', 'podsjetnici', 'podsjetnik'])
def command_handler(message):
    if message.chat.id not in ALLOWED_USERS:
        return
    
    cmd = message.text.lower().strip()
    
    if cmd.startswith('/start'):
        bot.reply_to(message, "✅ Bot je aktivan!")
        return

    # Ako je komanda sa kosicom
    if cmd.startswith(('/lista', '/list', '/podsjetnici', '/podsjetnik')):
        show_reminders(message)
        return


@bot.message_handler(func=lambda m: True)
def handle(message):
    if message.chat.id not in ALLOWED_USERS:
        return

    text = message.text.strip()
    lower = text.lower()

    # 1. Prvo provjeri listu podsjetnika
    list_keywords = ["lista", "list", "podsjetnici", "podsjetnik", "moji podsjetnici", "pokaži podsjetnike", "što imam", "pregled"]
    if any(k in lower for k in list_keywords):
        show_reminders(message)
        return

    # 2. Pokušaj prepoznati kao podsjetnik (glavna provjera)
    result, rtype = parse_time(text)
    if result is not None:
        if rtype == "once":
            reminders.append({'text': text, 'time': result, 'chat_id': message.chat.id})
            bot.reply_to(message, f"✅ Podsjetnik postavljen za {result.strftime('%d.%m.%Y. %H:%M')}")
        else:
            if rtype == "daily":
                hour, minute = result
                recurring.append({'text': text, 'rtype': 'daily', 'hour': hour, 'minute': minute, 'chat_id': message.chat.id})
            else:
                weekday, hour, minute = result
                recurring.append({'text': text, 'rtype': 'weekly', 'weekday': weekday, 'hour': hour, 'minute': minute, 'chat_id': message.chat.id})
            bot.reply_to(message, "✅ Ponavljajući podsjetnik postavljen!")
        return

    # 3. Ako nije podsjetnik → razgovor sa OpenAI
    response = get_openai_response(text)
    bot.reply_to(message, response)
    
def get_openai_response(text):
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "system", "content": "Ti si koristan asistent."}, {"role": "user", "content": text}],
            temperature=0.7
        )
        return response.choices[0].message.content
    except:
        return "Žao mi je, imao sam problem sa odgovorom."

# ==================== START ====================
print("🚀 Bot pokrenut")
bot.delete_webhook(drop_pending_updates=True)
threading.Thread(target=check_reminders, daemon=True).start()
bot.infinity_polling()
