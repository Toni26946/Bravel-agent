import os
from datetime import datetime, timedelta
import time
import threading
import re
import telebot
from telebot import types
import keep_alive
from zoneinfo import ZoneInfo
import logging
from openai import OpenAI

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

keep_alive

os.environ["OPENAI_API_KEY"] = os.getenv("OPENAI_API_KEY")
client = OpenAI()

TELEGRAM_TOKEN = "8968996549:AAE5YFAnUcnWd-esCwYyLzFKgAObJfFVuZU"
bot = telebot.TeleBot(TELEGRAM_TOKEN)

ALLOWED_USERS = [5191857104, 7599693099]

print("Bravel Agent - Stabilna verzija sa ponavljajućim podsjetnicima")

reminders = []      # jednokratni
recurring = []      # ponavljajući

def get_current_datetime():
    return datetime.now(ZoneInfo("Europe/Zagreb"))

def parse_time(text):
    text = text.lower().strip()
    now = get_current_datetime()
    
    # ==================== PONAVLJAJUĆI ====================
    if any(word in text for word in ["svaki dan", "svakodnevno", "every day", "daily"]):
        match = re.search(r'(?:u|at|oko)\s*(\d{1,2})[:.]?(\d{2})?', text)
        if match:
            hour = int(match.group(1))
            minute = int(match.group(2) or 0)
            return (hour, minute), "daily"
    
    days_map = {
        "ponedjeljak":0, "pon":0, "utorak":1, "uto":1, "srijeda":2, "sri":2,
        "četvrtak":3, "čet":3, "petak":4, "pet":4, "subota":5, "sub":5,
        "nedjelja":6, "ned":6
    }
    for day_name, num in days_map.items():
        if day_name in text:
            match = re.search(r'(?:u|at|oko)\s*(\d{1,2})[:.]?(\d{2})?', text)
            if match:
                hour = int(match.group(1))
                minute = int(match.group(2) or 0)
                return (num, hour, minute), "weekly"
    
    # ==================== JEDNOKRATNI ====================
    # 1. Konkretan datum i vrijeme (npr. 5.7. u 18:30)
    match = re.search(r'(\d{1,2})[\./](\d{1,2})(?:[\./](\d{2,4}))?\s*(?:u|at|oko)?\s*(\d{1,2})[:.]?(\d{2})?', text)
    if match:
        day = int(match.group(1))
        month = int(match.group(2))
        year = int(match.group(3)) if match.group(3) else now.year
        if year < 100: year += 2000
        hour = int(match.group(4))
        minute = int(match.group(5) or 0)
        
        try:
            target = datetime(year, month, day, hour, minute, tzinfo=ZoneInfo("Europe/Zagreb"))
            if target < now:
                target = target.replace(year=target.year + 1)
            return target, "once"
        except:
            pass

    # 2. Sutra / prekosutra
    if "sutra" in text:
        match = re.search(r'(?:u|at|oko)\s*(\d{1,2})[:.]?(\d{2})?', text)
        if match:
            hour = int(match.group(1))
            minute = int(match.group(2) or 0)
            target = (now + timedelta(days=1)).replace(hour=hour, minute=minute, second=0, microsecond=0)
            return target, "once"
    
    if "prekosutra" in text:
        match = re.search(r'(?:u|at|oko)\s*(\d{1,2})[:.]?(\d{2})?', text)
        if match:
            hour = int(match.group(1))
            minute = int(match.group(2) or 0)
            target = (now + timedelta(days=2)).replace(hour=hour, minute=minute, second=0, microsecond=0)
            return target, "once"

    # 3. Za X minuta / sati
    match = re.search(r'za (\d+)\s*(minut|min|h|sat)', text)
    if match:
        num = int(match.group(1))
        unit = match.group(2)
        if unit.startswith('h') or unit.startswith('sat'):
            return now + timedelta(hours=num), "once"
        else:
            return now + timedelta(minutes=num), "once"

    return None, None

