import sqlite3
import datetime
import telebot
import os
from telebot.handler_backends import State, StatesGroup
from telebot import custom_filters

# Инициализация бота по токену из переменных окружения Render
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    # Запасной вариант на случай локального запуска (вставьте свой токен сюда при тестах на ПК, если нужно)
    BOT_TOKEN = "8938982971:AAfw3Sr1c0MYChPY1h4JdMvqQ7V9c3lZTs"

bot = telebot.TeleBot(BOT_TOKEN)

# --- НАСТРОЙКИ ПРОЕКТА ---
ADMIN_ID = 7015819580  # Ваш Telegram ID
ADMIN_USERNAME = "@charon238"  # Ваш юзернейм в Telegram
PAYMENTS_CHANNEL = "@pocket_cash_channel"  # Канал с выплатами


# --- БАЗА ДАННЫХ ---
def init_db():
    conn = sqlite3.connect("pocket_cash.db")
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            balance REAL DEFAULT 0.0,
            is_active INTEGER DEFAULT 0,
            game_level INTEGER DEFAULT 1,
            last_claim TEXT,
            spin_count INTEGER DEFAULT 0,
            streak_days INTEGER DEFAULT 0,
            last_streak_date TEXT,
            invited_by INTEGER,
            referral_count INTEGER DEFAULT 0,
            completed_quests TEXT DEFAULT ''
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS promo_codes (
            code TEXT PRIMARY KEY,
            reward REAL,
            uses_left INTEGER
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS used_promos (
            user_id INTEGER,
            code TEXT,
            PRIMARY KEY (user_id, code)
        )
    """)
    conn.commit()
    conn.close()

init_db()

# --- СОСТОЯНИЯ (FSM) ---
class WithdrawState(StatesGroup):
    waiting_for_phone = State()

class PromoState(StatesGroup):
    waiting_for_code = State()

class BroadcastState(StatesGroup):
    waiting_for_message = State()

# Регистрируем состояние для telebot
bot.add_custom_filter(custom_filters.StateFilter(bot))

# --- ГЛАВНОЕ МЕНЮ ---
def get_main_menu(is_active: bool, game_level: int = 1):
    keyboard = telebot.types.InlineKeyboardMarkup()
    
    # Кнопка игры всегда видна
    keyboard.add(telebot.types.InlineKeyboardButton(text="📦 Открыть сундуки (3 попытки)", callback_data="claim_bonus"))
    
    # Если аккаунт не активен, показываем кнопку активации
    if not is_active:
        cost = 50 if game_level == 1 else 30
        keyboard.add(telebot.types.InlineKeyboardButton(text=f"💎 Активировать доступ ({cost} TMT)", callback_data="buy_access"))
    
    keyboard.row(
        telebot.types.InlineKeyboardButton(text="🏆 Топ Игроков", callback_data="leaderboard"),
        telebot.types.InlineKeyboardButton(text="🎯 Задания (+2 TMT)", callback_data="quests")
    )
    keyboard.row(
        telebot.types.InlineKeyboardButton(text="📖 Как работает игра?", callback_data="how_to_earn"),
        telebot.types.InlineKeyboardButton(text="🎁 Промокод", callback_data="use_promo")
    )
    keyboard.add(telebot.types.InlineKeyboardButton(text="💰 Мой баланс", callback_data="my_balance"))
    keyboard.add(telebot.types.InlineKeyboardButton(text="👥 Рефералы (+5 TMT)", callback_data="ref_link"))
    keyboard.add(telebot.types.InlineKeyboardButton(text="📤 Запросить вывод", callback_data="withdraw"))
    
    return keyboard

# --- КОМАНДА /START ---
@bot.message_handler(commands=['start'])
def cmd_start(message: telebot.types.Message):
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name
    
    # Получаем аргументы команды /start (для рефералок)
    args = message.text.split()
    ref_arg = args[1] if len(args) > 1 else None
    
    conn = sqlite3.connect("pocket_cash.db")
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    user = cursor.fetchone()
    
    if not user:
        invited_by = None
        if ref_arg and ref_arg.isdigit():
            ref_id = int(ref_arg)
            if ref_id != user_id:
                cursor.execute("SELECT * FROM users WHERE user_id = ?", (ref_id,))
                if cursor.fetchone():
                    invited_by = ref_id
                    cursor.execute("UPDATE users SET referral_count = referral_count + 1 WHERE user_id = ?", (ref_id,))
        
        cursor.execute(
            "INSERT INTO users (user_id, username, invited_by) VALUES (?, ?, ?)",
            (user_id, username, invited_by)
        )
        conn.commit()
    
    cursor.execute("SELECT is_active, game_level, streak_days, balance FROM users WHERE user_id = ?", (user_id,))
    res = cursor.fetchone()
    is_active, game_level, streak, balance = res[0], res[1], res[2], res[3]
    conn.close()
    
    if not is_active:
        welcome_text = (
            f"✨ **Добро пожаловать в POCKET CASH TM!** ✨\n\n"
            f"👋 Привет, **{username}**!\n\n"
            f"🎁 **Главный Джекпот в сундуках:** `400.00 TMT`!\n"
            f"📦 Испытайте свою удачу и выигрывайте ценные призы!"
        )
    else:
        welcome_text = (
            f"👑 **POCKET CASH TM | ЛИЧНЫЙ КАБИНЕТ**\n\n"
            f"👋 С возвращением, **{username}**!\n"
            f"🎮 Игровой уровень: **Раунд #{game_level}**\n"
            f"💰 Ваш баланс: **{balance:.2f} TMT**\n"
            f"🔥 Серия дней: **{streak} дн.**\n\n"
            f"🎁 *Сундуки готовы к открытию! Выберите сундук и заберите свой приз!*"
        )
    
    bot.send_message(user_id, welcome_text, reply_markup=get_main_menu(is_active, game_level), parse_mode="Markdown")

# --- ИНСТРУКЦИЯ ПО АКТИВАЦИИ И ПОКУПКЕ РАУНДА ---
@bot.callback_query_handler(func=lambda call: call.data == "buy_access")
def buy_access(callback: telebot.types.CallbackQuery):
    user_id = callback.from_user.id
    
    conn = sqlite3.connect("pocket_cash.db")
    cursor = conn.cursor()
    cursor.execute("SELECT game_level FROM users WHERE user_id = ?", (user_id,))
    game_level = cursor.fetchone()[0]
    conn.close()
    
    cost = 50 if game_level == 1 else 30
    
    text = (
        f"💎 **БЫСТРАЯ АКТИВАЦИЯ РАУНДА #{game_level}** 💎\n\n"
        f"Получите 3 попытки открытия сундуков с призами до **400 TMT**:\n\n"
        f"1️⃣ Напишите администратору: **{ADMIN_USERNAME}**\n"
        f"2️⃣ Пополните разовый баланс на **{cost} TMT**.\n"
        f"3️⃣ Отправьте скриншот чека администратору.\n\n"
        f"📌 **Ваш персональный ID:** `{user_id}` *(нажмите, чтобы скопировать)*\n\n"
        f"🚀 *После проверки администратор запустит ваш Раунд #{game_level}, и вы сможете сразу открыть сундуки!*"
    )
    keyboard = telebot.types.InlineKeyboardMarkup()
    keyboard.add(telebot.types.InlineKeyboardButton(text="✉️ Написать Администратору", url=f"https://t.me/{ADMIN_USERNAME.replace('@', '')}"))
    
    bot.send_message(callback.message.chat.id, text, reply_markup=keyboard, parse_mode="Markdown")
    bot.answer_callback_query(callback.id)

# --- 📦 ИГРА «СУНДУКИ УДАЧИ» ---
@bot.callback_query_handler(func=lambda call: call.data == "claim_bonus")
def start_chest_game(callback: telebot.types.CallbackQuery):
    user_id = callback.from_user.id
    
    conn = sqlite3.connect("pocket_cash.db")
    cursor = conn.cursor()
    cursor.execute("SELECT is_active, spin_count FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    
    if not row or row[0] == 0:
        conn.close()
        return bot.answer_callback_query(callback.id, f"🔒 Доступ ограничен! Для открытия сундуков сначала активируйте доступ у администратора {ADMIN_USERNAME}", show_alert=True)
        
    is_active, spin_count = row
    
    if spin_count >= 3:
        conn.close()
        return bot.answer_callback_query(callback.id, f"⏳ Вы использовали все 3 попытки в этом раунде! Выведите средства и купите новый раунд за 30 TMT!", show_alert=True)

    keyboard = telebot.types.InlineKeyboardMarkup()
    keyboard.row(
        telebot.types.InlineKeyboardButton(text="🎁 Сундук #1", callback_data="open_chest_1"),
        telebot.types.InlineKeyboardButton(text="🎁 Сундук #2", callback_data="open_chest_2"),
        telebot.types.InlineKeyboardButton(text="🎁 Сундук #3", callback_data="open_chest_3")
    )
    
    bot.send_message(callback.message.chat.id, "🎰 **АБСОЛЮТНАЯ УДАЧА**\n\nПеред вами 3 сундука! В одном из них спрятан ДЖЕКПOТ **400 TMT**! Какой откроете?", reply_markup=keyboard, parse_mode="Markdown")
    bot.answer_callback_query(callback.id)

@bot.callback_query_handler(func=lambda call: call.data.startswith("open_chest_"))
def open_chest_handler(callback: telebot.types.CallbackQuery):
    user_id = callback.from_user.id
    chest_num = callback.data.split("_")[2]
    
    conn = sqlite3.connect("pocket_cash.db")
    cursor = conn.cursor()
    cursor.execute("SELECT spin_count, game_level FROM users WHERE user_id = ?", (user_id,))
    res = cursor.fetchone()
    if not res:
        conn.close()
        return bot.answer_callback_query(callback.id)
    
    spin_count, game_level = res
    spin_count += 1
    
    if game_level == 1:
        if spin_count < 3:
            win = 20.0
            msg = f"💥 **СУНДУК #{chest_num} ОТКРЫТ!** 💥\n\nВам выпало: **+20.00 TMT**! 🔥\n\n*Испытайте удачу в следующем сундуке, главный приз 400 TMT еще не найден!*"
        else:
            win = 0.0
            msg = f"😢 **Сундук #{chest_num} оказался пустым (0 TMT)!**\n\n💰 Ваш итоговый выигрыш за Раунд #1 составил: **40.00 TMT**!\n\n*Вы можете заказать вывод средств или купить новый раунд за 30 TMT, чтобы побороться за джекпот снова!*"
            cursor.execute("UPDATE users SET is_active = 0, game_level = game_level + 1 WHERE user_id = ?", (user_id,))
    else:
        if spin_count < 3:
            win = 10.0
            msg = f"💥 **СУНДУК #{chest_num} ОТКРЫТ!** 💥\n\nВам выпало: **+10.00 TMT**! 🔥\n\n*Открывайте следующий сундук!*"
        else:
            win = 0.0
            msg = f"😢 **Сундук #{chest_num} оказался пустым (0 TMT)!**\n\n💰 Ваш итоговый выигрыш за Раунд #{game_level} составил: **20.00 TMT**!\n\n*Заказывайте вывод средств и запускайте следующий раунд!*"
            cursor.execute("UPDATE users SET is_active = 0, game_level = game_level + 1 WHERE user_id = ?", (user_id,))

    cursor.execute("UPDATE users SET balance = balance + ?, spin_count = ? WHERE user_id = ?", (win, spin_count, user_id))
    conn.commit()
    conn.close()
    
    bot.edit_message_text(msg, callback.message.chat.id, callback.message.message_id, parse_mode="Markdown")
    bot.answer_callback_query(callback.id)

# --- 🎯 РАЗДЕЛ ЗАДАНИЙ ---
@bot.callback_query_handler(func=lambda call: call.data == "quests")
def quests_handler(callback: telebot.types.CallbackQuery):
    user_id = callback.from_user.id
    conn = sqlite3.connect("pocket_cash.db")
    cursor = conn.cursor()
    cursor.execute("SELECT completed_quests FROM users WHERE user_id = ?", (user_id,))
    res = cursor.fetchone()
    conn.close()
    
    completed = res[0].split(",") if (res and res[0]) else []
    q1_btn = "✅ Задание выполнено (+2 TMT)" if "q1" in completed else "🎯 Выполнить задание (+2 TMT)"
    
    keyboard = telebot.types.InlineKeyboardMarkup()
    keyboard.add(telebot.types.InlineKeyboardButton(text=q1_btn, callback_data="claim_q1"))
    
    text = (
        "🎯 **ЕЖЕДНЕВНЫЕ ЗАДАНИЯ**\n\n"
        "Выполняйте задания и зарабатывайте бонусный баланс абсолютно бесплатно!\n\n"
        "1️⃣ **Подписка на наш канал выплат:** +2.00 TMT"
    )
    bot.send_message(callback.message.chat.id, text, reply_markup=keyboard, parse_mode="Markdown")
    bot.answer_callback_query(callback.id)

@bot.callback_query_handler(func=lambda call: call.data == "claim_q1")
def claim_q1(callback: telebot.types.CallbackQuery):
    user_id = callback.from_user.id
    conn = sqlite3.connect("pocket_cash.db")
    cursor = conn.cursor()
    cursor.execute("SELECT completed_quests FROM users WHERE user_id = ?", (user_id,))
    res = cursor.fetchone()
    
    completed = (res[0] or "").split(",") if res else []
    
    if "q1" in completed:
        conn.close()
        return bot.answer_callback_query(callback.id, "❌ Вы уже забирали эту награду!", show_alert=True)
        
    completed.append("q1")
    new_completed = ",".join(completed)
    cursor.execute("UPDATE users SET balance = balance + 2.0, completed_quests = ? WHERE user_id = ?", (new_completed, user_id))
    conn.commit()
    conn.close()
    
    bot.send_message(callback.message.chat.id, "🎉 Бонус **+2.00 TMT** успешно зачислен на ваш баланс!", parse_mode="Markdown")
    bot.answer_callback_query(callback.id)

# --- 🎁 ПРОМОКОДЫ ---
@bot.callback_query_handler(func=lambda call: call.data == "use_promo")
def ask_promo(callback: telebot.types.CallbackQuery):
    bot.send_message(callback.message.chat.id, "🎁 **Введите промокод:**", parse_mode="Markdown")
    bot.set_state(callback.from_user.id, PromoState.waiting_for_code, callback.message.chat.id)
    bot.answer_callback_query(callback.id)

@bot.message_handler(state=PromoState.waiting_for_code)
def process_promo(message: telebot.types.Message):
    code = message.text.strip().upper()
    user_id = message.from_user.id
    
    conn = sqlite3.connect("pocket_cash.db")
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM used_promos WHERE user_id = ? AND code = ?", (user_id, code))
    if cursor.fetchone():
        conn.close()
        bot.send_message(message.chat.id, "❌ Вы уже активировали данный код!")
        bot.delete_state(user_id, message.chat.id)
        return
        
    cursor.execute("SELECT reward, uses_left FROM promo_codes WHERE code = ?", (code,))
    promo = cursor.fetchone()
    
    if not promo or promo[1] <= 0:
        conn.close()
        bot.send_message(message.chat.id, "❌ Код не существует или истрачен.")
        bot.delete_state(user_id, message.chat.id)
        return
        
    reward, uses_left = promo
    cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (reward, user_id))
    cursor.execute("UPDATE promo_codes SET uses_left = uses_left - 1 WHERE code = ?", (code,))
    cursor.execute("INSERT INTO used_promos (user_id, code) VALUES (?, ?)", (user_id, code))
    conn.commit()
    conn.close()
    
    bot.send_message(message.chat.id, f"🎉 **Промокод активирован!** Вам начислено **+{reward:.2f} TMT**!", parse_mode="Markdown")
    bot.delete_state(user_id, message.chat.id)

# --- 📖 КАК РАБОТАЕТ ИГРА ---
@bot.callback_query_handler(func=lambda call: call.data == "how_to_earn")
def how_to_earn_handler(callback: telebot.types.CallbackQuery):
    instruction_text = (
        "📖 **ПРАВИЛА ИГРЫ И УДАЧИ** 📖\n\n"
        "1️⃣ **Игровые раунды:**\n"
        f"• Первый раунд активируется за **50 TMT**, а последующие — за **30 TMT** через администратора **{ADMIN_USERNAME}**.\n\n"
        "2️⃣ **Сундуки удачи:**\n"
        "• В каждом раунде вам дается **3 попытки** на открытие сундуков с призами до **400 TMT**!\n\n"
        "3️⃣ **Бесплатный бонус (Задания):**\n"
        "• Подписывайтесь на канал выплат во вкладке «🎯 Задания» и получайте **+2 TMT** даже с неактивным аккаунтом!\n\n"
        "4️⃣ **Партнерская программа:**\n"
        "• Приглашайте друзей по своей ссылке и получайте **+5 TMT** за каждого друга, который активирует раунд!"
    )
    bot.send_message(callback.message.chat.id, instruction_text, parse_mode="Markdown")
    bot.answer_callback_query(callback.id)

# --- 👑 АДМИН-ПАНЕЛЬ ---
@bot.message_handler(commands=['admin'])
def admin_panel(message: telebot.types.Message):
    if message.from_user.id != ADMIN_ID: return
    text = (
        "👑 **Админ-Панель**\n\n"
        "• `/activate ID` — Активировать/Перезапустить раунд пользователю (начислит +5 TMT пригласившему)\n"
        "• `/send` — Рассылка всем пользователям\n"
        "• `/addpromo КОД СУММА КОЛ_ВО` — Создать промокод"
    )
    bot.send_message(message.chat.id, text, parse_mode="Markdown")

@bot.message_handler(commands=['activate'])
def activate_user_cmd(message: telebot.types.Message):
    if message.from_user.id != ADMIN_ID: return
    try:
        args = message.text.split()
        target_id = int(args[1])
        conn = sqlite3.connect("pocket_cash.db")
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET is_active = 1, spin_count = 0 WHERE user_id = ?", (target_id,))
        
        cursor.execute("SELECT invited_by FROM users WHERE user_id = ?", (target_id,))
        row = cursor.fetchone()
        if row and row[0]:
            invited_by = row[0]
            ref_bonus = 5.0
            cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (ref_bonus, invited_by))
            try: 
                bot.send_message(invited_by, f"🎉 Ваш реферал активировал раунд! Вам начислено **+{ref_bonus:.2f} TMT**!", parse_mode="Markdown")
            except Exception: 
                pass

        conn.commit()
        conn.close()
        
        try:
            bot.send_message(target_id, "🎉 **Ваш раунд успешно активирован!** Нажмите «📦 Открыть сундуки» и заберите свой выигрыш!", parse_mode="Markdown")
        except Exception: pass
        
        bot.send_message(message.chat.id, f"✅ Игровой раунд пользователя `{target_id}` успешно активирован!", parse_mode="Markdown")
    except Exception:
        bot.send_message(message.chat.id, "❌ Ошибка! Укажите ID: `/activate 123456789`", parse_mode="Markdown")

@bot.message_handler(commands=['addpromo'])
def add_promo_cmd(message: telebot.types.Message):
    if message.from_user.id != ADMIN_ID: return
    try:
        args = message.text.split()
        code, reward, uses = args[1].upper(), float(args[2]), int(args[3])
        conn = sqlite3.connect("pocket_cash.db")
        cursor = conn.cursor()
        cursor.execute("INSERT INTO promo_codes VALUES (?, ?, ?)", (code, reward, uses))
        conn.commit()
        conn.close()
        bot.send_message(message.chat.id, f"✅ Промокод `{code}` на {reward} TMT создан!")
    except Exception:
        bot.send_message(message.chat.id, "Ошибка! Формат: `/addpromo BONUS 5 10`")

@bot.message_handler(commands=['send'])
def start_broadcast(message: telebot.types.Message):
    if message.from_user.id != ADMIN_ID: return
    bot.send_message(message.chat.id, "📢 Введите текст сообщения для рассылки:")
    bot.set_state(message.from_user.id, BroadcastState.waiting_for_message, message.chat.id)

@bot.message_handler(state=BroadcastState.waiting_for_message)
def process_broadcast(message: telebot.types.Message):
    text = message.text
    user_id = message.from_user.id
    conn = sqlite3.connect("pocket_cash.db")
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM users")
    users = cursor.fetchall()
    conn.close()
    
    count = 0
    for u in users:
        try:
            bot.send_message(u[0], f"📢 **УВЕДОМЛЕНИЕ:**\n\n{text}", parse_mode="Markdown")
            count += 1
        except Exception:
            pass
            
    bot.send_message(message.chat.id, f"✅ Рассылка отправлена {count} пользователям!")
    bot.delete_state(user_id, message.chat.id)

# --- ДОП. РАЗДЕЛЫ ---
@bot.callback_query_handler(func=lambda call: call.data == "leaderboard")
def leaderboard_handler(callback: telebot.types.CallbackQuery):
    conn = sqlite3.connect("pocket_cash.db")
    cursor = conn.cursor()
    cursor.execute("SELECT username, balance FROM users ORDER BY balance DESC LIMIT 5")
    top_bal = cursor.fetchall()
    conn.close()
    text = "🏆 **ТАБЛИЦА САМЫХ УСПЕШНЫХ ИГРОКОВ**\n\n💰 **Топ по заработку:**\n"
    for i, (name, bal) in enumerate(top_bal, 1): text += f"{i}. {name} — **{bal:.2f} TMT**\n"
    bot.send_message(callback.message.chat.id, text, parse_mode="Markdown")
    bot.answer_callback_query(callback.id)

@bot.callback_query_handler(func=lambda call: call.data == "my_balance")
def show_balance(callback: telebot.types.CallbackQuery):
    user_id = callback.from_user.id
    conn = sqlite3.connect("pocket_cash.db")
    cursor = conn.cursor()
    cursor.execute("SELECT balance, is_active, game_level, referral_count, streak_days FROM users WHERE user_id = ?", (user_id,))
    u = cursor.fetchone()
    conn.close()
    bot.send_message(
        callback.message.chat.id,
        f"💳 **ВАШ ЛИЧНЫЙ КОШЕЛЕК**\n\n• Баланс: **{u[0]:.2f} TMT**\n• Игровой раунд: **#{u[2]}**\n• Статус раунда: {'🟢 Активен' if u[1] else '🔴 Ожидает активации'}\n• Партнеров приглашено: **{u[3]}**",
        parse_mode="Markdown"
    )
    bot.answer_callback_query(callback.id)

@bot.callback_query_handler(func=lambda call: call.data == "ref_link")
def ref_link(callback: telebot.types.CallbackQuery):
    user_id = callback.from_user.id
    bot_info = bot.get_me()
    bot.send_message(callback.message.chat.id, f"👥 **ПАРТНЕРСКАЯ ССЫЛКА**\n\nПриглашайте друзей! За каждого друга, который **активирует раунд**, вам начислится **+5.00 TMT**:\n`https://t.me/{bot_info.username}?start={user_id}`", parse_mode="Markdown")
    bot.answer_callback_query(callback.id)

@bot.callback_query_handler(func=lambda call: call.data == "withdraw")
def withdraw_request(callback: telebot.types.CallbackQuery):
    user_id = callback.from_user.id
    conn = sqlite3.connect("pocket_cash.db")
    cursor = conn.cursor()
    cursor.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
    balance = cursor.fetchone()[0]
    conn.close()
    if balance < 20: return bot.answer_callback_query(callback.id, "⚠️ Минимальная сумма вывода: 20 TMT.", show_alert=True)
    bot.send_message(callback.message.chat.id, "📤 Введите ваш номер для вывода средств:")
    bot.set_state(user_id, WithdrawState.waiting_for_phone, callback.message.chat.id)
    bot.answer_callback_query(callback.id)

@bot.message_handler(state=WithdrawState.waiting_for_phone)
def process_withdraw(message: telebot.types.Message):
    phone = message.text
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name
    
    conn = sqlite3.connect("pocket_cash.db")
    cursor = conn.cursor()
    cursor.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
    balance = cursor.fetchone()[0]
    cursor.execute("UPDATE users SET balance = 0 WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()
    
    bot.send_message(ADMIN_ID, f"💸 **ЗАЯВКА НА ВЫВОД!**\nПользователь: @{username}\nСумма: **{balance:.2f} TMT**\nРеквизиты: `{phone}`", parse_mode="Markdown")
    try:
        masked_name = f"@{username[:3]}***" if username else "Игрок"
        bot.send_message(PAYMENTS_CHANNEL, f"💸 **ОФИЦИАЛЬНАЯ ВЫПЛАТА!**\n👤 Игрок: **{masked_name}**\n💰 Зачислено: **{balance:.2f} TMT**", parse_mode="Markdown")
    except Exception: pass
    
    bot.send_message(message.chat.id, "✅ Заявка отправлена администратору! Ожидайте зачисления.")
    bot.delete_state(user_id, message.chat.id)import threading
from flask import Flask

# Создаем простенький Flask-сервер для удержания бота активным на Render
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is alive and running!"

def run_flask():
    # Render передает порт через переменные окружения, по умолчанию 10000
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

if __name__ == "__main__":
    print("Запуск Flask-сервера в фоновом режиме...")
    flask_thread = threading.Thread(target=run_flask)
    flask_thread.daemon = True
    flask_thread.start()

    print("Бот Pocket Cash TM успешно запущен!")
    bot.infinity_polling(skip_pending=True)
    print("Бот Pocket Cash TM успешно запущен на telebot!")
    bot.infinity_polling(skip_pending=True)
