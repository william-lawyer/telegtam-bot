import asyncio
import json
import os
import random
import time
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.utils.keyboard import ReplyKeyboardBuilder
from aiogram.utils.markdown import hbold, hitalic, hunderline
from flask import Flask
import threading

# API-токен вашего бота
API_TOKEN = '7537085884:AAGuseMdxP0Uwlhhv4Ltgg3-hmo0EJYkAG4'

# Инициализация бота и диспетчера
bot = Bot(token=API_TOKEN)
dp = Dispatcher()

# Путь к файлу для хранения данных
DATA_FILE = "balances.json"

# Список администраторов (их Telegram ID)
ADMINS = ["729406890"]  # Ваш ID добавлен как администратор

# Данные пользователей
users = {}

# Начальный баланс, джекпот и счёт казино
STARTING_BALANCE = 1000
jackpot = 5000
casino_balance = 0

# Словарь текущей игры пользователя
current_game = {}

# Словарь дуэлей
duels = {}

# Флаг ожидания никнейма
awaiting_nickname = {}

# Время последней активности пользователя для антиспама
last_action_time = {}

# Минимальный интервал между действиями (в секундах)
SPAM_COOLDOWN = 2

# Ссылка на Telegram-канал
TELEGRAM_CHANNEL = "https://t.me/your_channel_name"  # Замените на реальную ссылку

# Бонус за реферала
REFERRAL_BONUS = 50000

# Флаг технических работ
MAINTENANCE_MODE = False  # Установите True для активации техработ

# Загрузка данных из файла
def load_data():
    global users, jackpot, casino_balance
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            users.update(data.get("users", {}))
            jackpot = data.get("jackpot", 5000)
            casino_balance = data.get("casino_balance", 0)
            for user_id, user_data in users.items():
                user_data.setdefault("nickname", user_data.get("username", "NoNickname"))
                user_data.setdefault("last_daily_bonus", 0.0)
                user_data.setdefault("subscribed", False)
                user_data.setdefault("invited_by", None)
                user_data.setdefault("hide_in_leaderboard", False)
    else:
        save_data()

# Сохранение данных в файл
def save_data():
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump({"users": users, "jackpot": jackpot, "casino_balance": casino_balance}, f, ensure_ascii=False, indent=4)

# Проверка антиспама
def check_spam(user_id):
    current_time = time.time()
    last_time = last_action_time.get(user_id, 0)
    if current_time - last_time < SPAM_COOLDOWN:
        return False
    last_action_time[user_id] = current_time
    return True

# Начисление ежедневного бонуса
def check_and_add_daily_bonus(user_id):
    current_time = time.time()
    last_bonus = users[user_id].get("last_daily_bonus", 0.0)
    if current_time - last_bonus >= 86400:
        users[user_id]["balance"] += 1000
        users[user_id]["last_daily_bonus"] = current_time
        save_data()
        return True
    return False

# Создание реферальной ссылки
def get_referral_link(user_id):
    return f"t.me/{bot._me.username}?start=ref_{user_id}"

# Обработка реферального бонуса
async def process_referral(referrer_id, new_user_id):
    if referrer_id == new_user_id:
        print(f"Самоприглашение: {referrer_id} == {new_user_id}")
        return
    if referrer_id in users and users[referrer_id].get("balance") is not None:
        users[referrer_id]["balance"] += REFERRAL_BONUS
        save_data()
        try:
            await bot.send_message(
                referrer_id,
                f"{hbold('НОВЫЙ РЕФЕРАЛ!')}\n\n"
                f"Вы пригласили друга и получили {hbold(f'{REFERRAL_BONUS} 💰')}\n"
                f"Ваш баланс: {hbold(str(users[referrer_id]['balance']) + ' 💰')}",
                parse_mode="HTML"
            )
            print(f"Бонус {REFERRAL_BONUS} начислен рефереру {referrer_id}")
        except Exception as e:
            print(f"Ошибка при отправке сообщения рефереру {referrer_id}: {e}")

# Функция для определения комбинации слотов
def get_combo_text(dice_value: int):
    values = ["BAR", "🍇", "🍋", "7"]
    dice_value -= 1
    result = []
    for _ in range(3):
        result.append(values[dice_value % 4])
        dice_value //= 4
    return result

# Определение выигрыша для слотов
def determine_slot_win(dice_value, bet, user_id):
    global jackpot, casino_balance
    winnings = 0
    combo = get_combo_text(dice_value)
    message = f"Комбинация: {combo[0]} {combo[1]} {combo[2]}\n"
    freespins = users[user_id].get("freespins", 0)

    if combo == ["7", "7", "7"]:
        winnings = bet * 10
        freespins += 3
        message += f"{hbold('ТРИ СЕМЁРКИ!')}\n{hunderline('+3 фриспина')}"
    elif combo == ["🍋", "🍋", "🍋"]:
        winnings = bet * 5 * (2 if freespins > 0 else 1)
        message += f"{hbold('ВЫИГРЫШ!')} {hitalic('Три лимона')}"
    elif combo == ["BAR", "BAR", "BAR"]:
        winnings = bet * 8
        message += f"{hbold('ВЫИГРЫШ!')} {hitalic('Три BAR')}"
    elif combo == ["🍇", "🍇", "🍇"]:
        winnings = bet * 6
        message += f"{hbold('ВЫИГРЫШ!')} {hitalic('Три винограда')}"
    elif combo[0] == "7" and combo[1] == "7":
        winnings = bet * 5
        message += f"{hbold('ВЫИГРЫШ!')} {hitalic('Две семёрки в начале')}"
    else:
        message += "Увы, нет выигрыша 😔"

    if random.random() < 0.05:
        bonus = random.randint(1, 3)
        if bonus <= 2:
            winnings += bonus * bet
            message += f"\n{hbold('СЛУЧАЙНЫЙ БОНУС:')} {hitalic(f'+{bonus * bet} 💰')}"
        else:
            freespins += 1
            message += f"\n{hbold('СЛУЧАЙНЫЙ БОНУС:')} {hunderline('+1 фриспин')}"

    users[user_id]["freespins"] = freespins
    return winnings, message, "gamble" if winnings > 0 and random.random() < 0.5 else None

