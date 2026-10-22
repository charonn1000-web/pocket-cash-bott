import sqlite3
import datetime
import asyncio
import telebot
import os

bot = telebot.TeleBot(os.getenv("BOT_TOKEN")) # или ваш токен


# --- НАСТРОЙКИ ПРОЕКТА ---
TOKEN = "8938982971:AAFw3Srlc0MYChPY1h4JdMvqXQ7V9c3lZTs"
ADMIN_ID = 7015819580  # Ваш Telegram ID
ADMIN_USERNAME = "@charon238"  # Ваш юзернейм в Telegram
PAYMENTS_CHANNEL = "@pocket_cash_channel"  # Канал с выплатами

bot = Bot(token=TOKEN)
dp = Dispatcher(storage=MemoryStorage())

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

# --- ГЛАВНОЕ МЕНЮ ---
def get_main_menu(is_active: bool, game_level: int = 1):
    keyboard = []
    
    # Кнопка игры всегда видна
    keyboard.append([types.InlineKeyboardButton(text="📦 Открыть сундуки (3 попытки)", callback_data="claim_bonus")])
    
    # Если аккаунт не активен, показываем кнопку активации/покупки раунда
    if not is_active:
        cost = 50 if game_level == 1 else 30
        keyboard.append([types.InlineKeyboardButton(text=f"💎 Активировать доступ ({cost} TMT)", callback_data="buy_access")])
    
    keyboard.append([
        types.InlineKeyboardButton(text="🏆 Топ Игроков", callback_data="leaderboard"),
        types.InlineKeyboardButton(text="🎯 Задания (+2 TMT)", callback_data="quests")
    ])
    keyboard.append([
        types.InlineKeyboardButton(text="📖 Как работает игра?", callback_data="how_to_earn"),
        types.InlineKeyboardButton(text="🎁 Промокод", callback_data="use_promo")
    ])
    keyboard.append([types.InlineKeyboardButton(text="💰 Мой баланс", callback_data="my_balance")])
    keyboard.append([types.InlineKeyboardButton(text="👥 Рефералы (+5 TMT)", callback_data="ref_link")])
    keyboard.append([types.InlineKeyboardButton(text="📤 Запросить вывод", callback_data="withdraw")])
    
    return types.InlineKeyboardMarkup(inline_keyboard=keyboard)

# --- КОМАНДА /START ---
@dp.message(Command("start"))
async def cmd_start(message: types.Message, command: CommandObject):
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name
    args = command.args
    
    conn = sqlite3.connect("pocket_cash.db")
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    user = cursor.fetchone()
    
    if not user:
        invited_by = None
        if args and args.isdigit():
            ref_id = int(args)
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
    
    await message.answer(welcome_text, reply_markup=get_main_menu(is_active, game_level), parse_mode="Markdown")

# --- ИНСТРУКЦИЯ ПО АКТИВАЦИИ И ПОКУПКЕ РАУНДА ---
@dp.callback_query(F.data == "buy_access")
async def buy_access(callback: types.CallbackQuery):
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
    keyboard = types.InlineKeyboardMarkup(
        inline_keyboard=[[types.InlineKeyboardButton(text="✉️ Написать Администратору", url=f"https://t.me/{ADMIN_USERNAME.replace('@', '')}")]]
    )
    await callback.message.answer(text, reply_markup=keyboard, parse_mode="Markdown")
    await callback.answer()

