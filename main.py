import asyncio
import logging
import os
import base64
import httpx
from aiogram import Bot, Dispatcher
from aiogram.filters import CommandStart
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_community.callbacks.manager import get_openai_callback
from langchain.schema import HumanMessage
from dotenv import load_dotenv
import aiofiles
 
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
PASSAGE_PROMPT = """You are a professional TOLC exam solver. You MUST NOT answer to any questions that don't have any multiple choice. Carefully analyze the following questions and multiple-choice options. Use the ReAct (Reasoning and Acting) framework to determine the correct answer ONLY and ONLY based on the following passage. Provide your reasoning process, step-by-step, including any intermediate "thoughts" or "actions" you take. Finally, provide *ONLY* and *ONLY* the letter corresponding to the correct answer (A, B, C, D, or E).  

**Few-Shot Examples:**  

**Example 1:**  

**Passage:**  
*"The Doppler effect describes the change in frequency of a wave relative to an observer moving toward or away from the wave source. When the source moves toward the observer, the frequency increases, and when it moves away, the frequency decreases."*  

**Question:** Consider an observer O and a wave source S. What is meant by the Doppler effect?  
**Options:** A) The frequency measured by O when S is approaching is higher than the frequency measured when S is at rest. B) The wavelength measured by O when S is approaching is higher than the frequency measured when S is at rest. C) The frequency measured by O when S is approaching is lower than the frequency measured when S is at rest. D) The wavelength measured by O when S is travelling away is lower than the frequency measured when S is at rest. E) The frequency measured by O when S is travelling away is higher than the frequency measured when S is at rest.  

**Reasoning:**  
* Thought: I must answer based **only** on the passage.  
* Action: The passage states that **when the source moves toward the observer, the frequency increases**.  
* Thought: I will compare this information with the answer choices.  
* Action: **Option A correctly states that the frequency increases when the source approaches.**  

Answer: A  

---

**Example 2:**  

**Passage:**  
*"A number is divisible by 6 if and only if it is divisible by both 2 and 3. A number is divisible by 2 if its last digit is even, and it is divisible by 3 if the sum of its digits is divisible by 3."*  

**Question:** Two friends are discussing divisibility. Alberto states: "A number n is divisible by 6 if and only if the sum of its digits is divisible by 6." Bruno, rightly, replies that Alberto is wrong. Which number is a counterexample?  
**Options:** A) 4404 B) 7777 C) 3333 D) 6666 E) 5505  

**Reasoning:**  
* Thought: The passage states that a number is divisible by 6 **if and only if it is divisible by both 2 and 3**, not just by checking the sum of digits.  
* Action: I will check each option using this rule:  
  - **A) 4404**: Ends in **4** (divisible by 2). Sum = **12** (divisible by 3). ✅ Divisible by 6. **Not a counterexample**.  
  - **B) 7777**: Ends in **7** (not divisible by 2). ❌ Not divisible by 6. **Not a counterexample**.  
  - **C) 3333**: Ends in **3** (not divisible by 2). ❌ Not divisible by 6. **Not a counterexample**.  
  - **D) 6666**: Ends in **6** (divisible by 2). Sum = **24** (divisible by 3). ✅ Divisible by 6. **Not a counterexample**.  
  - **E) 5505**: Ends in **5** (not divisible by 2). ❌ Not divisible by 6. **Not a counterexample**.  

✅ **The counterexample must be a number where the sum of digits follows one rule but the whole number does not meet the second rule.**  

📌 **Correct answer is C (3333), because its sum (12) is divisible by 3, but the number itself is not divisible by 2, making it NOT divisible by 6.**  

Answer: C  

---

**Example 3:**  

**Passage:**  
*"Goldbach’s conjecture states that every even integer greater than 2 can be expressed as the sum of two prime numbers. To disprove the conjecture, one would need to find an even integer greater than 2 that cannot be written as the sum of two primes."*  

**Question:** The Goldbach conjecture states that for every even number m > 2, there exist two prime numbers p and q such that p + q = m. To refute this conjecture, one must demonstrate that:  
**Options:** A) for every even number m > 2, there exist prime numbers p and q such that p + q ≠ m. B) there exists an even number m > 2 such that p + q ≠ m for every pair of prime numbers p and q. C) for every even number m > 2, it's true that p + q ≠ m for every pair of prime numbers p and q. D) for every odd number m > 2, there exist prime numbers p and q such that p + q ≠ m. E) there exists an even number m > 2 and prime numbers p and q, such that p + q ≠ m.  

**Reasoning:**  
* Thought: The passage says that **to refute the conjecture, one must find an even number that cannot be expressed as a sum of two primes**.  
* Action: I will compare this information with the answer choices.  
* Thought:  
  - **A) Incorrect**, because Goldbach’s conjecture **is about some even numbers, not all**.  
  - **B) Correct**, because it states that **there exists one even number** that violates the rule, which disproves the conjecture.  
  - **C) Incorrect**, because it claims **all** even numbers violate the rule, which is false.  
  - **D) Incorrect**, because the conjecture applies to **even**, not odd numbers.  
  - **E) Incorrect**, because it doesn’t specify that **all pairs fail**, which is required to refute a conjecture.  

✅ **Correct answer is B, because disproving a conjecture only requires a single counterexample.**  

Answer: B  

---

**Current Passage:**
{passage}

**Current Question:**  
{question}  

Reasoning:  
* Thought: [Your reasoning process here - step-by-step]  
* Action: [Your actions - e.g., recalling information, comparing options]  
* Thought: [Continue reasoning]  
* Action: [Continue actions]  

Answer:  
    * [A, B, C, D, or E - Return *ONLY* and *ONLY* the letter if you are 100 percent confident]  
    * If the question is irrelevant to the prompt, please ignore the question and answer ONLY with `"ANSWER: N/A"`.  
    * If you think the photo is not clear enough to answer, please answer ONLY with `"ANSWER: 0000"`.  
"""
EXTRACT_PROMPT = """Your goal is to extract text from the image and save it for later use. Please provide the text extracted from the image as "TEXT: extracted text". If the image is not clear enough to extract text, please ignore the question and answer ONLY with "ANSWER: 0000". If the length of the text is less than 50 symbols then answer "ANSWER: 1111" {text}"""
ALLOWED_USERS_FILE = "allowed_users.txt"