# Определение выигрышей для других одиночных игр
def determine_dice_win(value, bet):
    if value == 6:
        return bet * 3, f"{hbold('ШЕСТЁРКА!')}\n{hitalic('Отличный бросок')}"
    elif value == 5:
        return bet * 2, f"{hbold('ХОРОШИЙ БРОСОК!')}\n{hitalic('Неплохо')}"
    return 0, "Увы, нет выигрыша 😔"

def determine_darts_win(value, bet):
    if value == 6:
        return bet * 5, f"{hbold('В ЯБЛОЧКО!')}\n{hitalic('Отличный бросок')}"
    return 0, "Мимо 😔"

def determine_basketball_win(value, bet):
    if value in [4, 5]:
        return bet * 3, f"{hbold('В КОЛЬЦО!')}\n{hitalic('Классный бросок')}"
    return 0, "Мимо 😔"

def determine_football_win(value, bet):
    if value in [3, 4, 5]:
        return bet * 3, f"{hbold('ГОЛ!')}\n{hitalic('Отличный удар')}"
    return 0, "Мимо ворот 😔"

def determine_bowling_win(value, bet):
    if value == 6:
        return bet * 5, f"{hbold('СТРАЙК!')}\n{hitalic('Идеальный бросок')}"
    return 0, "Промах 😔"

# Создание меню
def get_casino_menu():
    builder = ReplyKeyboardBuilder()
    builder.button(text="Игры 🎮")
    builder.button(text="Аккаунт 👤")
    builder.button(text="Многопользовательское казино 👥")
    builder.button(text="Таблица лидеров 🏆")
    builder.button(text="Турниры 🏅")
    builder.adjust(2)
    return builder.as_markup(resize_keyboard=True)

def get_game_menu():
    builder = ReplyKeyboardBuilder()
    builder.button(text="Слоты 🎰")
    builder.button(text="Кубики 🎲")
    builder.button(text="Баскетбол 🏀")
    builder.button(text="Боулинг 🎳")
    builder.button(text="Футбол ⚽")
    builder.button(text="Дартс 🎯")
    builder.button(text="Назад в казино")
    builder.adjust(2)
    return builder.as_markup(resize_keyboard=True)

def get_bet_keyboard():
    builder = ReplyKeyboardBuilder()
    builder.button(text="10 💰")
    builder.button(text="100 💰")
    builder.button(text="1000 💰")
    builder.button(text="Олл-ин 💰")
    builder.button(text="Своя ставка")
    builder.button(text="Баланс")
    builder.button(text="Правила 📜")
    builder.button(text="Назад в меню")
    builder.adjust(2)
    return builder.as_markup(resize_keyboard=True)

def get_account_menu():
    builder = ReplyKeyboardBuilder()
    builder.button(text="Бонусы 🎁")
    builder.button(text="Передать деньги 💸")
    builder.button(text="Имя ✏️")
    builder.button(text="Назад в казино")
    builder.adjust(2)
    return builder.as_markup(resize_keyboard=True)

def get_bonus_menu():
    builder = ReplyKeyboardBuilder()
    builder.button(text="Подписка на канал (+500 💰)")
    builder.button(text="Пригласи друга 👤")
    builder.button(text="Назад в аккаунт")
    builder.adjust(1)
    return builder.as_markup(resize_keyboard=True)

def get_name_menu():
    builder = ReplyKeyboardBuilder()
    builder.button(text="Сменить никнейм")
    builder.button(text="Скрыть/Показать в таблице лидеров")
    builder.button(text="Назад в аккаунт")
    builder.adjust(1)
    return builder.as_markup(resize_keyboard=True)

def get_multiplayer_menu():
    builder = ReplyKeyboardBuilder()
    builder.button(text="Дуэль ⚔️")
    builder.button(text="Комнаты 🏠")
    builder.button(text="Назад в казино")
    builder.adjust(2)
    return builder.as_markup(resize_keyboard=True)

def get_duel_game_menu():
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Кубики 🎲", callback_data="duel_game_dice"),
         InlineKeyboardButton(text="Баскетбол 🏀", callback_data="duel_game_basketball")],
        [InlineKeyboardButton(text="Боулинг 🎳", callback_data="duel_game_bowling"),
         InlineKeyboardButton(text="Футбол ⚽", callback_data="duel_game_football")],
        [InlineKeyboardButton(text="Дартс 🎯", callback_data="duel_game_darts")]
    ])
    return keyboard

# Правила игры
async def send_rules(message: Message):
    rules = (
        f"{hbold('ПРАВИЛА ИГРЫ')}\n\n"
        f"{hunderline('СЛОТЫ')}\n"
        "  Символы: 7 BAR 🍋 🍇\n"
        f"  {hbold('КОМБИНАЦИИ:')}\n"
        f"    Три 🍋: {hitalic('x5 ставки (x2 во фриспинах)')}\n"
        f"    Три BAR: {hitalic('x8 ставки')}\n"
        f"    Три 🍇: {hitalic('x6 ставки')}\n"
        f"    Две 7 в начале: {hitalic('x5 ставки')}\n"
        f"    Три 7: {hitalic('x10 ставки, +3 фриспина')}\n"
        f"  {hbold('СЛУЧАЙНЫЙ БОНУС:')} {hitalic('5% шанс на +1-3x ставки 💰 или +1 фриспин')}\n"
        f"  {hbold('РИСК-ИГРА:')} {hitalic('50% шанс удвоить выигрыш (❤️ или ♠️)')}\n\n"
        f"КУБИКИ: {hitalic('6 — x3, 5 — x2')}\n"
        f"ДАРТС: {hitalic('6 — x5')}\n"
        f"БАСКЕТБОЛ: {hitalic('4 или 5 — x3')}\n"
        f"ФУТБОЛ: {hitalic('3, 4 или 5 — x3')}\n"
        f"БОУЛИНГ: {hitalic('6 — x5')}\n"
        f"\n{hitalic('Используй /rules для повторного просмотра!')}"
    )
    await message.reply(rules, parse_mode="HTML")

