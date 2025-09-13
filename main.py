import logging
import requests
import schedule
import asyncio
import os
import re
import json
import feedparser
import urllib.parse
from bs4 import BeautifulSoup
import requests
from aiogram import Bot, Dispatcher, types, F
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.storage.memory import MemoryStorage
import sys
import random
import signal
import string
from datetime import datetime, timedelta
from typing import List, Dict

# Ваши ключи и токены
API_TOKEN = '7226649270:AAFgXkNsHCqs5ICPrG3XoNHe0BTtWNPR1Ag'
OPENROUTER_API_KEY = "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"
GOOGLE_SEARCH_API_KEY = 'AIzaSyDlIECnnquOUu8Xr6pv0jqZZHRX7_m4W_0'
GOOGLE_SEARCH_ENGINE_ID = 'b6cc8f5bfe1264884'  # Добавьте ваш ID поисковой системы
MAIN_ADMIN_ID = 6223032529

DATA_FILE = 'bot_data.json'

# Инициализация бота и диспетчера
bot = Bot(token=API_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# Логгер
logging.basicConfig(level=logging.INFO)

# Глобальные переменные
channels = {}
is_posting_active = {1: False, 2: False, 3: False, 4: False}
admins = [MAIN_ADMIN_ID]
active_keys = {}
user_access = {}
randomization = {}
# Словарь для хранения задач постинга, ключ - (user_id, slot)
posting_tasks: Dict[tuple, asyncio.Task] = {}
# Словарь для хранения времени последнего поста для каждого слота, ключ - (user_id, slot)
last_post_time: Dict[tuple, datetime] = {}
logging_enabled = {}
# Словарь для хранения уже отправленных новостей
posted_news: Dict[tuple, List[str]] = {}
# Словарь для хранения пользовательского текста
user_texts: Dict[int, str] = {}

# Определение состояний
class Form(StatesGroup):
    slot = State()
    channel = State()
    interval = State()
    theme = State()
    post_size = State()
    signature = State()
    language = State()
    tone = State()
    custom_instructions = State()
    add_admin = State()
    generate_key = State()
    remove_admin = State()
    broadcast = State()
    enter_key = State()

def save_data():
    data = {
        'channels': channels, 
        'is_posting_active': is_posting_active, 
        'admins': admins, 
        'active_keys': {k: v.isoformat() for k, v in active_keys.items()},  # Преобразуем datetime в строку
        'user_access': {k: v.isoformat() for k, v in user_access.items()},  # Преобразуем datetime в строку
        'randomization': randomization, 
        'logging_enabled': logging_enabled,
        'last_post_time': {f"{k[0]}_{k[1]}": v.isoformat() if v else None for k, v in last_post_time.items()},
        'posted_news': {f"{k[0]}_{k[1]}": v for k, v in posted_news.items()},
        'user_texts': user_texts
    }
    with open(DATA_FILE, 'w') as f:
        json.dump(data, f)


def load_data():
    global channels, is_posting_active, admins, active_keys, user_access, randomization, logging_enabled, posted_news, user_texts
    if os.path.exists(DATA_FILE) and os.path.getsize(DATA_FILE) > 0:
        try:
            with open(DATA_FILE, 'r') as f:
                data = json.load(f)
            channels = data.get('channels', {})
            is_posting_active = data.get('is_posting_active', {1: False, 2: False, 3: False, 4: False})
            admins = data.get('admins', [MAIN_ADMIN_ID])
            active_keys = {k: datetime.fromisoformat(v) for k, v in data.get('active_keys', {}).items()}
            user_access = {k: datetime.fromisoformat(v) for k, v in data.get('user_access', {}).items()}
            randomization = data.get('randomization', {})
            last_post_time_str = data.get('last_post_time', {})
            last_post_time = {}
            for key, value in last_post_time_str.items():
                last_post_time[tuple(map(int, key.split('_'))) ] = datetime.fromisoformat(value) if value else None
            logging_enabled = data.get('logging_enabled', {})
            posted_news_str = data.get('posted_news', {})
            posted_news = {}
            for key, value in posted_news_str.items():
                posted_news[tuple(map(int, key.split('_')))] = value
            user_texts = data.get('user_texts', {})
        except json.JSONDecodeError:
            logging.error(f"Invalid JSON in {DATA_FILE}. Starting with default values.")
            # Initialize with default values
            channels = {}
            is_posting_active = {1: False, 2: False, 3: False, 4: False}
    else:
        # Initialize with default values if file doesn't exist or is empty
        channels = {}
        is_posting_active = {1: False, 2: False, 3: False, 4: False}
        admins = [MAIN_ADMIN_ID]
        active_keys = {}
        user_access = {}
        randomization = {}
        logging_enabled = {}
        posted_news = {}
        user_texts = {}


def signal_handler(signum, frame):
    logging.info("Получен сигнал завершения. Сохранение данных...")
    save_data()
    logging.info("Данные сохранены. Завершение работы.")
    sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)


async def check_channel_access(channel_id):
    try:
        chat = await bot.get_chat(channel_id)
        bot_member = await bot.get_chat_member(chat_id=channel_id, user_id=bot.id)
        if bot_member.status in ['administrator', 'member']:
            return True
        else:
            return False
    except Exception as e:
        logging.error(f"Ошибка при проверке доступа к каналу: {e}")
        return False


async def get_google_news_rss(theme, language):
    encoded_theme = urllib.parse.quote(theme)
    url = f"https://news.google.com/rss/search?q={encoded_theme}&hl={language}&gl=RU&ceid=RU:{language}"
    feed = feedparser.parse(url)
    return feed

