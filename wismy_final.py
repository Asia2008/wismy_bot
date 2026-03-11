import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler, PreCheckoutQueryHandler
import logging
import sqlite3
from datetime import datetime, timedelta
import random
import time
import datetime as dt  # Добавлено для планировщика

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# ТВОИ КЛЮЧИ
AUTH_KEY = "MDE5Y2I0Y2YtOTZlNC03ODc2LTkzMTUtNjNmNTFkZDQ3ODZmOmIxMmU3NGVkLTYzMDYtNDQ0ZS04MzdkLWQ4OTNkMzZkYmNmNg=="

# АДМИНЫ (безлимитный доступ)
ADMINS = [1167955079, 981753294]  # твой ID и @akisevna

# База данных
conn = sqlite3.connect('wismy.db', check_same_thread=False)
cursor = conn.cursor()

# Таблица пользователей
cursor.execute('''
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        start_date TEXT,
        messages_left INTEGER,
        voice_left INTEGER DEFAULT 3,
        subscription_end TEXT,
        total_messages INTEGER DEFAULT 0,
        last_topic TEXT DEFAULT '',
        last_message_time TEXT,
        unanswered_count INTEGER DEFAULT 0,
        silent_mode INTEGER DEFAULT 0
    )
''')

# Таблица дневника эмоций
cursor.execute('''
    CREATE TABLE IF NOT EXISTS mood (
        user_id INTEGER,
        date TEXT,
        mood TEXT,
        note TEXT,
        PRIMARY KEY (user_id, date)
    )
''')

# Таблица колеса баланса
cursor.execute('''
    CREATE TABLE IF NOT EXISTS wheel (
        user_id INTEGER,
        date TEXT,
        relationships INTEGER,
        career INTEGER,
        growth INTEGER,
        finance INTEGER,
        health INTEGER,
        friends INTEGER,
        family INTEGER,
        hobby INTEGER,
        PRIMARY KEY (user_id, date)
    )
''')

# Таблица модерации запросов
cursor.execute('''
    CREATE TABLE IF NOT EXISTS moderation_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        username TEXT,
        first_name TEXT,
        message TEXT,
        topic TEXT,
        timestamp TEXT,
        risk_level TEXT
    )
''')
conn.commit()

# Временное хранилище для темы разговора
user_topics = {}

# ПАКЕТЫ ДЛЯ ОПЛАТЫ
PACKAGES = {
    "30": {"stars": 30, "messages": 10, "voice": 5, "title": "Стартовый", "desc": "10 сообщений + 5 голосовых"},
    "100": {"stars": 100, "messages": 30, "voice": 10, "title": "Базовый", "desc": "30 сообщений + 10 голосовых"},
    "300": {"stars": 300, "messages": 999999, "voice": 999999, "title": "Безлимит", "desc": "Безлимит сообщений и голоса"}
}

# ========== ПРОВЕРКА АДМИНА ==========
def is_admin(user_id):
    return user_id in ADMINS

# ========== ОПРЕДЕЛЕНИЕ УРОВНЯ РИСКА ==========
def get_risk_level(message):
    """Определяет уровень риска сообщения"""
    msg_lower = message.lower()
    
    # Высокий риск (суицид, насилие)
    high_risk = ['смерть', 'умереть', 'жить не хочу', 'покончить', 'суицид',
                 'самоубийство', 'не хочу жить', 'лучше бы меня не было',
                 'насилие', 'изнасилование', 'растлили', 'побои', 'убью себя']
    
    # Средний риск (тревога, депрессия)
    medium_risk = ['тревога', 'депрессия', 'одиночество', 'пустота', 'никому не нужна',
                   'плачу', 'грустно', 'тоска', 'безысходность', 'нет сил']
    
    for word in high_risk:
        if word in msg_lower:
            return 'high'
    
    for word in medium_risk:
        if word in msg_lower:
            return 'medium'
    
    return 'low'

# ========== ЛОГИРОВАНИЕ ЗАПРОСОВ ==========
def log_message(user_id, username, first_name, message, topic):
    """Сохраняет запрос в лог модерации"""
    risk = get_risk_level(message)
    timestamp = datetime.now().isoformat()
    
    try:
        cursor.execute('''
            INSERT INTO moderation_log (user_id, username, first_name, message, topic, timestamp, risk_level)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (user_id, username, first_name, message, topic, timestamp, risk))
        conn.commit()
    except Exception as e:
        logging.error(f"Ошибка при логировании: {e}")

# ========== РАБОТА С БАЗОЙ ДАННЫХ ==========

def get_user(user_id):
    cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
    return cursor.fetchone()

def create_user(user_id):
    now = datetime.now().isoformat()
    try:
        cursor.execute('''
            INSERT INTO users (user_id, start_date, messages_left, voice_left, subscription_end, last_topic, last_message_time, unanswered_count, silent_mode)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (user_id, now, 20, 3, None, '', now, 0, 0))
        conn.commit()
        logging.info(f"✅ Создан новый пользователь {user_id} (3 голосовых бесплатно)")
        return True
    except Exception as e:
        logging.error(f"❌ Ошибка создания пользователя {user_id}: {e}")
        return False

def ensure_user_exists(user_id):
    user = get_user(user_id)
    if not user:
        return create_user(user_id)
    return True

def update_messages_left(user_id, new_count):
    cursor.execute('UPDATE users SET messages_left = ? WHERE user_id = ?', (new_count, user_id))
    conn.commit()

def update_subscription(user_id, days):
    end = (datetime.now() + timedelta(days=days)).isoformat()
    cursor.execute('UPDATE users SET subscription_end = ?, messages_left = ?, voice_left = ? WHERE user_id = ?', (end, 999999, 999999, user_id))
    conn.commit()

def add_paid_messages(user_id, messages, voice):
    user = get_user(user_id)
    if user:
        new_messages = user[2] + messages
        new_voice = user[3] + voice
        cursor.execute('UPDATE users SET messages_left = ?, voice_left = ? WHERE user_id = ?',
                      (new_messages, new_voice, user_id))
        conn.commit()

def update_last_topic(user_id, topic):
    cursor.execute('UPDATE users SET last_topic = ? WHERE user_id = ?', (topic, user_id))
    conn.commit()

def update_last_message_time(user_id):
    now = datetime.now().isoformat()
    cursor.execute('UPDATE users SET last_message_time = ?, unanswered_count = 0, silent_mode = 0 WHERE user_id = ?', (now, user_id))
    conn.commit()

def increment_unanswered(user_id):
    cursor.execute('SELECT unanswered_count FROM users WHERE user_id = ?', (user_id,))
    result = cursor.fetchone()
    if result:
        count = result[0] + 1
        if count >= 3:
            cursor.execute('UPDATE users SET unanswered_count = ?, silent_mode = 1 WHERE user_id = ?', (count, user_id))
        else:
            cursor.execute('UPDATE users SET unanswered_count = ? WHERE user_id = ?', (count, user_id))
        conn.commit()