# Обработчик команды /start
@dp.message(Command(commands=["start"]))
async def start_command(message: Message):
    if MAINTENANCE_MODE:
        await message.reply(
            f"{hbold('ТЕХНИЧЕСКИЕ РАБОТЫ')}\n\n"
            f"Бот временно недоступен. Ведутся технические работы. Пожалуйста, попробуйте позже!",
            parse_mode="HTML"
        )
        return

    user_id = str(message.from_user.id)
    username = message.from_user.username or "NoUsername"
    args = message.text.split()

    referrer_id = None
    if len(args) > 1 and args[1].startswith("ref_"):
        referrer_id = args[1].replace("ref_", "")
        print(f"Реферальный код найден: ref_{referrer_id}")

    if user_id not in users:
        users[user_id] = {
            "balance": STARTING_BALANCE,
            "username": username,
            "freespins": 0,
            "multiplier": 1.0,
            "last_daily_bonus": 0.0,
            "subscribed": False,
            "invited_by": referrer_id,
            "hide_in_leaderboard": False
        }
        awaiting_nickname[user_id] = True
        await message.reply(
            f"{hbold('ДОБРО ПОЖАЛОВАТЬ!')}\n\n"
            f"Пожалуйста, введи свой никнейм:",
            parse_mode="HTML"
        )
        if referrer_id:
            print(f"Новый пользователь {user_id} приглашен реферером {referrer_id}")
            await process_referral(referrer_id, user_id)
    else:
        if check_and_add_daily_bonus(user_id):
            await message.reply(
                f"{hbold('ЕЖЕДНЕВНЫЙ БОНУС!')}\n\n"
                f"Вам начислено {hbold('1000 💰')}\n"
                f"Новый баланс: {hbold(str(users[user_id]['balance']) + ' 💰')}\n\n"
                f"{hbold('ВЫБЕРИ РАЗДЕЛ:')}",
                reply_markup=get_casino_menu(),
                parse_mode="HTML"
            )
        else:
            await message.reply(
                f"{hbold('ВЫБЕРИ РАЗДЕЛ:')}\n",
                reply_markup=get_casino_menu(),
                parse_mode="HTML"
            )

# Установка никнейма
@dp.message(lambda message: str(message.from_user.id) in awaiting_nickname and not MAINTENANCE_MODE)
async def set_nickname(message: Message):
    user_id = str(message.from_user.id)
    nickname = message.text.strip()

    if len(nickname) > 20:
        await message.reply(
            f"{hbold('Ошибка:')} Никнейм слишком длинный (максимум 20 символов)!",
            parse_mode="HTML"
        )
        return

    users[user_id]["nickname"] = nickname
    del awaiting_nickname[user_id]
    save_data()
    await message.reply(
        f"{hbold('Никнейм установлен:')} {nickname}\n\n"
        f"{hbold('ВЫБЕРИ РАЗДЕЛ:')}\n",
        reply_markup=get_casino_menu(),
        parse_mode="HTML"
    )

# Обработчик команды /rules
@dp.message(Command(commands=["rules"]))
async def rules_command(message: Message):
    if MAINTENANCE_MODE:
        await message.reply(
            f"{hbold('ТЕХНИЧЕСКИЕ РАБОТЫ')}\n\n"
            f"Бот временно недоступен. Ведутся технические работы. Пожалуйста, попробуйте позже!",
            parse_mode="HTML"
        )
        return
    await send_rules(message)

# Обработчик команды /addcoins
@dp.message(Command(commands=["addcoins"]))
async def add_coins(message: Message):
    if MAINTENANCE_MODE:
        await message.reply(
            f"{hbold('ТЕХНИЧЕСКИЕ РАБОТЫ')}\n\n"
            f"Бот временно недоступен. Ведутся технические работы. Пожалуйста, попробуйте позже!",
            parse_mode="HTML"
        )
        return

    user_id = str(message.from_user.id)
    if user_id not in ADMINS:
        await message.reply(
            f"{hbold('Ошибка:')} Только администраторы могут использовать эту команду!",
            parse_mode="HTML"
        )
        return

    args = message.text.split()
    if len(args) != 3 or not args[2].isdigit():
        await message.reply(
            f"{hbold('Ошибка:')} Используй: /addcoins <username> <amount>",
            parse_mode="HTML"
        )
        return
    
    target_username = args[1].lstrip('@')
    amount = int(args[2])
    
    if amount <= 0:
        await message.reply(
            f"{hbold('Ошибка:')} Сумма должна быть {hunderline('положительной')}",
            parse_mode="HTML"
        )
        return
    
    target_user_id = None
    for uid, data in users.items():
        if data["username"].lower() == target_username.lower():
            target_user_id = uid
            break
    
    if target_user_id is None:
        await message.reply(
            f"{hbold('Ошибка:')} Пользователь @{target_username} не найден",
            parse_mode="HTML"
        )
        return
    
    users[target_user_id]["balance"] += amount
    save_data()
    await message.reply(
        f"{hbold('Успех!')} Добавлено {hbold(str(amount) + ' 💰')} пользователю @{target_username}\n"
        f"Новый баланс: {hbold(str(users[target_user_id]['balance']) + ' 💰')}",
        parse_mode="HTML"
    )

# Риск-игра
async def offer_gamble(user_id, chat_id, winnings):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❤️", callback_data=f"gamble_{user_id}_red_{winnings}"),
         InlineKeyboardButton(text="♠️", callback_data=f"gamble_{user_id}_black_{winnings}")]
    ])
    await bot.send_message(
        chat_id,
        f"{hbold('УДВОИТЬ ВЫИГРЫШ?')}\n\n"
        f"Сейчас: {hbold(str(winnings) + ' 💰')}\n\n"
        f"{hitalic('Выбери цвет:')}",
        reply_markup=keyboard,
        parse_mode="HTML"
    )

