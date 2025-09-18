import json
import logging
import datetime
import asyncio
import aiohttp   # для запросов к DictionaryAPI
from googletrans import Translator
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackContext, MessageHandler,
    filters, CallbackQueryHandler, ConversationHandler
)

# =============== НАСТРОЙКИ ===============
import os

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))
USERS_FILE = "users.json"
WORDS_FILE = "words.json"

translator = Translator()
logging.basicConfig(level=logging.INFO)

# ================= JSON =================
def load_users():
    try:
        with open(USERS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return {}

def save_users(users):
    with open(USERS_FILE, "w", encoding="utf-8") as f:
        json.dump(users, f, indent=4, ensure_ascii=False)

def load_words():
    try:
        with open(WORDS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return []

def save_words(words):
    with open(WORDS_FILE, "w", encoding="utf-8") as f:
        json.dump(words, f, indent=4, ensure_ascii=False)

# ================= API для слов =================
async def fetch_word(session, word):
    url = f"https://api.dictionaryapi.dev/api/v2/entries/en/{word}"
    async with session.get(url) as resp:
        if resp.status == 200:
            data = await resp.json()
            try:
                meaning = data[0]["meanings"][0]["definitions"][0]["definition"]
                return {
                    "word": word,
                    "translation": translator.translate(word, dest="ru").text,
                    "definition": meaning
                }
            except:
                return None
        return None

async def update_words_file():
    words = load_words()
    if len(words) < 50:  # если слов меньше 50 → обновляем
        sample_words = [
            "apple", "book", "computer", "school", "water",
            "friend", "language", "beautiful", "music", "travel",
            "work", "future", "happiness", "family", "dream",
            "power", "light", "energy", "nature", "health"
        ]
        new_words = []

        async with aiohttp.ClientSession() as session:
            for w in sample_words:
                word_data = await fetch_word(session, w)
                if word_data:
                    new_words.append(word_data)

        words.extend(new_words)
        save_words(words)

# ================= Регистрация =================
ASK_LEVEL, ASK_WORDS, ASK_TIME = range(3)

async def start(update: Update, context: CallbackContext):
    users = load_users()
    user_id = str(update.effective_user.id)

    if user_id not in users:
        await update.message.reply_text(
            "Добро пожаловать! 🚀\nВыберите ваш уровень английского:",
            reply_markup=ReplyKeyboardMarkup(
                [["Beginner", "Intermediate", "Advanced"]],
                one_time_keyboard=True, resize_keyboard=True
            ),
        )
        return ASK_LEVEL
    else:
        await update.message.reply_text("Вы уже зарегистрированы ✅\nИспользуйте /menu для настроек.")
        return ConversationHandler.END

async def ask_words(update: Update, context: CallbackContext):
    context.user_data["level"] = update.message.text
    await update.message.reply_text("Сколько слов в день вы хотите получать?")
    return ASK_WORDS

async def ask_time(update: Update, context: CallbackContext):
    try:
        context.user_data["words_per_day"] = int(update.message.text)
    except:
        await update.message.reply_text("Введите число!")
        return ASK_WORDS

    await update.message.reply_text("Введите время (часы:минуты). Пример: 09:00")
    return ASK_TIME

async def finish_registration(update: Update, context: CallbackContext):
    user_id = str(update.effective_user.id)
    users = load_users()

    users[user_id] = {
        "level": context.user_data["level"],
        "words_per_day": context.user_data["words_per_day"],
        "time": update.message.text,
        "premium": False,
        "translations_today": 0,
        "learned_words": []
    }
    save_users(users)

    await update.message.reply_text("Регистрация завершена ✅\nИспользуйте /menu для настроек.")
    return ConversationHandler.END

# ================= Меню =================
async def menu(update: Update, context: CallbackContext):
    keyboard = [
        [InlineKeyboardButton("Изменить уровень", callback_data="set_level")],
        [InlineKeyboardButton("Изменить количество слов", callback_data="set_words")],
        [InlineKeyboardButton("Изменить время", callback_data="set_time")],
        [InlineKeyboardButton("Переводчик", callback_data="translate_mode")],
        [InlineKeyboardButton("Купить Premium", callback_data="buy_premium")]
    ]
    await update.message.reply_text("Меню ⚙️", reply_markup=InlineKeyboardMarkup(keyboard))

async def menu_callback(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()

    if query.data == "buy_premium":
        await query.message.reply_text("💎 Чтобы купить Premium, свяжитесь с админом.")
        await context.bot.send_message(ADMIN_ID, f"Пользователь {query.from_user.id} хочет Premium!")
    elif query.data == "translate_mode":
        context.user_data["mode"] = "translate"
        await query.message.reply_text("Переводчик включён. Напишите слово 📖")

# ================= Переводчик =================
async def handle_message(update: Update, context: CallbackContext):
    user_id = str(update.effective_user.id)
    users = load_users()

    if user_id not in users:
        await update.message.reply_text("Сначала зарегистрируйтесь с помощью /start")
        return

    user = users[user_id]

    if context.user_data.get("mode") == "translate":
        limit = 20 if user["premium"] else 5
        if user["translations_today"] >= limit:
            await update.message.reply_text("❌ Лимит переводов на сегодня достигнут")
            return

        word = update.message.text
        translation = translator.translate(word, dest="ru").text
        definition = translator.translate(word, src="en", dest="en").text

        user["translations_today"] += 1
        save_users(users)

        await update.message.reply_text(
            f"🔤 {word}\nПеревод: {translation}\nОписание: {definition}"
        )

# ================= Авто-отправка слов =================
async def send_daily_words(app: Application):
    while True:
        await update_words_file()
        users = load_users()
        words = load_words()
        now = datetime.datetime.now().strftime("%H:%M")

        for user_id, data in users.items():
            if data["time"] == now:
                count = data["words_per_day"]
                learned = set(data["learned_words"])
                new_words = [w for w in words if w["word"] not in learned][:count]

                if new_words:
                    text = "📚 Сегодняшние слова:\n"
                    for w in new_words:
                        text += f"\n🔤 {w['word']} - {w['translation']}\n📖 {w['definition']}\n"
                        data["learned_words"].append(w["word"])

                    await app.bot.send_message(user_id, text)

        save_users(users)
        await asyncio.sleep(60)

# ================= Основное =================
def main():
    app = Application.builder().token(BOT_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            ASK_LEVEL: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_words)],
            ASK_WORDS: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_time)],
            ASK_TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, finish_registration)],
        },
        fallbacks=[],
    )

    app.add_handler(conv_handler)
    app.add_handler(CommandHandler("menu", menu))
    app.add_handler(CallbackQueryHandler(menu_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    app.job_queue.run_once(lambda ctx: asyncio.create_task(send_daily_words(app)), 1)

    app.run_polling()

if __name__ == "__main__":
    main()