async def get_image_url(article_url):
    try:
        response = requests.get(article_url)
        soup = BeautifulSoup(response.text, 'html.parser')
        og_image = soup.find('meta', property='og:image')
        if og_image:
            return og_image['content']
    except Exception as e:
        logging.error(f"Ошибка при получении изображения: {e}")
    return None


async def generate_post(user_id, slot, channel_id, themes, post_size, signature, language, tone, custom_instructions):
    try:
        if not await check_channel_access(channel_id):
            error_message = f"Бот не имеет доступа к каналу {channel_id}. Пожалуйста, проверьте настройки канала."
            logging.error(error_message)
            await bot.send_message(user_id, error_message)
            return

        # Проверяем, прошло ли достаточно времени с момента последнего поста
        if (user_id, slot) in last_post_time and (datetime.now() - last_post_time[(user_id, slot)]).total_seconds() < 60:
            logging.info(f"Пост для пользователя {user_id}, слот {slot} пропущен, так как еще не прошло достаточно времени с момента последнего поста.")
            return

        logging.info(f"Запрос новостей для пользователя {user_id}, слот {slot}...")
        await bot.send_message(user_id, f"Запрос новостей для слота {slot}...")

        theme = random.choice(themes)
        feed = await get_google_news_rss(theme, language)

        if not feed.entries:
            error_message = f"Новости не найдены для слота {slot} по теме '{theme}'. Попробуйте изменить тему."
            logging.error(error_message)
            await bot.send_message(user_id, error_message)
            return

        # Выбираем случайную новость из последних 5 (или меньше, если новостей меньше 5)
        article = random.choice(feed.entries[:min(5, len(feed.entries))])
        title = article.title
        content = article.summary
        link = article.link

        # Проверка на повторение новостей
        if (user_id, slot) not in posted_news:
            posted_news[(user_id, slot)] = []
        if title in posted_news[(user_id, slot)]:
            logging.info(f"Новость '{title}' уже была отправлена. Пропускаем.")
            return

        image_url = await get_image_url(link)

        logging.info(f"Запрос к OpenRouter API для пользователя {user_id}, слот {slot}...")
        await bot.send_message(user_id, f"Генерация поста с помощью AI для слота {slot}...")

        openrouter_url = "https://openrouter.ai/api/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "Content-Type": "application/json"
        }
        data = {
            "messages": [
                {"role": "system", "content": f"You are a helpful assistant that rewrites news articles in {language} with a {tone} tone. {custom_instructions}"},
                {"role": "user", "content": f"Rewrite the following news article in about {post_size} characters in {language} with a {tone} tone. The article should be clearly about the theme '{theme}'. Make sure the first paragraph is a brief summary of the article. Do not include any English text in your response. Use Markdown formatting for better readability:\n\nTitle: {title}\n\n{content}"}
            ],
            "model": "deepseek/deepseek-chat-v3.1:free",
            "max_tokens": post_size
        }

        openrouter_response = requests.post(openrouter_url, json=data, headers=headers)

        if openrouter_response.status_code != 200:
            error_message = f"Ошибка при запросе к OpenRouter API для слота {slot}: {openrouter_response.status_code} - {openrouter_response.text}"
            logging.error(error_message)
            await bot.send_message(user_id, error_message)
            return

        openrouter_data = openrouter_response.json()
        post_text = openrouter_data['choices'][0]['message']['content'].strip()

        # Функция для очистки Markdown
        def clean_markdown(text):
            # Заменяем одинарные звездочки на нижние подчеркивания для курсива
            text = re.sub(r'(?<!\*)\*(?!\*)(.*?)(?<!\*)\*(?!\*)', r'_\1_', text)
            # Заменяем двойные звездочки на одинарные для жирного шрифта
            text = re.sub(r'\*\*(.*?)\*\*', r'*\1*', text)
            # Удаляем все оставшиеся одиночные звездочки
            text = re.sub(r'(?<!\*)\*(?!\*)', '', text)
            # Убеждаемся, что все открывающие теги имеют закрывающие
            open_tags = re.findall(r'(\*|_)', text)
            for tag in open_tags:
                if open_tags.count(tag) % 2 != 0:
                    text = text.replace(tag, '', 1)
            return text

        # Очищаем текст
        post_text = clean_markdown(post_text)

        # Разделяем текст на абзацы
        paragraphs = post_text.split('\n\n')

        # Гарантированно выделяем первый абзац (заголовок) жирным шрифтом
        if paragraphs:
            paragraphs[0] = f"*{paragraphs[0].strip('*_')}*"

        # Собираем текст обратно
        post_text = '\n\n'.join(paragraphs)

        # Добавляем подпись и ссылку на оригинальную статью
        post_text += f"\n\n*{signature}*"

        # Отправляем сообщение с изображением, если оно есть
        if image_url:
            await bot.send_photo(channel_id, photo=image_url, caption=post_text, parse_mode='Markdown')
        else:
            await send_message_with_retry(channel_id, post_text, parse_mode='Markdown')

        # Обновляем время последнего поста
        last_post_time[(user_id, slot)] = datetime.now()
        # Добавляем новость в список отправленных
        posted_news[(user_id, slot)].append(title)

    except Exception as e:
        error_message = f"Ошибка при генерации или отправке поста для слота {slot}: {str(e)}"
        logging.error(error_message)
        await bot.send_message(user_id, error_message)
        logging.exception("Полное исключение:")


async def send_message_with_retry(chat_id, text, parse_mode='Markdown', max_retries=3):
    for attempt in range(max_retries):
        try:
            await bot.send_message(chat_id, text, parse_mode=parse_mode)
            return
        except TelegramAPIError as e:
            if "can't parse entities" in str(e):
                logging.warning(f"Ошибка парсинга Markdown (попытка {attempt + 1}): {e}")
                if attempt == max_retries - 
Generated by DeepSeek-V2.5
дальше

