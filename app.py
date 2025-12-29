import os
import logging
import psycopg2
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes, ConversationHandler
)

# ===== НАСТРОЙКИ =====
TOKEN = os.environ.get('BOT_TOKEN')
ADMIN_CHAT_ID = os.environ.get('ADMIN_CHAT_ID', '1294415669')
DATABASE_URL = os.environ.get('DATABASE_URL')  # PostgreSQL URL из Render

# Состояния для ConversationHandler
AREA, TERM, CONTACT, CONFIRM = range(4)

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ===== ФУНКЦИИ БАЗЫ ДАННЫХ =====
def init_db():
    """Инициализация таблиц в PostgreSQL"""
    if not DATABASE_URL:
        logger.warning("⚠️ DATABASE_URL не настроен, используется память")
        return
    
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cursor = conn.cursor()
        
        # Таблица заявок
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS leads (
                id SERIAL PRIMARY KEY,
                user_id BIGINT,
                username VARCHAR(100),
                name VARCHAR(100),
                contact VARCHAR(100),
                contact_type VARCHAR(20),
                area VARCHAR(50),
                term VARCHAR(50),
                status VARCHAR(20) DEFAULT 'new',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                notes TEXT
            )
        ''')
        
        # Таблица активности (для аналитики)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_activity (
                id SERIAL PRIMARY KEY,
                user_id BIGINT,
                action VARCHAR(50),
                details TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        conn.commit()
        cursor.close()
        conn.close()
        logger.info("✅ База данных PostgreSQL инициализирована")
    except Exception as e:
        logger.error(f"❌ Ошибка инициализации БД: {e}")

def save_lead_to_db(lead_data):
    """Сохранение заявки в PostgreSQL"""
    if not DATABASE_URL:
        logger.warning("⚠️ БД не настроена, заявка сохраняется только в памяти")
        return None
    
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO leads (user_id, username, name, contact, contact_type, area, term, status)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        ''', (
            lead_data['user_id'],
            lead_data.get('username', ''),
            lead_data['name'],
            lead_data['contact'],
            lead_data['contact_type'],
            lead_data['area'],
            lead_data['term'],
            'new'
        ))
        
        lead_id = cursor.fetchone()[0]
        conn.commit()
        cursor.close()
        conn.close()
        
        logger.info(f"✅ Заявка #{lead_id} сохранена в PostgreSQL")
        return lead_id
    except Exception as e:
        logger.error(f"❌ Ошибка сохранения в БД: {e}")
        return None

def get_db_stats():
    """Получение статистики из PostgreSQL"""
    if not DATABASE_URL:
        return {'total': 0, 'today': 0, 'new': 0, 'contacted': 0}
    
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT 
                COUNT(*) as total_leads,
                COUNT(CASE WHEN created_at::date = CURRENT_DATE THEN 1 END) as today_leads,
                COUNT(CASE WHEN status = 'new' THEN 1 END) as new_leads,
                COUNT(CASE WHEN status = 'contacted' THEN 1 END) as contacted_leads
            FROM leads
        ''')
        
        stats = cursor.fetchone()
        cursor.close()
        conn.close()
        
        return {
            'total': stats[0] or 0,
            'today': stats[1] or 0,
            'new': stats[2] or 0,
            'contacted': stats[3] or 0
        }
    except Exception as e:
        logger.error(f"❌ Ошибка получения статистики: {e}")
        return {'total': 0, 'today': 0, 'new': 0, 'contacted': 0}

def get_recent_leads(limit=5):
    """Получение последних заявок"""
    if not DATABASE_URL:
        return []
    
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT id, name, contact, area, term, created_at
            FROM leads 
            ORDER BY created_at DESC 
            LIMIT %s
        ''', (limit,))
        
        leads = cursor.fetchall()
        cursor.close()
        conn.close()
        
        return leads
    except Exception as e:
        logger.error(f"❌ Ошибка получения заявок: {e}")
        return []

