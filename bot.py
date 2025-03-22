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

API_TOKEN = '7537085884:AAGuseMdxP0Uwlhhv4Ltgg3-hmo0EJYkAG4'
bot = Bot(token=API_TOKEN)
dp = Dispatcher()
DATA_FILE = "balances.json"
ADMINS = ["729406890"]
users = {}
STARTING_BALANCE = 1000
jackpot = 5000
casino_balance = 0
current_game = {}
duels = {}
awaiting_nickname = {}
last_action_time = {}
SPAM_COOLDOWN = 2
TELEGRAM_CHANNEL = "https://t.me/your_channel_name"
REFERRAL_BONUS = 50000
MAINTENANCE_MODE = False

def load_data():
    global users, jackpot, casino_balance
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            users = data.get("users", {})
            jackpot = data.get("jackpot", 5000)
            casino_balance = data.get("casino_balance", 0)
            for user_id, user_data in users.items():
                if "nickname" not in user_data: user_data["nickname"] = user_data["username"]
                if "last_daily_bonus" not in user_data: user_data["last_daily_bonus"] = 0.0
                if "subscribed" not in user_data: user_data["subscribed"] = False
                if "invited_by" not in user_data: user_data["invited_by"] = None
                if "hide_in_leaderboard" not in user_data: user_data["hide_in_leaderboard"] = False
    else:
        users = {}
        jackpot = 5000
        casino_balance = 0

def save_data():
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump({"users": users, "jackpot": jackpot, "casino_balance": casino_balance}, f, ensure_ascii=False, indent=4)

def check_spam(user_id):
    current_time = time.time()
    last_time = last_action_time.get(user_id, 0)
    if current_time - last_time < SPAM_COOLDOWN: return False
    last_action_time[user_id] = current_time
    return True

def check_and_add_daily_bonus(user_id):
    current_time = time.time()
    last_bonus = users[user_id].get("last_daily_bonus", 0.0)
    if current_time - last_bonus >= 86400:
        users[user_id]["balance"] += 1000
        users[user_id]["last_daily_bonus"] = current_time
        save_data()
        return True
    return False

def get_referral_link(user_id):
    return f"t.me/{bot._me.username}?start=ref_{user_id}"

async def process_referral(referrer_id, new_user_id):
    if referrer_id == new_user_id: return
    if referrer_id in users and users[referrer_id].get("balance") is not None:
        users[referrer_id]["balance"] += REFERRAL_BONUS
        save_data()
        await bot.send_message(referrer_id, f"{hbold('НОВЫЙ РЕФЕРАЛ!')}\n\nВы пригласили друга и получили {hbold(f'{REFERRAL_BONUS} 💰')}\nВаш баланс: {hbold(str(users[referrer_id]['balance']) + ' 💰')}", parse_mode="HTML")

def get_combo_text(dice_value: int):
    values = ["BAR", "🍇", "🍋", "7"]
    dice_value -= 1
    result = []
    for _ in range(3):
        result.append(values[dice_value % 4])
        dice_value //= 4
    return result

def determine_slot_win(dice_value, bet, user_id):
    global jackpot, casino_balance
    winnings = 0
    combo = get_combo_text(dice_value)
    message = f"Комбинация: {combo[0]} {combo[1]} {combo[2]}\n"
    freespins = users[user_id].get("freespins", 0)
    if combo == ["7", "7", "7"]: winnings, freespins, message = bet * 10, freespins + 3, message + f"{hbold('ТРИ СЕМЁРКИ!')}\n{hunderline('+3 фриспина')}"
    elif combo == ["🍋", "🍋", "🍋"]: winnings, message = bet * 5 * (2 if freespins > 0 else 1), message + f"{hbold('ВЫИГРЫШ!')} {hitalic('Три лимона')}"
    elif combo == ["BAR", "BAR", "BAR"]: winnings, message = bet * 8, message + f"{hbold('ВЫИГРЫШ!')} {hitalic('Три BAR')}"
    elif combo == ["🍇", "🍇", "🍇"]: winnings, message = bet * 6, message + f"{hbold('ВЫИГРЫШ!')} {hitalic('Три винограда')}"
    elif combo[0] == "7" and combo[1] == "7": winnings, message = bet * 5, message + f"{hbold('ВЫИГРЫШ!')} {hitalic('Две семёрки в начале')}"
    else: message += "Увы, нет выигрыша 😔"
    if random.random() < 0.05:
        bonus = random.randint(1, 3)
        if bonus <= 2: winnings, message = winnings + bonus * bet, message + f"\n{hbold('СЛУЧАЙНЫЙ БОНУС:')} {hitalic(f'+{bonus * bet} 💰')}"
        else: freespins, message = freespins + 1, message + f"\n{hbold('СЛУЧАЙНЫЙ БОНУС:')} {hunderline('+1 фриспин')}"
    users[user_id]["freespins"] = freespins
    return winnings, message, "gamble" if winnings > 0 and random.random() < 0.5 else None

def determine_dice_win(value, bet):
    if value == 6: return bet * 3, f"{hbold('ШЕСТЁРКА!')}\n{hitalic('Отличный бросок')}"
    elif value == 5: return bet * 2, f"{hbold('ХОРОШИЙ БРОСОК!')}\n{hitalic('Неплохо')}"
    return 0, "Увы, нет выигрыша 😔"

