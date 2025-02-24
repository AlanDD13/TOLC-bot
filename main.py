import asyncio
import logging
import os
import base64
import httpx
import json
from datetime import datetime
from aiogram import Bot, Dispatcher
from aiogram.filters import CommandStart
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton
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

RED, GREEN, YELLOW, BLUE, MAGENTA, CYAN, RESET = 91, 92, 93, 94, 95, 96, 0
BOLD, UNDERLINE, ITALIC, REVERSE, STRIKETHROUGH = 1, 4, 3, 7, 9

ALLOWED_USERS = set()
active_sessions = {}
passage = ''
lang = 'english'

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

def colored(text, color_code, styles=None):
    codes = [color_code]
    if styles:
        codes.extend(styles)
    style_codes = ";".join(map(str, codes))
    return f"\033[{style_codes}m{text}\033[0m"

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
            f.write(f"USER: {username}, ID: {user_id}\n")
    
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
        elif '1111' in passage:
            print(colored(f"{timestamp} - AI - User {username} ({user_id}) - Not a text image.", MAGENTA))
            await send_localized_message(message, "not_a_text")
        else:
            last_index = ai_reply.rfind("ANSWER:")
            print(colored(f"{timestamp} - AI - User {username} ({user_id}) - Answer provided.", MAGENTA))
            await message.answer(ai_reply[last_index:])
    else:
        print(colored(f"{timestamp} - AI - User {username} ({user_id}) - No answer found.", MAGENTA))
        await send_localized_message(message, "no_answer")

@dp.message(CommandStart())
async def start_command(message: Message):
    user_id = message.from_user.id
    username = message.from_user.username
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    record_user(username, user_id)
    
    if not await check_allowed_user(user_id):
        print(colored(f"{timestamp} - DENIED - User {username} ({user_id}) denied access (not in allowed users).", RED, [BOLD]))
        await message.answer(DENIED_MESSAGE, parse_mode=ParseMode.MARKDOWN)
        return
    
    active_sessions[user_id] = message.chat.id
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
        await message.answer(confirmation, parse_mode=ParseMode.MARKDOWN)
        await message.answer(rules, parse_mode=ParseMode.MARKDOWN)
    else:
        await message.answer("⚠️ Other languages are not supported yet.")

@dp.message(lambda message: message.text is not None and message.text != "/logout")
async def handle_text_question(message: Message):
    user_id = message.from_user.id
    username = message.from_user.username
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    if user_id not in active_sessions:
        print(colored(f"{timestamp} - EXPIRED - User {username} ({user_id}) attempted text question without active session.", RED, [BOLD]))
        await send_localized_message(message, "session_expired")
        return
    
    print(colored(f"{timestamp} - TEXT - User {username} ({user_id}) asked: {message.text}", BLUE, [BOLD, ITALIC]))
    try:
        with get_openai_callback() as cb:
            response = llm.invoke([HumanMessage(content=PROMPT.format(question=message.text))])
            #print(f'EVALUATOR: Evaluator Gemini Callback (Text Question): {cb}')
        await process_ai_reply(message, response.content.strip().upper())
    except Exception as e:
        logging.error(f"Error processing text: {e}")
        await send_localized_message(message, "processing_error")

@dp.message(lambda message: message.photo is not None)
async def handle_image_question(message: Message):
    global passage
    user_id = message.from_user.id
    username = message.from_user.username
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    if user_id not in active_sessions:
        print(colored(f"{timestamp} - EXPIRED - User {username} ({user_id}) attempted image question without active session.", RED, [BOLD]))
        await send_localized_message(message, "session_expired")
        return
    
    caption = message.caption.strip().lower() if message.caption else None
    print(colored(f"{timestamp} - IMAGE - User {username} ({user_id}) sent an image (caption: {caption or 'None'})", BLUE, [BOLD, ITALIC]))
    
    photo = message.photo[-1]
    file_info = await bot.get_file(photo.file_id)
    file_url = f"https://api.telegram.org/file/bot{TELEGRAM_BOT_TOKEN}/{file_info.file_path}"
    file_path = os.path.join("telegram_photos", f"{file_info.file_path.split('/')[-1].split('.')[0]}_{username}_{user_id}.jpg")
    os.makedirs("telegram_photos", exist_ok=True)
    
    if not await download_photo(file_url, file_path):
        await send_localized_message(message, "processing_error")
        return
    
    try:
        image_data = base64.b64encode(httpx.get(file_url).content).decode("utf-8")
        prompts = {
            None: PROMPT.format(question='[Image Question]', lang=lang),
            'text': EXTRACT_PROMPT.format(text='[Image Question]'),
            'question': PASSAGE_PROMPT.format(question='[Image Question]', passage=passage, lang=lang)
        }
        
        response = llm.invoke([HumanMessage(content=[
            {"type": "text", "text": prompts[caption]},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_data}"}},
        ])])
        
        if caption == 'text':
            passage = response.content.strip().lower()
            if "ANSWER:" in passage:
                print(colored(f"{timestamp} - EXTRACT - User {username} ({user_id}) - Text extracted with answer.", BLUE))
                await process_ai_reply(message, passage.upper())
            else:
                print(colored(f"{timestamp} - EXTRACT - User {username} ({user_id}) - Text extracted and saved.", BLUE))
                await send_localized_message(message, "text_saved")
        else:
            await process_ai_reply(message, response.content.strip().upper())
            
    except Exception as e:
        logging.error(f"Error processing image: {e}")
        await send_localized_message(message, "processing_error")

@dp.message(lambda message: message.text == "/logout")
async def logout_user(message: Message):
    user_id = message.from_user.id
    username = message.from_user.username
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    print(colored(f"{timestamp} - LOGOUT - User {username} ({user_id}) logged out.", YELLOW, [BOLD]))
    
    if user_id in active_sessions:
        del active_sessions[user_id]
        await message.answer("✅ You have been logged out.")
    else:
        await message.answer("⚠️ No active session found.")

async def main():
    #logging.basicConfig(level=logging.INFO)
    print(colored("Bot started successfully.", GREEN, [BOLD, UNDERLINE]))

    logging_events = [
        ("Button Press", "Cyan", CYAN),
        ("Logout", "Yellow", YELLOW),
        ("Session Expired", "Red", RED),
        ("Access Denied", "Red", RED),
        ("AI Response", "Magenta", MAGENTA),
        ("Photo Download", "Cyan", CYAN),  
        ("Text Extraction", "Blue", BLUE)
    ]
    
    print(colored("Logging Colors:", GREEN, [BOLD]))
    print(colored("Event".ljust(20) + "Color", GREEN, [BOLD]))
    print(colored("-" * 30, GREEN))
    for event, color_text, color_code in logging_events:
        print(colored(f"{event.ljust(20)}{color_text}", color_code))
    print(colored("-" * 30, GREEN))
    
    await dp.start_polling(bot)
    print(colored("Bot stopped.", RED, [BOLD]))

if __name__ == "__main__":
    if os.name == 'nt':
        os.system('')
    asyncio.run(main())