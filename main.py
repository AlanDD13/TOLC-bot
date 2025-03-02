import asyncio
import logging
import os
import base64
import httpx
import json
from datetime import datetime
from aiogram import Bot, Dispatcher
from aiogram.filters import CommandStart
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton, FSInputFile, InputMediaPhoto
from aiogram.enums import ParseMode
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_community.callbacks.manager import get_openai_callback
from langchain.schema import HumanMessage
from dotenv import load_dotenv
import aiofiles

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
USER_INFO_FILE = "users/user_info.txt"
ALLOWED_USERS_FILE = "users/allowed_users.txt"
TRIAL_USERS_FILE = "users/trial_users.txt" 
TRIAL_LIMIT = 3
REGISTRATION_LINK = "#"  

RED, GREEN, YELLOW, BLUE, MAGENTA, CYAN, RESET = 91, 92, 93, 94, 95, 96, 0
BOLD, UNDERLINE, ITALIC, REVERSE, STRIKETHROUGH = 1, 4, 3, 7, 9

ALLOWED_USERS = set()
active_sessions = {}
lang = 'english'
trial_reminder_tasks = {} 
expired_promotion_tasks = {}

bot = Bot(token=TELEGRAM_BOT_TOKEN)
dp = Dispatcher()
llm = ChatGoogleGenerativeAI(model="gemini-2.0-flash", google_api_key=GOOGLE_API_KEY)

lang_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="🇬🇧 English"), 
         KeyboardButton(text="🇷🇺 Russian"), 
         KeyboardButton(text="🇺🇿 Uzbek")]
    ],
    resize_keyboard=True
)

main_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="📖 Save Reading Text"), KeyboardButton(text="❓ Ask Reading Question")],
        [KeyboardButton(text="📈 Proof of Success"), KeyboardButton(text="📜 Instructions")],
        [KeyboardButton(text="🌐 Change Language"), KeyboardButton(text="📋 Exam Registration")]
    ],
    resize_keyboard=True
)

def colored(text, color_code, styles=None):
    codes = [color_code]
    if styles:
        codes.extend(styles)
    style_codes = ";".join(map(str, codes))
    return f"\033[{style_codes}m{text}\033[0m"

def load_trial_users():
    trial_users = {}
    try:
        with open(TRIAL_USERS_FILE, "r", encoding="utf-8") as f:
            for line in f:
                if ": " in line:
                    user_id, count = line.strip().split(": ")
                    trial_users[int(user_id)] = int(count)
    except FileNotFoundError:
        pass 
    return trial_users

def save_trial_users(trial_users):
    with open(TRIAL_USERS_FILE, "w", encoding="utf-8") as f:
        for user_id, count in trial_users.items():
            f.write(f"{user_id}: {count}\n")

def load_allowed_users():
    global ALLOWED_USERS
    try:
        with open(ALLOWED_USERS_FILE, "r") as f:
            ALLOWED_USERS = {int(line.strip()) for line in f if line.strip().isdigit()}
    except (FileNotFoundError, ValueError):
        ALLOWED_USERS = set()

def record_user(username, user_id):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        with open(USER_INFO_FILE, "r", encoding="utf-8") as f:
            existing_users = {int(line.split(", ")[1].split(":")[1].strip()) 
                            for line in f if ", " in line}
    except FileNotFoundError:
        existing_users = set()
    
    new_user = user_id not in existing_users
    if new_user:
        with open(USER_INFO_FILE, "a", encoding="utf-8") as f:
            f.write(f"USER: {username}, ID: {user_id}, Trial Messages: {TRIAL_LIMIT}\n")
    
    print(colored(f"{timestamp} - START - User {username} ({user_id}) started the bot. {'NEW' if new_user else 'EXISTS'}", 
                 GREEN, [BOLD, UNDERLINE]))

def load_text_from_file(filepath):
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        print(colored(f"ERROR: File '{filepath}' not found.", RED, [BOLD]))
        return ""

