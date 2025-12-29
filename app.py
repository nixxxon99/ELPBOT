import os
import logging
import smtplib
import psycopg2
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes, ConversationHandler
)

# ===== НАСТРОЙКИ =====
TOKEN = os.environ.get('BOT_TOKEN')
ADMIN_CHAT_ID = os.environ.get('ADMIN_CHAT_ID', '1294415669')
DATABASE_URL = os.environ.get('DATABASE_URL')

# ===== EMAIL НАСТРОЙКИ =====
SMTP_SERVER = os.environ.get('SMTP_SERVER', 'smtp.gmail.com')
SMTP_PORT = int(os.environ.get('SMTP_PORT', 587))
EMAIL_USER = os.environ.get('EMAIL_USER', 'strategy.elp@gmail.com')
EMAIL_PASSWORD = os.environ.get('EMAIL_PASSWORD', '')
EMAIL_TO = os.environ.get('EMAIL_TO', 'strategy.elp@gmail.com')

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

# ===== EMAIL ФУНКЦИИ =====
def send_email_notification_sync(lead_data, lead_id_display):
    """Отправка email-уведомления о новой заявке (синхронная версия)"""
    if not EMAIL_PASSWORD:
        logger.warning("⚠️ Пароль email не настроен, уведомления не отправляются")
        return False
    
    try:
        # Тема письма
        subject = f"🚀 Новая заявка ELP {lead_id_display} - {lead_data['name']}"
        
        # HTML тело письма
        body = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
                .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                .header {{ background: #1a3d7a; color: white; padding: 20px; text-align: center; border-radius: 5px 5px 0 0; }}
                .content {{ background: #f9f9f9; padding: 20px; border: 1px solid #ddd; }}
                .lead-info {{ background: white; padding: 15px; margin: 10px 0; border-left: 4px solid #1a3d7a; }}
                .label {{ font-weight: bold; color: #1a3d7a; }}
                .footer {{ text-align: center; margin-top: 20px; color: #666; font-size: 12px; }}
                .button {{ display: inline-block; background: #1a3d7a; color: white; padding: 10px 20px; text-decoration: none; border-radius: 4px; margin-top: 10px; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h2>🚀 Новая заявка с бота ELP</h2>
                </div>
                
                <div class="content">
                    <div class="lead-info">
                        <p><span class="label">📋 ID заявки:</span> {lead_id_display}</p>
                        <p><span class="label">👤 Клиент:</span> {lead_data['name']}</p>
                        <p><span class="label">📧 Контакт:</span> {lead_data['contact']} ({lead_data['contact_type']})</p>
                        <p><span class="label">📐 Интересуемая площадь:</span> {lead_data['area']}</p>
                        <p><span class="label">📅 Срок аренды:</span> {lead_data['term']}</p>
                        <p><span class="label">⏰ Дата и время:</span> {datetime.now().strftime('%d.%m.%Y %H:%M')}</p>
                        <p><span class="label">🔗 User ID:</span> {lead_data['user_id']}</p>
                        <p><span class="label">👤 Username:</span> @{lead_data.get('username', 'не указан')}</p>
                    </div>
                    
                    <p><strong>📞 Быстрый ответ:</strong></p>
                    <p>• Email: <a href="mailto:{lead_data['contact']}">{lead_data['contact']}</a></p>
                    
                    <p style="margin-top: 20px;">
                        <a href="https://t.me/elp_almaty_bot" class="button">💬 Открыть бота</a>
                    </p>
                </div>
                
                <div class="footer">
                    <p>📍 Евразийский Логистический Парк | Алматы</p>
                    <p>📧 strategy.elp@gmail.com | 🌐 elpk.kz</p>
                    <p><em>Заявка сгенерирована автоматически Telegram-ботом ELP</em></p>
                </div>
            </div>
        </body>
        </html>
        """
        
        # Создаем письмо
        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From'] = f"ELP Telegram Bot <{EMAIL_USER}>"
        msg['To'] = EMAIL_TO
        
        # Добавляем HTML версию
        html_part = MIMEText(body, 'html')
        msg.attach(html_part)
        
        # Отправляем
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(EMAIL_USER, EMAIL_PASSWORD)
            server.send_message(msg)
        
        logger.info(f"✅ Email отправлен на {EMAIL_TO}")
        return True
        
    except Exception as e:
        logger.error(f"❌ Ошибка отправки email: {e}")
        return False

# ===== БАЗА ЗНАНИЙ ELP =====
KNOWLEDGE_BASE = {
    'area': "🏭 *Площади складов ELP:*\n\n• Корпус А: 32 800 м²\n• Корпус В: 17 500 м²\n• Минимальная аренда: от 3 500 м²\n\nВсе склады класса А с полным комплектом инженерных систем.",
    'price': "💰 *Стоимость аренды:*\n\n• От 5 500 ₸ за кв.м/мес\n• Включает OPEX (эксплуатационные расходы)\n• Индивидуальный расчёт для площадей от 3 500 м²\n\nНужен точный расчёт для вашего бизнеса?",
    'location': "📍 *Расположение:*\n\n• Алматинская область, Талгарский район\n• Кульджинский тракт, 200\n• 30 км до центра Алматы\n• 22 км до международного аэропорта\n• 5 км до развязки БАКАД\n\nКоординаты: 43.394771, 77.173137",
    'specs': "⚙️ *Технические характеристики:*\n\n• Класс А по международной классификации\n• Высота до подкранового пути: 12 м\n• Допустимая нагрузка на пол: 8 т/м²\n• Шаг колонн: 12×24 м\n• Доки: 1 на 1200 м²\n• Современные системы пожаротушения\n• Круглосуточная охрана и видеонаблюдение",
    'contact': "👨‍💼 *Контакты директора по развитию:*\n\n**Директор по развитию ELP**\n• Email: strategy.elp@gmail.com\n• Telegram: @elp_almaty_bot\n\nСпециализируется на стратегическом развитии логистических мощностей в Алматы.",
    'timeline': "📅 *Сроки реализации:*\n\n• Период проекта: 2025–2028 гг.\n• 1 этап (Корпус В) — введён в эксплуатацию\n• Поэтапный ввод до общей площади 250 000 м²"
}

# ===== КЛАВИАТУРЫ =====
def main_menu_keyboard():
    keyboard = [
        [InlineKeyboardButton("📐 Площади", callback_data='area'), InlineKeyboardButton("💰 Стоимость", callback_data='price')],
        [InlineKeyboardButton("📍 Расположение", callback_data='location'), InlineKeyboardButton("⚙️ Характеристики", callback_data='specs')],
        [InlineKeyboardButton("👨‍💼 Контакты", callback_data='contact'), InlineKeyboardButton("📅 Сроки", callback_data='timeline')],
        [InlineKeyboardButton("📝 Оставить заявку", callback_data='start_request')]
    ]
    return InlineKeyboardMarkup(keyboard)

def action_keyboard(action_type='default'):
    if action_type == 'price':
        keyboard = [
            [InlineKeyboardButton("📝 Оставить заявку", callback_data='start_request'), InlineKeyboardButton("👨‍💼 Написать директору", callback_data='contact')],
            [InlineKeyboardButton("🗓️ Записаться на просмотр", callback_data='schedule_tour')]
        ]
    elif action_type == 'contact':
        keyboard = [
            [InlineKeyboardButton("✉️ Написать email", callback_data='write_email'), InlineKeyboardButton("📝 Оставить заявку", callback_data='start_request')],
            [InlineKeyboardButton("🏭 Посмотреть площади", callback_data='area')]
        ]
    else:
        keyboard = [
            [InlineKeyboardButton("📝 Оставить заявку", callback_data='start_request'), InlineKeyboardButton("💰 Узнать стоимость", callback_data='price')],
            [InlineKeyboardButton("👨‍💼 Связаться с директором", callback_data='contact')]
        ]
    return InlineKeyboardMarkup(keyboard)

def area_selection_keyboard():
    keyboard = [
        [InlineKeyboardButton("до 500 м²", callback_data='area_500')],
        [InlineKeyboardButton("500 - 1 000 м²", callback_data='area_1000')],
        [InlineKeyboardButton("1 000 - 3 500 м²", callback_data='area_3500')],
        [InlineKeyboardButton("более 3 500 м²", callback_data='area_5000')],
        [InlineKeyboardButton("↩️ Назад", callback_data='cancel')]
    ]
    return InlineKeyboardMarkup(keyboard)

def term_selection_keyboard():
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
    welcome_text = "🏭 *Добро пожаловать в официальный бот Евразийского Логистического Парка!*\n\nЗдесь вы можете получить всю информацию о складах класса А в Алматы.\n\nВыберите интересующий раздел:"
    
    if update.message:
        await update.message.reply_text(welcome_text, parse_mode='Markdown', reply_markup=main_menu_keyboard())
    else:
        await update.callback_query.edit_message_text(welcome_text, parse_mode='Markdown', reply_markup=main_menu_keyboard())
    return ConversationHandler.END

async def handle_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    
    if data in KNOWLEDGE_BASE:
        action_type = 'price' if data == 'price' else 'contact' if data == 'contact' else 'default'
        await query.edit_message_text(text=KNOWLEDGE_BASE[data], parse_mode='Markdown', reply_markup=action_keyboard(action_type))
    elif data == 'start_request':
        await query.edit_message_text(
            text="📋 *Оформление заявки*\n\nДавайте подберём оптимальное решение для вашего бизнеса.\n\n🔄 *Шаг 1 из 4*\nКакая площадь склада вас интересует?",
            parse_mode='Markdown', reply_markup=area_selection_keyboard()
        )
        return AREA
    elif data == 'write_email':
        await query.edit_message_text(
            text="✉️ *Написать директору по развитию:*\n\nEmail: strategy.elp@gmail.com\n\nУкажите в теме письма:\n«Запрос по складам ELP»\n\nМы ответим в течение 24 часов.",
            parse_mode='Markdown', reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("📝 Оставить заявку через бота", callback_data='start_request'),
                InlineKeyboardButton("🏠 В главное меню", callback_data='main_menu')
            ]])
        )
    elif data == 'schedule_tour':
        await query.edit_message_text(
            text="🗓️ *Запись на просмотр*\n\nДля записи на индивидуальный просмотр:\n1. Оставьте заявку через бота\n2. Директор по развитию свяжется с вами\n3. Согласуем удобное время\n\nПросмотры проводятся по будням с 10:00 до 17:00.",
            parse_mode='Markdown', reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("📝 Оставить заявку", callback_data='start_request'),
                InlineKeyboardButton("🏠 В меню", callback_data='main_menu')
            ]])
        )
    elif data == 'main_menu':
        await start(update, context)

# ===== ПРОЦЕСС ЗАЯВКИ =====
async def select_area(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == 'cancel':
        await start(update, context)
        return ConversationHandler.END
    
    area_map = {
        'area_500': 'до 500 м²', 'area_1000': '500 - 1 000 м²',
        'area_3500': '1 000 - 3 500 м²', 'area_5000': 'более 3 500 м²'
    }
    
    context.user_data['lead'] = {
        'area': area_map.get(query.data, query.data),
        'user_id': query.from_user.id,
        'username': query.from_user.username or query.from_user.first_name,
        'created': datetime.now().isoformat()
    }
    
    await query.edit_message_text(
        text=f"📋 *Оформление заявки*\n\n✅ Площадь: {context.user_data['lead']['area']}\n\n🔄 *Шаг 2 из 4*\nНа какой срок планируете аренду?",
        parse_mode='Markdown', reply_markup=term_selection_keyboard()
    )
    return TERM

async def select_term(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == 'back_to_area':
        await query.edit_message_text(
            text="📋 *Оформление заявки*\n\n🔄 *Шаг 1 из 4*\nКакая площадь склада вас интересует?",
            parse_mode='Markdown', reply_markup=area_selection_keyboard()
        )
        return AREA
    
    term_map = {
        'term_6': '6 месяцев', 'term_12': '1 год',
        'term_24': '2 года', 'term_36': '3+ года'
    }
    
    context.user_data['lead']['term'] = term_map.get(query.data, query.data)
    
    await query.edit_message_text(
        text=f"📋 *Оформление заявки*\n\n✅ Площадь: {context.user_data['lead']['area']}\n✅ Срок аренды: {context.user_data['lead']['term']}\n\n🔄 *Шаг 3 из 4*\nКак к вам обращаться? Отправьте ваше имя.",
        parse_mode='Markdown'
    )
    return CONTACT

async def get_contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message:
        context.user_data['lead']['name'] = update.message.text
        
        keyboard = [[
            InlineKeyboardButton("📱 Отправить телефон", callback_data='send_phone'),
            InlineKeyboardButton("📧 Указать email", callback_data='send_email')
        ], [
            InlineKeyboardButton("↩️ Назад", callback_data='back_to_term')
        ]]
        
        await update.message.reply_text(
            text=f"📋 *Оформление заявки*\n\n✅ Площадь: {context.user_data['lead']['area']}\n✅ Срок: {context.user_data['lead']['term']}\n✅ Имя: {context.user_data['lead']['name']}\n\n🔄 *Шаг 4 из 4*\nКак с вами связаться?",
            parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return CONFIRM

async def confirm_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = None
    if hasattr(update, 'callback_query'):
        query = update.callback_query
        if query:
            await query.answer()
    
    if query and query.data == 'back_to_term':
        await query.edit_message_text(
            text=f"📋 *Оформление заявки*\n\n✅ Площадь: {context.user_data['lead']['area']}\n✅ Срок аренды: {context.user_data['lead']['term']}\n\n🔄 *Шаг 3 из 4*\nКак к вам обращаться? Отправьте ваше имя.",
            parse_mode='Markdown'
        )
        return CONTACT
    
    if query and query.data in ['send_phone', 'send_email']:
        context.user_data['contact_type'] = 'телефон' if query.data == 'send_phone' else 'email'
        await query.edit_message_text(text=f"Отправьте ваш {context.user_data['contact_type']}:", parse_mode='Markdown')
        return CONFIRM
    
    if update.message:
        if update.message.contact:
            contact = update.message.contact.phone_number
            contact_type = 'телефон'
        else:
            contact = update.message.text
            contact_type = context.user_data.get('contact_type', 'контакт')
        
        lead = context.user_data['lead']
        lead['contact'] = contact
        lead['contact_type'] = contact_type
        
        lead_id = save_lead_to_db(lead)
        lead_id_display = f"#{lead_id}" if lead_id else f"lead_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        # Отправляем email
        email_sent = send_email_notification_sync(lead, lead_id_display)
        
        admin_message = (
            f"🚀 *НОВАЯ ЗАЯВКА С БОТА ELP!*\n\n"
            f"📋 ID: `{lead_id_display}`\n"
            f"📧 Email: {'✅ Отправлен' if email_sent else '⚠️ Не отправлен'}\n"
            f"👤 Имя: {lead['name']}\n"
            f"👤 Username: @{lead['username']}\n"
            f"📞 Контакт ({lead['contact_type']}): {lead['contact']}\n"
            f"📐 Площадь: {lead['area']}\n"
            f"📅 Срок: {lead['term']}\n"
            f"⏰ Время: {datetime.now().strftime('%d.%m.%Y %H:%M')}\n\n"
            f"User ID: `{lead['user_id']}`"
        )
        
        try:
            await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=admin_message, parse_mode='Markdown')
            logger.info(f"Заявка отправлена админу: {lead_id_display}")
        except Exception as e:
            logger.error(f"Ошибка отправки админу: {e}")
        
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("👨‍💼 Написать директору", callback_data='contact'),
            InlineKeyboardButton("🏠 В главное меню", callback_data='main_menu')
        ]])
        
        await update.message.reply_text(
            text="✅ *Заявка успешно отправлена!*\n\nС вами свяжется **директор по развитию ELP** в ближайшее время.\n\n✉️ Контакты для связи:\n• Email: strategy.elp@gmail.com\n• Telegram: @elp_almaty_bot\n\nРабочие часы: Пн-Пт, 9:00-18:00",
            parse_mode='Markdown', reply_markup=keyboard
        )
        
        context.user_data.clear()
        return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Заявка отменена.", reply_markup=main_menu_keyboard())
    context.user_data.clear()
    return ConversationHandler.END

# ===== КОМАНДЫ АДМИНА =====
async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.effective_user.id) != ADMIN_CHAT_ID:
        await update.message.reply_text("⛔ Доступ запрещён")
        return
    
    stats = get_db_stats()
    stats_text = (
        f"📊 *Статистика бота ELP*\n\n"
        f"• Всего заявок: {stats['total']}\n"
        f"• За сегодня: {stats['today']}\n"
        f"• Новые: {stats['new']}\n"
        f"• В работе: {stats['contacted']}\n\n"
        f"📧 Email: {'✅ Настроен' if EMAIL_PASSWORD else '⚠️ Не настроен'}\n"
        f"🗄️ База данных: {'✅ Активна' if DATABASE_URL else '⚠️ В памяти'}"
    )
    await update.message.reply_text(stats_text, parse_mode='Markdown')

# ===== ОБРАБОТКА ТЕКСТОВЫХ СООБЩЕНИЙ =====
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.lower()
    
    if any(word in text for word in ['привет', 'здравств', 'hello', 'hi']):
        await update.message.reply_text("Привет! Чем могу помочь?", reply_markup=main_menu_keyboard())
    elif any(word in text for word in ['спасибо', 'благодар']):
        await update.message.reply_text("Рад был помочь! 🤝")
    else:
        await update.message.reply_text("Выберите интересующий раздел:", reply_markup=main_menu_keyboard())

# ===== ГЛАВНАЯ ФУНКЦИЯ =====
def main():
    if not TOKEN:
        logger.error("❌ Токен бота не найден! Установите BOT_TOKEN в Render")
        return
    
    init_db()
    
    application = Application.builder().token(TOKEN).build()
    
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
        fallbacks=[CommandHandler('cancel', cancel), CallbackQueryHandler(start, pattern='^cancel$')],
        allow_reentry=True
    )
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("stats", admin_stats))
    application.add_handler(conv_handler)
    application.add_handler(CallbackQueryHandler(handle_menu))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    
    logger.info("🤖 Бот ELP запускается...")
    application.run_polling()

if __name__ == '__main__':
    main()
