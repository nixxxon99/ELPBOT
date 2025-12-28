import asyncio
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from config import BOT_TOKEN
from keyboards import main_kb

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

@dp.message(Command("start"))
async def start(message: types.Message):
    await message.answer(
        "Добро пожаловать в ELPK Bot 👋\n"
        "Я помогу вам узнать всё о складском комплексе класса A в Алматы.",
        reply_markup=main_kb()
    )

@dp.message()
async def handler(message: types.Message):
    text = message.text.lower()

    if "проект" in text:
        await message.answer_from_config("about.txt")
    elif "характер" in text or "склад" in text:
        await message.answer_from_config("specs.txt")
    elif "контакт" in text or "адрес" in text:
        await message.answer_from_config("contacts.txt")
    elif "вопрос" in text or "faq" in text:
        await message.answer_from_config("faq.txt")
    else:
        await message.answer("Пожалуйста, выберите раздел из меню 👇")

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())