# --- 📦 ИГРА «СУНДУКИ УДАЧИ» ---
@dp.callback_query(F.data == "claim_bonus")
async def start_chest_game(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    
    conn = sqlite3.connect("pocket_cash.db")
    cursor = conn.cursor()
    cursor.execute("SELECT is_active, spin_count FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    
    if not row or row[0] == 0:
        conn.close()
        return await callback.answer(f"🔒 Доступ ограничен! Для открытия сундуков сначала активируйте доступ у администратора {ADMIN_USERNAME}", show_alert=True)
        
    is_active, spin_count = row
    
    if spin_count >= 3:
        conn.close()
        return await callback.answer(f"⏳ Вы использовали все 3 попытки в этом раунде! Выведите средства и купите новый раунд за 30 TMT!", show_alert=True)

    keyboard = types.InlineKeyboardMarkup(
        inline_keyboard=[[
            types.InlineKeyboardButton(text="🎁 Сундук #1", callback_data="open_chest_1"),
            types.InlineKeyboardButton(text="🎁 Сундук #2", callback_data="open_chest_2"),
            types.InlineKeyboardButton(text="🎁 Сундук #3", callback_data="open_chest_3")
        ]]
    )
    
    await callback.message.answer("🎰 **АБСОЛЮТНАЯ УДАЧА**\n\nПеред вами 3 сундука! В одном из них спрятан ДЖЕКПOТ **400 TMT**! Какой откроете?", reply_markup=keyboard, parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(F.data.startswith("open_chest_"))
async def open_chest_handler(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    chest_num = callback.data.split("_")[2]
    
    conn = sqlite3.connect("pocket_cash.db")
    cursor = conn.cursor()
    cursor.execute("SELECT spin_count, game_level FROM users WHERE user_id = ?", (user_id,))
    spin_count, game_level = cursor.fetchone()
    
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
    
    await callback.message.edit_text(msg, parse_mode="Markdown")
    await callback.answer()

# --- 🎯 РАЗДЕЛ ЗАДАНИЙ (ДОСТУПЕН ДАЖЕ НЕАКТИВНЫМ) ---
@dp.callback_query(F.data == "quests")
async def quests_handler(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    conn = sqlite3.connect("pocket_cash.db")
    cursor = conn.cursor()
    cursor.execute("SELECT completed_quests FROM users WHERE user_id = ?", (user_id,))
    res = cursor.fetchone()
    conn.close()
    
    completed = res[0].split(",") if (res and res[0]) else []
    q1_btn = "✅ Задание выполнено (+2 TMT)" if "q1" in completed else "🎯 Выполнить задание (+2 TMT)"
    
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=[[types.InlineKeyboardButton(text=q1_btn, callback_data="claim_q1")]])
    
    text = (
        "🎯 **ЕЖЕДНЕВНЫЕ ЗАДАНИЯ**\n\n"
        "Выполняйте задания и зарабатывайте бонусный баланс абсолютно бесплатно!\n\n"
        "1️⃣ **Подписка на наш канал выплат:** +2.00 TMT"
    )
    await callback.message.answer(text, reply_markup=keyboard, parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(F.data == "claim_q1")
async def claim_q1(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    conn = sqlite3.connect("pocket_cash.db")
    cursor = conn.cursor()
    cursor.execute("SELECT completed_quests FROM users WHERE user_id = ?", (user_id,))
    res = cursor.fetchone()
    
    completed = (res[0] or "").split(",") if res else []
    
    if "q1" in completed:
        conn.close()
        return await callback.answer("❌ Вы уже забирали эту награду!", show_alert=True)
        
    completed.append("q1")
    new_completed = ",".join(completed)
    cursor.execute("UPDATE users SET balance = balance + 2.0, completed_quests = ? WHERE user_id = ?", (new_completed, user_id))
    conn.commit()
    conn.close()
    
    await callback.message.answer("🎉 Бонус **+2.00 TMT** успешно зачислен на ваш баланс!", parse_mode="Markdown")
    await callback.answer()

# --- 🎁 ПРОМОКОДЫ ---
@dp.callback_query(F.data == "use_promo")
async def ask_promo(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("🎁 **Введите промокод:**")
    await state.set_state(PromoState.waiting_for_code)
    await callback.answer()

@dp.message(PromoState.waiting_for_code)
async def process_promo(message: types.Message, state: FSMContext):
    code = message.text.strip().upper()
    user_id = message.from_user.id
    
    conn = sqlite3.connect("pocket_cash.db")
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM used_promos WHERE user_id = ? AND code = ?", (user_id, code))
    if cursor.fetchone():
        conn.close()
        await message.answer("❌ Вы уже активировали данный код!")
        return await state.clear()
        
    cursor.execute("SELECT reward, uses_left FROM promo_codes WHERE code = ?", (code,))
    promo = cursor.fetchone()
    
    if not promo or promo[1] <= 0:
        conn.close()
        await message.answer("❌ Код не существует или истрачен.")
        return await state.clear()
        
    reward, uses_left = promo
    cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (reward, user_id))
    cursor.execute("UPDATE promo_codes SET uses_left = uses_left - 1 WHERE code = ?", (code,))
    cursor.execute("INSERT INTO used_promos (user_id, code) VALUES (?, ?)", (user_id, code))
    conn.commit()
    conn.close()
    
    await message.answer(f"🎉 **Промокод активирован!** Вам начислено **+{reward:.2f} TMT**!", parse_mode="Markdown")
    await state.clear()

# --- 📖 КАК РАБОТАЕТ ИГРА ---
@dp.callback_query(F.data == "how_to_earn")
async def how_to_earn_handler(callback: types.CallbackQuery):
    instruction_text = (
        "📖 **ПРАВИЛА ИГРЫ И УДАЧИ** 📖\n\n"
        "1️⃣ **Игровые раунды:**\n"
        "• Первый раунд активируется за **50 TMT**, а последующие — за **30 TMT** через администратора **{ADMIN_USERNAME}**.\n\n"
        "2️⃣ **Сундуки удачи:**\n"
        "• В каждом раунде вам дается **3 попытки** на открытие сундуков с призами до **400 TMT**!\n\n"
        "3️⃣ **Бесплатный бонус (Задания):**\n"
        "• Подписывайтесь на канал выплат во вкладке «🎯 Задания» и получайте **+2 TMT** даже с неактивным аккаунтом!\n\n"
        "4️⃣ **Партнерская программа:**\n"
        "• Приглашайте друзей по своей ссылке и получайте **+5 TMT** за каждого друга, который активирует раунд!"
    ).format(ADMIN_USERNAME=ADMIN_USERNAME)
    await callback.message.answer(instruction_text, parse_mode="Markdown")
    await callback.answer()

# --- 👑 АДМИН-ПАНЕЛЬ ---
@dp.message(Command("admin"))
async def admin_panel(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    text = (
        "👑 **Админ-Панель**\n\n"
        "• `/activate ID` — Активировать/Перезапустить раунд пользователю (начислит +5 TMT пригласившему)\n"
        "• `/send` — Рассылка всем пользователям\n"
        "• `/addpromo КОД СУММА КОЛ_ВО` — Создать промокод"
    )
    await message.answer(text, parse_mode="Markdown")

@dp.message(Command("activate"))
async def activate_user_cmd(message: types.Message, command: CommandObject):
    if message.from_user.id != ADMIN_ID: return
    try:
        target_id = int(command.args.strip())
        conn = sqlite3.connect("pocket_cash.db")
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET is_active = 1, spin_count = 0 WHERE user_id = ?", (target_id,))
        
        # Начисление рефералу ровно +5 TMT при активации приглашенным игроком
        cursor.execute("SELECT invited_by FROM users WHERE user_id = ?", (target_id,))
        row = cursor.fetchone()
        if row and row[0]:
            invited_by = row[0]
            ref_bonus = 5.0
            cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (ref_bonus, invited_by))
            try: 
                await bot.send_message(invited_by, f"🎉 Ваш реферал активировал раунд! Вам начислено **+{ref_bonus:.2f} TMT**!", parse_mode="Markdown")
            except Exception: 
                pass

        conn.commit()
        conn.close()
        
        try:
            await bot.send_message(target_id, "🎉 **Ваш раунд успешно активирован!** Нажмите «📦 Открыть сундуки» и заберите свой выигрыш!")
        except Exception: pass
        
        await message.answer(f"✅ Игровой раунд пользователя `{target_id}` успешно активирован!", parse_mode="Markdown")
    except Exception:
        await message.answer("❌ Ошибка! Укажите ID: `/activate 123456789`", parse_mode="Markdown")

@dp.message(Command("addpromo"))
async def add_promo_cmd(message: types.Message, command: CommandObject):
    if message.from_user.id != ADMIN_ID: return
    try:
        args = command.args.split()
        code, reward, uses = args[0].upper(), float(args[1]), int(args[2])
        conn = sqlite3.connect("pocket_cash.db")
        cursor = conn.cursor()
        cursor.execute("INSERT INTO promo_codes VALUES (?, ?, ?)", (code, reward, uses))
        conn.commit()
        conn.close()
        await message.answer(f"✅ Промокод `{code}` на {reward} TMT создан!")
    except Exception:
        await message.answer("Ошибка! Формат: `/addpromo BONUS 5 10`")

@dp.message(Command("send"))
async def start_broadcast(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID: return
    await message.answer("📢 Введите текст сообщения для рассылки:")
    await state.set_state(BroadcastState.waiting_for_message)

@dp.message(BroadcastState.waiting_for_message)
async def process_broadcast(message: types.Message, state: FSMContext):
    text = message.text
    conn = sqlite3.connect("pocket_cash.db")
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM users")
    users = cursor.fetchall()
    conn.close()
    
    count = 0
    for u in users:
        try:
            await bot.send_message(u[0], f"📢 **УВЕДОМЛЕНИЕ:**\n\n{text}", parse_mode="Markdown")
            count += 1
            await asyncio.sleep(0.05)
        except Exception:
            pass
            
    await message.answer(f"✅ Рассылка отправлена {count} пользователям!")
    await state.clear()

# --- ДОП. РАЗДЕЛЫ ---
@dp.callback_query(F.data == "leaderboard")
async def leaderboard_handler(callback: types.CallbackQuery):
    conn = sqlite3.connect("pocket_cash.db")
    cursor = conn.cursor()
    cursor.execute("SELECT username, balance FROM users ORDER BY balance DESC LIMIT 5")
    top_bal = cursor.fetchall()
    conn.close()
    text = "🏆 **ТАБЛИЦА САМЫХ УСПЕШНЫХ ИГРОКОВ**\n\n💰 **Топ по заработку:**\n"
    for i, (name, bal) in enumerate(top_bal, 1): text += f"{i}. {name} — **{bal:.2f} TMT**\n"
    await callback.message.answer(text, parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(F.data == "my_balance")
async def show_balance(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    conn = sqlite3.connect("pocket_cash.db")
    cursor = conn.cursor()
    cursor.execute("SELECT balance, is_active, game_level, referral_count, streak_days FROM users WHERE user_id = ?", (user_id,))
    u = cursor.fetchone()
    conn.close()
    await callback.message.answer(
        f"💳 **ВАШ ЛИЧНЫЙ КОШЕЛЕК**\n\n• Баланс: **{u[0]:.2f} TMT**\n• Игровой раунд: **#{u[2]}**\n• Статус раунда: {'🟢 Активен' if u[1] else '🔴 Ожидает активации'}\n• Партнеров приглашено: **{u[3]}**",
        parse_mode="Markdown"
    )
    await callback.answer()

@dp.callback_query(F.data == "ref_link")
async def ref_link(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    bot_info = await bot.get_me()
    await callback.message.answer(f"👥 **ПАРТНЕРСКАЯ ССЫЛКА**\n\nПриглашайте друзей! За каждого друга, который **активирует раунд**, вам начислится **+5.00 TMT**:\n`https://t.me/{bot_info.username}?start={user_id}`", parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(F.data == "withdraw")
async def withdraw_request(callback: types.CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    conn = sqlite3.connect("pocket_cash.db")
    cursor = conn.cursor()
    cursor.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
    balance = cursor.fetchone()[0]
    conn.close()
    if balance < 20: return await callback.answer("⚠️ Минимальная сумма вывода: 20 TMT.", show_alert=True)
    await callback.message.answer("📤 Введите ваш номер для вывода средств:")
    await state.set_state(WithdrawState.waiting_for_phone)
    await callback.answer()

@dp.message(WithdrawState.waiting_for_phone)
async def process_withdraw(message: types.Message, state: FSMContext):
    phone, user_id, username = message.text, message.from_user.id, message.from_user.username or message.from_user.first_name
    conn = sqlite3.connect("pocket_cash.db")
    cursor = conn.cursor()
    cursor.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
    balance = cursor.fetchone()[0]
    cursor.execute("UPDATE users SET balance = 0 WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()
    
    await bot.send_message(ADMIN_ID, f"💸 **ЗАЯВКА НА ВЫВОД!**\nПользователь: @{username}\nСумма: **{balance:.2f} TMT**\nРеквизиты: `{phone}`", parse_mode="Markdown")
    try:
        masked_name = f"@{username[:3]}***" if username else "Игрок"
        await bot.send_message(PAYMENTS_CHANNEL, f"💸 **ОФИЦИАЛЬНАЯ ВЫПЛАТА!**\n👤 Игрок: **{masked_name}**\n💰 Зачислено: **{balance:.2f} TMT**", parse_mode="Markdown")
    except Exception: pass
    await message.answer("✅ Заявка отправлена администратору! Ожидайте зачисления.")
    await state.clear()

async def main():
    print("Бот Pocket Cash TM успешно запущен!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