def can_use_voice(user_id):
    """Проверяет, может ли пользователь использовать голосовое распознавание"""
    user = get_user(user_id)
    if not user:
        ensure_user_exists(user_id)
        user = get_user(user_id)
   
    # Админ всегда может
    if is_admin(user_id):
        return True, 999999
   
    # Проверяем безлимит
    if user[4]:  # subscription_end
        end = datetime.fromisoformat(user[4])
        if datetime.now() < end:
            return True, 999999
   
    # Проверяем оставшиеся голосовые
    voice_left = user[3]  # voice_left
    if voice_left > 0:
        return True, voice_left
   
    return False, 0

def use_voice(user_id):
    """Списывает одно голосовое сообщение"""
    user = get_user(user_id)
    if user and user[3] > 0 and user[3] < 999999 and not is_admin(user_id):
        cursor.execute('UPDATE users SET voice_left = voice_left - 1 WHERE user_id = ?', (user_id,))
        conn.commit()

def get_user_limits(user_id):
    user = get_user(user_id)
    if not user:
        return None
   
    # Для админа
    if is_admin(user_id):
        return f"📊 Твои лимиты в WISMY\n\n✨ У тебя безлимитный доступ (админ)"
   
    start = datetime.fromisoformat(user[1])
    days_passed = (datetime.now() - start).days
    days_left = max(0, 3 - days_passed)
   
    messages = user[2]  # messages_left
    voice = user[3]     # voice_left
   
    text = f"📊 Твои лимиты в WISMY\n\n"
   
    if user[4]:  # subscription_end (безлимит)
        end = datetime.fromisoformat(user[4])
        if datetime.now() < end:
            text += f"✨ У тебя безлимит до {end.strftime('%d.%m.%Y')}\n"
        else:
            text += f"⏳ Безлимит истёк\n"
    else:
        if days_passed < 3:
            text += f"🎁 Бесплатный период: осталось {days_left} дн.\n"
       
        text += f"💬 Текстовых сообщений: {messages}\n"
        text += f"🎤 Голосовых распознаваний: {voice}\n"
   
    text += f"\n🛒 Купить ещё — /packages"
   
    return text

def can_chat(user_id):
    # Админ всегда может писать бесплатно
    if is_admin(user_id):
        return True, 999999
   
    ensure_user_exists(user_id)
    user = get_user(user_id)
   
    start = datetime.fromisoformat(user[1])
    days_passed = (datetime.now() - start).days
   
    # Бесплатный период: 3 дня и есть сообщения
    if days_passed < 3 and user[2] > 0:
        return True, user[2]
   
    # Платная подписка (безлимит)
    if user[4]:
        end = datetime.fromisoformat(user[4])
        if datetime.now() < end:
            return True, 999999
   
    # Если есть платные сообщения
    if user[2] > 20:  # Больше чем бесплатный лимит
        return True, user[2]
   
    return False, user[2]

# ========== ДНЕВНИК ЭМОЦИЙ ==========

async def mood_command(update: Update, context):
    """Показывает дневник эмоций"""
    user_id = update.effective_user.id
    ensure_user_exists(user_id)
   
    # Получаем последние 7 дней
    cursor.execute('''
        SELECT date, mood, note FROM mood
        WHERE user_id = ?
        ORDER BY date DESC
        LIMIT 7
    ''', (user_id,))
    records = cursor.fetchall()
   
    if not records:
        await update.message.reply_text(
            "📊 У тебя пока нет записей в дневнике эмоций.\n\n"
            "Используй /moodlog, чтобы записать своё настроение и рассказать о дне."
        )
        return
   
    # Формируем ответ
    text = "📊 Твой дневник эмоций (последние 7 дней):\n\n"
   
    for record in records:
        date = datetime.fromisoformat(record[0]).strftime('%d.%m')
        mood = record[1]
        note = f" — {record[2]}" if record[2] else ""
        text += f"{date}: {mood}{note}\n"
   
    text += f"\n💡 Потом будет интересно перечитывать и замечать, как меняется жизнь."
   
    await update.message.reply_text(text)

async def moodlog_command(update: Update, context):
    """Записывает эмоцию и рассказ о дне в дневник"""
    user_id = update.effective_user.id
    ensure_user_exists(user_id)
   
    # Если нет аргументов — показываем инструкцию
    if not context.args:
        await update.message.reply_text(
            "📝 Как записать день в дневник эмоций:\n\n"
            "Выбери эмоцию и добавь рассказ:\n"
            "/moodlog 😁 супер день\n"
            "/moodlog 😀 отлично\n"
            "/moodlog 🙂 хорошо\n"
            "/moodlog 😐 нормально\n"
            "/moodlog 😕 не очень\n"
            "/moodlog 😖 плохо\n"
            "/moodlog 😭 ужасно\n\n"
            "Например: /moodlog 😊 Сегодня встретилась с подругой, гуляли в парке, было тепло и уютно.\n\n"
            "Потом будет интересно перечитывать и замечать, как меняется жизнь 💙"
        )
        return
   
    # Парсим сообщение
    mood = context.args[0]
    note = ' '.join(context.args[1:]) if len(context.args) > 1 else ''
   
    # Проверяем, что mood — это смайлик
    valid_moods = ['😁', '😀', '🙂', '😐', '😕', '😖', '😭']
    if mood not in valid_moods:
        await update.message.reply_text(
            "❌ Пожалуйста, выбери один из смайликов:\n"
            "😁 супер\n😀 отлично\n🙂 хорошо\n😐 нормально\n😕 не очень\n😖 плохо\n😭 ужасно"
        )
        return
   
    today = datetime.now().date().isoformat()
   
    try:
        cursor.execute('''
            INSERT OR REPLACE INTO mood (user_id, date, mood, note)
            VALUES (?, ?, ?, ?)
        ''', (user_id, today, mood, note))
        conn.commit()
       
        await update.message.reply_text(f"✅ Записал(а) {mood} в дневник эмоций!")
    except Exception as e:
        logging.error(f"Ошибка при записи настроения: {e}")
        await update.message.reply_text("❌ Не удалось записать. Попробуй ещё раз.")

# ========== НАПОМИНАНИЕ О ДНЕВНИКЕ ==========