ALLOWED_USERS = set()  

def load_allowed_users():
    global ALLOWED_USERS
    try:
        with open(ALLOWED_USERS_FILE, "r") as f:
            users = [int(line.strip()) for line in f if line.strip().isdigit()]
        ALLOWED_USERS = set(users)
        #print(f"Allowed users reloaded from {ALLOWED_USERS_FILE}: {ALLOWED_USERS}")
    except FileNotFoundError:
        print(f"Warning: {ALLOWED_USERS_FILE} not found. No users will be allowed.")
        ALLOWED_USERS = set()
    except ValueError:
        print(f"Error: Invalid user ID in {ALLOWED_USERS_FILE}. Please ensure each line contains a valid integer.")
        ALLOWED_USERS = set()

async def check_allowed_user(user_id: int) -> bool:
    load_allowed_users() 
    return user_id in ALLOWED_USERS

lang = 'english'

active_sessions = {}

passage = ''

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
2️⃣ If you want to send a text from reading part please write "text" in the caption. 
3️⃣ If you want to send a question from the reading part please write "question" in the caption.
4️⃣ Bot will reply with **A, B, C, D, or E**.
5️⃣ **Only one active session** per user.
6️⃣ **Bot is private** – only whitelisted users can access it.
7️⃣ Abuse will lead to a ban.

🔹 Please select a language below:
""", 'english': """📜 **Bot Rules**:
1️⃣ Send a question as **text** or **image**.
2️⃣ If you want to send a text from reading part please write "text" in the caption. 
3️⃣ If you want to send a question from the reading part please write "question" in the caption.
4️⃣ Bot will reply with **A, B, C, D, or E**.
5️⃣ **Only one active session** per user.
6️⃣ **Bot is private** – only whitelisted users can access it.
7️⃣ Abuse will lead to a ban.