Конечно, продолжим. Мы добавим обработку пользовательского текста и обновим остальные части кода, чтобы они соответствовали новому API провайдеру OpenRouter.

Обработка пользовательского текста
Мы добавим обработку пользовательского текста, который пользователь может отправить в диалог с ботом. Этот текст будет использоваться в ближайшем посте.

Обновленный код
python
Copy code
async def send_message_with_retry(chat_id, text, parse_mode='Markdown', max_retries=3):
    for attempt in range(max_retries):
        try:
            await bot.send_message(chat_id, text, parse_mode=parse_mode)
            return
        except TelegramAPIError as e:
            if "can't parse entities" in str(e):
                logging.warning(f"Ошибка парсинга Markdown (попытка {attempt + 1}): {e}")
                if attempt == max_retries - 1:
                    # Последняя попытка - отправляем без форматирования
                    await bot.send_message(chat_id, text, parse_mode=None)
            else:
                raise


def schedule_post(user_id, slot, channel_id, settings):
    interval = settings['interval']
    if randomization.get(user_id, False):
        interval = random.randint(max(1, interval - 5), interval + 5)

    async def post_task():
        await generate_post(
            user_id,
            slot,
            channel_id,
            settings['themes'],
            settings['post_size'],
            settings['signature'],
            settings['language'],
            settings['tone'],
            settings.get('custom_instructions', '')
        )

    # Запланируем задачу с учетом возможной отмены
    loop = asyncio.get_event_loop()
    task = loop.create_task(post_task())
    posting_tasks[(user_id, slot)] = task
    logging.info(f"Запланирован постинг для пользователя {user_id}, слот {slot} в канал {channel_id} через {interval} минут.")


def reschedule_posts():
    """Перепланирует все задачи постинга."""
    global posting_tasks
    # Отменяем все текущие задачи
    for task in posting_tasks.values():
        task.cancel()
    posting_tasks = {}

    # Планируем новые задачи
    for user_id, user_settings in channels.items():
        for slot, settings in user_settings.items():
            if 'channels_to_post' not in settings or 'interval' not in settings:
                continue
            channel_id = settings['channels_to_post'][0]

            next_run = datetime.now() + timedelta(minutes=interval)
            if next_run.year > 9999:  # Проверка на переполнение
                logging.error(f"Ошибка планирования для пользователя {user_id}, слот {slot}: дата выходит за допустимые пределы")
                continue

            schedule.every(interval).minutes.do(
                lambda user_id=user_id, slot=slot, channel_id=channel_id, settings=settings: asyncio.create_task(
                    generate_post(
                        user_id,
                        slot,
                        channel_id,
                        settings['themes'],
                        settings['post_size'],
                        settings['signature'],
                        settings['language'],
                        settings['tone'],
                        settings.get('custom_instructions', '')
                    )
                )
            )
            logging.info(f"Запланирован постинг для пользователя {user_id}, слот {slot} в канал {channel_id} каждые {interval} минут.")


@dp.message(Command(commands=['start']))
async def send_welcome(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    if user_id in admins:
        await message.reply("Добрый день! Вы авторизированы как Администратор ✅")
        await show_main_menu(message)
    elif user_id not in user_access or not user_access[user_id]:
        await message.reply("Добрый день! Приобретите ключ у @Trappeew1ch")
        await message.answer("Введите ваш ключ доступа:")
        await state.set_state(Form.enter_key)
    else:
        await show_main_menu(message)

async def show_main_menu(message: types.Message):
    user_id = message.from_user.id
    keyboard = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="📋 Меню")]], resize_keyboard=True)
    await message.answer("Главное меню", reply_markup=keyboard)

@dp.message(F.text == "📋 Меню")
async def show_inline_menu(message: types.Message):
    user_id = message.from_user.id
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🤖 Нейропостинг", callback_data='neuroposting')],
            [InlineKeyboardButton(text="⚙️ Настройки", callback_data='settings')]
        ]
    )

    if user_id in admins:
        keyboard.inline_keyboard.append([InlineKeyboardButton(text="👑 Админ панель", callback_data='admin_panel')])

    await message.answer("Выберите действие:", reply_markup=keyboard)

@dp.message(Form.enter_key)
async def process_key(message: types.Message, state: FSMContext):
    entered_key = message.text
    if entered_key in active_keys:
        user_id = message.from_user.id
        user_access[user_id] = active_keys[entered_key]
        del active_keys[entered_key]
        await message.answer("Ключ принят. Доступ предоставлен.")
        await show_main_menu(message)
    else:
        await message.answer("Неверный ключ. Попробуйте еще раз или свяжитесь с администратором.")
    await state.clear()

@dp.callback_query(F.data == 'neuroposting')
async def process_neuroposting(callback_query: types.CallbackQuery):
    global is_posting_active
    # Ensure is_posting_active has all required keys
    for i in range(1, 5):
        if i not in is_posting_active:
            is_posting_active[i] = False

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=f"Слот {i} {'✅' if is_posting_active[i] else '❌'}", callback_data=f'slot_{i}') for i in range(1, 5)],
            [InlineKeyboardButton(text="🔙 Назад", callback_data='back_to_main')]
        ]
    )

    await bot.answer_callback_query(callback_query.id)
    await bot.edit_message_text(chat_id=callback_query.from_user.id, message_id=callback_query.message.message_id, 
                                text="Выберите слот для настройки:", reply_markup=keyboard)

@dp.callback_query(F.data == 'back_to_main')
async def process_back_to_main(callback_query: types.CallbackQuery):
    await bot.answer_callback_query(callback_query.id)
    await show_inline_menu(callback_query.message)