PROMPT = load_text_from_file("prompts/prompt.txt")
PASSAGE_PROMPT = load_text_from_file("prompts/passage_prompt.txt")
EXTRACT_PROMPT = load_text_from_file("prompts/extract_prompt.txt")
DENIED_MESSAGE = load_text_from_file("messages/denied_message.txt")
with open("messages/messages.json", "r", encoding="utf-8") as f:
    MESSAGES = json.load(f)
with open("messages/rules_messages.json", "r", encoding="utf-8") as f:
    RULES_MESSAGE = json.load(f)

async def check_allowed_user(user_id: int) -> bool:
    load_allowed_users()
    return user_id in ALLOWED_USERS

async def send_localized_message(message: Message, key: str):
    await message.answer(MESSAGES[key][lang], parse_mode=ParseMode.MARKDOWN)

async def download_photo(file_url: str, file_path: str):
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(file_url, timeout=10)
            response.raise_for_status()
            async with aiofiles.open(file_path, "wb") as f:
                await f.write(response.content)
            print(colored(f"{datetime.now():%Y-%m-%d %H:%M:%S} - DOWNLOAD - Photo downloaded to: {file_path}", CYAN))
            return True
        except (httpx.HTTPStatusError, httpx.TimeoutException, Exception) as e:
            print(colored(f"{datetime.now():%Y-%m-%d %H:%M:%S} - DOWNLOAD - Error downloading photo: {e}", RED, [BOLD]))
            return False

async def process_ai_reply(message: Message, ai_reply: str):
    user_id = message.from_user.id
    username = message.from_user.username
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    if "ANSWER:" in ai_reply:
        if '0000' in ai_reply:
            print(colored(f"{timestamp} - AI - User {username} ({user_id}) - Image not clear.", MAGENTA))
            await send_localized_message(message, "image_not_clear")
        elif '1111' in ai_reply:
            print(colored(f"{timestamp} - AI - User {username} ({user_id}) - Not a text image.", MAGENTA))
            await send_localized_message(message, "not_a_text")
        else:
            last_index = ai_reply.rfind("ANSWER:")
            answer = ai_reply[last_index + 7:].strip()
            if answer.upper() == "N/A":
                print(colored(f"{timestamp} - AI - User {username} ({user_id}) - No valid question detected.", MAGENTA))
                await send_localized_message(message, "no_question_detected")
            else:
                print(colored(f"{timestamp} - AI - User {username} ({user_id}) - Answer provided.", MAGENTA))
                await message.answer(f"{MESSAGES['answer_provided_prefix'][lang]} **{answer}**", 
                                   parse_mode=ParseMode.MARKDOWN, reply_markup=main_keyboard)
    else:
        print(colored(f"{timestamp} - AI - User {username} ({user_id}) - No answer found.", MAGENTA))
        await send_localized_message(message, "no_answer")

async def check_trial_limit(message: Message):
    user_id = message.from_user.id
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    trial_users = load_trial_users()

    if user_id not in trial_users:
        trial_users[user_id] = TRIAL_LIMIT
        save_trial_users(trial_users)
    
    if user_id not in active_sessions:
        active_sessions[user_id] = {
            "chat_id": message.chat.id,
            "trial_count": trial_users[user_id],
            "passage": "",
            "language": "english"
        }
    
    if not await check_allowed_user(user_id):
        active_sessions[user_id]["trial_count"] -= 1
        trial_users[user_id] = active_sessions[user_id]["trial_count"]
        save_trial_users(trial_users)
        
        remaining = active_sessions[user_id]["trial_count"] + 1
        if remaining <= 0:
            print(colored(f"{timestamp} - TRIAL EXPIRED - User {user_id} has no attempts left.", RED))
            await message.answer(
                MESSAGES["trial_over"][lang] + "\n[👉 Tap to Contact](https://t.me/teqstura)",
                parse_mode=ParseMode.MARKDOWN, reply_markup=main_keyboard
            )

            if user_id not in expired_promotion_tasks:
                task = asyncio.create_task(send_expired_trial_promotion(user_id))
                expired_promotion_tasks[user_id] = task

            if user_id in trial_reminder_tasks:
                trial_reminder_tasks[user_id].cancel()
                del trial_reminder_tasks[user_id]
            return False
        else:
            print(colored(f"{timestamp} - TRIAL - User {user_id} has {remaining} attempts left.", YELLOW))
            await message.answer(MESSAGES["trial_remaining"][lang].format(remaining=remaining - 1), reply_markup=main_keyboard)
    return True