def check_reminders():
    while True:
        now = get_current_datetime()
        
        # Jednokratni
        for r in reminders[:]:
            if r['time'] <= now:
                bot.send_message(r['chat_id'], f"🛎️ **PODSJETNIK**\n\n{r['text']}", parse_mode='Markdown')
                reminders.remove(r)
        
        # Ponavljajući
        for r in recurring:
            if r['type'] == "daily":
                if r['hour'] == now.hour and r['minute'] == now.minute:
                    bot.send_message(r['chat_id'], f"🔄 **PONAVLJAJUĆI PODSJETNIK**\n\n{r['text']}", parse_mode='Markdown')
            elif r['type'] == "weekly":
                if r['weekday'] == now.weekday() and r['hour'] == now.hour and r['minute'] == now.minute:
                    bot.send_message(r['chat_id'], f"🔄 **PONAVLJAJUĆI PODSJETNIK**\n\n{r['text']}", parse_mode='Markdown')
        
        time.sleep(5)

threading.Thread(target=check_reminders, daemon=True).start()

# Brisanje
@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    try:
        if call.data.startswith("delete_"):
            index = int(call.data.split("_")[1])
            all_rem = reminders + recurring
            if 0 <= index < len(all_rem):
                deleted = all_rem[index]
                if deleted in reminders:
                    reminders.remove(deleted)
                else:
                    recurring.remove(deleted)
                bot.answer_callback_query(call.id, "✅ Izbrisano!")
                bot.edit_message_text("✅ Podsjetnik je izbrisan.", call.message.chat.id, call.message.message_id)
    except:
        pass

@bot.message_handler(func=lambda message: True)
def handle_message(message):
    if message.chat.id not in ALLOWED_USERS:
        return
    
    text = message.text.strip()
    chat_id = message.chat.id

    try:
        if "podsjetnici" in text.lower() or "lista" in text.lower():
            if not reminders and not recurring:
                bot.reply_to(message, "Nemaš aktivnih podsjetnika.")
                return

            msg = "📋 **Tvoji aktivni podsjetnici:**\n\n"
            markup = types.InlineKeyboardMarkup(row_width=1)
            count = 0

            if reminders:
                msg += "**📌 Jednokratni podsjetnici:**\n"
                for r in reminders:
                    btn = types.InlineKeyboardButton("🗑 Izbriši", callback_data=f"delete_{count}")
                    markup.add(btn)
                    msg += f"{count+1}. {r['text']}\n"
                    count += 1

            if recurring:
                msg += "\n**🔄 Ponavljajući podsjetnici:**\n"
                for r in recurring:
                    btn = types.InlineKeyboardButton("🗑 Izbriši", callback_data=f"delete_{count}")
                    markup.add(btn)
                    if r['type'] == "daily":
                        msg += f"{count+1}. {r['text']} (🔄 svaki dan u {r['hour']:02d}:{r['minute']:02d})\n"
                    else:
                        days = ["Ponedjeljak","Utorak","Srijeda","Četvrtak","Petak","Subota","Nedjelja"]
                        msg += f"{count+1}. {r['text']} (🔄 svaki {days[r['weekday']]} u {r['hour']:02d}:{r['minute']:02d})\n"
                    count += 1

            bot.reply_to(message, msg, reply_markup=markup)
            return

        if "status" in text.lower():
            bot.reply_to(message, "✅ Bot je aktivan i radi 24/7.")
            return

        result = parse_time(text)
        if result and result[0] is not None:
            data, rtype = result
            if rtype in ["daily", "weekly"]:
                recurring.append({**data, 'text': text, 'chat_id': chat_id})
                bot.reply_to(message, f"✅ **Ponavljajući podsjetnik postavljen!**\n\n{text}")
            else:
                reminders.append({'text': text, 'time': data, 'chat_id': chat_id})
                bot.reply_to(message, f"✅ **Podsjetnik postavljen!**\n\n{text}")
            return

        # OpenAI
        current_time = get_current_datetime()
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "system", "content": "Odgovaraj na istom jeziku na kojem ti je korisnik postavio pitanje."},
                      {"role": "user", "content": text}],
            temperature=0.7
        )
        bot.reply_to(message, response.choices[0].message.content)

    except Exception as e:
        logger.error(f"Greška: {e}")
        bot.reply_to(message, "Došlo je do greške. Pokušaj ponovo.")

print("Bot je aktivan.")
bot.infinity_polling()