# ===== БАЗА ЗНАНИЙ ELP (обновленные тексты) =====
KNOWLEDGE_BASE = {
    'area': "🏭 *Площади складов ELP:*\n\n"
            "• Корпус А: 32 800 м²\n"
            "• Корпус В: 17 500 м²\n"
            "• Минимальная аренда: от 3 500 м²\n\n"
            "Все склады класса А с полным комплектом инженерных систем.",
    
    'price': "💰 *Стоимость аренды:*\n\n"
             "• От 5 500 ₸ за кв.м/мес\n"
             "• Включает OPEX (эксплуатационные расходы)\n"
             "• Индивидуальный расчёт для площадей от 3 500 м²\n\n"
             "Нужен точный расчёт для вашего бизнеса?",
    
    'location': "📍 *Расположение:*\n\n"
                "• Алматинская область, Талгарский район\n"
                "• Кульджинский тракт, 200\n"
                "• 30 км до центра Алматы\n"
                "• 22 км до международного аэропорта\n"
                "• 5 км до развязки БАКАД\n\n"
                "Координаты: 43.394771, 77.173137",
    
    'specs': "⚙️ *Технические характеристики:*\n\n"
             "• Класс А по международной классификации\n"
             "• Высота до подкранового пути: 12 м\n"
             "• Допустимая нагрузка на пол: 8 т/м²\n"
             "• Шаг колонн: 12×24 м\n"
             "• Доки: 1 на 1200 м²\n"
             "• Современные системы пожаротушения\n"
             "• Круглосуточная охрана и видеонаблюдение",
    
    'contact': "👨‍💼 *Контакты директора по развитию:*\n\n"
               "**Директор по развитию ELP**\n"
               "• Email: strategy.elp@gmail.com\n"
               "• Telegram: @elp_almaty_bot\n\n"
               "Специализируется на стратегическом развитии логистических мощностей в Алматы.",
    
    'timeline': "📅 *Сроки реализации:*\n\n"
                "• Период проекта: 2025–2028 гг.\n"
                "• 1 этап (Корпус В) — введён в эксплуатацию\n"
                "• Поэтапный ввод до общей площади 250 000 м²"
}

# ===== КЛАВИАТУРЫ =====
def main_menu_keyboard():
    """Главное меню (inline-кнопки)"""
    keyboard = [
        [InlineKeyboardButton("📐 Площади", callback_data='area'),
         InlineKeyboardButton("💰 Стоимость", callback_data='price')],
        [InlineKeyboardButton("📍 Расположение", callback_data='location'),
         InlineKeyboardButton("⚙️ Характеристики", callback_data='specs')],
        [InlineKeyboardButton("👨‍💼 Контакты", callback_data='contact'),
         InlineKeyboardButton("📅 Сроки", callback_data='timeline')],
        [InlineKeyboardButton("📝 Оставить заявку", callback_data='start_request')]
    ]
    return InlineKeyboardMarkup(keyboard)

def action_keyboard(action_type='default'):
    """Кнопки действий после ответа"""
    if action_type == 'price':
        keyboard = [
            [InlineKeyboardButton("📝 Оставить заявку", callback_data='start_request'),
             InlineKeyboardButton("👨‍💼 Написать директору", callback_data='contact')],
            [InlineKeyboardButton("🗓️ Записаться на просмотр", callback_data='schedule_tour')]
        ]
    elif action_type == 'contact':
        keyboard = [
            [InlineKeyboardButton("✉️ Написать email", callback_data='write_email'),
             InlineKeyboardButton("📝 Оставить заявку", callback_data='start_request')],
            [InlineKeyboardButton("🏭 Посмотреть площади", callback_data='area')]
        ]
    else:
        keyboard = [
            [InlineKeyboardButton("📝 Оставить заявку", callback_data='start_request'),
             InlineKeyboardButton("💰 Узнать стоимость", callback_data='price')],
            [InlineKeyboardButton("👨‍💼 Связаться с директором", callback_data='contact')]
        ]
    return InlineKeyboardMarkup(keyboard)