async def send_trial_reminder(user_id: int):
    while True:
        if user_id not in active_sessions or await check_allowed_user(user_id) or active_sessions[user_id]["trial_count"] <= 0:
            if user_id in trial_reminder_tasks:
                del trial_reminder_tasks[user_id]
            break
        
        chat_id = active_sessions[user_id]["chat_id"]
        user_lang = active_sessions[user_id]["language"]
        try:
            await bot.send_message(
                chat_id=chat_id,
                text=MESSAGES["trial_reminder"][user_lang],
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=main_keyboard
            )
            print(colored(f"{datetime.now():%Y-%m-%d %H:%M:%S} - REMINDER - Sent to user {user_id}", CYAN))
        except Exception as e:
            print(colored(f"{datetime.now():%Y-%m-%d %H:%M:%S} - REMINDER ERROR - User {user_id}: {e}", RED))
        
        await asyncio.sleep(3 * 60 * 60) 

async def send_expired_trial_promotion(user_id: int):
    while True:
        if user_id not in active_sessions or await check_allowed_user(user_id):
            if user_id in expired_promotion_tasks:
                del expired_promotion_tasks[user_id]
            break
        
        chat_id = active_sessions[user_id]["chat_id"]
        user_lang = active_sessions[user_id]["language"]
        try:
          
            message_text = MESSAGES["trial_expired_promotion"][user_lang]
            await bot.send_message(
                chat_id=chat_id,
                text=message_text,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=main_keyboard
            )
            print(colored(f"{datetime.now():%Y-%m-%d %H:%M:%S} - PROMOTION REMINDER - Sent to user {user_id}", CYAN))
        except Exception as e:
            print(colored(f"{datetime.now():%Y-%m-%d %H:%M:%S} - PROMOTION REMINDER ERROR - User {user_id}: {e}", RED))
        
        await asyncio.sleep(3 * 60 * 60) 

@dp.message(CommandStart())
async def start_command(message: Message):
    user_id = message.from_user.id
    username = message.from_user.username
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    record_user(username, user_id)
    
    trial_users = load_trial_users()
    
    if user_id not in active_sessions:
        if user_id not in trial_users:
            trial_users[user_id] = TRIAL_LIMIT
            save_trial_users(trial_users)
        
        active_sessions[user_id] = {
            "chat_id": message.chat.id,
            "trial_count": trial_users[user_id],
            "passage": "",
            "language": "english"
        }
        if not await check_allowed_user(user_id):
            print(colored(f"{timestamp} - TRIAL - User {username} ({user_id}) started trial mode with {trial_users[user_id]} attempts.", YELLOW))
            if active_sessions[user_id]["trial_count"] > 0:
                if user_id not in trial_reminder_tasks:
                    task = asyncio.create_task(send_trial_reminder(user_id))
                    trial_reminder_tasks[user_id] = task
            else:
                if user_id not in expired_promotion_tasks:
                    task = asyncio.create_task(send_expired_trial_promotion(user_id))
                    expired_promotion_tasks[user_id] = task
        else:
            print(colored(f"{timestamp} - AUTH - User {username} ({user_id}) started as authorized.", GREEN))
    else:
        active_sessions[user_id]["chat_id"] = message.chat.id
    
    if not await check_allowed_user(user_id) and active_sessions[user_id]["trial_count"] <= 0:
        print(colored(f"{timestamp} - DENIED - User {username} ({user_id}) trial expired.", RED, [BOLD]))
        await message.answer(DENIED_MESSAGE, parse_mode=ParseMode.MARKDOWN)
        if user_id not in expired_promotion_tasks:
            task = asyncio.create_task(send_expired_trial_promotion(user_id))
            expired_promotion_tasks[user_id] = task
        return
    
    await message.answer(RULES_MESSAGE['default'], reply_markup=lang_keyboard, parse_mode=ParseMode.MARKDOWN)

