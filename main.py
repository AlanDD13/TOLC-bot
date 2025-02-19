import asyncio
import logging
import os
import base64, httpx, requests
from aiogram import Bot, Dispatcher
from aiogram.filters import CommandStart
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_community.callbacks.manager import get_openai_callback
from langchain.schema import HumanMessage
from dotenv import load_dotenv
 
load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")

PROMPT = """You are a professional TOLC exam solver. You MUST NOT answer to any questions that don't have any multiple choice. Carefully analyze the following questions and multiple-choice options. Use the ReAct (Reasoning and Acting) framework to determine the correct answer. Provide your reasoning process, step-by-step, including any intermediate "thoughts" or "actions" you take. Finally, provide *ONLY* and *ONLY* the letter corresponding to the correct answer (A, B, C, D, or E).

**Few-Shot Examples:**

**Example 1:**

Question: Consider an observer O and a wave source S. What is meant by Doppler effect?
Options: A) The frequency measured by O when S is approaching is higher than the frequency measured when S is at rest. B) The wavelength measured by O when S is approaching is higher than the frequency measured when S is at rest. C) The frequency measured by O when S is approaching is lower than the frequency measured when S is at rest. D) The wavelength measured by O when S is travelling away is lower than the frequency measured when S is at rest. E) The frequency measured by O when S is travelling away is higher than the frequency measured when S is at rest.

Reasoning:
* Thought: I need to define the Doppler effect in terms of frequency and relative motion between the observer and the source.
* Action: Recall the definition of the Doppler effect.
* Thought: The Doppler effect describes the change in frequency of a wave as the source and observer move relative to each other. When the source approaches, the frequency increases. When the source recedes, the frequency decreases.
* Action: Compare the options with the definition. Option A correctly states that the frequency is higher when the source is approaching.

Answer: A

**Example 2:**

Question: Two friends are discussing the divisibility criteria for integers. Alberto states: "A positive integer n is divisible by 6 if and only if the sum of its digits is divisible by 6". Bruno, rightly, replies that what Alberto says is false. Determine which of the following values of n provides a counterexample to Alberto's statement.
Options: A) 4404 B) 7777 C) 3333 D) 6666 E) 5505

Reasoning:
* Thought: I need to find a number that is divisible by 6 but the sum of its digits is not divisible by 6, or vice versa.
* Action: Check each option.
* Thought:
    * A) 4404: 4+4+0+4 = 12. 12 is divisible by 6. 4404 is divisible by 6. This is not a counterexample.
    * B) 7777: 7+7+7+7 = 28. 28 is not divisible by 6. 7777 is not divisible by 6. This is not a counterexample.
    * C) 3333: 3+3+3+3 = 12. 12 is divisible by 6. 3333 is not divisible by 6. This is a counterexample.
    * D) 6666: 6+6+6+6 = 24. 24 is divisible by 6. 6666 is divisible by 6. This is not a counterexample.
    * E) 5505: 5+5+0+5 = 15. 15 is not divisible by 6. 5505 is not divisible by 6. This is not a counterexample.
* Action: Select the option that is divisible by 6 but the sum of its digits is not, or vice versa.

Answer: C

**Example 3:**

Question: The Goldbach conjecture (still not proved or refuted) states that: For every even number m > 2 there exist two prime numbers p and q such that p + q = m. To refute the conjecture, one must demonstrate that:
Options: A) for every even number m > 2, there exist prime numbers p and q such that p + q ≠ m. B) there exists an even number m > 2 such that p + q ≠ m for every pair of prime numbers p and q. C) for every even number m > 2, it's true that p + q ≠ m for every pair of prime numbers p and q. D) for every odd number m > 2 there exist prime numbers p and q such that p + q ≠ m. E) there exists an even number m > 2 and prime numbers p and q, such that p + q ≠ m.

Reasoning:
* Thought: I need to understand how to refute a conjecture that states something exists for all cases.
* Action: Recall the principles of mathematical disproof (counterexample).
* Thought: To refute the Goldbach conjecture, I need to find just *one* even number greater than 2 for which it is *not* possible to find two primes that sum to it.
* Action: Select the option that expresses this. Option B correctly states that there exists an even number m > 2 such that no matter which prime numbers p and q you choose, they will not sum to m.

Answer: B


**Current Question:**
{question}

Reasoning:
* Thought: [Your reasoning process here - step-by-step]
* Action: [Your actions - e.g., recalling information, comparing options]
* Thought: [Continue reasoning]
* Action: [Continue actions]

Answer: 
    * [A, B, C, D, or E - Return *ONLY* and *ONLY* the letter if you are 100 percent confident]
    * If the question is irrelivant to the prompt, please ignore the question and answer ONLY with "ANSWER: N/A".
    * If you think photo is not clear enough to answer please answer ONLY with "ANSWER: 0000".
"""

