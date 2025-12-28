import os
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from flask import Flask

# Flask app для Render
app = Flask(__name__)

@app.route('/')
def home():
    return "✅ Бот ELP активен!"

# Запуск Flask на Render
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)

# ========== TELEGRAM BOT ==========
TOKEN = os.getenv('BOT_TOKEN')

# База знаний
KNOWLEDGE = {
    "площадь": "🏭 ELP — логистический парк класса А общей площадью 250 000 кв. м.\n\n• Корпус А: 32 800 м²\n• Корпус В: 17 500 м²\n• Минимальная аренда: от 3 500 м²",
    "стоимость": "💰 От 5 500 ₸/м² с OPEX\n• Включает эксплуатационные расходы\n• Индивидуальный расчет у брокера",
    "расположение": "📍 Кульджинский тракт, 200 (Талгарский р-н)\n• 30 км до Алматы\n• 22 км до аэропорта\n• 5 км до БАКАД",
    "срок": "📅 Проект: 2025-2028 гг.\n• 1 этап (Корпус В) — сдан",
    "брокер": "🤝 Эксклюзивный брокер: Bright Rich | CORFAC International",
    "характеристики": "⚙️ Класс А:\n• Высота: 12 м\n• Нагрузка: 8 т/м²\n• Колонны: 12×24 м"
}

# Клавиатура
KEYBOARD = ReplyKeyboardMarkup(
    [["📐 Площади", "💰 Стоимость"],
     ["📍 Расположение", "⚙️ Характеристики"],
     ["🤝 Брокер", "📅 Сроки"]],
    resize_keyboard=True
)

# Команда /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🏭 *Евразийский Логистический Парк (ELP)*\n\nВыберите вопрос:",
        reply_markup=KEYBOARD,
        parse_mode='Markdown'
    )

# Обработка сообщений
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.lower()
    
    response = "Выберите вопрос из меню или напишите: площадь, стоимость, расположение и т.д."
    
    if "площад" in text:
        response = KNOWLEDGE["площадь"] + "\n\n" + KNOWLEDGE["стоимость"]
    elif "стоимост" in text or "цен" in text:
        response = KNOWLEDGE["стоимость"]
    elif "расположен" in text or "адрес" in text:
        response = KNOWLEDGE["расположение"]
    elif "характеристик" in text:
        response = KNOWLEDGE["характеристики"]
    elif "брокер" in text:
        response = KNOWLEDGE["брокер"]
    elif "срок" in text:
        response = KNOWLEDGE["срок"]
    
    await update.message.reply_text(response, reply_markup=KEYBOARD)

# Запуск бота
def run_bot():
    app_bot = Application.builder().token(TOKEN).build()
    
    app_bot.add_handler(CommandHandler("start", start))
    app_bot.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    print("✅ Бот запущен...")
    app_bot.run_polling()

if __name__ == '__main__':
    run_bot()