@dp.message(lambda message: message.text in ["🇬🇧 English", "🇷🇺 Russian", "🇺🇿 Uzbek"])
async def set_language(message: Message):
    global lang
    user_id = message.from_user.id
    username = message.from_user.username
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    print(colored(f"{timestamp} - BUTTON - User {username} ({user_id}) selected language: {message.text}", CYAN, [BOLD]))
    
    langs = {
        "🇬🇧 English": ("english", "✅ Language set to **English**.", RULES_MESSAGE['english']),
        "🇷🇺 Russian": ("russian", "✅ Язык установлен на **Русский**.", RULES_MESSAGE['russian']),
        "🇺🇿 Uzbek": ("uzbek", "✅ Til **O'zbekcha**ga sozlandi.", RULES_MESSAGE['uzbek'])
    }
    if message.text in langs:
        lang, confirmation, rules = langs[message.text]
        active_sessions[user_id]["language"] = lang 
        await message.answer(confirmation, parse_mode=ParseMode.MARKDOWN)
        await message.answer(rules, parse_mode=ParseMode.MARKDOWN)
        await message.answer(MESSAGES["start_prompt"][lang], reply_markup=main_keyboard)
    else:
        await message.answer(MESSAGES["lang_not_supported"][lang], reply_markup=main_keyboard)

@dp.message(lambda message: message.text == "📋 Exam Registration")
async def show_exam_registration(message: Message):
    user_id = message.from_user.id
    user_lang = active_sessions[user_id]["language"]
    messages = {
        "english": f"📋 To register for the exam, follow this link: [Exam Registration]({REGISTRATION_LINK})",
        "russian": f"📋 Чтобы зарегистрироваться на экзамен, перейдите по ссылке: [Регистрация на экзамен]({REGISTRATION_LINK})",
        "uzbek": f"📋 Imtihonga ro'yxatdan o'tish uchun ushbu havolaga o'ting: [Imtihonga ro'yxatdan o'tish]({REGISTRATION_LINK})"
    }
    await message.answer(messages[user_lang], parse_mode=ParseMode.MARKDOWN, reply_markup=main_keyboard)

@dp.message(lambda message: message.text == "📈 Proof of Success")
async def show_results(message: Message):
    user_id = message.from_user.id
    username = message.from_user.username
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    print(colored(f"{timestamp} - RESULTS - User {username} ({user_id}) requested proof of success.", BLUE))
    
    result_photos = ["results_photos/result1.jpg", "results_photos/result2.jpg", "results_photos/result3.jpg", "results_photos/result4.jpg"]
    
    if all(os.path.exists(photo_path) for photo_path in result_photos):
        media = [InputMediaPhoto(media=FSInputFile(photo_path)) for photo_path in result_photos]

        media[0].caption = MESSAGES["proof_caption"][lang]
        
        await bot.send_media_group(
            chat_id=message.chat.id,
            media=media
        )
        
        return
    else:
        await message.answer(MESSAGES["proof_coming_soon"][lang], reply_markup=main_keyboard)
                
async def show_instructions(message: Message):
    await message.answer(RULES_MESSAGE[lang], reply_markup=main_keyboard, parse_mode=ParseMode.MARKDOWN)

@dp.message(lambda message: message.text == "🌐 Change Language")
async def change_language(message: Message):
    await message.answer(MESSAGES["choose_lang"][lang], reply_markup=lang_keyboard)

