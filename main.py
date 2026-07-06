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

# ==================== PODSJETNICI ====================
def parse_time(text):
    text = text.lower().strip()
    now = get_now()

    # Ponavljajući
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

    # Jednokratni
    m = re.search(r'(\d{1,2})[\./](\d{1,2})(?:[\./](\d{2,4}))?\s*(?:u|at|oko)?\s*(\d{1,2})[:.]?(\d{2})?', text)
    if m:
        d, mo, y, h, mi = m.groups()
        year = int(y) if y else now.year
        if year < 100: year += 2000
        try:
            target = datetime(year, int(mo), int(d), int(h), int(mi or 0), tzinfo=ZoneInfo("Europe/Zagreb"))
            if target < now:
                target = target.replace(year=target.year + 1)
            return target, "once"
        except:
            pass

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

    m = re.search(r'za (\d+)\s*(min|sat|h)', text)
    if m:
        num = int(m.group(1))
        if "sat" in m.group(2) or "h" in m.group(2):
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
                text += f"🔄 {days[r['weekday']]} u {r['hour']:02d}:{r['minute']:02d} → {r['text']}\n"

    bot.reply_to(message, text, parse_mode='Markdown')

# ==================== OPENAI RAZGOVOR ====================
def get_openai_response(text):
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Ti si koristan, duhovit i direktan asistent."},
                {"role": "user", "content": text}
            ],
            temperature=0.7
        )
        return response.choices[0].message.content
    except:
        return "Žao mi je, trenutno imam problema sa odgovorom."

# ==================== HANDLERS ====================
@bot.message_handler(commands=['start', 'lista', 'list', 'podsjetnici', 'podsjetnik'])
def command_handler(message):
    if message.chat.id not in ALLOWED_USERS:
        return
    
    cmd = message.text.lower().strip()
    
    if cmd.startswith('/start'):
        bot.reply_to(message, "✅ Bot je aktivan!\n\nKoristi me za podsjetnike ili normalan razgovor.")
        return

    if cmd.startswith(('/lista', '/list', '/podsjetnici', '/podsjetnik')):
        show_reminders(message)
        return


@bot.message_handler(func=lambda m: True)
def handle(message):
    if message.chat.id not in ALLOWED_USERS:
        return

    text = message.text.strip().lower()

    # Provjera za podsjetnike
    reminder_keywords = ["podsjet", "podsjeti", "remind", "za ", "sutra", "prekosutra", "svaki dan", "svakodnevno"]
    if any(word in text for word in reminder_keywords):
        result, rtype = parse_time(message.text)
        if result:
            if rtype == "once":
                reminders.append({'text': message.text, 'time': result, 'chat_id': message.chat.id})
                bot.reply_to(message, f"✅ Podsjetnik postavljen za {result.strftime('%d.%m.%Y. %H:%M')}")
            else:
                if rtype == "daily":
                    hour, minute = result
                    recurring.append({'text': message.text, 'rtype': 'daily', 'hour': hour, 'minute': minute, 'chat_id': message.chat.id})
                else:
                    weekday, hour, minute = result
                    recurring.append({'text': message.text, 'rtype': 'weekly', 'weekday': weekday, 'hour': hour, 'minute': minute, 'chat_id': message.chat.id})
                bot.reply_to(message, "✅ Ponavljajući podsjetnik postavljen!")
            return

    # Normalan razgovor sa OpenAI
    response = get_openai_response(message.text)
    bot.reply_to(message, response)

# ==================== START ====================
print("🚀 Bot pokrenut - Podsjetnici + OpenAI")
bot.delete_webhook(drop_pending_updates=True)
threading.Thread(target=check_reminders, daemon=True).start()
bot.infinity_polling()