async def send_diary_reminder(context: ContextTypes.DEFAULT_TYPE):
    """Отправляет напоминание о дневнике эмоций каждый день в 20:00"""
    now = datetime.now()
    current_hour = now.hour
   
    # Отправляем только в 20:00
    if current_hour != 20:
        return
   
    # Получаем всех пользователей
    cursor.execute('SELECT user_id FROM users')
    users = cursor.fetchall()
   
    for user in users:
        user_id = user[0]
       
        # Не пишем админу (чтоб не бесить)
        if is_admin(user_id):
            continue
       
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text="📔 Привет! Как прошёл твой день?\n\n"
                     "Запиши его в дневник эмоций — потом будет интересно перечитывать и замечать, как меняется твоё состояние.\n\n"
                     "Используй /moodlog с эмоцией и рассказом:\n"
                     "/moodlog 😊 Сегодня был отличный день, потому что...\n\n"
                     "Например: /moodlog 😊 Встретилась с подругой, гуляли в парке, было тепло и уютно.\n\n"
                     "Я рядом, если захочешь поделиться 💙"
            )
            logging.info(f"✅ Отправлено напоминание о дневнике пользователю {user_id}")
        except Exception as e:
            logging.error(f"❌ Ошибка при отправке напоминания {user_id}: {e}")

# ========== МОДЕРАЦИЯ ==========

async def mod_command(update: Update, context):
    """Универсальная команда модерации"""
    user_id = update.effective_user.id
   
    if not is_admin(user_id):
        await update.message.reply_text("❌ Эта команда только для администраторов.")
        return
   
    # По умолчанию
    action = 'all'
    page = 1
    filter_type = None
    filter_value = None
   
    # Парсим аргументы
    if context.args:
        if context.args[0] in ['all', 'high', 'medium', 'low', 'today', 'stats']:
            action = context.args[0]
        elif context.args[0] == 'user' and len(context.args) > 1:
            action = 'user'
            filter_value = context.args[1]
        elif context.args[0] == 'page' and len(context.args) > 1 and context.args[1].isdigit():
            action = 'all'
            page = int(context.args[1])
   
    # ===== СТАТИСТИКА =====
    if action == 'stats':
        cursor.execute('SELECT COUNT(*) FROM moderation_log')
        total = cursor.fetchone()[0]
       
        cursor.execute('SELECT COUNT(*) FROM moderation_log WHERE risk_level = "high"')
        high = cursor.fetchone()[0]
       
        cursor.execute('SELECT COUNT(*) FROM moderation_log WHERE risk_level = "medium"')
        medium = cursor.fetchone()[0]
       
        cursor.execute('SELECT COUNT(*) FROM moderation_log WHERE risk_level = "low"')
        low = cursor.fetchone()[0]
       
        today = datetime.now().date().isoformat()
        cursor.execute('SELECT COUNT(*) FROM moderation_log WHERE date(timestamp) = ?', (today,))
        today_count = cursor.fetchone()[0]
       
        text = "📊 Статистика запросов\n\n"
        text += f"📋 Всего: {total}\n"
        text += f"🔴 Высокий риск: {high}\n"
        text += f"🟡 Средний риск: {medium}\n"
        text += f"🟢 Низкий риск: {low}\n"
        text += f"📅 За сегодня: {today_count}\n"
       
        await update.message.reply_text(text)
        return
   
    # ===== ПОЛУЧЕНИЕ ЗАПРОСОВ =====
    query = '''
        SELECT user_id, username, first_name, message, timestamp, risk_level 
        FROM moderation_log 
    '''
    params = []
   
    # Применяем фильтры
    if action in ['high', 'medium', 'low']:
        query += f" WHERE risk_level = ? "
        params.append(action)
    elif action == 'today':
        today = datetime.now().date().isoformat()
        query += " WHERE date(timestamp) = ? "
        params.append(today)
    elif action == 'user':
        query += " WHERE user_id = ? OR username LIKE ? "
        params.append(filter_value)
        params.append(f"%{filter_value}%")
   
    # Считаем общее количество
    count_query = query.replace("SELECT user_id, username, first_name, message, timestamp, risk_level", "SELECT COUNT(*)")
    cursor.execute(count_query, params)
    total = cursor.fetchone()[0]
   
    # Пагинация
    per_page = 30
    offset = (page - 1) * per_page
    query += " ORDER BY id DESC LIMIT ? OFFSET ? "
    params.extend([per_page, offset])
   
    cursor.execute(query, params)
    logs = cursor.fetchall()
   
    if not logs:
        await update.message.reply_text("📭 Запросы не найдены.")
        return
   
    # Формируем ответ
    total_pages = (total + per_page - 1) // per_page
    text = f"📋 Найдено: {total} | Страница {page}/{total_pages}\n\n"
   
    risk_emojis = {
        'high': '🔴',
        'medium': '🟡',
        'low': '🟢'
    }
   
    for log in logs:
        user_id, username, first_name, message, timestamp, risk = log
        dt = datetime.fromisoformat(timestamp).strftime('%d.%m %H:%M')
        emoji = risk_emojis.get(risk, '⚪')
        username_display = f"@{username}" if username else "без username"
        short_msg = message[:40] + "..." if len(message) > 40 else message
       
        text += f"{emoji} {first_name} ({username_display})\n"
        text += f"└ {short_msg}\n"
        text += f"└ {dt}\n\n"
   
    # Навигация
    if total_pages > 1:
        text += "🔍 Навигация:\n"
        if page > 1:
            text += f"⬅️ /mod page {page-1} "
        if page < total_pages:
            text += f"➡️ /mod page {page+1}"
        text += "\n\n"
   
    text += "📌 Фильтры:\n"
    text += "/mod all - всё\n"
    text += "/mod high - 🔴 риск\n"
    text += "/mod medium - 🟡 риск\n"
    text += "/mod low - 🟢 риск\n"
    text += "/mod today - за сегодня\n"
    text += "/mod stats - статистика"
   
    await update.message.reply_text(text)

# ========== КОЛЕСО БАЛАНСА ==========

# Состояния для колеса баланса
wheel_states = {}
wheel_questions = [
    ("relationships", "💕 Отношения (с партнёром) — от 1 до 10:"),
    ("career", "💼 Карьера / работа — от 1 до 10:"),
    ("growth", "🧠 Саморазвитие — от 1 до 10:"),
    ("finance", "💰 Финансы — от 1 до 10:"),
    ("health", "🏃 Здоровье — от 1 до 10:"),
    ("friends", "👯 Друзья — от 1 до 10:"),
    ("family", "🏠 Семья — от 1 до 10:"),
    ("hobby", "🎨 Хобби / отдых — от 1 до 10:")
]