@dp.message(lambda message: message.text == "📖 Save Reading Text" or (message.photo and message.caption and message.caption.lower().strip() == "text"))
async def save_reading_text(message: Message):
    user_id = message.from_user.id
    username = message.from_user.username
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    if user_id not in active_sessions:
        print(colored(f"{timestamp} - EXPIRED - User {username} ({user_id}) attempted to save text without active session.", RED, [BOLD]))
        await send_localized_message(message, "session_expired")
        return
    
    if message.text == "📖 Save Reading Text":
        await message.answer(MESSAGES["send_reading_prompt"][lang], reply_markup=main_keyboard)
        return
    
    if not message.photo or (message.caption and message.caption.lower().strip() != "text"):
        await message.answer(MESSAGES["photo_required"][lang], reply_markup=main_keyboard)
        return
    
    print(colored(f"{timestamp} - READING - User {username} ({user_id}) sent reading text photo.", BLUE, [BOLD, ITALIC]))
    
    photo = message.photo[-1]
    file_info = await bot.get_file(photo.file_id)
    file_url = f"https://api.telegram.org/file/bot{TELEGRAM_BOT_TOKEN}/{file_info.file_path}"
    file_path = os.path.join("telegram_photos", f"{file_info.file_path.split('/')[-1].split('.')[0]}_{username}_{user_id}.jpg")
    os.makedirs("telegram_photos", exist_ok=True)
    
    if not await download_photo(file_url, file_path):
        await send_localized_message(message, "processing_error")
        return
    
    await message.answer(MESSAGES["processing"][lang], reply_markup=main_keyboard)
    
    try:
        image_data = base64.b64encode(httpx.get(file_url).content).decode("utf-8")
        response = llm.invoke([HumanMessage(content=[
            {"type": "text", "text": EXTRACT_PROMPT.format(text='[Image Question]')},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_data}"}},
        ])])
        
        active_sessions[user_id]["passage"] = response.content.strip().lower()
        print(colored(f"{timestamp} - EXTRACT - User {username} ({user_id}) - Reading text saved.", BLUE))
        await send_localized_message(message, "text_saved")
        await message.answer(MESSAGES["text_saved_prompt"][lang], reply_markup=main_keyboard)
        
    except Exception as e:
        logging.error(f"Error processing reading text: {e}")
        await send_localized_message(message, "processing_error")

@dp.message(lambda message: message.text == "❓ Ask Reading Question" or (message.photo and message.caption and message.caption.lower().strip() == "question"))
async def ask_reading_question(message: Message):
    user_id = message.from_user.id
    username = message.from_user.username
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    if user_id not in active_sessions:
        print(colored(f"{timestamp} - EXPIRED - User {username} ({user_id}) attempted reading question without active session.", RED, [BOLD]))
        await send_localized_message(message, "session_expired")
        return
    
    if not await check_trial_limit(message):
        return
    
    if not active_sessions[user_id]["passage"]:
        await message.answer(MESSAGES["no_text_saved"][lang], reply_markup=main_keyboard)
        return
    
    if message.text == "❓ Ask Reading Question":
        await message.answer(MESSAGES["send_reading_question_prompt"][lang], reply_markup=main_keyboard)
        return
    
    if not message.photo or (message.caption and message.caption.lower().strip() != "question"):
        await message.answer(MESSAGES["photo_required"][lang], reply_markup=main_keyboard)
        return
    
    print(colored(f"{timestamp} - READING QUESTION - User {username} ({user_id}) sent a question photo.", BLUE, [BOLD, ITALIC]))
    
    photo = message.photo[-1]
    file_info = await bot.get_file(photo.file_id)
    file_url = f"https://api.telegram.org/file/bot{TELEGRAM_BOT_TOKEN}/{file_info.file_path}"
    file_path = os.path.join("telegram_photos", f"{file_info.file_path.split('/')[-1].split('.')[0]}_{username}_{user_id}.jpg")
    os.makedirs("telegram_photos", exist_ok=True)
    
    if not await download_photo(file_url, file_path):
        await send_localized_message(message, "processing_error")
        return
    
    await message.answer(MESSAGES["processing"][lang], reply_markup=main_keyboard)
    
    try:
        image_data = base64.b64encode(httpx.get(file_url).content).decode("utf-8")
        response = llm.invoke([HumanMessage(content=[
            {"type": "text", "text": PASSAGE_PROMPT.format(question='[Image Question]', passage=active_sessions[user_id]["passage"], lang=lang)},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_data}"}},
        ])])
        
        await process_ai_reply(message, response.content.strip().upper())
        
    except Exception as e:
        logging.error(f"Error processing reading question: {e}")
        await send_localized_message(message, "processing_error")