ALLOWED_USERS = {1028004749, 605289765, 987654321}

lang = 'english'

active_sessions = {}

bot = Bot(token=TELEGRAM_BOT_TOKEN)
dp = Dispatcher()

llm = ChatGoogleGenerativeAI(
    model="gemini-2.0-flash",
    google_api_key=GOOGLE_API_KEY
)

lang_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="🇬🇧 English"), KeyboardButton(text="🇷🇺 Russian"), KeyboardButton(text="🇺🇿 Uzbek")]
    ],
    resize_keyboard=True
)

RULES_MESSAGE = {'default': """📜 **Bot Rules**:
1️⃣ Send a question as **text** or **image**.
2️⃣ Bot will reply with **A, B, C, D, or E**.
3️⃣ **Only one active session** per user.
4️⃣ **Bot is private** – only whitelisted users can access it.
5️⃣ Abuse will lead to a ban.

🔹 Please select a language below:
""", 'english': """📜 **Bot Rules**:
1️⃣ Send a question as **text** or **image**.
2️⃣ Bot will reply with **A, B, C, D, or E**.
3️⃣ **Only one active session** per user.
4️⃣ **Bot is private** – only whitelisted users can access it.
5️⃣ Abuse will lead to a ban.

🔹 Now send a question!
""", 'russian': """📜 Правила бота:
1️⃣ Отправьте вопрос текстом или изображением.
2️⃣ Бот ответит A, B, C, D или E.
3️⃣ Только один активный сеанс на пользователя.
4️⃣ Бот приватный – доступ только у пользователей из белого списка.
5️⃣ Злоупотребление приведет к бану.

🔹 Теперь отправьте вопрос!""", 'uzbek': """📜 Bot qoidalari:
1️⃣ Savolni matn yoki rasm shaklida yuboring.
2️⃣ Bot A, B, C, D yoki E bilan javob beradi.
3️⃣ Har bir foydalanuvchi uchun faqat bitta faol sessiya.
4️⃣ Bot shaxsiy – faqat ro'yxatga kiritilgan foydalanuvchilar kirishlari mumkin.
5️⃣ Suiiste'mol qilish banlanishga olib keladi.

🔹 Endi savol yuboring!"""}