def area_selection_keyboard():
    """Выбор площади для заявки"""
    keyboard = [
        [InlineKeyboardButton("до 500 м²", callback_data='area_500')],
        [InlineKeyboardButton("500 - 1 000 м²", callback_data='area_1000')],
        [InlineKeyboardButton("1 000 - 3 500 м²", callback_data='area_3500')],
        [InlineKeyboardButton("более 3 500 м²", callback_data='area_5000')],
        [InlineKeyboardButton("↩️ Назад", callback_data='cancel')]
    ]
    return InlineKeyboardMarkup(keyboard)

def term_selection_keyboard():
    """Выбор срока аренды"""
    keyboard = [
        [InlineKeyboardButton("6 месяцев", callback_data='term_6')],
        [InlineKeyboardButton("1 год", callback_data='term_12')],
        [InlineKeyboardButton("2 года", callback_data='term_24')],
        [InlineKeyboardButton("3+ года", callback_data='term_36')],
        [InlineKeyboardButton("↩️ Назад", callback_data='back_to_area')]
    ]
    return InlineKeyboardMarkup(keyboard)

# ===== ОСНОВНЫЕ ОБРАБОТЧИКИ =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /start"""
    welcome_text = (
        "🏭 *Добро пожаловать в официальный бот Евразийского Логистического Парка!*\n\n"
        "Здесь вы можете получить всю информацию о складах класса А в Алматы.\n\n"
        "Выберите интересующий раздел:"
    )
    
    if update.message:
        await update.message.reply_text(
            welcome_text,
            parse_mode='Markdown',
            reply_markup=main_menu_keyboard()
        )
    else:
        await update.callback_query.edit_message_text(
            welcome_text,
            parse_mode='Markdown',
            reply_markup=main_menu_keyboard()
        )
    
    return ConversationHandler.END

async def handle_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка нажатий в главном меню"""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    data = query.data
    
    # Сохраняем активность в БД (если настроена)
    if DATABASE_URL:
        try:
            conn = psycopg2.connect(DATABASE_URL)
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO user_activity (user_id, action) VALUES (%s, %s)",
                (user_id, data)
            )
            conn.commit()
            cursor.close()
            conn.close()
        except Exception as e:
            logger.error(f"⚠️ Не удалось сохранить активность: {e}")
    
    # Обработка разных типов кнопок
    if data in KNOWLEDGE_BASE:
        # Показываем информацию + кнопки действий
        action_type = 'price' if data == 'price' else 'contact' if data == 'contact' else 'default'
        
        await query.edit_message_text(
            text=KNOWLEDGE_BASE[data],
            parse_mode='Markdown',
            reply_markup=action_keyboard(action_type)
        )
    
    elif data == 'start_request':
        # Начинаем процесс заявки
        await query.edit_message_text(
            text="📋 *Оформление заявки*\n\n"
                 "Давайте подберём оптимальное решение для вашего бизнеса.\n\n"
                 "🔄 *Шаг 1 из 4*\n"
                 "Какая площадь склада вас интересует?",
            parse_mode='Markdown',
            reply_markup=area_selection_keyboard()
        )
        return AREA
    
    elif data == 'write_email':
        await query.edit_message_text(
            text="✉️ *Написать директору по развитию:*\n\n"
                 "Email: strategy.elp@gmail.com\n\n"
                 "Укажите в теме письма:\n"
                 "«Запрос по складам ELP»\n\n"
                 "Мы ответим в течение 24 часов.",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("📝 Оставить заявку через бота", callback_data='start_request'),
                InlineKeyboardButton("🏠 В главное меню", callback_data='main_menu')
            ]])
        )
    
    elif data == 'schedule_tour':
        await query.edit_message_text(
            text="🗓️ *Запись на просмотр*\n\n"
                 "Для записи на индивидуальный просмотр:\n"
                 "1. Оставьте заявку через бота\n"
                 "2. Директор по развитию свяжется с вами\n"
                 "3. Согласуем удобное время\n\n"
                 "Просмотры проводятся по будням с 10:00 до 17:00.",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("📝 Оставить заявку", callback_data='start_request'),
                InlineKeyboardButton("🏠 В меню", callback_data='main_menu')
            ]])
        )
    
    elif data == 'main_menu':
        await start(update, context)

# ===== ПРОЦЕСС ЗАЯВКИ =====
async def select_area(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Шаг 1: Выбор площади"""
    query = update.callback_query
    await query.answer()
    
    if query.data == 'cancel':
        await start(update, context)
        return ConversationHandler.END
    
    # Сохраняем выбор площади
    area_map = {
        'area_500': 'до 500 м²',
        'area_1000': '500 - 1 000 м²',
        'area_3500': '1 000 - 3 500 м²',
        'area_5000': 'более 3 500 м²'
    }
    
    context.user_data['lead'] = {
        'area': area_map.get(query.data, query.data),
        'user_id': query.from_user.id,
        'username': query.from_user.username or query.from_user.first_name,
        'created': datetime.now().isoformat()
    }
    
    await query.edit_message_text(
        text="📋 *Оформление заявки*\n\n"
             f"✅ Площадь: {context.user_data['lead']['area']}\n\n"
             "🔄 *Шаг 2 из 4*\n"
             "На какой срок планируете аренду?",
        parse_mode='Markdown',
        reply_markup=term_selection_keyboard()
    )
    return TERM