@dp.callback_query(F.data.startswith('slot_'))
async def process_slot_selection(callback_query: types.CallbackQuery, state: FSMContext):
    slot = int(callback_query.data.split('_')[1])
    await state.update_data(current_slot=slot)

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔧 Установить канал", callback_data=f'set_channel_{slot}')],
            [InlineKeyboardButton(text="⏱ Установить интервал", callback_data=f'set_interval_{slot}')],
            [InlineKeyboardButton(text="📚 Установить тематику", callback_data=f'set_theme_{slot}')],
            [InlineKeyboardButton(text="✏️ Установить размер поста", callback_data=f'set_post_size_{slot}')],
            [InlineKeyboardButton(text="✍️ Установить подпись", callback_data=f'set_signature_{slot}')],
            [InlineKeyboardButton(text="🌐 Установить язык", callback_data=f'set_language_{slot}')],
            [InlineKeyboardButton(text="😊 Установить тон", callback_data=f'set_tone_{slot}')],
            [InlineKeyboardButton(text="🎨 Пользовательские инструкции", callback_data=f'set_custom_instructions_{slot}')],
            [InlineKeyboardButton(text="🔍 Просмотр настроек", callback_data=f'view_settings_{slot}')],
            [InlineKeyboardButton(text="▶️ Старт постинга", callback_data=f'start_posting_{slot}')],
            [InlineKeyboardButton(text="⏸️ Стоп постинга", callback_data=f'stop_posting_{slot}')],
            [InlineKeyboardButton(text="🔙 Назад", callback_data='neuroposting')]
        ]
    )

    await bot.answer_callback_query(callback_query.id)
    await bot.edit_message_text(chat_id=callback_query.from_user.id, message_id=callback_query.message.message_id,
                                text=f"Настройка слота {slot}. Выберите действие:", reply_markup=keyboard)

@dp.callback_query(F.data.startswith('set_channel_'))
async def process_set_channel(callback_query: types.CallbackQuery, state: FSMContext):
    slot = int(callback_query.data.split('_')[2])
    await state.update_data(current_slot=slot)
    await bot.answer_callback_query(callback_query.id)
    await bot.send_message(callback_query.from_user.id, f"Отправьте ID канала для слота {slot}:")
    await state.set_state(Form.channel)

@dp.callback_query(F.data == 'settings')
async def process_settings(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=f"🔑 Лицензия", callback_data='license')],
            [InlineKeyboardButton(text=f"🎲 Рандомизация отправки {'✅' if randomization.get(user_id, False) else '❌'}", callback_data='randomization')],
            [InlineKeyboardButton(text=f"📝 Логирование {'✅' if logging_enabled.get(user_id, False) else '❌'}", callback_data='logging')],
            [InlineKeyboardButton(text="🔙 Назад", callback_data='back_to_main')]
        ]
    )
    await bot.edit_message_text(chat_id=user_id, message_id=callback_query.message.message_id,
                                text="Настройки:", reply_markup=keyboard)

@dp.callback_query(F.data == 'license')
async def process_license(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    license_info = "Ваша лицензия действительна до: " + user_access.get(user_id, "Лицензия не найдена")
    await bot.answer_callback_query(callback_query.id, text=license_info, show_alert=True)

@dp.callback_query(F.data == 'randomization')
async def process_randomization(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Включить", callback_data='randomization_on'),
             InlineKeyboardButton(text="Выключить", callback_data='randomization_off')],
            [InlineKeyboardButton(text="🔙 Назад", callback_data='settings')]
        ]
    )
    await bot.edit_message_text(chat_id=user_id, message_id=callback_query.message.message_id,
                                text="Рандомизация - алгоритм, позволяющий отправлять посты с разбросом в 5 минут. "
                                     "Например, если интервал установлен на 1 час, пост может быть отправлен через 60-65 минут.",
                                reply_markup=keyboard)

# Новые функции для включения/выключения рандомизации
@dp.callback_query(F.data == 'randomization_on')
async def turn_randomization_on(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    randomization[user_id] = True
    await bot.answer_callback_query(callback_query.id, text="Рандомизация включена")
    await process_settings(callback_query)

@dp.callback_query(F.data == 'randomization_off')
async def turn_randomization_off(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    randomization[user_id] = False
    await bot.answer_callback_query(callback_query.id, text="Рандомизация выключена")
    await process_settings(callback_query)

# Новая функция для обработки кнопки "Логирование"
@dp.callback_query(F.data == 'logging')
async def process_logging(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Включить", callback_data='logging_on'),
             InlineKeyboardButton(text="Выключить", callback_data='logging_off')],
            [InlineKeyboardButton(text="🔙 Назад", callback_data='settings')]
        ]
    )
    await bot.edit_message_text(chat_id=user_id, message_id=callback_query.message.message_id,
                                text="Логирование - уведомление о всех действиях бота, таких как запросы, генерация ответов и т.д.",
                                reply_markup=keyboard)