def determine_darts_win(value, bet):
    if value == 6: return bet * 5, f"{hbold('В ЯБЛОЧКО!')}\n{hitalic('Отличный бросок')}"
    return 0, "Мимо 😔"

def determine_basketball_win(value, bet):
    if value in [4, 5]: return bet * 3, f"{hbold('В КОЛЬЦО!')}\n{hitalic('Классный бросок')}"
    return 0, "Мимо 😔"

def determine_football_win(value, bet):
    if value in [3, 4, 5]: return bet * 3, f"{hbold('ГОЛ!')}\n{hitalic('Отличный удар')}"
    return 0, "Мимо ворот 😔"

def determine_bowling_win(value, bet):
    if value == 6: return bet * 5, f"{hbold('СТРАЙК!')}\n{hitalic('Идеальный бросок')}"
    return 0, "Промах 😔"

def get_casino_menu():
    builder = ReplyKeyboardBuilder()
    builder.button(text="Игры 🎮"); builder.button(text="Аккаунт 👤")
    builder.button(text="Многопользовательское казино 👥"); builder.button(text="Таблица лидеров 🏆")
    builder.button(text="Турниры 🏅")
    builder.adjust(2)
    return builder.as_markup(resize_keyboard=True)

def get_game_menu():
    builder = ReplyKeyboardBuilder()
    builder.button(text="Слоты 🎰"); builder.button(text="Кубики 🎲")
    builder.button(text="Баскетбол 🏀"); builder.button(text="Боулинг 🎳")
    builder.button(text="Футбол ⚽"); builder.button(text="Дартс 🎯")
    builder.button(text="Назад в казино")
    builder.adjust(2)
    return builder.as_markup(resize_keyboard=True)

def get_bet_keyboard():
    builder = ReplyKeyboardBuilder()
    builder.button(text="10 💰"); builder.button(text="100 💰")
    builder.button(text="1000 💰"); builder.button(text="Олл-ин 💰")
    builder.button(text="Своя ставка"); builder.button(text="Баланс")
    builder.button(text="Правила 📜"); builder.button(text="Назад в меню")
    builder.adjust(2)
    return builder.as_markup(resize_keyboard=True)

def get_account_menu():
    builder = ReplyKeyboardBuilder()
    builder.button(text="Бонусы 🎁"); builder.button(text="Передать деньги 💸")
    builder.button(text="Имя ✏️"); builder.button(text="Назад в казино")
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
    builder.button(text="Дуэль ⚔️"); builder.button(text="Комнаты 🏠")
    builder.button(text="Назад в казино")
    builder.adjust(2)
    return builder.as_markup(resize_keyboard=True)

def get_duel_game_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Кубики 🎲", callback_data="duel_game_dice"), InlineKeyboardButton(text="Баскетбол 🏀", callback_data="duel_game_basketball")],
        [InlineKeyboardButton(text="Боулинг 🎳", callback_data="duel_game_bowling"), InlineKeyboardButton(text="Футбол ⚽", callback_data="duel_game_football")],
        [InlineKeyboardButton(text="Дартс 🎯", callback_data="duel_game_darts")]
    ])

async def send_rules(message: Message):
    rules = f"{hbold('ПРАВИЛА ИГРЫ')}\n\n{hunderline('СЛОТЫ')}\nСимволы: 7 BAR 🍋 🍇\n{hbold('КОМБИНАЦИИ:')}\n    Три 🍋: {hitalic('x5 ставки (x2 во фриспинах)')}\n    Три BAR: {hitalic('x8 ставки')}\n    Три 🍇: {hitalic('x6 ставки')}\n    Две 7 в начале: {hitalic('x5 ставки')}\n    Три 7: {hitalic('x10 ставки, +3 фриспина')}\n{hbold('СЛУЧАЙНЫЙ БОНУС:')} {hitalic('5% шанс на +1-3x ставки 💰 или +1 фриспин')}\n{hbold('РИСК-ИГРА:')} {hitalic('50% шанс удвоить выигрыш (❤️ или ♠️)')}\n\nКУБИКИ: {hitalic('6 — x3, 5 — x2')}\nДАРТС: {hitalic('6 — x5')}\nБАСКЕТБОЛ: {hitalic('4 или 5 — x3')}\nФУТБОЛ: {hitalic('3, 4 или 5 — x3')}\nБОУЛИНГ: {hitalic('6 — x5')}\n\n{hitalic('Используй /rules для повторного просмотра!')}"
    await message.reply(rules, parse_mode="HTML")

@dp.message(Command(commands=["start"]))
async def start_command(message: Message):
    if MAINTENANCE_MODE: return await message.reply(f"{hbold('ТЕХНИЧЕСКИЕ РАБОТЫ')}\n\nБот временно недоступен.", parse_mode="HTML")
    user_id = str(message.from_user.id)
    username = message.from_user.username or "NoUsername"
    args = message.text.split()
    referrer_id = args[1].replace("ref_", "") if len(args) > 1 and args[1].startswith("ref_") else None
    if user_id not in users:
        users[user_id] = {"balance": STARTING_BALANCE, "username": username, "freespins": 0, "multiplier": 1.0, "last_daily_bonus": 0.0, "subscribed": False, "invited_by": referrer_id, "hide_in_leaderboard": False}
        awaiting_nickname[user_id] = True
        await message.reply(f"{hbold('ДОБРО ПОЖАЛОВАТЬ!')}\n\nПожалуйста, введи свой никнейм:", parse_mode="HTML")
        if referrer_id: await process_referral(referrer_id, user_id)
    else:
        bonus = check_and_add_daily_bonus(user_id)
        await message.reply(f"{hbold('ЕЖЕДНЕВНЫЙ БОНУС!')}\n\nВам начислено {hbold('1000 💰')}\nНовый баланс: {hbold(str(users[user_id]['balance']) + ' 💰')}\n\n{hbold('ВЫБЕРИ РАЗДЕЛ:')}" if bonus else f"{hbold('ВЫБЕРИ РАЗДЕЛ:')}\n", reply_markup=get_casino_menu(), parse_mode="HTML")

