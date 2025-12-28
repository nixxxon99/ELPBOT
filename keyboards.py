from aiogram.types import ReplyKeyboardMarkup, KeyboardButton

def main_kb():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📍 О проекте"), KeyboardButton(text="📦 Характеристики склада")],
            [KeyboardButton(text="❓ FAQ"), KeyboardButton(text="📞 Контакты")]
        ],
        resize_keyboard=True
    )