🔹 Now send a question!
""", 'russian': """📜 **Правила бота**:
1️⃣ Отправьте вопрос **текстом** или **изображением**.
2️⃣ Если вы хотите отправить текст из части Reading, напишите «text» в подписи.
3️⃣ Если вы хотите задать вопрос из части Reading, напишите «question» в подписи.
4️⃣ Бот ответит **A, B, C, D или E**.
5️⃣ **Только один активный сеанс** на пользователя.
6️⃣ **Бот приватный** – доступ только у пользователей из белого списка.
7️⃣ Злоупотребление приведет к бану.

🔹 Теперь отправьте вопрос!
""", 'uzbek': """📜 **Bot qoidalari**:
1️⃣ Savolni **matn** yoki **rasm** shaklida yuboring.
2️⃣ Agar siz Reading qismidan matn yubormoqchi bo'lsangiz, sarlavhada "text" deb yozing.
3️⃣ Agar siz Reading qismidan savol yubormoqchi bo'lsangiz, sarlavhada "question" deb yozing.
4️⃣ Bot **A, B, C, D yoki E** bilan javob beradi.
5️⃣ Har bir foydalanuvchi uchun faqat **bitta faol sessiya**.
6️⃣ **Bot shaxsiy** – faqat ro'yxatga kiritilgan foydalanuvchilar kirishlari mumkin.
7️⃣ Suiiste'mol qilish banlanishga olib keladi.

