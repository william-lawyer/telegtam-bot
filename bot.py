import asyncio
import json
import os
import random
import time
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import Message
from aiogram.utils.keyboard import ReplyKeyboardBuilder
from aiogram.utils.markdown import hbold, hitalic, hunderline
from flask import Flask
import threading

API_TOKEN = '7537085884:AAGuseMdxP0Uwlhhv4Ltgg3-hmo0EJYkAG4'
bot = Bot(token=API_TOKEN)
dp = Dispatcher()
DATA_FILE = "balances.json"
users = {}
STARTING_BALANCE = 1000
jackpot = 5000
casino_balance = 0
current_game = {}
last_action_time = {}
SPAM_COOLDOWN = 2

def load_data():
    global users, jackpot, casino_balance
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            users.update(data.get("users", {}))
            jackpot = data.get("jackpot", 5000)
            casino_balance = data.get("casino_balance", 0)
    else:
        save_data()

def save_data():
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump({"users": users, "jackpot": jackpot, "casino_balance": casino_balance}, f, ensure_ascii=False, indent=4)

def check_spam(user_id):
    current_time = time.time()
    if current_time - last_action_time.get(user_id, 0) < SPAM_COOLDOWN:
        return False
    last_action_time[user_id] = current_time
    return True

def get_casino_menu():
    builder = ReplyKeyboardBuilder()
    builder.button(text="Игры 🎮")
    builder.button(text="Баланс 💰")
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
    builder.button(text="Назад в меню")
    builder.adjust(2)
    return builder.as_markup(resize_keyboard=True)

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
    if combo == ["7", "7", "7"]:
        winnings, freespins = bet * 10, freespins + 3
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
    users[user_id]["freespins"] = freespins
    return winnings, message

def determine_dice_win(value, bet):
    if value == 6: return bet * 3, f"{hbold('ШЕСТЁРКА!')}"
    elif value == 5: return bet * 2, f"{hbold('ХОРОШИЙ БРОСОК!')}"
    return 0, "Увы, нет выигрыша 😔"

def determine_basketball_win(value, bet):
    if value in [4, 5]: return bet * 3, f"{hbold('В КОЛЬЦО!')}"
    return 0, "Мимо 😔"

def determine_bowling_win(value, bet):
    if value == 6: return bet * 5, f"{hbold('СТРАЙК!')}"
    return 0, "Промах 😔"

def determine_football_win(value, bet):
    if value in [3, 4, 5]: return bet * 3, f"{hbold('ГОЛ!')}"
    return 0, "Мимо ворот 😔"

def determine_darts_win(value, bet):
    if value == 6: return bet * 5, f"{hbold('В ЯБЛОЧКО!')}"
    return 0, "Мимо 😔"

@dp.message(Command(commands=["start"]))
async def start_command(message: Message):
    user_id = str(message.from_user.id)
    username = message.from_user.username or "NoUsername"
    if user_id not in users:
        users[user_id] = {"balance": STARTING_BALANCE, "username": username, "freespins": 0}
        save_data()
    await message.reply(f"{hbold('ВЫБЕРИ РАЗДЕЛ:')}", reply_markup=get_casino_menu(), parse_mode="HTML")