# Новые функции для включения/выключения логирования
@dp.callback_query(F.data == 'logging_on')
async def turn_logging_on(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    logging_enabled[user_id] = True
    await bot.answer_callback_query(callback_query.id, text="Логирование включено")
    await process_settings(callback_query)

@dp.callback_query(F.data == 'logging_off')
async def turn_logging_off(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    logging_enabled[user_id] = False
    await bot.answer_callback_query(callback_query.id, text="Логирование выключено")
    await process_settings(callback_query)

# Обновленная функция process_set_theme
@dp.callback_query(F.data.startswith('set_theme_'))
async def process_set_theme(callback_query: types.CallbackQuery, state: FSMContext):
    slot = int(callback_query.data.split('_')[2])
    await state.update_data(current_slot=slot)
    await bot.answer_callback_query(callback_query.id)
    await bot
Generated by DeepSeek-V2.5
дальше

Конечно, продолжим с обновленной функцией process_set_theme и добавим обработку пользовательского текста.

Обновленная функция process_set_theme
python
Copy code
@dp.callback_query(F.data.startswith('set_theme_'))
async def process_set_theme(callback_query: types.CallbackQuery, state: FSMContext):
    slot = int(callback_query.data.split('_')[2])
    await state.update_data(current_slot=slot)
    await bot.answer_callback_query(callback_query.id)
    await bot.send_message(callback_query.from_user.id, 
                           "Введите тематики постов, которые вы хотите видеть. Вы можете ввести несколько тематик, разделяя их запятыми.\n"
                           "Примеры: новости нейросетей, способы заработка на бонусных программах, программирование, нейросети.")
    await state.set_state(Form.theme)
Обработка пользовательского текста
Мы добавим обработку пользовательского текста, который пользователь может отправить в диалог с ботом. Этот текст будет использоваться в ближайшем посте.

python
Copy code
@dp.message()
async def handle_user_text(message: types.Message):
    user_id = message.from_user.id
    user_texts[user_id] = message.text
    await message.reply("Ваш текст сохранен и будет использован в ближайшем посте.")
Обновленная функция generate_post с использованием пользовательского текста
Мы обновим функцию generate_post, чтобы она использовала пользовательский текст, если он доступен.

python
Copy code
async def generate_post(user_id, slot, channel_id, themes, post_size, signature, language, tone, custom_instructions):
    try:
        if not await check_channel_access(channel_id):
            error_message = f"Бот не имеет доступа к каналу {channel_id}. Пожалуйста, проверьте настройки канала."
            logging.error(error_message)
            await bot.send_message(user_id, error_message)
            return

        # Проверяем, прошло ли достаточно времени с момента последнего поста
        if (user_id, slot) in last_post_time and (datetime.now() - last_post_time[(user_id, slot)]).total_seconds() < 60:
            logging.info(f"Пост для пользователя {user_id}, слот {slot} пропущен, так как еще не прошло достаточно времени с момента последнего поста.")
            return

        logging.info(f"Запрос новостей для пользователя {user_id}, слот {slot}...")
        await bot.send_message(user_id, f"Запрос новостей для слота {slot}...")

        theme = random.choice(themes)
        feed = await get_google_news_rss(theme, language)

        if not feed.entries:
            error_message = f"Новости не найдены для слота {slot} по теме '{theme}'. Попробуйте изменить тему."
            logging.error(error_message)
            await bot.send_message(user_id, error_message)
            return

        # Выбираем случайную новость из последних 5 (или меньше, если новостей меньше 5)
        article = random.choice(feed.entries[:min(5, len(feed.entries))])
        title = article.title
        content = article.summary
        link = article.link

        # Проверка на повторение новостей
        if (user_id, slot) not in posted_news:
            posted_news[(user_id, slot)] = []
        if title in posted_news[(user_id, slot)]:
            logging.info(f"Новость '{title}' уже была отправлена. Пропускаем.")
            return

        image_url = await get_image_url(link)

        logging.info(f"Запрос к OpenRouter API для пользователя {user_id}, слот {slot}...")
        await bot.send_message(user_id, f"Генерация поста с помощью AI для слота {slot}...")

        # Используем пользовательский текст, если он доступен
        if user_id in user_texts:
            content = user_texts[user_id]
            del user_texts[user_id]

        openrouter_url = "https://openrouter.ai/api/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "Content-Type": "application/json"
        }
        data = {
            "messages": [
                {"role": "system", "content": f"You are a helpful assistant that rewrites news articles in {language} with a {tone} tone. {custom_instructions}"},
                {"role": "user", "content": f"Rewrite the following news article in about {post_size} characters in {language} with a {tone} tone. The article should be clearly about the theme '{theme}'. Make sure the first paragraph is a brief summary of the article. Do not include any English text in your response. Use Markdown formatting for better readability:\n\nTitle: {title}\n\n{content}"}
            ],
            "model": "google/gemini-pro-1.5-exp",
            "max_tokens": post_size
        }

        openrouter_response = requests.post(openrouter_url, json=data, headers=headers)

        if openrouter_response.status_code != 200:
            error_message = f"Ошибка при запросе к OpenRouter API для слота {slot}: {openrouter_response.status_code} - {openrouter_response.text}"
            logging.error(error_message)
            await bot.send_message(user_id, error_message)
            return

        openrouter_data = openrouter_response.json()
        post_text = openrouter_data['choices'][0]['message']['content'].strip()

        # Функция для очистки Markdown
        def clean_markdown(text):
            # Заменяем одинарные звездочки на нижние подчеркивания для курсива
            text = re.sub(r'(?<!\*)\*(?!\*)(.*?)(?<!\*)\*(?!\*)', r'_\1_', text)
            # Заменяем двойные звездочки на одинарные для жирного шрифта
            text = re.sub(r'\*\*(.*?)\*\*', r'*\1*', text)
            # Удаляем все оставшиеся одиночные звездочки
            text = re.sub(r'(?<!\*)\*(?!\*)', '', text)
            # Убеждаемся, что все открывающие теги имеют закрывающие
            open_tags = re.findall(r'(\*|_)', text)
            for tag in open_tags:
                if open_tags.count(tag) % 2 != 0:
                    text = text.replace(tag, '', 1)
            return text

        # Очищаем текст
        post_text = clean_markdown(post_text)

        # Разделяем текст на абзацы
        paragraphs = post_text.split('\n\n')

        # Гарантированно выделяем первый абзац (заголовок) жирным шрифтом
        if paragraphs:
            paragraphs[0] = f"*{paragraphs[0].strip('*_')}*"

        # Собираем текст обратно
        post_text = '\n\n'.join(paragraphs)

        # Добавляем подпись и ссылку на оригинальную статью
        post_text += f"\n\n*{signature}*"

        # Отправляем сообщение с изображением, если оно есть
        if image_url:
            await bot.send_photo(channel_id, photo=image_url, caption=post_text, parse_mode='Markdown')
        else:
            await send_message_with_retry(channel_id, post_text, parse_mode='Markdown')

        # Обновляем время последнего поста
        last_post_time[(user_id, slot)] = datetime.now()
        # Добавляем новость в список отправленных
        posted_news[(user_id, slot)].append(title)

    except Exception as e:
        error_message = f"Ошибка при генерации или отправке поста для слота {slot}: {str(e)}"
        logging.error(error_message)
        await bot.send_message(user_id, error_message)
        logging.exception("Полное исключение:")
Завершение кода
Теперь, когда все основные функции обновлены, мы можем завершить код, добавив обработку других состояний и запуск бота.

python
Copy code
@dp.message(Form.channel)
async def process_channel_id(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    channel_id = message.text
    data = await state.get_data()
    slot = data['current_slot']

    if not channel_id.startswith('@') and not channel_id.startswith('-100'):
        await bot.send_message(user_id, f"Пожалуйста, введите корректный ID канала (начинается с '@' или '-100') для слота {slot}.")
        return

    if await check_channel_access(channel_id):
        if user_id not in channels:
            channels[user_id] = {}
        if slot not in channels[user_id]:
            channels[user_id][slot] = {}
        channels[user_id][slot]['channels_to_post'] = [channel_id]
        await bot.send_message(user_id, f"✅ Канал {channel_id} сохранен для слота {slot}.")
        logging.info(f"Пользователь {user_id} установил канал {channel_id} для слота {slot}")
    else:
        await bot.send_message(user_id, f"Бот не имеет доступа к этому каналу для слота {slot}. Пожалуйста, добавьте бота в канал как администратора и попробуйте снова.")

    await state.clear()
    await show_slot_menu(message, slot)

@dp.message(Form.interval)
async def process_interval(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    data = await state.get_data()
    slot = data['current_slot']
    try:
        interval = int(message.text)
        if interval < 1:
            raise ValueError("Интервал должен быть положительным числом")

        if user_id not in channels:
            channels[user_id] = {}
        if slot not in channels[user_id]:
            channels[user_id][slot] = {}
        channels[user_id][slot]['interval'] = interval

        await bot.send_message(user_id, f"✅ Интервал {interval} минут сохранен для слота {slot}.")
        logging.info(f"Пользователь {user_id} установил интервал {interval} минут для слота {slot}")
    except ValueError:
        await bot.send_message(user_id, f"Пожалуйста, введите корректное положительное число для интервала слота {slot}.")

    await state.clear()
    await show_slot_menu(message, slot)

@dp.message(Form.theme)
async def process_theme(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    themes = [theme.strip() for theme in message.text.split(',')]
    data = await state.get_data()
    slot = data['current_slot']

    if user_id not in channels:
        channels[user_id] = {}
    if slot not in channels[user_id]:
        channels[user_id][slot] = {}
    channels[user_id][slot]['themes'] = themes

    await bot.send_message(user_id, f"✅ Тематики {', '.join(themes)} сохранены для слота {slot}.")
    logging.info(f"Пользователь {user_id} установил тематики {themes} для слота {slot}")
    await state.clear()
    await show_slot_menu(message, slot)

@dp.message(Form.post_size)
async def process_post_size(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    data = await state.get_data()
    slot = data['current_slot']
    try:
        post_size = int(message.text)
        if post_size < 1 or post_size > 4096:
            raise ValueError("Размер поста должен быть от 1 до 4096 символов")

        if user_id not in channels:
            channels[user_id] = {}
        if slot not in channels[user_id]:
            channels[user_id][slot] = {}
        channels[user_id][slot]['post_size'] = post_size

        await bot.send_message(user_id, f"✅ Размер поста {post_size} символов сохранен для слота {slot}.")
        logging.info(f"Пользователь {user_id} установил размер поста {post_size} символов для слота {slot}")
    except ValueError:
        await bot.send_message(user_id, f"Пожалуйста, введите корректное число от 1 до 4096 для размера поста слота {slot}.")

    await state.clear()
    await show_slot_menu(message, slot)

@dp.message(Form.signature)
async def process_signature(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    signature = message.text
    data = await state.get_data()
    slot = data['current_slot']

    if user_id not in channels:
        channels[user_id] = {}
    if slot not in channels[user_id]:
        channels[user_id][slot] = {}
    channels[user_id][slot]['signature'] = signature

    await bot.send_message(user_id, f"✅ Подпись '{signature}' сохранена для слота {slot}.")
    logging.info(f"Пользователь {user_id} установил подпись '{signature}' для слота {slot}")
    await state.clear()
    await show_slot_menu(message, slot)

@dp.message(Form.language)
async def process_language(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    language = message.text
    data = await state.get_data()
    slot = data['current_slot']

    if user_id not in channels:
        channels[user_id] = {}
    if slot not in channels[user_id]:
        channels[user_id][slot] = {}
    channels[user_id][slot]['language'] = language

    await bot.send_message(user_id, f"✅ Язык {language} сохранен для слота {slot}.")
    logging.info(f"Пользователь {user_id} установил язык {language} для слота {slot}")
    await state.clear()
    await show_slot_menu(message, slot)

@dp.
Generated by DeepSeek-V2.5
дальше

Конечно, продолжим с обработкой других состояний и завершением кода.

Обработка других состояний
python
Copy code
@dp.message(Form.tone)
async def process_tone(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    tone = message.text
    data = await state.get_data()
    slot = data['current_slot']

    if user_id not in channels:
        channels[user_id] = {}
    if slot not in channels[user_id]:
        channels[user_id][slot] = {}
    channels[user_id][slot]['tone'] = tone

    await bot.send_message(user_id, f"✅ Тон {tone} сохранен для слота {slot}.")
    logging.info(f"Пользователь {user_id} установил тон {tone} для слота {slot}")
    await state.clear()
    await show_slot_menu(message, slot)

@dp.message(Form.custom_instructions)
async def process_custom_instructions(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    custom_instructions = message.text
    data = await state.get_data()
    slot = data['current_slot']

    if user_id not in channels:
        channels[user_id] = {}
    if slot not in channels[user_id]:
        channels[user_id][slot] = {}
    channels[user_id][slot]['custom_instructions'] = custom_instructions

    await bot.send_message(user_id, f"✅ Пользовательские инструкции сохранены для слота {slot}.")
    logging.info(f"Пользователь {user_id} установил пользовательские инструкции для слота {slot}")
    await state.clear()
    await show_slot_menu(message, slot)

@dp.callback_query(F.data.startswith('view_settings_'))
async def process_view_settings(callback_query: types.CallbackQuery, state: FSMContext):
    user_id = callback_query.from_user.id
    slot = int(callback_query.data.split('_')[2])
    settings = channels.get(user_id, {}).get(slot, {})

    response_text = f"Настройки для слота {slot}:\n"
    response_text += f"Канал: {settings.get('channels_to_post', ['Не установлено'])[0]}\n"
    response_text += f"Интервал: {settings.get('interval', 'Не установлено')} минут\n"
    response_text += f"Тематики: {', '.join(settings.get('themes', ['Не установлено']))}\n"
    response_text += f"Размер поста: {settings.get('post_size', 'Не установлено')} символов\n"
    response_text += f"Подпись: {settings.get('signature', 'Не установлено')}\n"
    response_text += f"Язык: {settings.get('language', 'Не установлено')}\n"
    response_text += f"Тон: {settings.get('tone', 'Не установлено')}\n"
    response_text += f"Пользовательские инструкции: {settings.get('custom_instructions', 'Не установлено')}\n"

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Назад", callback_data=f'slot_{slot}')]
        ]
    )

    await bot.answer_callback_query(callback_query.id)
    await bot.edit_message_text(chat_id=user_id, message_id=callback_query.message.message_id,
                                text=response_text, reply_markup=keyboard, parse_mode='Markdown')

@dp.callback_query(F.data.startswith('start_posting_'))
async def process_start_posting(callback_query: types.CallbackQuery, state: FSMContext):
    user_id = callback_query.from_user.id
    slot = int(callback_query.data.split('_')[2])

    # Проверка, является ли пользователь администратором
    if user_id in admins:
        is_admin = True
    else:
        is_admin = False

    # Проверка лицензии только для обычных пользователей
    if not is_admin:
        if not check_license(user_id):
            await bot.answer_callback_query(callback_query.id, "Ваша лицензия истекла. Пожалуйста, приобретите новый ключ для продолжения использования бота.", show_alert=True)
            return

    if user_id not in channels or slot not in channels[user_id] or not all(key in channels[user_id][slot] for key in ['channels_to_post', 'interval', 'themes', 'post_size', 'signature', 'language', 'tone']):
        await bot.answer_callback_query(callback_query.id, f"Пожалуйста, настройте все параметры для слота {slot} перед запуском постинга.", show_alert=True)
        return

    settings = channels[user_id][slot]
    channel_id = settings['channels_to_post'][0]

    if not await check_channel_access(channel_id):
        await bot.answer_callback_query(callback_query.id, f"Бот не имеет доступа к каналу {channel_id} для слота {slot}. Пожалуйста, проверьте настройки канала.", show_alert=True)
        return

    is_posting_active[slot] = True
    await bot.answer_callback_query(callback_query.id, f"Постинг запущен для слота {slot}. Генерация первого поста...")
    logging.info(f"Постинг запущен для пользователя {user_id}, слот {slot}")

    # Немедленная отправка первого поста
    await generate_post(
        user_id,
        slot,
        channel_id,
        settings['themes'],
        settings['post_size'],
        settings['signature'],
        settings['language'],
        settings['tone'],
        settings.get('custom_instructions', '')
    )

    schedule_posts()
    await bot.send_message(user_id, f"Следующий пост для слота {slot} будет отправлен через {settings['interval']} минут.")

    # Обновляем клавиатуру
    await update_slot_keyboard(callback_query.message, slot)

@dp.callback_query(F.data.startswith('stop_posting_'))
async def process_stop_posting(callback_query: types.CallbackQuery, state: FSMContext):
    slot = int(callback_query.data.split('_')[2])
    is_posting_active[slot] = False
    schedule.clear()
    await bot.send_message(callback_query.from_user.id, f"Постинг остановлен для слота {slot}.")
    logging.info(f"Постинг остановлен для слота {slot}.")

    # Обновляем клавиатуру
    await update_slot_keyboard(callback_query.message, slot)

async def update_slot_keyboard(message: types.Message, updated_slot: int):
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=f"Слот {i} {'✅' if is_posting_active[i] else '❌'}", callback_data=f'slot_{i}') for i in range(1, 5)],
            [InlineKeyboardButton(text="🔙 Назад", callback_data='back_to_main')]
        ]
    )
    await bot.edit_message_reply_markup(chat_id=message.chat.id, message_id=message.message_id, reply_markup=keyboard)

@dp.callback_query(F.data == 'admin_panel')
async def show_admin_panel(callback_query: types.CallbackQuery):
    if callback_query.from_user.id not in admins:
        await bot.answer_callback_query(callback_query.id, text="У вас нет доступа к админ-панели.")
        return

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="➕ Добавить админа", callback_data='add_admin')],
            [InlineKeyboardButton(text="🔑 Сгенерировать ключ", callback_data='generate_key')],
            [InlineKeyboardButton(text="➖ Удалить админа", callback_data='remove_admin')],
            [InlineKeyboardButton(text="📢 Отправить сообщение всем", callback_data='broadcast')],
            [InlineKeyboardButton(text="🔙 Назад", callback_data='back_to_main')]
        ]
    )

    await bot.answer_callback_query(callback_query.id)
    await bot.edit_message_text(chat_id=callback_query.from_user.id, message_id=callback_query.message.message_id,
                                text="Админ-панель. Выберите действие:", reply_markup=keyboard)