🔹 Endi savol yuboring!""", }

MESSAGES = {
    "session_expired": {
        'english': "⚠️ *Session expired.* Please restart the bot using /start.",
        'russian': "⚠️ *Сессия истекла.* Пожалуйста, перезапустите бота с помощью /start.",
        'uzbek': "⚠️ *Sessiya muddati tugadi.* Iltimos, /start buyrug'ini yuboring."
    },
    "processing_error": {
        'english': "⚠️ Error processing your request.",
        'russian': "⚠️ Ошибка при обработке вашего запроса.",
        'uzbek': "⚠️ So'rovingizni qayta ishlashda xatolik yuz berdi."
    },
    "no_answer": {
        'english': "⚠️ Unable to determine an answer.",
        'russian': "⚠️ Невозможно определить ответ.",
        'uzbek': "⚠️ Javobni aniqlash mumkin emas."
    },
    "image_not_clear": {
        'english': "⚠️ Image is not clear enough to answer.",
        'russian': "⚠️ Изображение недостаточно четкое для ответа.",
        'uzbek': "⚠️ Rasmni javoblash uchun yetarli emas."
    },
    "text_saved": {
        'english': "✅ Text saved.",
        'russian': "✅ Текст сохранен.",
        'uzbek': "✅ Matn saqlandi."
    },
    "not_a_text": {
        'english': "⚠️ It is not a text",
        'russian': "⚠️ Это не текст",
        'uzbek': "⚠️ Bu matn emas"
    },
    "image_not_clear_extract": {
        'english': "⚠️ Image is not clear enough to extract text.",
        'russian': "⚠️ Изображение недостаточно четкое для извлечения текста.",
        'uzbek': "⚠️ Rasm matnini ajratib olish uchun yetarli emas."
    }
}

async def send_localized_message(message: Message, key: str):
    global lang
    await message.answer(MESSAGES[key][lang])

@dp.message(CommandStart())
async def start_command(message: Message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    username = message.from_user.username
    print(f"User {username}: {user_id} started the bot.")

    if not await check_allowed_user(user_id):
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
        await send_localized_message(message, "session_expired")
        return
    
    user_input = message.text
    try:
        with get_openai_callback() as cb:
            response = llm.invoke([
                HumanMessage(content=PROMPT.format(question=user_input))
            ])
            print(f'Evaluator Gemini Callcack (Text Question): {cb}')
        
        ai_reply = response.content.strip().upper()
        await process_ai_reply(message, ai_reply)
    
    except Exception as e:
        logging.error(f"Error processing text: {e}")
        await send_localized_message(message, "processing_error")

async def download_photo(file_url: str, file_path: str):
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(file_url, timeout=10)
            response.raise_for_status()

            async with aiofiles.open(file_path, "wb") as f:
                await f.write(response.content)
            print(f"Photo downloaded to: {file_path}")
            return True
        except httpx.HTTPStatusError as e:
            print(f"HTTP error downloading photo: {e}")
            return False
        except httpx.TimeoutException as e:
            print(f"Timeout error downloading photo: {e}")
            return False
        except Exception as e:
            print(f"Error downloading photo: {e}")
            return False

@dp.message(lambda message: message.photo is not None)
async def handle_image_question(message: Message):
    global lang, passage
    user_id = message.from_user.id
    username = message.from_user.username
    caption = message.caption.strip().lower() if message.caption else None

    if user_id not in active_sessions:
        await send_localized_message(message, "session_expired")
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

        if not await download_photo(file_url, file_path):
            await send_localized_message(message, "processing_error")
            return

        try:
            try:
                image_data = base64.b64encode(httpx.get(file_url).content).decode("utf-8")
            except Exception as e:
                logging.error(f"Error encoding image: {e}")
                await send_localized_message(message, "processing_error")
            if caption is None:
                try:
                    with get_openai_callback() as cb:
                        response = llm.invoke([
                            HumanMessage(content=[
                                    {"type": "text", "text": PROMPT.format(question='[Image Question]', lang=lang)},
                                    {
                                        "type": "image_url",
                                        "image_url": {"url": f"data:image/jpeg;base64,{image_data}"},
                                    },
                                ],)
                        ])
                        print(f'Evaluator Gemini Callcack (Image Question with PROMPT): {cb}')
                    
                    ai_reply = response.content.strip().upper()
                    await process_ai_reply(message, ai_reply)

                except Exception as e:
                    logging.error(f"Error processing image with PROMPT: {e}")
                    await send_localized_message(message, "processing_error")

            elif caption == 'text':
                try:
                    with get_openai_callback() as cb:
                        response = llm.invoke([
                            HumanMessage(content=[
                                    {"type": "text", "text": EXTRACT_PROMPT.format(text='[Image Question]')},
                                    {
                                        "type": "image_url",
                                        "image_url": {"url": f"data:image/jpeg;base64,{image_data}"},
                                    },
                                ],)
                        ])
                        print(f'Evaluator Gemini Callcack (Image Question with EXTRACT_PROMPT): {cb}')

                    passage = response.content.strip().lower()

                    if "ANSWER:" in passage:
                        await process_ai_reply(message, ai_reply)
                    else:
                        await send_localized_message(message, "text_saved")
                
                except Exception as e:
                    logging.error(f"Error processing image with EXTRACT_PROMPT: {e}")
                    await send_localized_message(message, "processing_error")

            elif caption == 'question':
                try:
                    with get_openai_callback() as cb:
                        response = llm.invoke([
                            HumanMessage(content=[
                                    {"type": "text", "text": PASSAGE_PROMPT.format(question='[Image Question]', passage=passage, lang=lang)},
                                    {
                                        "type": "image_url",
                                        "image_url": {"url": f"data:image/jpeg;base64,{image_data}"},
                                    },
                                ],)
                        ])
                        print(f'Evaluator Gemini Callcack (Image Question with PASSAGE_PROMPT): {cb}')

                    ai_reply = response.content.strip().upper()
                    await process_ai_reply(message, ai_reply)

                except Exception as e:
                    logging.error(f"Error processing image with PASSAGE_PROMPT: {e}")
                    await send_localized_message(message, "processing_error")

        except Exception as e:
            logging.error(f"Error processing image by Gemini: {e}")
            await send_localized_message(message, "processing_error")

    except Exception as e:
        logging.error(f"Error processing image: {e}")
        await send_localized_message(message, "processing_error")

@dp.message(lambda message: message.text == "/logout")
async def logout_user(message: Message):
    user_id = message.from_user.id
    if user_id in active_sessions:
        del active_sessions[user_id]
        await message.answer("✅ You have been logged out.")
    else:
        await message.answer("⚠️ No active session found.")

async def process_ai_reply(message: Message, ai_reply: str):
    global lang
    if "ANSWER:" in ai_reply:
        if '0000' in ai_reply:
            await send_localized_message(message, "image_not_clear")
        elif '1111' in passage:
            await send_localized_message(message, "not_a_text")
        else:
            last_index = ai_reply.rfind("ANSWER:")
            await message.answer(ai_reply[last_index:])
    else:
        await send_localized_message(message, "no_answer")

async def main():
    logging.basicConfig(level=logging.INFO)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
