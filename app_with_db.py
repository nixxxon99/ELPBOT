import os
import logging
import psycopg2
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes, ConversationHandler

# ===== НАСТРОЙКИ БД =====
DATABASE_URL = os.environ.get('DATABASE_URL')
BROKER_PHONE = os.environ.get('BROKER_PHONE', '+7 XXX XXX-XX-XX')
BROKER_EMAIL = os.environ.get('BROKER_EMAIL', 'broker@elp.kz')
ADMIN_CHAT_ID = os.environ.get('ADMIN_CHAT_ID', '1294415669')

# ===== ФУНКЦИИ БАЗЫ ДАННЫХ =====
def init_db():
    """Инициализация таблиц"""
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
        
        # Таблица активности
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
        logging.info("✅ База данных инициализирована")
    except Exception as e:
        logging.error(f"❌ Ошибка БД: {e}")

def save_lead(lead_data):
    """Сохранение заявки в БД"""
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO leads (user_id, username, name, contact, contact_type, area, term, status)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        ''', (
            lead_data['user_id'],
            lead_data['username'],
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
        
        logging.info(f"✅ Заявка #{lead_id} сохранена в БД")
        return lead_id
    except Exception as e:
        logging.error(f"❌ Ошибка сохранения: {e}")
        return None

def get_stats():
    """Получение статистики"""
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cursor = conn.cursor()
        
        # Общая статистика
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
        logging.error(f"❌ Ошибка статистики: {e}")
        return {'total': 0, 'today': 0, 'new': 0, 'contacted': 0}

# ===== ОСНОВНОЙ КОД БОТА (упрощенный) =====
# [ЗДЕСЬ ВСТАВЬТЕ ВАШ ТЕКУЩИЙ КОД ИЗ app.py, 
#  но замените сохранение заявок на функцию save_lead()]

# Вместо сохранения в leads_db:
# lead_id = save_lead(lead)

# И добавьте новую функцию:
async def admin_dashboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Расширенная статистика для админа"""
    if str(update.effective_user.id) != ADMIN_CHAT_ID:
        return
    
    stats = get_stats()
    
    dashboard_text = (
        "📊 *Панель управления ELP Bot*\n\n"
        f"• Всего заявок: {stats['total']}\n"
        f"• Сегодня: {stats['today']}\n"
        f"• Новые: {stats['new']}\n"
        f"• В работе: {stats['contacted']}\n\n"
        "*Команды:*\n"
        "/stats - эта панель\n"
        "/leads - последние заявки\n"
        "/export - экспорт в CSV"
    )
    
    await update.message.reply_text(dashboard_text, parse_mode='Markdown')

# В main() добавьте:
# application.add_handler(CommandHandler("dashboard", admin_dashboard))

if __name__ == '__main__':
    # Инициализируем БД при запуске
    init_db()
    
    # [ОСТАЛЬНОЙ КОД ЗАПУСКА]
