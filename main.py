import os
from datetime import datetime, timedelta
import time
import threading
import re
import telebot
import keep_alive
from zoneinfo import ZoneInfo

keep_alive.keep_alive()

TELEGRAM_TOKEN = "8968996549:AAE5YFAnUcnWd-esCwYyLzFKgAObJfFVuZU"
bot = telebot.TeleBot(TELEGRAM_TOKEN)

ALLOWED_USERS = [5191857104, 7599693099]

# In-memory storage (gubi se kad bot padne)
reminders = []      # jednokratni
recurring = []      # ponavljajući

def get_now():
    return datetime.now(ZoneInfo("Europe/Zagreb"))

# ==================== PARSE TIME ====================
def parse_time(text):
    text = text.lower().strip()
    now = get_now()

    # PONAVLJAJUĆI
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

    # JEDNOKRATNI
    # Datum + vrijeme: 5.7. u 18:30
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

    # Sutra i prekosutra
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

    # Za X minuta / sati
    m = re.search(r'za (\d+)\s*(min|sat|h)', text)
    if m:
        num = int(m.group(1))
        unit = m.group(2)
        if "sat" in unit or "h" in unit:
            return now + timedelta(hours=num), "once"
        return now + timedelta(minutes=num), "once"

    return None, None

# ==================== CHECK REMINDERS ====================
def check_reminders():
    global reminders, recurring
    while True:
        now = get_now()
        print(f"[{now.strftime('%H:%M:%S')}] Provjera... Jednokratnih: {len(reminders)} | Ponavljajućih: {len(recurring)}")

        # Jednokratni
        for r in reminders[:]:
            if r['time'] <= now:
                try:
                    bot.send_message(r['chat_id'], f"🔔 **PODSJETNIK**\n\n{r['text']}", parse_mode='Markdown')
                    reminders.remove(r)
                except:
                    pass

        # Ponavljajući
        for r in recurring:
            if r['rtype'] == "daily" and r['hour'] == now.hour and r['minute'] == now.minute:
                bot.send_message(r['chat_id'], f"🔄 **DNEVNI PODSJETNIK**\n\n{r['text']}", parse_mode='Markdown')
            elif r['rtype'] == "weekly" and r.get('weekday') == now.weekday() and r['hour'] == now.hour and r['minute'] == now.minute:
                bot.send_message(r['chat_id'], f"🔄 **TJEDNI PODSJETNIK**\n\n{r['text']}", parse_mode='Markdown')

        time.sleep(10)

# ==================== BOT ====================
@bot.message_handler(commands=['start'])
def start(message):
    if message.chat.id not in ALLOWED_USERS:
        return
    bot.reply_to(message, "✅ Bot pokrenut (bez SQLite).\n\nTestiraj:\n- svaki dan u 8:00 popij vodu\n- 6.7. u 18:30 trening\n- sutra u 9:00")

@bot.message_handler(func=lambda m: True)
def handle(message):
    if message.chat.id not in ALLOWED_USERS:
        return

    result, rtype = parse_time(message.text)
    
    if result:
        if rtype == "once":
            reminders.append({'text': message.text, 'time': result, 'chat_id': message.chat.id})
            bot.reply_to(message, f"✅ Jednokratni spremljen za {result.strftime('%d.%m.%Y. %H:%M')}")
        else:
            if rtype == "daily":
                hour, minute = result
                recurring.append({'text': message.text, 'rtype': 'daily', 'hour': hour, 'minute': minute, 'chat_id': message.chat.id})
            else:  # weekly
                weekday, hour, minute = result
                recurring.append({'text': message.text, 'rtype': 'weekly', 'weekday': weekday, 'hour': hour, 'minute': minute, 'chat_id': message.chat.id})
            
            bot.reply_to(message, f"✅ Ponavljajući spremljen!")
    else:
        bot.reply_to(message, "❌ Nisam uspio razumjeti vrijeme. Pokušaj drugačije.")

print("🚀 Bot pokrenut (in-memory verzija)")
threading.Thread(target=check_reminders, daemon=True).start()
bot.infinity_polling()