@dp.callback_query(F.data == 'add_admin')
async def process_add_admin(callback_query: types.CallbackQuery, state: FSMContext):
    await bot.answer_callback_query(callback_query.id)
    await bot.send_message(callback_query.from_user.id, "Введите ID пользователя, которого хотите сделать админом:")
    await state.set_state(Form.add_admin)

@dp.message(Form.add_admin)
async def add_admin(message: types.Message, state: FSMContext):
    try:
        new_admin_id = int(message.text)
        if new_admin_id not in admins:
            admins.append(new_admin_id)
            await message.reply(f"Пользователь с ID {new_admin_id} добавлен как админ.")
            logging.info(f"Добавлен новый админ: {new_admin_id}")
        else:
            await message.reply("Этот пользователь уже является админом.")
    except ValueError:
        await message.reply("Пожалуйста, введите корректный ID пользователя (целое число).")
    await state.clear()
    await show_admin_panel(message)

@dp.callback_query(F.data == 'generate_key')
async def process_generate_key(callback_query: types.CallbackQuery, state: FSMContext):
    await bot.answer_callback_query(callback_query.id)
    await bot.send_message(callback_query.from_user.id, "Введите срок действия ключа в формате: 1d 2h 30m (дни, часы, минуты):")
    await state.set_state(Form.generate_key)