@dp.message()
async def handle_game(message: Message):
    global jackpot, casino_balance
    user_id = str(message.from_user.id)
    text = message.text.strip()

    if user_id not in users:
        users[user_id] = {"balance": STARTING_BALANCE, "username": message.from_user.username or "NoUsername", "freespins": 0}
        save_data()
        return await message.reply(f"{hbold('ВЫБЕРИ РАЗДЕЛ:')}", reply_markup=get_casino_menu(), parse_mode="HTML")

    if not check_spam(user_id):
        return await message.reply(f"{hbold('СЛИШКОМ БЫСТРО!')}\nПодожди {SPAM_COOLDOWN} сек.", parse_mode="HTML")

    # Главное меню
    if text == "Игры 🎮":
        return await message.reply(f"{hbold('ВЫБЕРИ ИГРУ:')}", reply_markup=get_game_menu(), parse_mode="HTML")
    if text == "Баланс 💰":
        return await message.reply(f"{hbold('БАЛАНС')}\n{hbold(str(users[user_id]['balance']) + ' 💰')}", reply_markup=get_casino_menu(), parse_mode="HTML")

    # Выход из меню игр в главное меню
    if text == "Назад в казино":
        current_game.pop(user_id, None)
        return await message.reply(f"{hbold('ВЫБЕРИ РАЗДЕЛ:')}", reply_markup=get_casino_menu(), parse_mode="HTML")

    # Выбор игры
    games = {"Слоты 🎰": "slot", "Кубики 🎲": "dice", "Баскетбол 🏀": "basketball", 
             "Боулинг 🎳": "bowling", "Футбол ⚽": "football", "Дартс 🎯": "darts"}
    if text in games:
        current_game[user_id] = {"game": games[text], "awaiting_bet": False}
        return await message.reply(f"{hbold('ВЫБЕРИ СТАВКУ:')}", reply_markup=get_bet_keyboard(), parse_mode="HTML")

    # Выход из меню ставок в меню игр
    if text == "Назад в меню":
        if user_id in current_game:
            current_game[user_id]["awaiting_bet"] = False  # Сбрасываем ожидание ставки
        return await message.reply(f"{hbold('ВЫБЕРИ ИГРУ:')}", reply_markup=get_game_menu(), parse_mode="HTML")

    # Показ баланса в меню ставок
    if text == "Баланс" and user_id in current_game:
        return await message.reply(f"{hbold('БАЛАНС')}\n{hbold(str(users[user_id]['balance']) + ' 💰')}", reply_markup=get_bet_keyboard(), parse_mode="HTML")

    # Обработка ставок
    if user_id in current_game and "game" in current_game[user_id]:
        if text == "Своя ставка":
            current_game[user_id]["awaiting_bet"] = True
            return await message.reply(f"{hbold('ВВЕДИ СУММУ:')}", parse_mode="HTML")
        
        bet = None
        if text in ["10 💰", "100 💰", "1000 💰", "Олл-ин 💰"]:
            bet = users[user_id]["balance"] if text == "Олл-ин 💰" else int(text.split()[0])
        elif text.isdigit() and current_game[user_id].get("awaiting_bet"):
            bet = int(text)
            current_game[user_id]["awaiting_bet"] = False

        if bet is not None:
            if bet <= 0:
                return await message.reply(f"{hbold('Ошибка:')} Ставка должна быть больше 0!", parse_mode="HTML")
            if users[user_id]["balance"] < bet:
                return await message.reply(f"{hbold('Ошибка:')} Недостаточно 💰!", parse_mode="HTML")

            users[user_id]["balance"] -= bet
            casino_balance += bet
            jackpot += bet // 10

            game = current_game[user_id]["game"]
            emoji = {"slot": "🎰", "dice": "🎲", "basketball": "🏀", "bowling": "🎳", "football": "⚽", "darts": "🎯"}[game]
            dice = await bot.send_dice(chat_id=message.chat.id, emoji=emoji)
            await asyncio.sleep(4)
            dice_value = dice.dice.value

            determine_win = {"slot": determine_slot_win, "dice": determine_dice_win, "basketball": determine_basketball_win,
                            "bowling": determine_bowling_win, "football": determine_football_win, "darts": determine_darts_win}
            winnings, result_message = determine_win[game](dice_value, bet, user_id) if game == "slot" else determine_win[game](dice_value, bet)

            response = f"{hbold('РЕЗУЛЬТАТ')}\n\n{result_message}\n"
            if winnings > 0:
                users[user_id]["balance"] += winnings
                casino_balance -= winnings
                response += f"Выигрыш: {hbold(str(winnings) + ' 💰')}\n"
            else:
                response += f"Потеряно: {bet} 💰\n"
            response += f"Баланс: {hbold(str(users[user_id]['balance']) + ' 💰')}"

            save_data()
            await message.reply(response, reply_markup=get_bet_keyboard(), parse_mode="HTML")
            return

# Flask для Render
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is running!"

def run_flask():
    app.run(host='0.0.0.0', port=5000)

async def main():
    load_data()
    threading.Thread(target=run_flask, daemon=True).start()
    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())