@dp.message(lambda message: str(message.from_user.id) in awaiting_nickname and not MAINTENANCE_MODE)
async def set_nickname(message: Message):
    user_id = str(message.from_user.id)
    nickname = message.text.strip()
    if len(nickname) > 20: return await message.reply(f"{hbold('Ошибка:')} Никнейм слишком длинный (максимум 20 символов)!", parse_mode="HTML")
    users[user_id]["nickname"] = nickname
    del awaiting_nickname[user_id]
    save_data()
    await message.reply(f"{hbold('Никнейм установлен:')} {nickname}\n\n{hbold('ВЫБЕРИ РАЗДЕЛ:')}\n", reply_markup=get_casino_menu(), parse_mode="HTML")

@dp.message(Command(commands=["rules"]))
async def rules_command(message: Message):
    if MAINTENANCE_MODE: return await message.reply(f"{hbold('ТЕХНИЧЕСКИЕ РАБОТЫ')}\n\nБот временно недоступен.", parse_mode="HTML")
    await send_rules(message)

@dp.message(Command(commands=["addcoins"]))
async def add_coins(message: Message):
    if MAINTENANCE_MODE: return await message.reply(f"{hbold('ТЕХНИЧЕСКИЕ РАБОТЫ')}\n\nБот временно недоступен.", parse_mode="HTML")
    user_id = str(message.from_user.id)
    if user_id not in ADMINS: return await message.reply(f"{hbold('Ошибка:')} Только администраторы могут использовать эту команду!", parse_mode="HTML")
    args = message.text.split()
    if len(args) != 3 or not args[2].isdigit(): return await message.reply(f"{hbold('Ошибка:')} Используй: /addcoins <username> <amount>", parse_mode="HTML")
    target_username, amount = args[1].lstrip('@'), int(args[2])
    if amount <= 0: return await message.reply(f"{hbold('Ошибка:')} Сумма должна быть {hunderline('положительной')}", parse_mode="HTML")
    target_user_id = next((uid for uid, data in users.items() if data["username"].lower() == target_username.lower()), None)
    if not target_user_id: return await message.reply(f"{hbold('Ошибка:')} Пользователь @{target_username} не найден", parse_mode="HTML")
    users[target_user_id]["balance"] += amount
    save_data()
    await message.reply(f"{hbold('Успех!')} Добавлено {hbold(str(amount) + ' 💰')} пользователю @{target_username}\nНовый баланс: {hbold(str(users[target_user_id]['balance']) + ' 💰')}", parse_mode="HTML")

async def offer_gamble(user_id, chat_id, winnings):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❤️", callback_data=f"gamble_{user_id}_red_{winnings}"), InlineKeyboardButton(text="♠️", callback_data=f"gamble_{user_id}_black_{winnings}")]])
    await bot.send_message(chat_id, f"{hbold('УДВОИТЬ ВЫИГРЫШ?')}\n\nСейчас: {hbold(str(winnings) + ' 💰')}\n\n{hitalic('Выбери цвет:')}", reply_markup=keyboard, parse_mode="HTML")