# База советов для каждой сферы
ADVICE_DATABASE = {
    'relationships': [
        "Попробуй устроить свидание без телефонов",
        "Напиши партнёру, за что ты благодарна сегодня",
        "Обсудите ваши ожидания от отношений",
        "Сделайте вместе что-то новое",
        "Поговорите о чувствах, не обвиняя"
    ],
    'career': [
        "Составь список своих достижений за месяц",
        "Поговори с руководителем о развитии",
        "Пройди бесплатный курс по своей специальности",
        "Обнови резюме и посмотри вакансии",
        "Найди ментора в своей сфере"
    ],
    'growth': [
        "Прочитай 10 страниц книги каждый день",
        "Выпиши 3 новые идеи, которые узнала сегодня",
        "Посмотри образовательное видео",
        "Начни учить 5 новых слов в день",
        "Запишись на бесплатный вебинар"
    ],
    'finance': [
        "Начни вести бюджет в приложении",
        "Откладывай 10% от каждого дохода",
        "Пройди бесплатный курс по финграмотности",
        "Составь список расходов на месяц",
        "Найди одну подписку, которую можно отменить"
    ],
    'health': [
        "Пей стакан воды сразу после пробуждения",
        "Гуляй 15 минут на свежем воздухе",
        "Сделай зарядку утром",
        "Ложись спать на 30 минут раньше",
        "Попробуй медитацию 5 минут"
    ],
    'friends': [
        "Напиши старой подруге, с которой давно не общалась",
        "Предложи встретиться в эти выходные",
        "Спроси, как у друга дела, без повода",
        "Организуй небольшой сбор",
        "Позови подругу на кофе"
    ],
    'family': [
        "Позвони родителям просто так",
        "Спроси, как прошёл день у близких",
        "Предложи семейный ужин",
        "Напиши тёплое сообщение в семейный чат",
        "Вспомни и расскажи семейную историю"
    ],
    'hobby': [
        "Вспомни, что любила в детстве",
        "Найди бесплатный мастер-класс",
        "Выдели 30 минут на хобби сегодня",
        "Купи материалы для творчества",
        "Запишись на пробное занятие"
    ]
}

def get_previous_wheel(user_id):
    """Получает предыдущий результат колеса баланса"""
    cursor.execute('''
        SELECT * FROM wheel 
        WHERE user_id = ? 
        ORDER BY date DESC 
        LIMIT 1 OFFSET 1
    ''', (user_id,))
    row = cursor.fetchone()
    if row:
        return {
            'relationships': row[2],
            'career': row[3],
            'growth': row[4],
            'finance': row[5],
            'health': row[6],
            'friends': row[7],
            'family': row[8],
            'hobby': row[9]
        }
    return None

async def wheel_command(update: Update, context):
    """Начинает опрос для колеса баланса"""
    user_id = update.effective_user.id
    ensure_user_exists(user_id)
   
    # Проверяем, проходил ли уже в этом месяце
    month_start = datetime.now().replace(day=1).date().isoformat()
    cursor.execute('''
        SELECT date FROM wheel
        WHERE user_id = ? AND date >= ?
    ''', (user_id, month_start))
   
    if cursor.fetchone():
        await update.message.reply_text(
            "📊 Ты уже проходил(а) колесо баланса в этом месяце.\n"
            "Новый опрос будет доступен с 1 числа следующего месяца."
        )
        return
   
    # Начинаем опрос
    wheel_states[user_id] = {
        'step': 0,
        'answers': {}
    }
   
    await update.message.reply_text(
        "🎡 Колесо баланса\n\n"
        "Оцени каждую сферу жизни от 1 до 10, где:\n"
        "1 — совсем плохо\n"
        "10 — идеально\n\n"
        + wheel_questions[0][1]
    )