@dp.message(Form.generate_key)
async def generate_key(message: types.Message, state: FSMContext):
    try:
        duration = parse_duration(message.text)
        key = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
        expiration_time = datetime.now() + duration
        active_keys[key] = expiration_time
        await message.reply(f"Сгенерирован ключ: {key}\nСрок действия: до {expiration_time.strftime('%Y-%m-%d %H:%M:%S')}")
        logging.info(f"Сгенерирован новый ключ: {key}, действителен до {expiration_time}")
    except ValueError as e:
        await message.reply(str(e))
    await state.clear()
    await show_admin_panel(message)

def parse_duration(duration_str):
    parts = duration_str.split()
    duration = timedelta()
    for part in parts:
        if part.endswith('d'):
            duration += timedelta(days=int(part[:-1]))
        elif part.endswith('h'):
            duration += timedelta(hours=int(part[:-1]))
        elif part.endswith('m'):
            duration += timedelta(minutes=int(part[:-1]))
        else:
            raise ValueError("Неправильный формат. Используйте: 1d 2h 30m")
    if duration.total_seconds() == 0:
        raise ValueError("Продолжительность должна быть больше нуля")
    return duration

@dp.callback_query(F.data == 'remove_admin')
async def process_remove_admin(callback_query: types.CallbackQuery, state: FSMContext):
    await bot.answer_callback_query(callback_query.id)
    await bot.send_message(callback_query.from_user.id, "Введите ID админа, которого хотите удалить:")
    await state.set_state(Form.remove_admin)