# Обработчик callback-запросов
@dp.callback_query()
async def process_callback(callback: CallbackQuery):
    if MAINTENANCE_MODE:
        await callback.message.edit_text(
            f"{hbold('ТЕХНИЧЕСКИЕ РАБОТЫ')}\n\n"
            f"Бот временно недоступен. Ведутся технические работы. Пожалуйста, попробуйте позже!",
            parse_mode="HTML"
        )
        return

    global casino_balance
    user_id = str(callback.from_user.id)
    data = callback.data.split("_")

    if data[0] == "gamble":
        color = data[2]
        winnings = int(data[3])
        correct_color = random.choice(["red", "black"])
        if color == correct_color:
            users[user_id]["balance"] += winnings
            casino_balance -= winnings
            message = f"{hbold('УГАДАЛ!')}\nВыигрыш удвоен: {hbold(str(winnings * 2) + ' 💰')}"
        else:
            casino_balance += winnings
            message = f"{hbold('НЕ УГАДАЛ!')}\nВыигрыш {winnings} 💰 потерян 😔"
        save_data()
        await callback.message.edit_text(
            f"{message}\n\n"
            f"Баланс: {hbold(str(users[user_id]['balance']) + ' 💰')}",
            parse_mode="HTML"
        )

    elif data[0] == "check" and data[1] == "sub":
        user_id = data[2]
        if not users[user_id]["subscribed"]:
            users[user_id]["balance"] += 500
            users[user_id]["subscribed"] = True
            save_data()
            await callback.message.edit_text(
                f"{hbold('СПАСИБО ЗА ПОДПИСКУ!')}\n\n"
                f"Вам начислено {hbold('500 💰')}\n"
                f"Новый баланс: {hbold(str(users[user_id]['balance']) + ' 💰')}",
                parse_mode="HTML"
            )
        else:
            await callback.message.edit_text(
                f"{hbold('Вы уже подписаны!')}\n\n"
                f"Бонус за подписку уже получен.",
                parse_mode="HTML"
            )

    elif data[0] == "show" and data[1] == "full" and data[2] == "leaderboard":
        if not users:
            await callback.message.edit_text(
                f"{hbold('ТАБЛИЦА ЛИДЕРОВ')}\n\n"
                f"Пока нет игроков 😔",
                parse_mode="HTML"
            )
            return
        leaderboard = sorted(
            [(uid, data) for uid, data in users.items() if not data.get("hide_in_leaderboard", False)],
            key=lambda x: x[1]["balance"],
            reverse=True
        )
        response = f"{hbold('ПОЛНАЯ ТАБЛИЦА ЛИДЕРОВ')}\n\n"
        for i, (uid, data) in enumerate(leaderboard, 1):
            nickname = data.get("nickname", data["username"])
            if user_id in ADMINS:
                response += f"  {i}. {nickname} (@{data['username']}): {hbold(str(data['balance']) + ' 💰')}\n"
            else:
                response += f"  {i}. {nickname}: {hbold(str(data['balance']) + ' 💰')}\n"
        response += f"\n{hunderline('СЧЁТ КАЗИНО:')} {hbold(str(casino_balance) + ' 💰')}"
        await callback.message.edit_text(response, parse_mode="HTML")

    elif data[0] == "duel" and data[1] == "game":
        game = data[2]
        current_game[user_id] = {"mode": "duel", "game": game}
        await callback.message.edit_text(
            f"{hbold('ДУЭЛЬ')}\n\n"
            f"Игра выбрана: {game.capitalize()}\n"
            f"Укажите сумму ставки (число):",
            parse_mode="HTML"
        )

    elif data[0] == "duel" and data[1] == "accept":
        duel_id = "_".join(data[2:])
        if duel_id not in duels:
            await callback.message.edit_text(
                f"{hbold('Приглашение устарело!')}\n\n"
                f"Дуэль больше не актуальна.",
                parse_mode="HTML"
            )
            return

        challenger_id = duels[duel_id]["challenger"]
        opponent_id = user_id
        game = duels[duel_id]["game"]
        bet = duels[duel_id]["bet"]

        if users[opponent_id]["balance"] < bet:
            await callback.message.edit_text(
                f"{hbold('Ошибка!')}\n\n"
                f"У вас недостаточно средств для принятия дуэли!",
                parse_mode="HTML"
            )
            await bot.send_message(
                challenger_id,
                f"{hbold('Дуэль отклонена!')}\n\n"
                f"У @{users[opponent_id]['username']} недостаточно средств.",
                parse_mode="HTML"
            )
            del duels[duel_id]
            return

        users[challenger_id]["balance"] -= bet
        users[opponent_id]["balance"] -= bet
        save_data()

        game_names = {
            "dice": "Кубики 🎲",
            "basketball": "Баскетбол 🏀",
            "bowling": "Боулинг 🎳",
            "football": "Футбол ⚽",
            "darts": "Дартс 🎯"
        }

        duels[duel_id]["state"] = "rolling_order"
        duels[duel_id]["challenger_roll"] = None
        duels[duel_id]["opponent_roll"] = None

        await callback.message.edit_text(
            f"{hbold('Дуэль принята!')}\n\n"
            f"Бросьте кубики, чтобы определить порядок хода.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="Бросить кубики", callback_data=f"duel_roll_{duel_id}_{opponent_id}")]
            ]),
            parse_mode="HTML"
        )

        await bot.send_message(
            challenger_id,
            f"{hbold('Дуэль принята!')}\n\n"
            f"Игра: {game_names[game]}\n"
            f"Ставка: {bet} 💰\n"
            f"Бросьте кубики, чтобы определить порядок хода.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="Бросить кубики", callback_data=f"duel_roll_{duel_id}_{challenger_id}")]
            ]),
            parse_mode="HTML"
        )

    elif data[0] == "duel" and data[1] == "decline":
        duel_id = "_".join(data[2:])
        if duel_id not in duels:
            await callback.message.edit_text(
                f"{hbold('Приглашение устарело!')}\n\n"
                f"Дуэль больше не актуальна.",
                parse_mode="HTML"
            )
            return

        challenger_id = duels[duel_id]["challenger"]
        await callback.message.edit_text(
            f"{hbold('Дуэль отклонена!')}\n\n"
            f"Вы отказались от дуэли с @{users[challenger_id]['username']}.",
            parse_mode="HTML"
        )
        await bot.send_message(
            challenger_id,
            f"{hbold('Дуэль отклонена!')}\n\n"
            f"@{users[user_id]['username']} отказался от вашей дуэли.",
            parse_mode="HTML"
        )
        del duels[duel_id]

    elif data[0] == "duel" and data[1] == "roll":
        duel_id = "_".join(data[2:-1])
        player_id = data[-1]

        if duel_id not in duels or duels[duel_id]["state"] != "rolling_order":
            await callback.message.edit_text(
                f"{hbold('Ошибка!')}\n\n"
                f"Дуэль не в стадии определения порядка или завершена.",
                parse_mode="HTML"
            )
            return

        challenger_id = duels[duel_id]["challenger"]
        opponent_id = duels[duel_id]["opponent"]
        other_player_id = opponent_id if player_id == challenger_id else challenger_id

        if (player_id == challenger_id and duels[duel_id]["challenger_roll"] is not None) or \
           (player_id == opponent_id and duels[duel_id]["opponent_roll"] is not None):
            await callback.message.edit_text(
                f"{hbold('Ошибка!')}\n\n"
                f"Вы уже бросили кубики для определения порядка хода!",
                parse_mode="HTML"
            )
            return

        dice = await bot.send_dice(callback.message.chat.id, emoji="🎲")
        await asyncio.sleep(4)
        dice_value = dice.dice.value

        if player_id == challenger_id:
            duels[duel_id]["challenger_roll"] = dice_value
        else:
            duels[duel_id]["opponent_roll"] = dice_value

        await callback.message.edit_text(
            f"{hbold('Вы бросили кубики!')}\n\n"
            f"Ваш результат: {dice_value}",
            parse_mode="HTML"
        )

        await bot.send_message(
            other_player_id,
            f"{hbold('Противник бросил кубики!')}\n\n"
            f"@{users[player_id]['username']} выбросил: {dice_value}",
            parse_mode="HTML"
        )

        if duels[duel_id]["challenger_roll"] is not None and duels[duel_id]["opponent_roll"] is not None:
            challenger_value = duels[duel_id]["challenger_roll"]
            opponent_value = duels[duel_id]["opponent_roll"]

            if challenger_value >= opponent_value:
                first_player = challenger_id
                second_player = opponent_id
            else:
                first_player = opponent_id
                second_player = challenger_id

            duels[duel_id]["state"] = "playing"
            duels[duel_id]["first_player"] = first_player
            duels[duel_id]["second_player"] = second_player
            duels[duel_id]["current_turn"] = first_player

            game_names = {
                "dice": "Кубики 🎲",
                "basketball": "Баскетбол 🏀",
                "bowling": "Боулинг 🎳",
                "football": "Футбол ⚽",
                "darts": "Дартс 🎯"
            }
            game = duels[duel_id]["game"]
            bet = duels[duel_id]["bet"]

            await bot.send_message(
                challenger_id,
                f"{hbold('Дуэль началась!')}\n\n"
                f"Игра: {game_names[game]}\n"
                f"Ставка: {bet} 💰\n"
                f"Первый ход: @{users[first_player]['username']}\n"
                f"Ваш кубик: {challenger_value}, соперник: {opponent_value}",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="Сделать ход", callback_data=f"duel_turn_{duel_id}_{challenger_id}")]
                ]) if first_player == challenger_id else None,
                parse_mode="HTML"
            )
            await bot.send_message(
                opponent_id,
                f"{hbold('Дуэль началась!')}\n\n"
                f"Игра: {game_names[game]}\n"
                f"Ставка: {bet} 💰\n"
                f"Первый ход: @{users[first_player]['username']}\n"
                f"Ваш кубик: {opponent_value}, соперник: {challenger_value}",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="Сделать ход", callback_data=f"duel_turn_{duel_id}_{opponent_id}")]
                ]) if first_player == opponent_id else None,
                parse_mode="HTML"
            )

    elif data[0] == "duel" and data[1] == "turn":
        duel_id = "_".join(data[2:-1])
        player_id = data[-1]

        if duel_id not in duels or duels[duel_id]["state"] != "playing" or duels[duel_id]["current_turn"] != player_id:
            await callback.message.edit_text(
                f"{hbold('Ошибка!')}\n\n"
                f"Сейчас не ваш ход или дуэль завершена.",
                parse_mode="HTML"
            )
            return

        game = duels[duel_id]["game"]
        bet = duels[duel_id]["bet"]
        first_player = duels[duel_id]["first_player"]
        second_player = duels[duel_id]["second_player"]
        opponent_id = first_player if player_id == second_player else second_player

        emoji = {"dice": "🎲", "basketball": "🏀", "bowling": "🎳", "football": "⚽", "darts": "🎯"}[game]
        dice = await bot.send_dice(callback.message.chat.id, emoji=emoji)
        await asyncio.sleep(4)
        value = dice.dice.value

        determine_win = {
            "dice": determine_dice_win,
            "basketball": determine_basketball_win,
            "bowling": determine_bowling_win,
            "football": determine_football_win,
            "darts": determine_darts_win
        }[game]

        winnings, result_message = determine_win(value, bet)

        game_names = {
            "dice": "Кубики 🎲",
            "basketball": "Баскетбол 🏀",
            "bowling": "Боулинг 🎳",
            "football": "Футбол ⚽",
            "darts": "Дартс 🎯"
        }

        if game == "dice":
            await bot.send_message(
                opponent_id,
                f"{hbold('Противник сделал ход!')}\n\n"
                f"@{users[player_id]['username']} выбросил: {value}\n"
                f"{result_message}",
                parse_mode="HTML"
            )
        else:
            await bot.send_message(
                opponent_id,
                f"{hbold('Противник сделал ход!')}\n\n"
                f"@{users[player_id]['username']} сделал ход.\n"
                f"{result_message}",
                parse_mode="HTML"
            )

        if winnings > 0:
            users[player_id]["balance"] += bet * 2
            save_data()
            await bot.send_message(
                player_id,
                f"{hbold('Победа!')}\n\n"
                f"{result_message}\n"
                f"Вы выиграли дуэль в {game_names[game]} и забрали {hbold(f'{bet * 2} 💰')}\n"
                f"Ваш баланс: {hbold(str(users[player_id]['balance']) + ' 💰')}",
                parse_mode="HTML"
            )
            await bot.send_message(
                opponent_id,
                f"{hbold('Поражение!')}\n\n"
                f"@{users[player_id]['username']} выиграл дуэль в {game_names[game]}!\n"
                f"{result_message}\n"
                f"Вы потеряли {hbold(f'{bet} 💰')}\n"
                f"Ваш баланс: {hbold(str(users[opponent_id]['balance']) + ' 💰')}",
                parse_mode="HTML"
            )
            del duels[duel_id]
        else:
            duels[duel_id]["current_turn"] = opponent_id
            await bot.send_message(
                player_id,
                f"{hbold('Ход завершён!')}\n\n"
                f"{result_message}\n"
                f"Ход переходит к @{users[opponent_id]['username']}",
                parse_mode="HTML"
            )
            await bot.send_message(
                opponent_id,
                f"{hbold('Ваш ход!')}\n\n"
                f"@{users[player_id]['username']} промахнулся в {game_names[game]}!\n"
                f"{result_message}",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="Сделать ход", callback_data=f"duel_turn_{duel_id}_{opponent_id}")]
                ]),
                parse_mode="HTML"
            )