async def select_term(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Шаг 2: Выбор срока"""
    query = update.callback_query
    await query.answer()
    
    if query.data == 'back_to_area':
        await query.edit_message_text(
            text="📋 *Оформление заявки*\n\n"
                 "🔄 *Шаг 1 из 4*\n"
                 "Какая площадь склада вас интересует?",
            parse_mode='Markdown',
            reply_markup=area_selection_keyboard()
        )
        return AREA
    
    # Сохраняем срок
    term_map = {
        'term_6': '6 месяцев',
        'term_12': '1 год',
        'term_24': '2 года',
        'term_36': '3+ года'
    }
    
    context.user_data['lead']['term'] = term_map.get(query.data, query.data)
    
    await query.edit_message_text(
        text="📋 *Оформление заявки*\n\n"
             f"✅ Площадь: {context.user_data['lead']['area']}\n"
             f"✅ Срок аренды: {context.user_data['lead']['term']}\n\n"
             "🔄 *Шаг 3 из 4*\n"
             "Как к вам обращаться? Отправьте ваше имя.",
        parse_mode='Markdown'
    )
    return CONTACT

async def get_contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Шаг 3: Получение контакта"""
    if update.message:
        context.user_data['lead']['name'] = update.message.text
        
        keyboard = [[
            InlineKeyboardButton("📱 Отправить телефон", callback_data='send_phone'),
            InlineKeyboardButton("📧 Указать email", callback_data='send_email')
        ], [
            InlineKeyboardButton("↩️ Назад", callback_data='back_to_term')
        ]]
        
        await update.message.reply_text(
            text="📋 *Оформление заявки*\n\n"
                 f"✅ Площадь: {context.user_data['lead']['area']}\n"
                 f"✅ Срок: {context.user_data['lead']['term']}\n"
                 f"✅ Имя: {context.user_data['lead']['name']}\n\n"
                 "🔄 *Шаг 4 из 4*\n"
                 "Как с вами связаться?",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return CONFIRM

async def confirm_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Шаг 4: Подтверждение и отправка"""
    # Проверяем, есть ли query (для callback)
    query = None
    if hasattr(update, 'callback_query'):
        query = update.callback_query
        if query:
            await query.answer()
    
    if query and query.data == 'back_to_term':
        await query.edit_message_text(
            text="📋 *Оформление заявки*\n\n"
                 f"✅ Площадь: {context.user_data['lead']['area']}\n"
                 f"✅ Срок аренды: {context.user_data['lead']['term']}\n\n"
                 "🔄 *Шаг 3 из 4*\n"
                 "Как к вам обращаться? Отправьте ваше имя.",
            parse_mode='Markdown'
        )
        return CONTACT
    
    if query and query.data in ['send_phone', 'send_email']:
        context.user_data['contact_type'] = 'телефон' if query.data == 'send_phone' else 'email'
        
        await query.edit_message_text(
            text=f"Отправьте ваш {context.user_data['contact_type']}:",
            parse_mode='Markdown'
        )
        return CONFIRM
    
    # Если это сообщение с контактом
    if update.message:
        if update.message.contact:
            contact = update.message.contact.phone_number
            contact_type = 'телефон'
        else:
            contact = update.message.text
            contact_type = context.user_data.get('contact_type', 'контакт')
        
        # Сохраняем заявку
        lead = context.user_data['lead']
        lead['contact'] = contact
        lead['contact_type'] = contact_type
        
        # Сохраняем в PostgreSQL
        lead_id = save_lead_to_db(lead)
        
        if lead_id:
            lead['db_id'] = lead_id
            lead_id_display = f"#{lead_id}"
            logger.info(f"✅ Заявка сохранена в БД с ID: {lead_id}")
        else:
            # Резервный вариант, если БД не работает
            lead_id_display = f"lead_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            logger.warning(f"⚠️ Заявка не сохранена в БД, временный ID: {lead_id_display}")
        
        # Формируем сообщение для админа
        admin_message = (
            "🚀 *НОВАЯ ЗАЯВКА С БОТА ELP!*\n\n"
            f"📋 ID: `{lead_id_display}`\n"
            f"👤 Имя: {lead['name']}\n"
            f"👤 Username: @{lead['username']}\n"
            f"📞 Контакт ({lead['contact_type']}): {lead['contact']}\n"
            f"📐 Площадь: {lead['area']}\n"
            f"📅 Срок: {lead['term']}\n"
            f"⏰ Время: {datetime.now().strftime('%d.%m.%Y %H:%M')}\n\n"
            f"User ID: `{lead['user_id']}`"
        )
        
        # Отправляем админу
        try:
            await context.bot.send_message(
                chat_id=ADMIN_CHAT_ID,
                text=admin_message,
                parse_mode='Markdown'
            )
            logger.info(f"Заявка отправлена админу: {lead_id_display}")
        except Exception as e:
            logger.error(f"Ошибка отправки админу: {e}")
        
        # Сообщение пользователю
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("👨‍💼 Написать директору", callback_data='contact'),
            InlineKeyboardButton("🏠 В главное меню", callback_data='main_menu')
        ]])
        
        await update.message.reply_text(
            text="✅ *Заявка успешно отправлена!*\n\n"
                 "С вами свяжется **директор по развитию ELP** в ближайшее время.\n\n"
                 "✉️ Контакты для связи:\n"
                 "• Email: strategy.elp@gmail.com\n"
                 "• Telegram: @elp_almaty_bot\n\n"
                 "Рабочие часы: Пн-Пт, 9:00-18:00",
            parse_mode='Markdown',
            reply_markup=keyboard
        )
        
        # Очищаем данные
        context.user_data.clear()
        return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отмена заявки"""
    await update.message.reply_text(
        "Заявка отменена.",
        reply_markup=main_menu_keyboard()
    )
    context.user_data.clear()
    return ConversationHandler.END

# ===== КОМАНДЫ АДМИНА =====
async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /stats для просмотра статистики"""
    if str(update.effective_user.id) != ADMIN_CHAT_ID:
        await update.message.reply_text("⛔ Доступ запрещён")
        return
    
    stats = get_db_stats()
    recent_leads = get_recent_leads(5)
    
    stats_text = (
        f"📊 *Статистика бота ELP*\n\n"
        f"• Всего заявок: {stats['total']}\n"
        f"• За сегодня: {stats['today']}\n"
        f"• Новые: {stats['new']}\n"
        f"• В работе: {stats['contacted']}\n\n"
    )
    
    if recent_leads:
        stats_text += "📋 *Последние заявки:*\n"
        for i, (lead_id, name, contact, area, term, created_at) in enumerate(recent_leads, 1):
            date_str = created_at.strftime('%d.%m') if isinstance(created_at, datetime) else created_at[:10]
            stats_text += f"\n{i}. {name} - {area} ({date_str})"
    else:
        stats_text += "📭 Заявок пока нет"
    
    stats_text += "\n\n📈 *База данных:* " + ("✅ Активна" if DATABASE_URL else "⚠️ В памяти")
    
    await update.message.reply_text(stats_text, parse_mode='Markdown')

async def admin_leads(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /leads для детального просмотра"""
    if str(update.effective_user.id) != ADMIN_CHAT_ID:
        return
    
    recent_leads = get_recent_leads(10)
    
    if not recent_leads:
        await update.message.reply_text("📭 Заявок пока нет")
        return
    
    for i, (lead_id, name, contact, area, term, created_at) in enumerate(recent_leads, 1):
        date_str = created_at.strftime('%d.%m.%Y %H:%M') if isinstance(created_at, datetime) else created_at
        lead_text = (
            f"📋 *Заявка #{lead_id}*\n\n"
            f"👤 Имя: {name}\n"
            f"📞 Контакт: {contact}\n"
            f"📐 Площадь: {area}\n"
            f"📅 Срок: {term}\n"
            f"⏰ Дата: {date_str}"
        )
        await update.message.reply_text(lead_text, parse_mode='Markdown')

# ===== ОБРАБОТКА ТЕКСТОВЫХ СООБЩЕНИЙ =====
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка текстовых сообщений (не команд)"""
    text = update.message.text.lower()
    
    if any(word in text for word in ['привет', 'здравств', 'hello', 'hi']):
        await update.message.reply_text(
            "Привет! Чем могу помочь?",
            reply_markup=main_menu_keyboard()
        )
    elif any(word in text for word in ['спасибо', 'благодар']):
        await update.message.reply_text("Рад был помочь! 🤝")
    else:
        # Если непонятное сообщение — показываем меню
        await update.message.reply_text(
            "Выберите интересующий раздел:",
            reply_markup=main_menu_keyboard()
        )

# ===== ГЛАВНАЯ ФУНКЦИЯ =====
def main():
    """Запуск бота"""
    if not TOKEN:
        logger.error("❌ Токен бота не найден! Установите BOT_TOKEN в Render")
        return
    
    # Инициализируем БД при запуске
    init_db()
    
    # Создаем приложение
    application = Application.builder().token(TOKEN).build()
    
    # ConversationHandler для заявки
    conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(select_area, pattern='^area_')],
        states={
            AREA: [CallbackQueryHandler(select_area)],
            TERM: [CallbackQueryHandler(select_term)],
            CONTACT: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_contact)],
            CONFIRM: [
                CallbackQueryHandler(confirm_request),
                MessageHandler(filters.TEXT & ~filters.COMMAND, confirm_request),
                MessageHandler(filters.CONTACT, confirm_request)
            ]
        },
        fallbacks=[
            CommandHandler('cancel', cancel),
            CallbackQueryHandler(start, pattern='^cancel$')
        ],
        allow_reentry=True
    )
    
    # Регистрируем обработчики
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("stats", admin_stats))
    application.add_handler(CommandHandler("leads", admin_leads))
    application.add_handler(conv_handler)
    application.add_handler(CallbackQueryHandler(handle_menu))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    
    # Запускаем бота
    logger.info("🤖 Бот ELP запускается...")
    application.run_polling()

if __name__ == '__main__':
    main()