@dp.callback_query()
async def process_callback(callback: CallbackQuery):
    if MAINTENANCE_MODE: return await callback.message.edit_text(f"{hbold('ТЕХНИЧЕСКИЕ РАБОТЫ')}\n\nБот временно недоступен.", parse_mode="HTML")
    global casino_balance
    user_id = str(callback.from_user.id)
    data = callback.data.split("_")
    if data[0] == "gamble":
        color, winnings = data[2], int(data[3])
        correct_color = random.choice(["red", "black"])
        message = f"{hbold('УГАДАЛ!')}\nВыигрыш удвоен: {hbold(str(winnings * 2) + ' 💰')}" if color == correct_color else f"{hbold('НЕ УГАДАЛ!')}\nВыигрыш {winnings} 💰 потерян 😔"
        if color == correct_color: users[user_id]["balance"] += winnings; casino_balance -= winnings
        else: casino_balance += winnings
        save_data()
        await callback.message.edit_text(f"{message}\n\nБаланс: {hbold(str(users[user_id]['balance']) + ' 💰')}", parse_mode="HTML")
    elif data[0] == "check" and data[1] == "sub":
        user_id = data[2]
        if not users[user_id]["subscribed"]:
            users[user_id]["balance"] += 500; users[user_id]["subscribed"] = True; save_data()
            await callback.message.edit_text(f"{hbold('СПАСИБО ЗА ПОДПИСКУ!')}\n\nВам начислено {hbold('500 💰')}\nНовый баланс: {hbold(str(users[user_id]['balance']) + ' 💰')}", parse_mode="HTML")
        else:
            await callback.message.edit_text(f"{hbold('Вы уже подписаны!')}\n\nБонус за подписку уже получен.", parse_mode="HTML")
    elif data[0] == "show" and data[1] == "full" and data[2] == "leaderboard":
        if not users: return await callback.message.edit_text(f"{hbold('ТАБЛИЦА ЛИДЕРОВ')}\n\nПока нет игроков 😔", parse_mode="HTML")
        leaderboard = sorted([(uid, data) for uid, data in users.items() if not data.get("hide_in_leaderboard", False)], key=lambda x: x[1]["balance"], reverse=True)
        response = f"{hbold('ПОЛНАЯ ТАБЛИЦА ЛИДЕРОВ')}\n\n" + "".join(f"  {i}. {data.get('nickname', data['username'])} (@{data['username']}): {hbold(str(data['balance']) + ' 💰')}\n" if user_id in ADMINS else f"  {i}. {data.get('nickname', data['username'])}: {hbold(str(data['balance']) + ' 💰')}\n" for i, (uid, data) in enumerate(leaderboard, 1)) + f"\n{hunderline('СЧЁТ КАЗИНО:')} {hbold(str(casino_balance) + ' 💰')}"
        await callback.message.edit_text(response, parse_mode="HTML")
    elif data[0] == "duel" and data[1] == "game":
        game = data[2]
        current_game[user_id] = {"mode": "duel", "game": game}
        await callback.message.edit_text(f"{hbold('ДУЭЛЬ')}\n\nИгра выбрана: {game.capitalize()}\nУкажите сумму ставки (число):", parse_mode="HTML")
    elif data[0] == "duel" and data[1] == "accept":
        duel_id = "_".join(data[2:])
        if duel_id not in duels: return await callback.message.edit_text(f"{hbold('Приглашение устарело!')}\n\nДуэль больше не актуальна.", parse_mode="HTML")
        challenger_id, opponent_id, game, bet = duels[duel_id]["challenger"], user_id, duels[duel_id]["game"], duels[duel_id]["bet"]
        if users[opponent_id]["balance"] < bet:
            await callback.message.edit_text(f"{hbold('Ошибка!')}\n\nУ вас недостаточно средств для принятия дуэли!", parse_mode="HTML")
            await bot.send_message(challenger_id, f"{hbold('Дуэль отклонена!')}\n\nУ @{users[opponent_id]['username']} недостаточно средств.", parse_mode="HTML")
            del duels[duel_id]
            return
        users[challenger_id]["balance"] -= bet; users[opponent_id]["balance"] -= bet; save_data()
        game_names = {"dice": "Кубики 🎲", "basketball": "Баскетбол 🏀", "bowling": "Боулинг 🎳", "football": "Футбол ⚽", "darts": "Дартс 🎯"}
        duels[duel_id]["state"] = "rolling_order"; duels[duel_id]["challenger_roll"] = None; duels[duel_id]["opponent_roll"] = None
        await callback.message.edit_text(f"{hbold('Дуэль принята!')}\n\nБросьте кубики, чтобы определить порядок хода.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Бросить кубики", callback_data=f"duel_roll_{duel_id}_{opponent_id}")]]), parse_mode="HTML")
        await bot.send_message(challenger_id, f"{hbold('Дуэль принята!')}\n\nИгра: {game_names[game]}\nСтавка: {bet} 💰\nБросьте кубики, чтобы определить порядок хода.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Бросить кубики", callback_data=f"duel_roll_{duel_id}_{challenger_id}")]]), parse_mode="HTML")
    elif data[0] == "duel" and data[1] == "decline":
        duel_id = "_".join(data[2:])
        if duel_id not in duels: return await callback.message.edit_text(f"{hbold('Приглашение устарело!')}\n\nДуэль больше не актуальна.", parse_mode="HTML")
        challenger_id = duels[duel_id]["challenger"]
        await callback.message.edit_text(f"{hbold('Дуэль отклонена!')}\n\nВы отказались от дуэли с @{users[challenger_id]['username']}.", parse_mode="HTML")
        await bot.send_message(challenger_id, f"{hbold('Дуэль отклонена!')}\n\n@{users[user_id]['username']} отказался от вашей дуэли.", parse_mode="HTML")
        del duels[duel_id]
    elif data[0] == "duel" and data[1] == "roll":
        duel_id, player_id = "_".join(data[2:-1]), data[-1]
        if duel_id not in duels or duels[duel_id]["state"] != "rolling_order": return await callback.message.edit_text(f"{hbold('Ошибка!')}\n\nДуэль не в стадии определения порядка или завершена.", parse_mode="HTML")
        challenger_id, opponent_id = duels[duel_id]["challenger"], duels[duel_id]["opponent"]
        other_player_id = opponent_id if player_id == challenger_id else challenger_id
        if (player_id == challenger_id and duels[duel_id]["challenger_roll"]) or (player_id == opponent_id and duels[duel_id]["opponent_roll"]): return await callback.message.edit_text(f"{hbold('Ошибка!')}\n\nВы уже бросили кубики для определения порядка хода!", parse_mode="HTML")
        dice = await bot.send_dice(callback.message.chat.id, emoji="🎲"); await asyncio.sleep(4); dice_value = dice.dice.value
        if player_id == challenger_id: duels[duel_id]["challenger_roll"] = dice_value
        else: duels[duel_id]["opponent_roll"] = dice_value
        await callback.message.edit_text(f"{hbold('Вы бросили кубики!')}\n\nВаш результат: {dice_value}", parse_mode="HTML")
        await bot.send_message(other_player_id, f"{hbold('Противник бросил кубики!')}\n\n@{users[player_id]['username']} выбросил: {dice_value}", parse_mode="HTML")
        if duels[duel_id]["challenger_roll"] and duels[duel_id]["opponent_roll"]:
            challenger_value, opponent_value = duels[duel_id]["challenger_roll"], duels[duel_id]["opponent_roll"]
            first_player, second_player = (challenger_id, opponent_id) if challenger_value >= opponent_value else (opponent_id, challenger_id)
            duels[duel_id]["state"] = "playing"; duels[duel_id]["first_player"] = first_player; duels[duel_id]["second_player"] = second_player; duels[duel_id]["current_turn"] = first_player
            game_names = {"dice": "Кубики 🎲", "basketball": "Баскетбол 🏀", "bowling": "Боулинг 🎳", "football": "Футбол ⚽", "darts": "Дартс 🎯"}
            game, bet = duels[duel_id]["game"], duels[duel_id]["bet"]
            await bot.send_message(challenger_id, f"{hbold('Дуэль началась!')}\n\nИгра: {game_names[game]}\nСтавка: {bet} 💰\nПервый ход: @{users[first_player]['username']}\nВаш кубик: {challenger_value}, соперник: {opponent_value}", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Сделать ход", callback_data=f"duel_turn_{duel_id}_{challenger_id}")]]) if first_player == challenger_id else None, parse_mode="HTML")
            await bot.send_message(opponent_id, f"{hbold('Дуэль началась!')}\n\nИгра: {game_names[game]}\nСтавка: {bet} 💰\nПервый ход: @{users[first_player]['username']}\nВаш кубик: {opponent_value}, соперник: {challenger_value}", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Сделать ход", callback_data=f"duel_turn_{duel_id}_{opponent_id}")]]) if first_player == opponent_id else None, parse_mode="HTML")
    elif data[0] == "duel" and data[1] == "turn":
        duel_id, player_id = "_".join(data[2:-1]), data[-1]
        if duel_id not in duels or duels[duel_id]["state"] != "playing" or duels[duel_id]["current_turn"] != player_id: return await callback.message.edit_text(f"{hbold('Ошибка!')}\n\nСейчас не ваш ход или дуэль завершена.", parse_mode="HTML")
        game, bet, first_player, second_player = duels[duel_id]["game"], duels[duel_id]["bet"], duels[duel_id]["first_player"], duels[duel_id]["second_player"]
        opponent_id = first_player if player_id == second_player else second_player
        emoji = {"dice": "🎲", "basketball": "🏀", "bowling": "🎳", "football": "⚽", "darts": "🎯"}[game]
        dice = await bot.send_dice(callback.message.chat.id, emoji=emoji); await asyncio.sleep(4); value = dice.dice.value
        determine_win = {"dice": determine_dice_win, "basketball": determine_basketball_win, "bowling": determine_bowling_win, "football": determine_football_win, "darts": determine_darts_win}[game]
        winnings, result_message = determine_win(value, bet)
        game_names = {"dice": "Кубики 🎲", "basketball": "Баскетбол 🏀", "bowling": "Боулинг 🎳", "football": "Футбол ⚽", "darts": "Дартс 🎯"}
        await bot.send_message(opponent_id, f"{hbold('Противник сделал ход!')}\n\n@{users[player_id]['username']} выбросил: {value}\n{result_message}" if game == "dice" else f"{hbold('Противник сделал ход!')}\n\n@{users[player_id]['username']} сделал ход.\n{result_message}", parse_mode="HTML")
        if winnings > 0:
            users[player_id]["balance"] += bet * 2; save_data()
            await bot.send_message(player_id, f"{hbold('Победа!')}\n\n{result_message}\nВы выиграли дуэль в {game_names[game]} и забрали {hbold(f'{bet * 2} 💰')}\nВаш баланс: {hbold(str(users[player_id]['balance']) + ' 💰')}", parse_mode="HTML")
            await bot.send_message(opponent_id, f"{hbold('Поражение!')}\n\n@{users[player_id]['username']} выиграл дуэль в {game_names[game]}!\n{result_message}\nВы потеряли {hbold(f'{bet} 💰')}\nВаш баланс: {hbold(str(users[opponent_id]['balance']) + ' 💰')}", parse_mode="HTML")
            del duels[duel_id]
        else:
            duels[duel_id]["current_turn"] = opponent_id
            await bot.send_message(player_id, f"{hbold('Ход завершён!')}\n\n{result_message}\nХод переходит к @{users[opponent_id]['username']}", parse_mode="HTML")
            await bot.send_message(opponent_id, f"{hbold('Ваш ход!')}\n\n@{users[player_id]['username']} промахнулся в {game_names[game]}!\n{result_message}", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Сделать ход", callback_data=f"duel_turn_{duel_id}_{opponent_id}")]]), parse_mode="HTML")

@dp.message()
async def handle_game(message: Message):
    if MAINTENANCE_MODE: return await message.reply(f"{hbold('ТЕХНИЧЕСКИЕ РАБОТЫ')}\n\nБот временно недоступен.", parse_mode="HTML")
    global jackpot, casino_balance
    user_id = str(message.from_user.id)
    username = message.from_user.username or "NoUsername"
    text = message.text.strip()
    if user_id not in users:
        users[user_id] = {"balance": STARTING_BALANCE, "username": username, "freespins": 0, "multiplier": 1.0, "last_daily_bonus": 0.0, "subscribed": False, "invited_by": None, "hide_in_leaderboard": False}
        awaiting_nickname[user_id] = True
        return await message.reply(f"{hbold('ДОБРО ПОЖАЛОВАТЬ!')}\n\nПожалуйста, введи свой никнейм:", parse_mode="HTML")
    if user_id in awaiting_nickname: return
    if check_and_add_daily_bonus(user_id): await message.reply(f"{hbold('ЕЖЕДНЕВНЫЙ БОНУС!')}\n\nВам начислено {hbold('1000 💰')}\nНовый баланс: {hbold(str(users[user_id]['balance']) + ' 💰')}", parse_mode="HTML")
    if text in ["10 💰", "100 💰", "1000 💰", "Олл-ин 💰", "Своя ставка"] or text.isdigit():
        if not check_spam(user_id): return await message.reply(f"{hbold('СЛИШКОМ БЫСТРО!')}\n\nПодожди {SPAM_COOLDOWN} секунды перед следующим действием.", parse_mode="HTML")
    if text == "Игры 🎮": return await message.reply(f"{hbold('ВЫБЕРИ ИГРУ:')}\n", reply_markup=get_game_menu(), parse_mode="HTML")
    if text == "Аккаунт 👤": return await message.reply(f"{hbold('АККАУНТ')}\n\nВыбери действие:", reply_markup=get_account_menu(), parse_mode="HTML")
    if text == "Многопользовательское казино 👥": return await message.reply(f"{hbold('МНОГОПОЛЬЗОВАТЕЛЬСКОЕ КАЗИНО')}\n\nВыбери режим:", reply_markup=get_multiplayer_menu(), parse_mode="HTML")
    if text == "Дуэль ⚔️": return await message.reply(f"{hbold('ДУЭЛЬ')}\n\nВыберите игру для дуэли:", reply_markup=get_duel_game_menu(), parse_mode="HTML")
    if text == "Комнаты 🏠": return await message.reply(f"{hbold('КОМНАТЫ')}\n\nПока в разработке 🔧", parse_mode="HTML")
    if text == "Назад в казино": current_game.pop(user_id, None); return await message.reply(f"{hbold('ВЫБЕРИ РАЗДЕЛ:')}\n", reply_markup=get_casino_menu(), parse_mode="HTML")
    if text.isdigit() and user_id in current_game and current_game[user_id].get("mode") == "duel" and "game" in current_game[user_id]:
        bet = int(text)
        if bet <= 0: return await message.reply(f"{hbold('Ошибка:')} Ставка должна быть больше 0!", parse_mode="HTML")
        if users[user_id]["balance"] < bet: return await message.reply(f"{hbold('Ошибка:')} Недостаточно средств на балансе!", parse_mode="HTML")
        current_game[user_id]["bet"] = bet
        return await message.reply(f"{hbold('ПРИГЛАСИ СОПЕРНИКА')}\n\nВведите @username игрока:", parse_mode="HTML")
    if text.startswith("@") and user_id in current_game and current_game[user_id].get("mode") == "duel" and "bet" in current_game[user_id]:
        target_username = text.lstrip('@')
        target_user_id = next((uid for uid, data in users.items() if data["username"].lower() == target_username.lower()), None)
        if not target_user_id: return await message.reply(f"{hbold('Ошибка:')} Пользователь @{target_username} не найден!", parse_mode="HTML")
        if target_user_id == user_id: return await message.reply(f"{hbold('Ошибка:')} Нельзя вызвать самого себя на дуэль!", parse_mode="HTML")
        duel_id = f"{user_id}_{target_user_id}_{int(time.time())}"
        game_names = {"dice": "Кубики 🎲", "basketball": "Баскетбол 🏀", "bowling": "Боулинг 🎳", "football": "Футбол ⚽", "darts": "Дартс 🎯"}
        duels[duel_id] = {"challenger": user_id, "opponent": target_user_id, "game": current_game[user_id]["game"], "bet": current_game[user_id]["bet"], "state": "pending", "timestamp": time.time()}
        current_game.pop(user_id)
        await message.reply(f"{hbold('Приглашение отправлено!')}\n\nОжидайте ответа от @{target_username}.", parse_mode="HTML")
        keyboard = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Принять", callback_data=f"duel_accept_{duel_id}"), InlineKeyboardButton(text="Отклонить", callback_data=f"duel_decline_{duel_id}")]])
        await bot.send_message(target_user_id, f"{hbold('Вас вызвали на дуэль!')}\n\nИгрок: @{users[user_id]['username']}\nИгра: {game_names[duels[duel_id]['game']]}\nСтавка: {duels[duel_id]['bet']} 💰\nПриглашение действительно 10 минут.", reply_markup=keyboard, parse_mode="HTML")
        await asyncio.sleep(600)
        if duel_id in duels and duels[duel_id]["state"] == "pending":
            del duels[duel_id]
            await bot.send_message(user_id, f"{hbold('Приглашение истекло!')}\n\n@{target_username} не ответил на вашу дуэль.", parse_mode="HTML")
            await bot.send_message(target_user_id, f"{hbold('Приглашение истекло!')}\n\nДуэль с @{users[user_id]['username']} больше не актуальна.", parse_mode="HTML")
        return
    if text == "Бонусы 🎁": return await message.reply(f"{hbold('БОНУСЫ')}\n\nВыбери бонус:", reply_markup=get_bonus_menu(), parse_mode="HTML")
    if text == "Подписка на канал (+500 💰)":
        if users[user_id]["subscribed"]: return await message.reply(f"{hbold('Вы уже подписаны!')}\n\nБонус за подписку уже получен.", reply_markup=get_bonus_menu(), parse_mode="HTML")
        keyboard = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Подписаться", url=TELEGRAM_CHANNEL)], [InlineKeyboardButton(text="Проверить подписку", callback_data=f"check_sub_{user_id}")]])
        return await message.reply(f"{hbold('ПОДПИШИСЬ НА КАНАЛ')}\n\nПерейди по ссылке и подпишись, затем нажми 'Проверить подписку':", reply_markup=keyboard, parse_mode="HTML")
    if text == "Пригласи друга 👤": return await message.reply(f"{hbold('ПРИГЛАСИ ДРУГА')}\n\nВаша реферальная ссылка:\n{hunderline(get_referral_link(user_id))}\n\nПриглашайте друзей и получайте {hbold(f'{REFERRAL_BONUS} 💰')} за каждого нового игрока!", reply_markup=get_bonus_menu(), parse_mode="HTML")
    if text == "Таблица лидеров 🏆":
        if not users: return await message.reply(f"{hbold('ТАБЛИЦА ЛИДЕРОВ')}\n\nПока нет игроков 😔", parse_mode="HTML")
        leaderboard = sorted([(uid, data) for uid, data in users.items() if not data.get("hide_in_leaderboard", False)], key=lambda x: x[1]["balance"], reverse=True)[:5]
        response = f"{hbold('ТАБЛИЦА ЛИДЕРОВ')}\n\n" + "".join(f"  {i}. {data.get('nickname', data['username'])} (@{data['username']}): {hbold(str(data['balance']) + ' 💰')}\n" if user_id in ADMINS else f"  {i}. {data.get('nickname', data['username'])}: {hbold(str(data['balance']) + ' 💰')}\n" for i, (uid, data) in enumerate(leaderboard, 1)) + f"\n{hunderline('СЧЁТ КАЗИНО:')} {hbold(str(casino_balance) + ' 💰')}"
        keyboard = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Показать всю таблицу", callback_data="show_full_leaderboard")]])
        return await message.reply(response, reply_markup=keyboard, parse_mode="HTML")
    if text == "Турниры 🏅": return await message.reply(f"{hbold('ТУРНИРЫ')}\n\nПока в разработке 🔧", reply_markup=get_casino_menu(), parse_mode="HTML")
    if text == "Назад в аккаунт": return await message.reply(f"{hbold('АККАУНТ')}\n\nВыбери действие:", reply_markup=get_account_menu(), parse_mode="HTML")
    if text == "Передать деньги 💸": return await message.reply(f"{hbold('ПЕРЕДАТЬ ДЕНЬГИ')}\n\nВведите @username и сумму через пробел (например, @User 500):", parse_mode="HTML")
    if text.startswith("@") and len(text.split()) == 2 and text.split()[1].isdigit():
        sender_id, target_username, amount = user_id, text.split()[0].lstrip('@'), int(text.split()[1])
        if amount <= 0: return await message.reply(f"{hbold('Ошибка:')} Сумма должна быть положительной!", parse_mode="HTML")
        if users[sender_id]["balance"] < amount: return await message.reply(f"{hbold('Ошибка:')} Недостаточно средств на балансе!", parse_mode="HTML")
        target_user_id = next((uid for uid, data in users.items() if data["username"].lower() == target_username.lower()), None)
        if not target_user_id: return await message.reply(f"{hbold('Ошибка:')} Пользователь @{target_username} не найден!", parse_mode="HTML")
        if target_user_id == sender_id: return await message.reply(f"{hbold('Ошибка:')} Нельзя перевести деньги самому себе!", parse_mode="HTML")
        users[sender_id]["balance"] -= amount; users[target_user_id]["balance"] += amount; save_data()
        await message.reply(f"{hbold('Успех!')} Вы передали {hbold(f'{amount} 💰')} пользователю @{target_username}\nВаш баланс: {hbold(str(users[sender_id]['balance']) + ' 💰')}", reply_markup=get_account_menu(), parse_mode="HTML")
        try: await bot.send_message(target_user_id, f"{hbold('Вам передали деньги!')}\n\nПользователь @{users[sender_id]['username']} перевёл вам {hbold(f'{amount} 💰')}\nВаш баланс: {hbold(str(users[target_user_id]['balance']) + ' 💰')}", parse_mode="HTML")
        except Exception as e: print(f"Ошибка при отправке уведомления {target_user_id}: {e}")
        return
    if text == "Имя ✏️": return await message.reply(f"{hbold('УПРАВЛЕНИЕ ИМЕНЕМ')}\n\nТекущий никнейм: {hbold(users[user_id]['nickname'])}\nСкрыт в таблице лидеров: {hbold('Да' if users[user_id]['hide_in_leaderboard'] else 'Нет')}", reply_markup=get_name_menu(), parse_mode="HTML")
    if text == "Сменить никнейм": awaiting_nickname[user_id] = True; return await message.reply(f"{hbold('СМЕНА НИКНЕЙМА')}\n\nВведите новый никнейм:", parse_mode="HTML")
    if text == "Скрыть/Показать в таблице лидеров": users[user_id]["hide_in_leaderboard"] = not users[user_id]["hide_in_leaderboard"]; save_data(); return await message.reply(f"{hbold('Настройки обновлены!')}\n\nСкрыт в таблице лидеров: {hbold('Да' if users[user_id]['hide_in_leaderboard'] else 'Нет')}", reply_markup=get_name_menu(), parse_mode="HTML")
    games = {"Слоты 🎰": "slot", "Кубики 🎲": "dice", "Баскетбол 🏀": "basketball", "Боулинг 🎳": "bowling", "Футбол ⚽": "football", "Дартс 🎯": "darts"}
    if text in games: current_game[user_id] = games[text]; return await message.reply("", reply_markup=get_bet_keyboard(), parse_mode="HTML")
    if text == "Назад в меню": current_game.pop(user_id, None); return await message.reply(f"{hbold('ВЫБЕРИ ИГРУ:')}\n", reply_markup=get_game_menu(), parse_mode="HTML")
    if text == "Баланс": return await message.reply(f"{hbold('ТВОЙ БАЛАНС')}\n\n  {hbold(str(users[user_id]['balance']) + ' 💰')}\n  {hitalic('Фриспины:')} {hbold(str(users[user_id]['freespins']))}", parse_mode="HTML")
    if text == "Правила 📜": return await send_rules(message)
    predefined_bets = ["10 💰", "100 💰", "1000 💰", "Олл-ин 💰"]
    if text in predefined_bets:
        bet = users[user_id]["balance"] if text == "Олл-ин 💰" else int(text.split()[0])
        if text == "Олл-ин 💰" and bet == 0: return await message.reply(f"{hbold('Ошибка:')} Ваш баланс 0 💰, нечего ставить!", parse_mode="HTML")
    elif text == "Своя ставка": return await message.reply(f"{hbold('ВВЕДИ СУММУ СТАВКИ')} {hitalic('(число):')}", parse_mode="HTML")
    elif text.isdigit():
        bet = int(text)
        if bet <= 0: return await message.reply(f"{hbold('Ошибка:')} Ставка должна быть {hunderline('больше 0')}", parse_mode="HTML")
    else: return await message.reply(f"{hbold('Ошибка:')} Выбери игру или используй кнопки для ставки!", parse_mode="HTML")
    if user_id not in current_game: return await message.reply(f"{hbold('Ошибка:')} Сначала выбери игру!\n", reply_markup=get_game_menu(), parse_mode="HTML")
    if users[user_id]["freespins"] > 0: bet, users[user_id]["freespins"] = 0, users[user_id]["freespins"] - 1
    elif users[user_id]["balance"] < bet: return await message.reply(f"{hbold('Ошибка:')} Недостаточно 💰 на балансе!", parse_mode="HTML")
    else: users[user_id]["balance"] -= bet; casino_balance += bet; jackpot += bet // 10
    save_data()
    emoji = {"slot": "🎰", "dice": "🎲", "basketball": "🏀", "bowling": "🎳", "football": "⚽", "darts": "🎯"}[current_game[user_id]]
    data = await bot.send_dice(chat_id=message.chat.id, emoji=emoji); dice_value = data.dice.value
    delay = {"slot": 2, "dice": 4, "basketball": 4, "bowling": 4, "football": 4, "darts": 4}[current_game[user_id]]
    await asyncio.sleep(delay)
    if current_game[user_id] == "slot":
        winnings, result_message, action = determine_slot_win(dice_value, bet, user_id)
        response = f"{hbold('РЕЗУЛЬТАТ СПИНА')}\n\n{result_message}\n\n"
        if winnings > 0: users[user_id]["balance"] += winnings; casino_balance -= winnings; response += f"{hunderline('Выигрыш:')} {hbold(str(winnings) + ' 💰')}\n"
        else: response += f"Потеряно: {bet} 💰\n"
        response += f"\n{hitalic('Баланс:')} {hbold(str(users[user_id]['balance']) + ' 💰')}\n{hitalic('Фриспины:')} {hbold(str(users[user_id]['freespins']))}"
        save_data(); await message.reply(response, parse_mode="HTML")
        if action == "gamble": await offer_gamble(user_id, message.chat.id, winnings)
    else:
        winnings, result_message = {"dice": determine_dice_win, "basketball": determine_basketball_win, "bowling": determine_bowling_win, "football": determine_football_win, "darts": determine_darts_win}[current_game[user_id]](dice_value, bet)
        response = f"{hbold('РЕЗУЛЬТАТ')}\n\n{result_message}\n\n"
        if winnings > 0: users[user_id]["balance"] += winnings; casino_balance -= winnings; response += f"{hunderline('Выигрыш:')} {hbold(str(winnings) + ' 💰')}\n"
        else: response += f"Потеряно: {bet} 💰\n"
        response += f"\n{hitalic('Баланс:')} {hbold(str(users[user_id]['balance']) + ' 💰')}"
        save_data(); await message.reply(response, parse_mode="HTML")

# Flask для Render
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is running!"

def run_flask():
    app.run(host='0.0.0.0', port=5000)

# Запуск бота
async def main():
    load_data()
    threading.Thread(target=run_flask, daemon=True).start()
    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())