# Обработчик текстовых сообщений
@dp.message()
async def handle_game(message: Message):
    if MAINTENANCE_MODE:
        await message.reply(
            f"{hbold('ТЕХНИЧЕСКИЕ РАБОТЫ')}\n\n"
            f"Бот временно недоступен. Ведутся технические работы. Пожалуйста, попробуйте позже!",
            parse_mode="HTML"
        )
        return

    global jackpot, casino_balance
    user_id = str(message.from_user.id)
    username = message.from_user.username or "NoUsername"
    text = message.text.strip()

    if user_id not in users:
        users[user_id] = {
            "balance": STARTING_BALANCE,
            "username": username,
            "freespins": 0,
            "multiplier": 1.0,
            "last_daily_bonus": 0.0,
            "subscribed": False,
            "invited_by": None,
            "hide_in_leaderboard": False
        }
        awaiting_nickname[user_id] = True
        await message.reply(
            f"{hbold('ДОБРО ПОЖАЛОВАТЬ!')}\n\n"
            f"Пожалуйста, введи свой никнейм:",
            parse_mode="HTML"
        )
        return

    if user_id in awaiting_nickname:
        return

    if check_and_add_daily_bonus(user_id):
        await message.reply(
            f"{hbold('ЕЖЕДНЕВНЫЙ БОНУС!')}\n\n"
            f"Вам начислено {hbold('1000 💰')}\n"
            f"Новый баланс: {hbold(str(users[user_id]['balance']) + ' 💰')}",
            parse_mode="HTML"
        )

    if text in ["10 💰", "100 💰", "1000 💰", "Олл-ин 💰", "Своя ставка"] or text.isdigit():
        if not check_spam(user_id):
            await message.reply(
                f"{hbold('СЛИШКОМ БЫСТРО!')}\n\n"
                f"Подожди {SPAM_COOLDOWN} секунды перед следующим действием.",
                parse_mode="HTML"
            )
            return

    # Главное меню
    if text == "Игры 🎮":
        await message.reply(
            f"{hbold('ВЫБЕРИ ИГРУ:')}\n",
            reply_markup=get_game_menu(),
            parse_mode="HTML"
        )
        return

    if text == "Аккаунт 👤":
        await message.reply(
            f"{hbold('АККАУНТ')}\n\n"
            f"Выбери действие:",
            reply_markup=get_account_menu(),
            parse_mode="HTML"
        )
        return

    if text == "Многопользовательское казино 👥":
        await message.reply(
            f"{hbold('МНОГОПОЛЬЗОВАТЕЛЬСКОЕ КАЗИНО')}\n\n"
            f"Выбери режим:",
            reply_markup=get_multiplayer_menu(),
            parse_mode="HTML"
        )
        return

    if text == "Дуэль ⚔️":
        await message.reply(
            f"{hbold('ДУЭЛЬ')}\n\n"
            f"Выберите игру для дуэли:",
            reply_markup=get_duel_game_menu(),
            parse_mode="HTML"
        )
        return

    if text == "Комнаты 🏠":
        await message.reply(
            f"{hbold('КОМНАТЫ')}\n\n"
            f"Пока в разработке 🔧",
            parse_mode="HTML"
        )
        return

    if text == "Назад в казино":
        current_game.pop(user_id, None)
        await message.reply(
            f"{hbold('ВЫБЕРИ РАЗДЕЛ:')}\n",
            reply_markup=get_casino_menu(),
            parse_mode="HTML"
        )
        return

    # Дуэли
    if text.isdigit() and user_id in current_game and current_game[user_id].get("mode") == "duel" and "game" in current_game[user_id]:
        bet = int(text)
        if bet <= 0:
            await message.reply(
                f"{hbold('Ошибка:')} Ставка должна быть больше 0!",
                parse_mode="HTML"
            )
            return
        if users[user_id]["balance"] < bet:
            await message.reply(
                f"{hbold('Ошибка:')} Недостаточно средств на балансе!",
                parse_mode="HTML"
            )
            return
        current_game[user_id]["bet"] = bet
        await message.reply(
            f"{hbold('ПРИГЛАСИ СОПЕРНИКА')}\n\n"
            f"Введите @username игрока:",
            parse_mode="HTML"
        )
        return

    if text.startswith("@") and user_id in current_game and current_game[user_id].get("mode") == "duel" and "bet" in current_game[user_id]:
        target_username = text.lstrip('@')
        target_user_id = None
        for uid, data in users.items():
            if data["username"].lower() == target_username.lower():
                target_user_id = uid
                break

        if target_user_id is None:
            await message.reply(
                f"{hbold('Ошибка:')} Пользователь @{target_username} не найден!",
                parse_mode="HTML"
            )
            return

        if target_user_id == user_id:
            await message.reply(
                f"{hbold('Ошибка:')} Нельзя вызвать самого себя на дуэль!",
                parse_mode="HTML"
            )
            return

        duel_id = f"{user_id}_{target_user_id}_{int(time.time())}"
        game_names = {
            "dice": "Кубики 🎲",
            "basketball": "Баскетбол 🏀",
            "bowling": "Боулинг 🎳",
            "football": "Футбол ⚽",
            "darts": "Дартс 🎯"
        }
        duels[duel_id] = {
            "challenger": user_id,
            "opponent": target_user_id,
            "game": current_game[user_id]["game"],
            "bet": current_game[user_id]["bet"],
            "state": "pending",
            "timestamp": time.time()
        }
        current_game.pop(user_id)

        await message.reply(
            f"{hbold('Приглашение отправлено!')}\n\n"
            f"Ожидайте ответа от @{target_username}.",
            parse_mode="HTML"
        )

        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Принять", callback_data=f"duel_accept_{duel_id}"),
             InlineKeyboardButton(text="Отклонить", callback_data=f"duel_decline_{duel_id}")]
        ])
        await bot.send_message(
            target_user_id,
            f"{hbold('Вас вызвали на дуэль!')}\n\n"
            f"Игрок: @{users[user_id]['username']}\n"
            f"Игра: {game_names[duels[duel_id]['game']]}\n"
            f"Ставка: {duels[duel_id]['bet']} 💰\n"
            f"Приглашение действительно 10 минут.",
            reply_markup=keyboard,
            parse_mode="HTML"
        )

        await asyncio.sleep(600)
        if duel_id in duels and duels[duel_id]["state"] == "pending":
            del duels[duel_id]
            await bot.send_message(
                user_id,
                f"{hbold('Приглашение истекло!')}\n\n"
                f"@{target_username} не ответил на вашу дуэль.",
                parse_mode="HTML"
            )
            await bot.send_message(
                target_user_id,
                f"{hbold('Приглашение истекло!')}\n\n"
                f"Дуэль с @{users[user_id]['username']} больше не актуальна.",
                parse_mode="HTML"
            )
        return

    # Бонусы и аккаунт
    if text == "Бонусы 🎁":
        await message.reply(
            f"{hbold('БОНУСЫ')}\n\n"
            f"Выбери бонус:",
            reply_markup=get_bonus_menu(),
            parse_mode="HTML"
        )
        return

    if text == "Подписка на канал (+500 💰)":
        if users[user_id]["subscribed"]:
            await message.reply(
                f"{hbold('Вы уже подписаны!')}\n\n"
                f"Бонус за подписку уже получен.",
                reply_markup=get_bonus_menu(),
                parse_mode="HTML"
            )
        else:
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="Подписаться", url=TELEGRAM_CHANNEL)],
                [InlineKeyboardButton(text="Проверить подписку", callback_data=f"check_sub_{user_id}")]
            ])
            await message.reply(
                f"{hbold('ПОДПИШИСЬ НА КАНАЛ')}\n\n"
                f"Перейди по ссылке и подпишись, затем нажми 'Проверить подписку':",
                reply_markup=keyboard,
                parse_mode="HTML"
            )
        return

    if text == "Пригласи друга 👤":
        referral_link = get_referral_link(user_id)
        await message.reply(
            f"{hbold('ПРИГЛАСИ ДРУГА')}\n\n"
            f"Ваша реферальная ссылка:\n"
            f"{hunderline(referral_link)}\n\n"
            f"Приглашайте друзей и получайте {hbold(f'{REFERRAL_BONUS} 💰')} за каждого нового игрока!",
            reply_markup=get_bonus_menu(),
            parse_mode="HTML"
        )
        return

    if text == "Таблица лидеров 🏆":
        if not users:
            await message.reply(
                f"{hbold('ТАБЛИЦА ЛИДЕРОВ')}\n\n"
                f"Пока нет игроков 😔",
                parse_mode="HTML"
            )
            return
        leaderboard = sorted(
            [(uid, data) for uid, data in users.items() if not data.get("hide_in_leaderboard", False)],
            key=lambda x: x[1]["balance"],
            reverse=True
        )[:5]
        response = f"{hbold('ТАБЛИЦА ЛИДЕРОВ')}\n\n"
        for i, (uid, data) in enumerate(leaderboard, 1):
            nickname = data.get("nickname", data["username"])
            if user_id in ADMINS:
                response += f"  {i}. {nickname} (@{data['username']}): {hbold(str(data['balance']) + ' 💰')}\n"
            else:
                response += f"  {i}. {nickname}: {hbold(str(data['balance']) + ' 💰')}\n"
        response += f"\n{hunderline('СЧЁТ КАЗИНО:')} {hbold(str(casino_balance) + ' 💰')}"
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Показать всю таблицу", callback_data="show_full_leaderboard")]
        ])
        await message.reply(response, reply_markup=keyboard, parse_mode="HTML")
        return

    if text == "Турниры 🏅":
        await message.reply(
            f"{hbold('ТУРНИРЫ')}\n\n"
            f"Пока в разработке 🔧",
            reply_markup=get_casino_menu(),
            parse_mode="HTML"
        )
        return

    if text == "Назад в аккаунт":
        await message.reply(
            f"{hbold('АККАУНТ')}\n\n"
            f"Выбери действие:",
            reply_markup=get_account_menu(),
            parse_mode="HTML"
        )
        return

    if text == "Передать деньги 💸":
        await message.reply(
            f"{hbold('ПЕРЕДАТЬ ДЕНЬГИ')}\n\n"
            f"Введите @username и сумму через пробел (например, @User 500):",
            parse_mode="HTML"
        )
        return

    if text.startswith("@") and len(text.split()) == 2 and text.split()[1].isdigit():
        sender_id = user_id
        target_username = text.split()[0].lstrip('@')
        amount = int(text.split()[1])

        if amount <= 0:
            await message.reply(
                f"{hbold('Ошибка:')} Сумма должна быть положительной!",
                parse_mode="HTML"
            )
            return

        if users[sender_id]["balance"] < amount:
            await message.reply(
                f"{hbold('Ошибка:')} Недостаточно средств на балансе!",
                parse_mode="HTML"
            )
            return

        target_user_id = None
        for uid, data in users.items():
            if data["username"].lower() == target_username.lower():
                target_user_id = uid
                break

        if target_user_id is None:
            await message.reply(
                f"{hbold('Ошибка:')} Пользователь @{target_username} не найден!",
                parse_mode="HTML"
            )
            return

        if target_user_id == sender_id:
            await message.reply(
                f"{hbold('Ошибка:')} Нельзя перевести деньги самому себе!",
                parse_mode="HTML"
            )
            return

        users[sender_id]["balance"] -= amount
        users[target_user_id]["balance"] += amount
        save_data()

        await message.reply(
            f"{hbold('Успех!')} Вы передали {hbold(f'{amount} 💰')} пользователю @{target_username}\n"
            f"Ваш баланс: {hbold(str(users[sender_id]['balance']) + ' 💰')}",
            reply_markup=get_account_menu(),
            parse_mode="HTML"
        )
        try:
            await bot.send_message(
                target_user_id,
                f"{hbold('Вам передали деньги!')}\n\n"
                f"Пользователь @{users[sender_id]['username']} перевёл вам {hbold(f'{amount} 💰')}\n"
                f"Ваш баланс: {hbold(str(users[target_user_id]['balance']) + ' 💰')}",
                parse_mode="HTML"
            )
        except Exception as e:
            print(f"Ошибка при отправке уведомления {target_user_id}: {e}")
        return

    if text == "Имя ✏️":
        await message.reply(
            f"{hbold('УПРАВЛЕНИЕ ИМЕНЕМ')}\n\n"
            f"Текущий никнейм: {hbold(users[user_id]['nickname'])}\n"
            f"Скрыт в таблице лидеров: {hbold('Да' if users[user_id]['hide_in_leaderboard'] else 'Нет')}",
            reply_markup=get_name_menu(),
            parse_mode="HTML"
        )
        return

    if text == "Сменить никнейм":
        awaiting_nickname[user_id] = True
        await message.reply(
            f"{hbold('СМЕНА НИКНЕЙМА')}\n\n"
            f"Введите новый никнейм:",
            parse_mode="HTML"
        )
        return

    if text == "Скрыть/Показать в таблице лидеров":
        users[user_id]["hide_in_leaderboard"] = not users[user_id]["hide_in_leaderboard"]
        save_data()
        await message.reply(
            f"{hbold('Настройки обновлены!')}\n\n"
            f"Скрыт в таблице лидеров: {hbold('Да' if users[user_id]['hide_in_leaderboard'] else 'Нет')}",
            reply_markup=get_name_menu(),
            parse_mode="HTML"
        )
        return

    # Одиночные игры
    games = {
        "Слоты 🎰": "slot",
        "Кубики 🎲": "dice",
        "Баскетбол 🏀": "basketball",
        "Боулинг 🎳": "bowling",
        "Футбол ⚽": "football",
        "Дартс 🎯": "darts"
    }
    if text in games:
        current_game[user_id] = {"mode": "single", "game": games[text]}
        await message.reply(
            f"{hbold('ВЫБЕРИ СТАВКУ:')}\n",
            reply_markup=get_bet_keyboard(),
            parse_mode="HTML"
        )
        return

    if text == "Назад в меню":
        current_game.pop(user_id, None)
        await message.reply(
            f"{hbold('ВЫБЕРИ ИГРУ:')}\n",
            reply_markup=get_game_menu(),
            parse_mode="HTML"
        )
        return

    if text == "Баланс":
        await message.reply(
            f"{hbold('ТВОЙ БАЛАНС')}\n\n"
            f"  {hbold(str(users[user_id]['balance']) + ' 💰')}\n"
            f"  {hitalic('Фриспины:')} {hbold(str(users[user_id]['freespins']))}",
            reply_markup=get_bet_keyboard() if user_id in current_game else get_casino_menu(),
            parse_mode="HTML"
        )
        return

    if text == "Правила 📜":
        await send_rules(message)
        return

    predefined_bets = ["10 💰", "100 💰", "1000 💰", "Олл-ин 💰"]
    if text in predefined_bets or text == "Своя ставка" or text.isdigit():
        if user_id not in current_game or "game" not in current_game[user_id]:
            await message.reply(
                f"{hbold('Ошибка:')} Сначала выбери игру!\n",
                reply_markup=get_game_menu(),
                parse_mode="HTML"
            )
            return

        if text == "Своя ставка":
            await message.reply(
                f"{hbold('ВВЕДИ СУММУ СТАВКИ')} {hitalic('(число):')}",
                parse_mode="HTML"
            )
            return

        if text in predefined_bets:
            bet = users[user_id]["balance"] if text == "Олл-ин 💰" else int(text.split()[0])
            if bet == 0 and text == "Олл-ин 💰":
                await message.reply(
                    f"{hbold('Ошибка:')} Ваш баланс 0 💰, нечего ставить!",
                    parse_mode="HTML"
                )
                return
        elif text.isdigit():
            bet = int(text)
            if bet <= 0:
                await message.reply(
                    f"{hbold('Ошибка:')} Ставка должна быть {hunderline('больше 0')}",
                    parse_mode="HTML"
                )
                return
        else:
            return

        if users[user_id]["freespins"] > 0:
            bet = 0
            users[user_id]["freespins"] -= 1
        elif users[user_id]["balance"] < bet:
            await message.reply(
                f"{hbold('Ошибка:')} Недостаточно 💰 на балансе!",
                parse_mode="HTML"
            )
            return
        else:
            users[user_id]["balance"] -= bet
            casino_balance += bet
            jackpot += bet // 10

        save_data()

        game = current_game[user_id]["game"]
        emoji = {"slot": "🎰", "dice": "🎲", "basketball": "🏀", "bowling": "🎳", "football": "⚽", "darts": "🎯"}[game]
        data = await bot.send_dice(chat_id=message.chat.id, emoji=emoji)
        dice_value = data.dice.value
        delay = {"slot": 2, "dice": 4, "basketball": 4, "bowling": 4, "football": 4, "darts": 4}[game]

        print(f"Game: {game}, Dice value: {dice_value}")

        await asyncio.sleep(delay)

        if game == "slot":
            winnings, result_message, action = determine_slot_win(dice_value, bet, user_id)
            response = f"{hbold('РЕЗУЛЬТАТ СПИНА')}\n\n" \
                    f"{result_message}\n\n"
            if winnings > 0:
                users[user_id]["balance"] += winnings
                casino_balance -= winnings
                response += f"{hunderline('Выигрыш:')} {hbold(str(winnings) + ' 💰')}\n"
            else:
                response += f"Потеряно: {bet} 💰\n"
            response += f"\n{hitalic('Баланс:')} {hbold(str(users[user_id]['balance']) + ' 💰')}\n" \
                        f"{hitalic('Фриспины:')} {hbold(str(users[user_id]['freespins']))}"
            
            save_data()
            await message.reply(response, reply_markup=get_bet_keyboard(), parse_mode="HTML")
            
            if action == "gamble":
                await offer_gamble(user_id, message.chat.id, winnings)
        else:
            determine_win = {
                "dice": determine_dice_win,
                "basketball": determine_basketball_win,
                "bowling": determine_bowling_win,
                "football": determine_football_win,
                "darts": determine_darts_win
            }
            winnings, result_message = determine_win[game](dice_value, bet)

            response = f"{hbold('РЕЗУЛЬТАТ')}\n\n" \
                    f"{result_message}\n\n"
            if winnings > 0:
                users[user_id]["balance"] += winnings
                casino_balance -= winnings
                response += f"{hunderline('Выигрыш:')} {hbold(str(winnings) + ' 💰')}\n"
            else:
                response += f"Потеряно: {bet} 💰\n"
            response += f"\n{hitalic('Баланс:')} {hbold(str(users[user_id]['balance']) + ' 💰')}"
            save_data()
            await message.reply(response, reply_markup=get_bet_keyboard(), parse_mode="HTML")

# Flask для Render
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is running!"

def run_flask():
    app.run(host='0.0.0.0', port=5000)

# Асинхронная функция для запуска бота
async def main():
    load_data()
    threading.Thread(target=run_flask, daemon=True).start()
    await dp.start_polling(bot)

# Запуск бота
if __name__ == '__main__':
    asyncio.run(main())