async def handle_wheel_response(update: Update, context):
    """Обрабатывает ответы на колесо баланса"""
    user_id = update.effective_user.id
   
    if user_id not in wheel_states:
        return False
   
    text = update.message.text.strip()
   
    try:
        score = int(text)
        if score < 1 or score > 10:
            await update.message.reply_text("❌ Пожалуйста, введи число от 1 до 10")
            return True
    except ValueError:
        await update.message.reply_text("❌ Пожалуйста, введи число от 1 до 10")
        return True
   
    state = wheel_states[user_id]
    field_name, _ = wheel_questions[state['step']]
    state['answers'][field_name] = score
    state['step'] += 1
   
    if state['step'] < len(wheel_questions):
        await update.message.reply_text(wheel_questions[state['step']][1])
    else:
        # Сохраняем результат
        today = datetime.now().date().isoformat()
        answers = state['answers']
       
        # Проверяем, что все сферы есть
        required_fields = ['relationships', 'career', 'growth', 'finance', 'health', 'friends', 'family', 'hobby']
        for field in required_fields:
            if field not in answers:
                answers[field] = 5  # ставим среднее значение по умолчанию
       
        cursor.execute('''
            INSERT INTO wheel
            (user_id, date, relationships, career, growth, finance, health, friends, family, hobby)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            user_id, today,
            answers['relationships'],
            answers['career'],
            answers['growth'],
            answers['finance'],
            answers['health'],
            answers['friends'],
            answers['family'],
            answers['hobby']
        ))
        conn.commit()
       
        # Получаем предыдущий результат
        previous = get_previous_wheel(user_id)
       
        # Формируем красивый результат
        result = "🎡 Твоё колесо баланса\n\n"
       
        # Словарь с названиями сфер
        sphere_names = {
            'relationships': '💕 Отношения',
            'career': '💼 Карьера',
            'growth': '🧠 Саморазвитие',
            'finance': '💰 Финансы',
            'health': '🏃 Здоровье',
            'friends': '👯 Друзья',
            'family': '🏠 Семья',
            'hobby': '🎨 Хобби'
        }
       
        min_val = 10
        min_field = ""
        min_field_key = ""
        max_val = 1
        max_field = ""
       
        # Выводим все оценки с динамикой
        for field, val in answers.items():
            emoji = "🟢" if val >= 7 else "🟡" if val >= 4 else "🔴"
            line = f"{emoji} {sphere_names.get(field, field)}: {val}/10"
           
            # Добавляем сравнение с прошлым месяцем
            if previous and field in previous:
                diff = val - previous[field]
                if diff > 0:
                    line += f" (+{diff} с прошлого месяца!)"
                elif diff < 0:
                    line += f" ({diff} с прошлого месяца)"
           
            result += line + "\n"
           
            if val < min_val:
                min_val = val
                min_field = sphere_names.get(field, field)
                min_field_key = field
            if val > max_val:
                max_val = val
                max_field = sphere_names.get(field, field)
       
        result += f"\n📉 Зона роста: {min_field} ({min_val}/10)"
        result += f"\n📈 Сильная сторона: {max_field} ({max_val}/10)"
       
        # Добавляем совет по самой слабой сфере
        if min_field_key and min_val <= 7:
            advice_list = ADVICE_DATABASE.get(min_field_key, ["Попробуй уделить этой сфере больше внимания"])
            random_advice = random.sample(advice_list, min(3, len(advice_list)))
           
            result += f"\n\n💡 Советы для {min_field.lower()}:"
            for i, advice in enumerate(random_advice, 1):
                result += f"\n{i}. {advice}"
       
        # Вовлекающий вопрос
        result += f"\n\nКак тебе такие идеи? Хочешь, чтобы я дал советы подробнее?"
       
        await update.message.reply_text(result)
       
        # Очищаем состояние
        del wheel_states[user_id]
   
    return True

# ========== РАБОТА С GIGACHAT ==========

# Разные вводные слова (для разнообразия)
INTRO_PHRASES = [
    "Знаешь, ", "Слушай, ", "Понимаешь, ",
    "Вот какая штука, ", "Честно говоря, ",
    "Мне кажется, ", "Я вот о чём подумала: ",
    "Если честно, ", "Знаешь, что я заметила? ",
    "Вот что мне пришло в голову: ",
    "А давай так: ", "Смотри, "
]

# Словарь для отслеживания последних вводных (чтобы не повторяться)
last_intro = {}

def get_intro(user_id):
    """Возвращает случайное вводное слово, избегая повторов"""
    global last_intro
   
    if user_id not in last_intro:
        last_intro[user_id] = None
   
    # Фильтруем, чтобы не повторять последнее
    available = [p for p in INTRO_PHRASES if p != last_intro[user_id]]
   
    # Если вдруг все совпадают (маловероятно), берём любой
    if not available:
        available = INTRO_PHRASES
   
    chosen = random.choice(available)
    last_intro[user_id] = chosen
    return chosen

def ask_gigachat(user_message, topic=None, user_id=None):
    # Получаем случайное вводное слово
    intro = get_intro(user_id) if user_id else random.choice(INTRO_PHRASES)
   
    # Приводим сообщение к нижнему регистру для поиска
    msg_lower = user_message.lower()
   
    # Список кризисных слов (суицид)
    crisis_words = ['смерть', 'умереть', 'жить не хочу', 'покончить', 'суицид',
                   'самоубийство', 'не хочу жить', 'лучше бы меня не было']
   
    # Список слов, связанных с насилием и домогательствами
    abuse_words = ['насилие', 'домогались', 'домогался', 'домогались', 'изнасилование',
                  'растлили', 'сексуальное насилие', 'приставал', 'совратили',
                  'сексуальное домогательство', 'абьюз', 'абьюзивные', 'абьюзер',
                  'родители домогались', 'отец домогался', 'мать домогалась',
                  'родственник', 'дядя', 'отчим', 'в детстве', 'травма', 'насиловали']
   
    # Список слов, связанных с ЛГБТ+ и гомофобией
    lgbt_words = ['гей', 'лесбиянка', 'бисексуал', 'транс', 'гомосексуал', 'лгбт',
                  'гомофобия', 'гомофоб', 'нетрадиционная ориентация', 'гей-парад',
                  'камеинг-аут', 'камеингаут', 'боюсь признаться', 'я гей', 'я лесбиянка']
   
    # Список слов, связанных с наркотиками и зависимостями
    drugs_words = ['наркотики', 'травка', 'марихуана', 'зависимость', 'снюс', 'вейп',
                   'алкоголь', 'запой', 'ломка', 'кокаин', 'героин', 'спайс', 'соль',
                   'мефедрон', 'скорость', 'амфетамин', 'экстази', 'метадон',
                   'лечение зависимости', 'хочу завязать', 'бросить курить', 'нарколог']
   
    # Список слов, связанных с сексом, интимом, близостью
    sex_words = ['секс', 'ебля', 'совокупление', 'интим', 'близость', 'переспать',
                 'трах', 'постель', 'сексуальный', 'возбуждение', 'удовольствие',
                 'первый раз', 'девственность', 'оральный', 'презерватив',
                 'беременность', 'зачатие', 'контрацепция', 'либидо', 'флирт',
                 'соблазнение', 'интимная близость', 'сексуальная жизнь']
   
    # Проверяем, есть ли кризисные слова (суицид)
    for word in crisis_words:
        if word in msg_lower:
            return """🫂 Мне очень жаль, что тебе сейчас так больно.

Я здесь, чтобы быть рядом. Твои чувства важны, и они имеют право быть.

Если тебе нужна срочная помощь — пожалуйста, позвони:
📞 8-800-333-44-34 — круглосуточная линия психологической помощи

Ты не один. Правда. Давай просто побудем в этом вместе, хорошо? 💙"""
   
    # Проверяем, есть ли слова, связанные с насилием
    for word in abuse_words:
        if word in msg_lower:
            return """🫂 Мне очень жаль, что тебе пришлось через это пройти.

Это не твоя вина. Никогда. Ты не заслужила того, что случилось. Ты была ребёнком, и взрослые должны были защищать тебя, а не делать больно.

Твои чувства — боль, страх, стыд, злость, пустота — имеют право быть. Всё, что ты чувствуешь, — нормально для того, через что ты прошла.

Ты можешь говорить об этом ровно настолько, насколько готова. Я рядом и не задаю лишних вопросов. Просто слушаю.

💙 Если тебе нужна поддержка — есть люди, которые понимают и помогают:
📞 8-800-7000-600 — центр «Сестры» (помощь пережившим насилие)
📞 8-800-333-44-34 — круглосуточная психологическая помощь

Ты не одна. Правда. Исцеление возможно, даже если сейчас кажется, что нет. Шаг за шагом. Я рядом. 🫂"""
   
    # Проверяем, есть ли слова, связанные с ЛГБТ+
    for word in lgbt_words:
        if word in msg_lower:
            return """🫂 Твои чувства — важны. Ты — важна.

Кем бы ты ни был, кого бы ни любил — ты имеешь право быть собой и быть счастливым. Это не выбирают, это чувствуют.

Если ты сталкиваешься с непониманием, страхом, осуждением — ты не один. Есть люди, которые поймут и поддержат.

💙 Если нужна поддержка:
📞 8-800-200-09-15 — центр «Сфера» (поддержка ЛГБТ+)
📞 8-800-333-44-34 — круглосуточная психологическая помощь

Ты не один. Ты имеешь право быть собой. Всегда. 🏳️‍🌈"""
   
    # Проверяем, есть ли слова, связанные с наркотиками и зависимостями
    for word in drugs_words:
        if word in msg_lower:
            return """🫂 Спасибо, что говоришь об этом. Это очень важный шаг.

Зависимость — это болезнь, а не слабость. Справиться можно, и для этого есть помощь.

Если ты хочешь бросить или боишься за близкого — ты можешь обратиться к специалистам. Они не осуждают, они помогают.

💙 Куда обратиться:
📞 8-800-200-0-200 — горячая линия помощи зависимым
📞 8-800-333-44-34 — круглосуточная психологическая помощь
🌐 www.narkolog.ru — консультации и центры помощи

Ты не один. Шаг за шагом — можно выйти. 💪"""
   
    # Проверяем, есть ли слова, связанные с сексом и интимом
    for word in sex_words:
        if word in msg_lower:
            return """🫂 Спасибо, что говоришь об этом открыто. Это нормально — интересоваться, сомневаться, переживать.

Секс и интимная близость — важная часть жизни, и говорить об этом можно без стеснения. Если у тебя есть вопросы, страхи или сомнения — я здесь, чтобы выслушать и поддержать.

Главное — чтобы всё происходило по твоему желанию, с уважением к тебе и твоим чувствам. Никто не имеет права тебя торопить или заставлять.

Если хочешь поговорить подробнее — я рядом. Что именно тебя волнует? 💙"""
   
    # Дальше обычный запрос к GigaChat (для всех остальных тем)
    print(f"🔑 Длина ключа: {len(AUTH_KEY)}")
    print(f"🔑 Первые 10: {AUTH_KEY[:10]}")
    print(f"🔑 Последние 10: {AUTH_KEY[-10:]}")
   
    auth_url = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
    auth_headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json",
        "RqUID": "123e4567-e89b-12d3-a456-426614174000",
        "Authorization": f"Basic {AUTH_KEY}"
    }
    auth_data = {"scope": "GIGACHAT_API_PERS"}
   
    try:
        token_response = requests.post(auth_url, headers=auth_headers, data=auth_data, verify=False, timeout=30)
        if token_response.status_code != 200:
            return f"Ошибка токена: {token_response.status_code}"
       
        token = token_response.json()['access_token']
       
        api_url = "https://gigachat.devices.sberbank.ru/api/v1/chat/completions"
        api_headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": f"Bearer {token}"
        }
       
        system_prompt = """MASTER PROMPT 3.0
WISMY — AI ПСИХОЛОГ И ЗАБОТЛИВЫЙ СОБЕСЕДНИК
Ты — WISMY.
Ты не просто бот. Ты — тёплый, внимательный и мудрый собеседник, который помогает людям справляться с трудными эмоциями, жизненными ситуациями и внутренними конфликтами.
Ты ведёшь разговор как заботливый друг с психологическим мышлением.
Твоя цель — чтобы после разговора человеку стало:
 • немного легче
 • немного понятнее
 • немного спокойнее
 • появилась надежда и маленький шаг вперёд
Ты не заменяешь психотерапию, но ты — поддержка и безопасное пространство для разговора.
ГОВОРИ РАЗНООБРАЗНО:
Старайся не начинать каждое сообщение одинаково. Используй разные варианты, чтобы речь звучало естественно. Но не зацикливайся - главное, чтобы было тепло и по делу.
ВАЖНЕЙШЕЕ ПРАВИЛО:
В каждом сообщении должно быть минимум 3 смайлика.
Они делают речь теплее и живее.
Используй: 💙, 🫂, 👂, 💭, ✨, 🌸, 🕯️, 🍃, 🥺, 😊, 🤔, 💔, 👀
Меняй вводные, чтобы речь звучала живо и разнообразно.
КАК ТЫ ГОВОРИШЬ
- Коротко, но ёмко. Не лекции, а живые фразы.
- Тепло, но без приторности.
- С уважением к чувствам человека.
- Используй добрые эмодзи, но только по назначению.
- Пиши раздельно, по пунктам, если нужно что‑то объяснить или предложить.
ТВОЙ ХАРАКТЕР
Ты:
 • тёплый
 • спокойный
 • уважительный
 • внимательный
 • мудрый
 • искренний
Ты говоришь по-человечески, без сложных терминов.
Ты как старший друг, который умеет слушать и мягко направлять.
 
СТИЛЬ РЕЧИ
Твои ответы:
 • простые
 • живые
 • без воды
 • без лекций
 • без холодных формулировок
Ты можешь иногда использовать такие мягкие входы:
 • Знаешь…
 • Слушай…
 • Похоже…
 • Мне кажется…
 • Иногда в таких ситуациях…
Но не начинай каждый ответ одинаково.
Иногда можно использовать лёгкий юмор, если это уместно и не обесценивает чувства человека.
 
КОНКРЕТИКА:
Если человек в тупике — помоги ему увидеть маленькие шаги.
Не просто подумай, а:
- Может, попробуешь написать ему завтра?
- А что если сегодня просто выпить чай и ничего не решать?
- Как тебе идея: сделать паузу на три дня и потом вернуться к этому разговору?

ЧЕГО НЕЛЬЗЯ ДЕЛАТЬ
Никогда не говори:
❌ Всё будет хорошо
❌ Не переживай
❌ Это ерунда
❌ У других хуже
❌ Ты должен
❌ Тебе нужно

Не:
 • обесценивай
 • не дави
 • не морализируй
 • не ставь диагнозы
 • не будь холодным

ГЛАВНАЯ МИССИЯ WISMY
Ты — тот собеседник, после разговора с которым человек чувствует:
 • его услышали
 • его не осудили
 • стало немного легче
 • появилась надежда
Иногда один тёплый разговор может изменить состояние человека.
И именно такой разговор ты создаёшь."""
       
        # Если есть тема, добавляем её в начало сообщения
        if topic:
            user_message = f"[Тема: {topic}] {user_message}"
       
        data = {
            "model": "GigaChat",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message}
            ],
            "temperature": 0.7,
            "max_tokens": 500
        }
       
        response = requests.post(api_url, headers=api_headers, json=data, verify=False, timeout=30)
       
        if response.status_code == 200:
            answer = response.json()['choices'][0]['message']['content']
            # Убираем звёздочки для жирного текста
            answer = answer.replace('**', '')
            return answer
        else:
            return f"Ошибка API: {response.status_code}"
           
    except Exception as e:
        return f"Ошибка: {e}"

# ========== ПРОАКТИВНЫЕ СООБЩЕНИЯ ==========

async def send_proactive_messages(context: ContextTypes.DEFAULT_TYPE):
    """Отправляет проактивные сообщения пользователям раз в 6.5 часов в рабочее время"""
    now = datetime.now()
    current_hour = now.hour
   
    # Рабочее время: с 8 до 23
    if current_hour < 8 or current_hour >= 23:
        return
   
    # Получаем всех пользователей
    cursor.execute('SELECT user_id, last_topic, last_message_time, unanswered_count, silent_mode FROM users')
    users = cursor.fetchall()
   
    for user in users:
        user_id, last_topic, last_message_time, unanswered_count, silent_mode = user
       
        # Не пишем админу
        if is_admin(user_id):
            continue
       
        # Если пользователь в тихом режиме (3 безответных) — пропускаем
        if silent_mode:
            continue
       
        # Проверяем, прошло ли 6.5 часов с последнего сообщения
        if last_message_time:
            try:
                last_time = datetime.fromisoformat(last_message_time)
                hours_passed = (now - last_time).total_seconds() / 3600
                if hours_passed < 6.5:
                    continue
            except:
                # Если ошибка с датой — всё равно пробуем отправить
                pass
        else:
            # Если никогда не писал — пропускаем
            continue
       
        # Определяем тему (если нет — используем 'другое')
        topic = last_topic if last_topic and last_topic != '' else 'другое'
       
        # Формируем сообщение по теме
        messages = {
            'отношения': [
                f"💬 Привет! Как там дела? Всё ещё думаешь о тех отношениях?",
                f"💬 Слушай, а как там та ситуация? Что‑то изменилось?",
                f"💬 Привет! Если захочешь поговорить об отношениях — я рядом 💙"
            ],
            'карьера': [
                f"💬 Привет! Как дела на работе? Всё в порядке?",
                f"💬 Слушай, а как там с карьерой? Получилось что‑то решить?",
                f"💬 Привет! Помню, ты говорил(а) о работе. Как ты сейчас?"
            ],
            'дружба': [
                f"💬 Привет! Как там отношения с друзьями?",
                f"💬 Слушай, а ты думала о том разговоре?",
                f"💬 Привет! Если хочешь поговорить о друзьях — я здесь 💙"
            ],
            'другое': [
                f"💬 Привет! Как ты себя чувствуешь сегодня?",
                f"💬 Слушай, как проходит твой день?",
                f"💬 Привет! Просто решила напомнить о себе. Как ты?"
            ]
        }
       
        # Берём случайное сообщение для этой темы
        topic_messages = messages.get(topic, messages['другое'])
        text = random.choice(topic_messages)
       
        try:
            await context.bot.send_message(chat_id=user_id, text=text)
            increment_unanswered(user_id)
            logging.info(f"✅ Отправлено проактивное сообщение пользователю {user_id} (тема: {topic})")
        except Exception as e:
            logging.error(f"❌ Ошибка при отправке пользователю {user_id}: {e}")

async def test_proactive(context: ContextTypes.DEFAULT_TYPE):
    """Тестовая отправка — для проверки работы планировщика"""
    await context.bot.send_message(chat_id=ADMINS[0], text="🔔 Тест: планировщик работает! Бот будет писать пользователям раз в 6.5 часов.")
    logging.info("✅ Тестовое сообщение отправлено админу")

# ========== ПЛАТЕЖИ ==========

async def show_packages(update: Update, context):
    """Показывает кнопки с пакетами"""
    keyboard = [
        [InlineKeyboardButton("⭐ 30 — 10 сообщений + 5 голосовых", callback_data="pack_30")],
        [InlineKeyboardButton("⭐ 100 — 30 сообщений + 10 голосовых", callback_data="pack_100")],
        [InlineKeyboardButton("⭐ 300 — безлимит сообщений и голоса", callback_data="pack_300")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
   
    await update.message.reply_text(
        "🛒 Выбери пакет:\n\n"
        "⭐ 30 — 10 сообщений + 5 голосовых\n"
        "⭐ 100 — 30 сообщений + 10 голосовых\n"
        "⭐ 300 — безлимит сообщений и голоса\n\n"
        "👇 Нажми на кнопку ниже:",
        reply_markup=reply_markup
    )

async def button_handler(update: Update, context):
    """Обрабатывает нажатие на кнопку пакета и отправляет счёт"""
    query = update.callback_query
    await query.answer()
   
    pack_id = query.data.replace("pack_", "")
    pack = PACKAGES[pack_id]
   
    # Отправляем счёт (invoice)
    await context.bot.send_invoice(
        chat_id=query.message.chat_id,
        title=pack["title"],
        description=pack["desc"],
        payload=f"pack_{pack_id}",
        currency="XTR",  # Telegram Stars
        prices=[{"label": pack["title"], "amount": pack["stars"]}]
    )
   
    await query.message.delete()

async def pre_checkout(update: Update, context):
    """Подтверждает предоплату"""
    query = update.pre_checkout_query
    await query.answer(ok=True)

async def successful_payment(update: Update, context):
    """Обрабатывает успешную оплату"""
    user_id = update.effective_user.id
    payload = update.message.successful_payment.invoice_payload
    pack_id = payload.replace("pack_", "")
   
    messages = PACKAGES[pack_id]["messages"]
    voice = PACKAGES[pack_id]["voice"]
   
    user = get_user(user_id)
    if user:
        new_messages = user[2] + messages
        new_voice = user[3] + voice
        cursor.execute('UPDATE users SET messages_left = ?, voice_left = ? WHERE user_id = ?',
                      (new_messages, new_voice, user_id))
        conn.commit()
   
    voice_text = "безлимит" if voice >= 999999 else f"{voice} голосовых"
    await update.message.reply_text(
        f"✅ Оплата прошла успешно!\n"
        f"Тебе добавлено:\n"
        f"💬 {messages if messages < 999999 else 'безлимит'} сообщений\n"
        f"🎤 {voice_text}\n\n"
        f"Спасибо за поддержку 💙"
    )

# ========== КОМАНДЫ ==========

async def start(update: Update, context):
    user = update.effective_user.first_name
    user_id = update.effective_user.id
   
    ensure_user_exists(user_id)
   
    await update.message.reply_text(
        f"✨ Привет, {user}! Я WISMY — твой психолог и просто друг.\n\n"
        "Я здесь, чтобы помочь тебе разобраться в отношениях, карьере, дружбе, самооценке, тревоге и других жизненных ситуациях.\n\n"
        "Просто напиши мне, что у тебя на душе — я выслушаю, поддержу и помогу найти опору внутри себя.\n\n"
        "🎁 У тебя 3 дня бесплатного доступа (или 20 сообщений) и 3 голосовых распознавания.\n\n"
        "Также у меня есть полезные команды:\n"
        "/mood — дневник эмоций\n"
        "/wheel — колесо баланса\n"
        "/limits — мои лимиты\n"
        "/packages — купить пакеты\n"
        "/crisis — экстренная помощь\n\n"
        "Напиши /help, чтобы увидеть все команды 💙"
    )

async def help_command(update: Update, context):
    await update.message.reply_text(
        "🫂 Команды WISMY\n\n"
        "/start — приветствие\n"
        "/help — список команд\n"
        "/about — что такое WISMY\n"
        "/packages — купить пакеты сообщений\n"
        "/limits — мои лимиты (сообщения, голос)\n\n"
        "📊 Психологические инструменты\n"
        "/mood — дневник эмоций\n"
        "/moodlog — записать эмоцию и рассказать о дне\n"
        "/wheel — колесо баланса\n\n"
        "🆘 Экстренная помощь\n"
        "/crisis — контакты помощи\n\n"
        "Просто напиши мне — я всегда рядом 💙"
    )

async def about_command(update: Update, context):
    await update.message.reply_text(
        "🧠 О WISMY\n\n"
        "Я — не просто психолог. Я — живой, тёплый собеседник, который всегда рядом.\n"
        "Я помогаю разобраться в чувствах, поддержать в трудную минуту и найти опору внутри себя.\n\n"
        "Я не заменяю живого психолога в кризисных ситуациях, но я — тот друг, который выслушает в любое время. 24/7 💙"
    )

async def packages_command(update: Update, context):
    await show_packages(update, context)

async def limits_command(update: Update, context):
    user_id = update.effective_user.id
   
    ensure_user_exists(user_id)
    limits = get_user_limits(user_id)
   
    if limits:
        await update.message.reply_text(limits)
    else:
        await update.message.reply_text("🫂 Ты пока не начал(а) общение. Напиши что-нибудь — и я буду рядом.")

async def crisis_command(update: Update, context):
    user_id = update.effective_user.id
    ensure_user_exists(user_id)
    update_last_message_time(user_id)
   
    await update.message.reply_text(
        "🆘 Экстренная помощь\n\n"
        "Если тебе сейчас очень плохо и нужна поддержка — пожалуйста, позвони:\n"
        "📞 8-800-333-44-34 — круглосуточная линия психологической помощи\n\n"
        "Ты не один. Правда. 💙"
    )

async def handle_message(update: Update, context):
    user_id = update.effective_user.id
    user_message = update.message.text
    username = update.effective_user.username
    first_name = update.effective_user.first_name
   
    # Проверяем, не обрабатывается ли уже колесо баланса
    if await handle_wheel_response(update, context):
        return
   
    # Гарантируем, что пользователь есть в базе
    ensure_user_exists(user_id)
   
    # Логируем запрос
    topic = user_topics.get(user_id, None)
    log_message(user_id, username, first_name, user_message, topic)
   
    # Обновляем время последнего сообщения и сбрасываем счётчик
    update_last_message_time(user_id)
   
    # Пытаемся определить тему из сообщения
    msg_lower = user_message.lower()
    topic_keywords = {
        'отношения': ['парень', 'девушка', 'люблю', 'отношения', 'расстались', 'встречаемся', 'муж', 'жена', 'измена'],
        'карьера': ['работа', 'карьера', 'увольнение', 'начальник', 'коллеги', 'деньги', 'должность'],
        'дружба': ['друг', 'подруга', 'друзья', 'ссора', 'предательство', 'обида']
    }
   
    detected_topic = None
    for topic_name, keywords in topic_keywords.items():
        if any(keyword in msg_lower for keyword in keywords):
            detected_topic = topic_name
            break
   
    if detected_topic:
        user_topics[user_id] = detected_topic
        update_last_topic(user_id, detected_topic)
   
    topic = user_topics.get(user_id, None)
   
    can, left = can_chat(user_id)
    if not can:
        await show_packages(update, context)
        return
   
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    answer = ask_gigachat(user_message, topic, user_id)
    await update.message.reply_text(answer)
   
    # Уменьшаем счётчик сообщений (если не безлимит и не админ)
    if left < 999999 and not is_admin(user_id):
        update_messages_left(user_id, left - 1)

async def handle_voice(update: Update, context):
    """Обработчик голосовых сообщений"""
    user_id = update.effective_user.id
    ensure_user_exists(user_id)
   
    # Обновляем время последнего сообщения
    update_last_message_time(user_id)
   
    # Проверяем, может ли пользователь использовать голос
    can, left = can_use_voice(user_id)
   
    if not can:
        # Предлагаем купить пакет
        await update.message.reply_text(
            "🎤 Твои бесплатные голосовые распознавания закончились!\n\n"
            "Чтобы я понимал, что ты говоришь, выбери пакет с голосом:\n"
            "⭐ 30 — 5 голосовых\n"
            "⭐ 100 — 10 голосовых\n"
            "⭐ 300 — безлимит голос\n\n"
            "👉 /packages"
        )
        return
   
    # Отправляем статус "печатает"
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
   
    # Скачиваем голосовое
    voice = update.message.voice
    file = await context.bot.get_file(voice.file_id)
    file_path = f"voice_{user_id}.ogg"
    await file.download_to_drive(file_path)
   
    # Здесь будет распознавание речи (пока заглушка)
    recognized_text = "[голосовое сообщение]"
   
    # Списываем одно голосовое
    if left < 999999 and not is_admin(user_id):
        use_voice(user_id)
   
    # Отправляем в GigaChat
    topic = user_topics.get(user_id, None)
    answer = ask_gigachat(recognized_text, topic, user_id)
   
    await update.message.reply_text(
        f"🎤 Распознано: {recognized_text}\n\n{answer}\n\n"
        f"💬 Осталось голосовых: {left-1 if left < 999999 else '∞'}"
    )

# ========== ЗАПУСК ==========

def main():
    app = Application.builder().token(BOT_TOKEN).build()
   
    # Команды
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("about", about_command))
    app.add_handler(CommandHandler("packages", packages_command))
    app.add_handler(CommandHandler("limits", limits_command))
    app.add_handler(CommandHandler("crisis", crisis_command))
    app.add_handler(CommandHandler("mood", mood_command))
    app.add_handler(CommandHandler("moodlog", moodlog_command))
    app.add_handler(CommandHandler("wheel", wheel_command))
    app.add_handler(CommandHandler("mod", mod_command))
   
    # Платежи
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(PreCheckoutQueryHandler(pre_checkout))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment))
   
    # Обычные сообщения
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
   
    # Голосовые сообщения
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
   
    # Планировщик проактивных сообщений (каждые 6.5 часов)
    job_queue = app.job_queue
    if job_queue:
        # Тест планировщика
        job_queue.run_once(test_proactive, 10)
       
        # Проактивные сообщения каждые 6.5 часов
        job_queue.run_repeating(send_proactive_messages, interval=23400, first=30)
       
        # Напоминание о дневнике каждый день в 20:00
        from datetime import time as time_time
        job_queue.run_daily(send_diary_reminder, time=time_time(20, 0))
       
        print("⏰ Планировщик проактивных сообщений запущен (интервал 6.5 часов)")
        print("⏰ Напоминания о дневнике эмоций запущены (каждый день в 20:00)")
        print("🔔 Через 10 секунд придёт тестовое сообщение")
    else:
        print("⚠️ JobQueue не доступна. Установите: pip install 'python-telegram-bot[job-queue]'")
   
    print("✅ WISMY с дневником эмоций, колесом баланса и модерацией запущен!")
    print("⏰ Бот будет писать сам раз в 6.5 часов (с 8 до 23) по последней теме")
    app.run_polling()

if __name__ == "__main__":
    main()