@dp.message(Form.remove_admin)
async def remove_admin(message: types.Message, state: FSMContext):
    try:
        admin_id = int(message.text)
        if admin_id == MAIN_ADMIN_ID:
            await message.reply("Нельзя удалить главного администратора.")
        elif admin_id in admins:
            admins.remove(admin_id)
            await message.reply(f"Админ с ID {admin_id} удален.")
            logging.info(f"Удален админ: {admin_id}")
        else:
            await message.reply("Этот пользователь не является админом.")
    except ValueError:
        await message.reply("Пожалуйста, введите корректный ID пользователя (целое число).")
    await state.clear()
    await show_admin_panel(message)

@dp.callback_query(F.data == 'broadcast')
async def process_broadcast(callback_query: types.CallbackQuery, state: FSMContext):
    await bot.answer_callback_query(callback_query.id)
    await bot.send_message(callback_query.from_user.id, "Введите сообщение для рассылки всем пользователям:")
    await state.set_state(Form.broadcast)

@dp.message(Form.broadcast)
async def send_broadcast(message: types.Message, state: FSMContext):
    broadcast_message = message.text
    success_count = 0
    fail_count = 0
    for user_id in user_access.keys():
        try:
            await bot.send_message(user_id, broadcast_message)
            success_count += 1
        except Exception as e:
            logging.error(f"Ошибка при отправке сообщения пользователю {user_id}: {e}")
            fail_count += 1

    await message.reply(f"Рассылка завершена.\nУспешно отправлено: {success_count}\nОшибок: {fail_count}")
    logging.info(f"Выполнена рассылка. Успешно: {success_count}, Ошибок: {fail_count}")
    await state.clear()
    await show_admin_panel(message)

async def scheduler():
    while True:
        for slot in is_posting_active:
            if is_posting_active[slot]:
                schedule.run_pending()
        await asyncio.sleep(1)

async def periodic_save():
    while True:
        await asyncio.sleep(300)  # 5 минут
        save_data()
        logging.info("Периодическое сохранение данных выполнено.")

async def main():
    await asyncio.gather(
        dp.start_polling(bot),
        scheduler(),
        periodic_save()
    )

if __name__ == "__main__":
    load_data()
    asyncio.run(main())