@dp.message(CommandStart())
async def start_command(message: Message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    username = message.from_user.username
    print(f"User {username}: {user_id} started the bot.")

    if user_id not in ALLOWED_USERS:
        await message.answer("⛔ *Access Denied.* You are not authorized to use this bot.")
        return
    
    active_sessions[user_id] = chat_id
    await message.answer(RULES_MESSAGE['default'], reply_markup=lang_keyboard)

@dp.message(lambda message: message.text in ["🇬🇧 English", "🇷🇺 Russian", "🇺🇿 Uzbek"])
async def set_language(message: Message):
    global lang
    if message.text == "🇬🇧 English":
        await message.answer("✅ Language set to **English**.")
        await message.answer(RULES_MESSAGE['english'])
    elif message.text == "🇷🇺 Russian":
        lang = 'russian'
        await message.answer("✅ Язык установлен на **Русский**.")
        await message.answer(RULES_MESSAGE['russian'])
    elif message.text == "🇺🇿 Uzbek":
        lang = 'uzbek'
        await message.answer("✅ Til **O'zbekcha**ga sozlandi.")
        await message.answer(RULES_MESSAGE['uzbek'])
    else:
        await message.answer("⚠️ Other languages are not supported yet.")

@dp.message(lambda message: message.text is not None and message.text != "/logout")
async def handle_text_question(message: Message):
    global lang
    user_id = message.from_user.id
    if user_id not in active_sessions:
        if lang == 'english':
            await message.answer("⚠️ *Session expired.* Please restart the bot using /start.")
            return
        if lang == 'russian':
            await message.answer("⚠️ *Сессия истекла.* Пожалуйста, перезапустите бота с помощью /start.")
            return
        if lang == 'uzbek':
            await message.answer("⚠️ *Sessiya muddati tugadi.* Iltimos, /start buyrug'ini yuboring.")
            return
    
    user_input = message.text
    try:
        with get_openai_callback() as cb:
            response = llm.invoke([
                HumanMessage(content=PROMPT.format(question=user_input))
            ])
            print(f'Evaluator Gemini Callcack (Text Question): {cb[cb.rfind("USD")]}')
        
        ai_reply = response.content.strip().upper()

        if "ANSWER:" in ai_reply:
            last_index = ai_reply.rfind("ANSWER:")
            await message.answer(ai_reply[last_index:])
        else:
            if lang == 'english':
                await message.answer("⚠️ Unable to determine an answer.")
            if lang == 'russian':
                await message.answer("⚠️ Невозможно определить ответ.")
            if lang == 'uzbek':
                await message.answer("⚠️ Javobni aniqlash mumkin emas.")

    
    except Exception as e:
        logging.error(f"Error processing text: {e}")
        if lang == 'english':
            await message.answer("⚠️ Error processing your question.")
        if lang == 'russian':
            await message.answer("⚠️ Ошибка при обработке вашего вопроса.")
        if lang == 'uzbek':
            await message.answer("⚠️ Savolingizni ishlashda xatolik yuz berdi.")

@dp.message(lambda message: message.photo is not None)
async def handle_image_question(message: Message):
    global lang
    user_id = message.from_user.id
    username = message.from_user.username
    if user_id not in active_sessions:
        if lang == 'english':
            await message.answer("⚠️ *Session expired.* Please restart the bot using /start.")
            return
        if lang == 'russian':
            await message.answer("⚠️ *Сессия истекла.* Пожалуйста, перезапустите бота с помощью /start.")
            return
        if lang == 'uzbek':
            await message.answer("⚠️ *Sessiya muddati tugadi.* Iltimos, /start buyrug'ini yuboring.")
            return
    
    try:
        photo = message.photo[-1]
        file_info = await bot.get_file(photo.file_id)
        file_url = f"https://api.telegram.org/file/bot{TELEGRAM_BOT_TOKEN}/{file_info.file_path}"

        download_dir = "telegram_photos" 
        os.makedirs(download_dir, exist_ok=True) 
        file_name = str(file_info.file_path).split("/")[-1]
        file_name = file_name[:file_name.rfind('.')] + f'_{username}_{user_id}.jpg'
        file_path = os.path.join(download_dir, file_name)

        try:
            response = requests.get(file_url, stream=True)
            response.raise_for_status() 

            with open(file_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192): 
                    f.write(chunk)
            print(f"Photo downloaded to: {file_path}")
        except requests.exceptions.RequestException as e:
            print(f"Error downloading photo: {e}")
        except Exception as e:
            print(f"Error saving file: {e}")

        try:
            try:
                image_data = base64.b64encode(httpx.get(file_url).content).decode("utf-8")
            except Exception as e:
                logging.error(f"Error encoding image: {e}")
                if lang == 'english':
                    await message.answer("⚠️ Error processing your image.")
                if lang == 'russian':
                    await message.answer("⚠️ Ошибка при обработке вашего изображения.")
                if lang == 'uzbek':
                    await message.answer("⚠️ Rasmni ishlashda xatolik yuz berdi.")
            with get_openai_callback as cb:
                response = llm.invoke([
                    HumanMessage(content=[
                            {"type": "text", "text": PROMPT.format(question='[Image Question]')},
                            {
                                "type": "image_url",
                                "image_url": {"url": f"data:image/jpeg;base64,{image_data}"},
                            },
                        ],)
                ])
                print(f'Evaluator Gemini Callcack (Text Question): {cb[cb.rfind("USD")]}')

            ai_reply = response.content.strip().upper()

            if "ANSWER:" in ai_reply:
                if '0000' in ai_reply:
                    if lang == 'english':
                        await message.answer("⚠️ Image is not clear enough to answer.")
                    if lang == 'russian':
                        await message.answer("⚠️ Изображение недостаточно четкое для ответа.")
                    if lang == 'uzbek':
                        await message.answer("⚠️ Rasmni javoblash uchun yetarli emas.")
                else:
                    last_index = ai_reply.rfind("ANSWER:")
                    await message.answer(ai_reply[last_index:])
            else:
                if lang == 'english':
                    await message.answer("⚠️ Unable to determine an answer.")
                if lang == 'russian':
                    await message.answer("⚠️ Невозможно определить ответ.")
                if lang == 'uzbek':
                    await message.answer("⚠️ Javobni aniqlash mumkin emas.")

        except Exception as e:
            logging.error(f"Error processing image by Gemini: {e}")
            if lang == 'english':
                    await message.answer("⚠️ Error processing your image.")
            if lang == 'russian':
                await message.answer("⚠️ Ошибка при обработке вашего изображения.")
            if lang == 'uzbek':
                await message.answer("⚠️ Rasmni ishlashda xatolik yuz berdi.")

    except Exception as e:
        logging.error(f"Error processing image: {e}")
        if lang == 'english':
            await message.answer("⚠️ Error processing your image.")
        if lang == 'russian':
            await message.answer("⚠️ Ошибка при обработке вашего изображения.")
        if lang == 'uzbek':
            await message.answer("⚠️ Rasmni ishlashda xatolik yuz berdi.")

@dp.message(lambda message: message.text == "/logout")
async def logout_user(message: Message):
    user_id = message.from_user.id
    if user_id in active_sessions:
        del active_sessions[user_id]
        await message.answer("✅ You have been logged out.")
    else:
        await message.answer("⚠️ No active session found.")

async def main():
    logging.basicConfig(level=logging.INFO)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