@dp.message(lambda message: message.photo and message.caption not in ["text", "question"])
async def handle_image_question(message: Message):
    user_id = message.from_user.id
    username = message.from_user.username
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    if user_id not in active_sessions:
        print(colored(f"{timestamp} - EXPIRED - User {username} ({user_id}) attempted image question without active session.", RED, [BOLD]))
        await send_localized_message(message, "session_expired")
        return
    
    if not await check_trial_limit(message):
        return
    
    print(colored(f"{timestamp} - IMAGE - User {username} ({user_id}) sent an image", BLUE, [BOLD, ITALIC]))
    
    photo = message.photo[-1]
    file_info = await bot.get_file(photo.file_id)
    file_url = f"https://api.telegram.org/file/bot{TELEGRAM_BOT_TOKEN}/{file_info.file_path}"
    file_path = os.path.join("telegram_photos", f"{file_info.file_path.split('/')[-1].split('.')[0]}_{username}_{user_id}.jpg")
    os.makedirs("telegram_photos", exist_ok=True)
    
    if not await download_photo(file_url, file_path):
        await send_localized_message(message, "processing_error")
        return
    
    await message.answer(MESSAGES["processing"][lang], reply_markup=main_keyboard)
    
    try:
        image_data = base64.b64encode(httpx.get(file_url).content).decode("utf-8")
        response = llm.invoke([HumanMessage(content=[
            {"type": "text", "text": PROMPT.format(question='[Image Question]', lang=lang)},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_data}"}},
        ])])
        
        await process_ai_reply(message, response.content.strip().upper())
        
    except Exception as e:
        logging.error(f"Error processing image: {e}")
        await send_localized_message(message, "processing_error")

@dp.message(lambda message: message.text and message.text not in ["/logout", "📈 Proof of Success", "📜 Instructions", "🌐 Change Language", "📖 Save Reading Text", "❓ Ask Reading Question"])
async def handle_text_question(message: Message):
    user_id = message.from_user.id
    username = message.from_user.username
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    if user_id not in active_sessions:
        print(colored(f"{timestamp} - EXPIRED - User {username} ({user_id}) attempted text question without active session.", RED, [BOLD]))
        await send_localized_message(message, "session_expired")
        return
    
    if not await check_trial_limit(message):
        return
    
    print(colored(f"{timestamp} - TEXT - User {username} ({user_id}) asked: {message.text}", BLUE, [BOLD, ITALIC]))
    await message.answer(MESSAGES["processing"][lang], reply_markup=main_keyboard)
    
    try:
        with get_openai_callback() as cb:
            response = llm.invoke([HumanMessage(content=PROMPT.format(question=message.text))])
        await process_ai_reply(message, response.content.strip().upper())
    except Exception as e:
        logging.error(f"Error processing text: {e}")
        await send_localized_message(message, "processing_error")

@dp.message(lambda message: message.text == "/logout")
async def logout_user(message: Message):
    user_id = message.from_user.id
    username = message.from_user.username
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    print(colored(f"{timestamp} - LOGOUT - User {username} ({user_id}) logged out.", YELLOW, [BOLD]))
    
    if user_id in active_sessions:
        del active_sessions[user_id]
        await message.answer(MESSAGES["logout_success"][lang])
    else:
        await message.answer(MESSAGES["no_session"][lang])

async def main():
    print(colored("Bot started successfully.", GREEN, [BOLD, UNDERLINE]))
    await dp.start_polling(bot)
    for task in trial_reminder_tasks.values():
        task.cancel()
    for task in expired_promotion_tasks.values():
        task.cancel()
    print(colored("Bot stopped.", RED, [BOLD]))

if __name__ == "__main__":
    if os.name == 'nt':
        os.system('')
    asyncio.run(main())