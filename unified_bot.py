#!/usr/bin/env python3
"""
Объединенный Telegram-бот с поддержкой Yandex GPT и GigaChat
Позволяет пользователю выбирать модель через кнопки
Обязательное логирование всех операций
"""

import os
import time
import logging
import asyncio
import json
from datetime import datetime
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
try:
    from yandex_cloud_ml_sdk import YCloudML
    YANDEX_AVAILABLE = True
except ImportError:
    YCloudML = None
    YANDEX_AVAILABLE = False
    print("⚠️ Yandex Cloud ML SDK не установлен. Yandex GPT будет недоступен.")

# Импортируем модуль для работы с GigaChat
from gigachat import GigaChat

# Импорты для SSL сертификатов
import ssl
import certifi
import urllib3

# Отключаем предупреждения SSL
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Импорт для веб-поиска
try:
    from duckduckgo_search import DDGS
    SEARCH_AVAILABLE = True
except ImportError:
    SEARCH_AVAILABLE = False
    print("⚠️ DuckDuckGo Search не установлен. Функция поиска будет недоступна.")

# Импорт мультипоиска
try:
    from multi_search import search_web_multi
    MULTI_SEARCH_AVAILABLE = True
    print("✅ Мультипоиск доступен")
except ImportError:
    MULTI_SEARCH_AVAILABLE = False
    print("⚠️ Мультипоиск недоступен")

# Импорт RSS новостей
try:
    from rss_news import get_news_context as rss_news_context
    RSS_NEWS_AVAILABLE = True
    print("✅ RSS новости доступны (РИА, ТАСС, Интерфакс)")
except ImportError:
    rss_news_context = None
    RSS_NEWS_AVAILABLE = False
    print("⚠️ RSS новости недоступны")

# Импорт для запросов к API
import requests

def search_web(query: str, max_results: int = 3) -> str:
    """
    Поиск актуальной информации в интернете через DuckDuckGo
    Использует как обычный поиск, так и новостной для максимальной актуальности
    
    Args:
        query: поисковый запрос
        max_results: максимальное количество результатов
    
    Returns:
        Строка с найденной информацией или пустая строка
    """
    if not SEARCH_AVAILABLE:
        return ""
    
    context = ""
    
    # Улучшаем запрос для более релевантных результатов
    improved_query = query
    query_lower = query.lower()
    
    # Если запрос про новости/события - добавляем ключевые слова
    if any(word in query_lower for word in ['новост', 'сейчас', 'что там', 'события', 'актуальн']):
        improved_query = f"{query} новости 2025"
    # Если про политиков/людей - уточняем запрос
    elif any(name in query_lower for name in ['макрон', 'трамп', 'путин', 'байден', 'президент', 'министр']):
        improved_query = f"{query} последние новости"
    
    try:
        # Пробуем новостной поиск для актуальных событий
        with DDGS() as ddgs:
            try:
                news_results = list(ddgs.news(improved_query, max_results=max_results))
                if news_results:
                    logger.info(f"DuckDuckGo News вернул {len(news_results)} новостей")
                    context += "\n📰 СВЕЖИЕ НОВОСТИ:\n"
                    for i, result in enumerate(news_results, 1):
                        title = result.get('title', 'Без названия')
                        body = result.get('body', result.get('excerpt', ''))
                        date = result.get('date', '')
                        source = result.get('source', '')
                        url = result.get('url', '')
                        
                        context += f"\n{i}. **{title}**"
                        if date:
                            context += f" ({date})"
                        if source:
                            context += f" - {source}"
                        context += "\n"
                        
                        if body:
                            # Берём до 400 символов из новости
                            body_text = body[:400] + "..." if len(body) > 400 else body
                            context += f"   {body_text}\n"
                        
                        if url:
                            context += f"   🔗 {url}\n"
                    
                    context += "\n"
                    logger.info(f"Новостной контекст сформирован: {len(context)} символов")
            except Exception as news_error:
                logger.warning(f"Новостной поиск не сработал: {news_error}")
        
        # Если новостей мало или нет, дополняем обычным поиском
        if len(context) < 200:
            with DDGS() as ddgs:
                text_results = list(ddgs.text(query, max_results=max_results))
                
                if text_results:
                    logger.info(f"DuckDuckGo Text вернул {len(text_results)} результатов")
                    if not context:
                        context = "\n🔍 НАЙДЕННАЯ ИНФОРМАЦИЯ:\n"
                    else:
                        context += "\n🔍 ДОПОЛНИТЕЛЬНО:\n"
                    
                    for i, result in enumerate(text_results, 1):
                        title = result.get('title', 'Без названия')
                        body = result.get('body', result.get('snippet', result.get('description', '')))
                        href = result.get('href', '')
                        
                        context += f"\n{i}. **{title}**\n"
                        if body:
                            # Берём до 400 символов
                            body_text = body[:400] + "..." if len(body) > 400 else body
                            context += f"   {body_text}\n"
                        if href:
                            context += f"   🔗 {href}\n"
                    
                    context += "\n"
        
        if context:
            logger.info(f"✅ Итоговый контекст: {len(context)} символов")
            # Добавляем инструкцию для AI
            context += "\n⚠️ ВАЖНО: Используй ЭТУ информацию для ответа! Она актуальная!\n"
            return context
        else:
            logger.warning("Поиск не вернул никаких результатов")
            return ""
            
    except Exception as e:
        logger.error(f"Критическая ошибка поиска в DuckDuckGo: {e}", exc_info=True)
        return ""


async def get_browser_news_context(query: str, max_results: int = 3) -> str:
    """Асинхронно получает новостной контекст через headless-браузер (запускает синхронный Playwright в отдельном потоке)."""
    if not BROWSER_SEARCH_AVAILABLE or not browser_news_context:
        return ""
    try:
        # Запускаем синхронный browser_news_context в отдельном потоке (правильный способ для Windows)
        context = await asyncio.to_thread(browser_news_context, query, max_results)
        if context:
            logger.info(f"Браузерный поиск новостей вернул контекст из {len(context)} символов")
        return context
    except Exception as e:
        logger.error(f"Ошибка браузерного поиска новостей: {e}", exc_info=True)
        return ""

def normalize_city_name(city: str) -> str:
    """
    Нормализует название города, убирая падежные окончания
    
    Args:
        city: Название города (может быть в любом падеже)
    
    Returns:
        Нормализованное название города в именительном падеже
    """
    # Словарь частых городов с вариантами написания
    city_variations = {
        'москве': 'Moscow',
        'москвы': 'Moscow',
        'москву': 'Moscow',
        'москва': 'Moscow',
        'петербурге': 'Saint Petersburg',
        'питере': 'Saint Petersburg',
        'питер': 'Saint Petersburg',
        'новосибирске': 'Novosibirsk',
        'новосибирска': 'Novosibirsk',
        'новосибирск': 'Novosibirsk',
        'екатеринбурге': 'Yekaterinburg',
        'екатеринбург': 'Yekaterinburg',
        'казани': 'Kazan',
        'казань': 'Kazan',
        'нижнем': 'Nizhny Novgorod',
        'красноярске': 'Krasnoyarsk',
        'красноярск': 'Krasnoyarsk',
        'лондоне': 'London',
        'лондон': 'London',
        'париже': 'Paris',
        'париж': 'Paris',
        'берлине': 'Berlin',
        'берлин': 'Berlin',
        'нью-йорке': 'New York',
        'вашингтоне': 'Washington',
        'вашингтон': 'Washington',
        'токио': 'Tokyo',
        'пекине': 'Beijing',
        'пекин': 'Beijing',
    }
    
    city_lower = city.lower().strip()
    
    # Проверяем словарь
    if city_lower in city_variations:
        return city_variations[city_lower]
    
    # Для неизвестных городов пробуем убрать типичные окончания
    # Предложный падеж: -е, -ске
    if city_lower.endswith('ске'):
        return city[:-2]  # новосибирск
    elif city_lower.endswith('не'):
        return city[:-1]  # лондон
    elif city_lower.endswith('е') and len(city) > 3:
        # Проверяем, не заканчивается ли на -ие (в таких случаях -е не убираем)
        if not city_lower.endswith('ие'):
            return city[:-1]
    
    # Родительный падеж: -ы, -а
    if city_lower.endswith('ы') and len(city) > 3:
        return city[:-1]
    
    # Возвращаем как есть, если не смогли нормализовать
    return city


def get_weather(city: str, api_key: str = None) -> str:
    """
    Получает актуальную погоду для указанного города через OpenWeatherMap API
    
    Args:
        city: Название города (на русском или английском)
        api_key: API ключ OpenWeatherMap (опционально, берется из .env)
    
    Returns:
        Строка с информацией о погоде или пустая строка при ошибке
    """
    # Нормализуем название города
    city = normalize_city_name(city)
    if not api_key:
        api_key = os.getenv("OPENWEATHER_API_KEY")
    
    if not api_key:
        logger.warning("OpenWeatherMap API ключ не найден")
        # Возвращаем ссылку на сайт погоды
        return f"""
🌡️ **ПОГОДА В {city.upper()}:**

К сожалению, для получения актуальной погоды требуется настройка API ключа.

Вы можете посмотреть погоду здесь:
🌤️ [Яндекс.Погода](https://yandex.ru/pogoda/{city.lower()})
🌐 [OpenWeatherMap](https://openweathermap.org/city/{city})
📱 [Gismeteo](https://www.gismeteo.ru/search/{city}/)
"""
    
    try:
        # Используем бесплатный API OpenWeatherMap
        base_url = "http://api.openweathermap.org/data/2.5/weather"
        params = {
            'q': city,
            'appid': api_key,
            'units': 'metric',  # Цельсий
            'lang': 'ru'  # Русский язык
        }
        
        response = requests.get(base_url, params=params, timeout=5)
        
        if response.status_code == 200:
            data = response.json()
            
            # Извлекаем данные
            temp = data['main']['temp']
            feels_like = data['main']['feels_like']
            humidity = data['main']['humidity']
            pressure = data['main']['pressure']
            description = data['weather'][0]['description']
            wind_speed = data['wind']['speed']
            
            weather_info = f"""
🌡️ **ПОГОДА В {city.upper()}:**

🌤️ Сейчас: {description}
🌡️ Температура: {temp}°C (ощущается как {feels_like}°C)
💧 Влажность: {humidity}%
🎐 Давление: {pressure} гПа
💨 Ветер: {wind_speed} м/с

📅 Данные актуальны на {datetime.now().strftime('%H:%M, %d.%m.%Y')}
"""
            logger.info(f"Получена погода для {city}: {temp}°C")
            return weather_info
        elif response.status_code == 404:
            logger.warning(f"Город не найден: {city}")
            return f"❌ Город '{city}' не найден. Проверьте написание."
        else:
            logger.error(f"Ошибка API погоды: {response.status_code}")
            return ""
            
    except requests.Timeout:
        logger.error("Timeout при запросе погоды")
        return "⏱️ Превышено время ожидания ответа от сервиса погоды"
    except Exception as e:
        logger.error(f"Ошибка получения погоды: {e}", exc_info=True)
        return ""

def get_maps_info(location: str) -> str:
    """
    Получает информацию о местоположении с картами
    Использует бесплатный API Nominatim (OpenStreetMap)
    
    Args:
        location: Название места для поиска
    
    Returns:
        Строка с информацией о местоположении
    """
    try:
        # Отключаем предупреждения SSL для этого запроса
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        # Используем бесплатный Nominatim API
        base_url = "https://nominatim.openstreetmap.org/search"
        params = {
            'q': location,
            'format': 'json',
            'limit': 1,
            'addressdetails': 1
        }
        headers = {
            'User-Agent': 'TelegramBot/1.0'  # Обязательно для Nominatim
        }
        
        response = requests.get(base_url, params=params, headers=headers, timeout=5, verify=False)
        
        if response.status_code == 200:
            data = response.json()
            
            if data:
                place = data[0]
                lat = place.get('lat')
                lon = place.get('lon')
                display_name = place.get('display_name')
                
                # Формируем ссылки на карты
                osm_link = f"https://www.openstreetmap.org/?mlat={lat}&mlon={lon}&zoom=15"
                google_maps_link = f"https://www.google.com/maps?q={lat},{lon}"
                yandex_maps_link = f"https://yandex.ru/maps/?ll={lon}%2C{lat}&z=15&l=map"
                
                maps_info = f"""
🗺️ **ИНФОРМАЦИЯ О МЕСТОПОЛОЖЕНИИ:**

📍 {display_name}

🌐 Координаты: {lat}, {lon}

🔗 **Открыть на карте:**
• [OpenStreetMap]({osm_link})
• [Google Maps]({google_maps_link})
• [Яндекс.Карты]({yandex_maps_link})

📅 Данные актуальны на {datetime.now().strftime('%H:%M, %d.%m.%Y')}
"""
                logger.info(f"Найдено местоположение: {display_name}")
                return maps_info
            else:
                logger.warning(f"Nominatim не нашёл местоположение: {location}. Веб-поиск будет использован вместо карт.")
                return ""  # Возвращаем пустую строку - веб-поиск сработает
        else:
            logger.error(f"Ошибка API карт: {response.status_code}")
            return ""
            
    except requests.Timeout:
        logger.error("Timeout при запросе карт")
        return "⏱️ Превышено время ожидания ответа от сервиса карт"
    except Exception as e:
        logger.error(f"Ошибка получения информации о картах: {e}", exc_info=True)
        return ""

def setup_russian_certificates():
    """Настраивает российские сертификаты для GigaChat"""
    cert_dir = "./certs"
    
    if not os.path.exists(cert_dir):
        logger.warning("Папка certs не найдена")
        return False
    
    # Ищем .cer файлы
    cer_files = []
    for file in os.listdir(cert_dir):
        if file.endswith('.cer'):
            cer_files.append(os.path.join(cert_dir, file))
    
    if not cer_files:
        logger.warning("Сертификаты .cer не найдены в папке certs")
        return False
    
    # Используем основной сертификат только для логирования/диагностики.
    # ВАЖНО: Не выставляем глобальные переменные окружения SSL, чтобы
    # не нарушить TLS-подключения к Telegram (они начинают использовать
    # только этот корневой сертификат и падают по self-signed chain).
    # Для GigaChat внизу используется verify_ssl_certs=False, поэтому
    # дополнительные глобальные настройки не требуются.
    main_cert = cer_files[0]
    logger.info(f"Сертификаты обнаружены: {main_cert}")
    return True

# Загружаем переменные окружения
load_dotenv()

# Настройка расширенного логирования
def setup_logging():
    """Настройка системы логирования"""
    # Создаем папку для логов если её нет
    if not os.path.exists('logs'):
        os.makedirs('logs')
    
    # Формат логов с временными метками
    log_format = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    date_format = '%Y-%m-%d %H:%M:%S'
    
    # Настройка корневого логгера
    logging.basicConfig(
        level=logging.INFO,
        format=log_format,
        datefmt=date_format,
        handlers=[
            # Лог в файл с ротацией по дням
            logging.FileHandler('logs/unified_bot.log', encoding='utf-8'),
            # Лог в консоль
            logging.StreamHandler()
        ]
    )
    
    # Создаем отдельный логгер для ошибок
    error_logger = logging.getLogger('ErrorLogger')
    error_logger.setLevel(logging.ERROR)
    error_handler = logging.FileHandler('logs/errors.log', encoding='utf-8')
    error_handler.setFormatter(logging.Formatter(log_format, date_format))
    error_logger.addHandler(error_handler)
    
    # Создаем логгер для бота
    logger = logging.getLogger('UnifiedBot')
    logger.setLevel(logging.INFO)
    
    # Логгер для пользовательских действий
    user_logger = logging.getLogger('UserActions')
    user_logger.setLevel(logging.INFO)
    
    # Логгер для API запросов
    api_logger = logging.getLogger('APIRequests')
    api_logger.setLevel(logging.INFO)
    
    return logger, user_logger, api_logger

# Инициализируем логирование
logger, user_logger, api_logger = setup_logging()

# Конфигурация из переменных окружения
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN")
YANDEX_FOLDER_ID = os.getenv("YANDEX_FOLDER_ID")
YANDEX_AUTH_TOKEN = os.getenv("YANDEX_AUTH_TOKEN")
YANDEX_API_KEY = os.getenv("YANDEX_API_KEY")  # Бессрочный API ключ (приоритет)
# Поддержка двух вариантов переменных GigaChat
GIGACHAT_CREDENTIALS = os.getenv("GIGA_KEY") or os.getenv("GIGACHAT_CREDENTIALS")
GIGACHAT_SCOPE = os.getenv("GIGA_SCOPE", "GIGACHAT_API_PERS")

# Логируем загрузку конфигурации
logger.info("=" * 50)
logger.info("ЗАПУСК ОБЪЕДИНЕННОГО БОТА")
logger.info("=" * 50)

# Проверяем наличие токена Telegram
if not TELEGRAM_TOKEN:
    logger.error("TELEGRAM_TOKEN или TELEGRAM_BOT_TOKEN не найден в .env файле")
    raise ValueError("TELEGRAM_TOKEN или TELEGRAM_BOT_TOKEN не найден в .env файле")

logger.info(f"Telegram токен загружен: {TELEGRAM_TOKEN[:10]}...")

# Проверяем наличие конфигурации для Yandex
if not YANDEX_FOLDER_ID or (not YANDEX_API_KEY and not YANDEX_AUTH_TOKEN):
    logger.warning("Yandex GPT не настроен - отсутствуют YANDEX_FOLDER_ID и (YANDEX_API_KEY или YANDEX_AUTH_TOKEN)")
else:
    if YANDEX_API_KEY:
        logger.info(f"Yandex конфигурация загружена: folder_id={YANDEX_FOLDER_ID[:10]}..., используется бессрочный API ключ")
    else:
        logger.info(f"Yandex конфигурация загружена: folder_id={YANDEX_FOLDER_ID[:10]}..., используется временный IAM токен")

# Проверяем наличие конфигурации для GigaChat
if not GIGACHAT_CREDENTIALS:
    logger.warning("GigaChat не настроен - отсутствует GIGACHAT_CREDENTIALS")
else:
    logger.info("GigaChat конфигурация загружена")

logger.info("Конфигурация загружена успешно")

class UnifiedBot:
    """Объединенный бот с поддержкой Yandex GPT и GigaChat"""
    
    def __init__(self):
        """Инициализация бота"""
        logger.info("Инициализация UnifiedBot...")
        
        self.application = Application.builder().token(TELEGRAM_TOKEN).build()
        
        # Инициализация Yandex GPT
        self.yandex_sdk = None
        self.yandex_model = None
        if YANDEX_AVAILABLE and YANDEX_FOLDER_ID and (YANDEX_API_KEY or YANDEX_AUTH_TOKEN):
            try:
                logger.info("Инициализация Yandex GPT SDK...")
                # Приоритет методов аутентификации:
                # 1. API Key (бессрочный, строка)
                # 2. IAM токен (временный, строка)
                if YANDEX_API_KEY:
                    logger.info(f"Использую бессрочный API ключ: {YANDEX_API_KEY[:10]}...")
                    self.yandex_sdk = YCloudML(
                        folder_id=YANDEX_FOLDER_ID,
                        auth=YANDEX_API_KEY,  # Передаем API ключ как строку
                    )
                elif YANDEX_AUTH_TOKEN:
                    logger.info(f"Использую временный IAM токен: {YANDEX_AUTH_TOKEN[:10]}...")
                    self.yandex_sdk = YCloudML(
                        folder_id=YANDEX_FOLDER_ID,
                        auth=YANDEX_AUTH_TOKEN,  # Передаем IAM токен как строку
                    )
                else:
                    raise ValueError("Нет доступных методов аутентификации для Yandex GPT")
                self.yandex_model = self.yandex_sdk.models.completions("yandexgpt")
                logger.info("✅ Yandex GPT инициализирован успешно")
            except Exception as e:
                logger.error(f"❌ Ошибка инициализации Yandex GPT: {e}", exc_info=True)
        elif not YANDEX_AVAILABLE:
            logger.warning("❌ Yandex GPT недоступен - SDK не установлен")
        
        # Инициализация GigaChat
        self.giga_client = None
        if GIGACHAT_CREDENTIALS:
            try:
                logger.info("Инициализация GigaChat клиента...")
                # Настраиваем российские сертификаты
                setup_russian_certificates()
                # Инициализируем GigaChat напрямую
                self.giga_client = GigaChat(
                    credentials=GIGACHAT_CREDENTIALS,
                    scope=GIGACHAT_SCOPE,
                    verify_ssl_certs=False
                )
                logger.info("✅ GigaChat клиент создан успешно")
            except Exception as e:
                logger.error(f"❌ Ошибка инициализации GigaChat: {e}", exc_info=True)
        
        # Статистика
        self.stats = {
            'messages_processed': 0,
            'yandex_requests': 0,
            'giga_requests': 0,
            'errors': 0,
            'start_time': datetime.now()
        }
        
        logger.info("Статистика инициализирована")
        
        # Настройка обработчиков
        self.setup_handlers()
        logger.info("Обработчики настроены")
    
    def setup_handlers(self):
        """Настройка обработчиков команд"""
        self.application.add_handler(CommandHandler("start", self.start_command))
        self.application.add_handler(CommandHandler("help", self.help_command))
        self.application.add_handler(CommandHandler("status", self.status_command))
        self.application.add_handler(CommandHandler("select_model", self.select_model_command))
        self.application.add_handler(CallbackQueryHandler(self.button_callback))
        self.application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message))
        self.application.add_error_handler(self.error_handler)
    
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Обработчик команды /start"""
        user_id = update.effective_user.id
        user_name = update.effective_user.first_name or "пользователь"
        username = update.effective_user.username or "Unknown"
        
        user_logger.info(f"Команда /start от пользователя {username} (ID: {user_id})")
        
        welcome_message = f"""
🤖 **Привет, {user_name}!**

Я умный помощник с поддержкой двух AI моделей:

🔵 **Yandex GPT** - российская модель от Яндекса
🟢 **GigaChat** - модель от Сбера

💡 **Как использовать:**
1. Выберите модель командой /select_model
2. Или просто напишите сообщение - я использую модель по умолчанию

📋 **Доступные команды:**
/select_model - выбрать модель
/status - статистика бота
/help - справка

Начнем общение! 🚀
        """
        
        # Создаем кнопки для выбора модели
        keyboard = [
            [
                InlineKeyboardButton("🔵 Yandex GPT", callback_data="model_yandex"),
                InlineKeyboardButton("🟢 GigaChat", callback_data="model_giga")
            ],
            [
                InlineKeyboardButton("🔄 Выбрать модель", callback_data="back_to_menu")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(welcome_message, parse_mode='Markdown', reply_markup=reply_markup)
        logger.info(f"Приветственное сообщение отправлено пользователю {username}")
    
    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Обработчик команды /help"""
        user_id = update.effective_user.id
        username = update.effective_user.username or "Unknown"
        
        user_logger.info(f"Команда /help от пользователя {username} (ID: {user_id})")
        
        help_text = """
📚 **Справка по использованию бота**

🤖 **Доступные модели:**

🔵 **Yandex GPT**
• Российская модель от Яндекса
• Хорошо работает с русским языком
• Быстрые ответы

🟢 **GigaChat**
• Модель от Сбера
• Поддерживает сложные задачи
• Детальные ответы

💬 **Как общаться:**
1. Выберите модель командой /select_model
2. Напишите любое сообщение
3. Получите ответ от выбранной модели

⚙️ **Команды:**
/start - приветствие и выбор модели
/select_model - выбрать модель
/status - статистика бота
/help - эта справка

❓ **Примеры вопросов:**
• "Расскажи о Python"
• "Напиши стихотворение"
• "Помоги решить задачу"
• "Объясни квантовую физику"

Готов помочь! 🚀
        """
        
        await update.message.reply_text(help_text, parse_mode='Markdown')
        logger.info(f"Справка отправлена пользователю {username}")
    
    async def status_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Обработчик команды /status"""
        user_id = update.effective_user.id
        username = update.effective_user.username or "Unknown"
        
        user_logger.info(f"Команда /status от пользователя {username} (ID: {user_id})")
        
        uptime = datetime.now() - self.stats['start_time']
        uptime_str = str(uptime).split('.')[0]  # Убираем микросекунды
        
        status_text = f"""
📊 **Статистика бота**

⏱️ **Время работы:** {uptime_str}
💬 **Обработано сообщений:** {self.stats['messages_processed']}
🔵 **Запросов к Yandex GPT:** {self.stats['yandex_requests']}
🟢 **Запросов к GigaChat:** {self.stats['giga_requests']}
❌ **Ошибок:** {self.stats['errors']}

🔧 **Статус моделей:**
"""
        
        # Статус Yandex GPT
        if self.yandex_model:
            status_text += "🔵 Yandex GPT: ✅ Активна\n"
        else:
            status_text += "🔵 Yandex GPT: ❌ Недоступна\n"
        
        # Статус GigaChat
        if self.giga_client:
            status_text += f"🟢 GigaChat: ✅ Активна\n"
        else:
            status_text += "🟢 GigaChat: ❌ Недоступна\n"
        
        await update.message.reply_text(status_text, parse_mode='Markdown')
        logger.info(f"Статистика отправлена пользователю {username}")
    
    async def select_model_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Обработчик команды /select_model"""
        user_id = update.effective_user.id
        username = update.effective_user.username or "Unknown"
        
        user_logger.info(f"Команда /select_model от пользователя {username} (ID: {user_id})")
        
        await self.show_model_selection(update, context)
    
    async def show_model_selection(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Показать меню выбора модели"""
        keyboard = []
        
        # Кнопка для Yandex GPT
        if self.yandex_model:
            keyboard.append([InlineKeyboardButton("🔵 Yandex GPT", callback_data="model_yandex")])
        else:
            keyboard.append([InlineKeyboardButton("🔵 Yandex GPT (недоступна)", callback_data="model_unavailable")])
        
        # Кнопка для GigaChat
        if self.giga_client:
            keyboard.append([InlineKeyboardButton("🟢 GigaChat", callback_data="model_giga")])
        else:
            keyboard.append([InlineKeyboardButton("🟢 GigaChat (недоступна)", callback_data="model_unavailable")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        text = "🤖 **Выберите модель для общения:**\n\n"
        if not self.yandex_model and not (self.giga_client):
            text += "❌ **Внимание:** Ни одна модель не доступна. Проверьте конфигурацию."
        
        await update.message.reply_text(text, parse_mode='Markdown', reply_markup=reply_markup)
        logger.info("Меню выбора модели отправлено")
    
    async def show_model_selection_from_callback(self, query, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Показать меню выбора модели из callback query"""
        keyboard = []
        
        # Кнопка для Yandex GPT
        if self.yandex_model:
            keyboard.append([InlineKeyboardButton("🔵 Yandex GPT", callback_data="model_yandex")])
        else:
            keyboard.append([InlineKeyboardButton("🔵 Yandex GPT (недоступна)", callback_data="model_unavailable")])
        
        # Кнопка для GigaChat
        if self.giga_client:
            keyboard.append([InlineKeyboardButton("🟢 GigaChat", callback_data="model_giga")])
        else:
            keyboard.append([InlineKeyboardButton("🟢 GigaChat (недоступна)", callback_data="model_unavailable")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        text = "🤖 **Выберите модель для общения:**\n\n"
        if not self.yandex_model and not (self.giga_client):
            text += "❌ **Внимание:** Ни одна модель не доступна. Проверьте конфигурацию."
        
        await query.edit_message_text(text, parse_mode='Markdown', reply_markup=reply_markup)
        logger.info("Меню выбора модели обновлено из callback")
    
    async def button_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Обработчик нажатий на кнопки"""
        query = update.callback_query
        user_id = query.from_user.id
        username = query.from_user.username or "Unknown"
        
        await query.answer()
        
        user_logger.info(f"Нажатие кнопки '{query.data}' от пользователя {username} (ID: {user_id})")
        
        if query.data == "model_yandex":
            if self.yandex_model:
                context.user_data['selected_model'] = 'yandex'
                keyboard = [[InlineKeyboardButton("🔄 Вернуться к выбору модели", callback_data="back_to_menu")]]
                reply_markup = InlineKeyboardMarkup(keyboard)
                await query.edit_message_text("🔵 **Выбрана модель: Yandex GPT**\n\nТеперь напишите сообщение, и я отвечу используя Yandex GPT!", parse_mode='Markdown', reply_markup=reply_markup)
                logger.info(f"Пользователь {username} выбрал Yandex GPT")
            else:
                keyboard = [[InlineKeyboardButton("🔄 Вернуться к выбору модели", callback_data="back_to_menu")]]
                reply_markup = InlineKeyboardMarkup(keyboard)
                await query.edit_message_text("❌ **Yandex GPT недоступна**\n\nПроверьте конфигурацию в .env файле.", parse_mode='Markdown', reply_markup=reply_markup)
                logger.warning(f"Пользователь {username} попытался выбрать недоступную Yandex GPT")
        
        elif query.data == "model_giga":
            if self.giga_client:
                context.user_data['selected_model'] = 'giga'
                keyboard = [[InlineKeyboardButton("🔄 Вернуться к выбору модели", callback_data="back_to_menu")]]
                reply_markup = InlineKeyboardMarkup(keyboard)
                await query.edit_message_text("🟢 **Выбрана модель: GigaChat**\n\nТеперь напишите сообщение, и я отвечу используя GigaChat!", parse_mode='Markdown', reply_markup=reply_markup)
                logger.info(f"Pользователь {username} выбрал GigaChat")
            else:
                keyboard = [[InlineKeyboardButton("🔄 Вернуться к выбору модели", callback_data="back_to_menu")]]
                reply_markup = InlineKeyboardMarkup(keyboard)
                await query.edit_message_text("❌ **GigaChat недоступна**\n\nПроверьте конфигурацию в .env файле.", parse_mode='Markdown', reply_markup=reply_markup)
                logger.warning(f"Пользователь {username} попытался выбрать недоступную GigaChat")
        
        elif query.data == "model_unavailable":
            keyboard = [[InlineKeyboardButton("🔄 Вернуться к выбору модели", callback_data="back_to_menu")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text("❌ **Модель недоступна**\n\nПроверьте конфигурацию в .env файле.", parse_mode='Markdown', reply_markup=reply_markup)
            logger.warning(f"Пользователь {username} попытался выбрать недоступную модель")
        
        elif query.data == "back_to_menu":
            await self.show_model_selection_from_callback(query, context)
            logger.info(f"Пользователь {username} вернулся к выбору модели")
    
    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Обработчик текстовых сообщений"""
        user_message = update.message.text
        user_id = update.effective_user.id
        username = update.effective_user.username or "Unknown"
        
        # Логируем входящее сообщение
        user_logger.info(f"Сообщение от {username} (ID: {user_id}): {user_message[:100]}{'...' if len(user_message) > 100 else ''}")
        
        # Увеличиваем счетчик сообщений
        self.stats['messages_processed'] += 1
        
        # Определяем выбранную модель
        selected_model = context.user_data.get('selected_model')
        
        # Если модель не выбрана, используем доступную по умолчанию
        if not selected_model:
            if self.yandex_model:
                selected_model = 'yandex'
                logger.info(f"Автоматически выбрана Yandex GPT для пользователя {username}")
            elif self.giga_client:
                selected_model = 'giga'
                logger.info(f"Автоматически выбрана GigaChat для пользователя {username}")
            else:
                await update.message.reply_text("❌ **Ошибка:** Ни одна модель не доступна. Проверьте конфигурацию.")
                logger.error(f"Ни одна модель не доступна для пользователя {username}")
                return
        
        # Отправляем сообщение о том, что бот обрабатывает запрос
        processing_message = await update.message.reply_text("🤔 Обрабатываю ваш запрос...")
        
        try:
            if selected_model == 'yandex':
                await self.handle_yandex_request(update, processing_message, user_message, username)
            elif selected_model == 'giga':
                await self.handle_giga_request(update, processing_message, user_message, username)
            else:
                await processing_message.edit_text("❌ Неизвестная модель")
                logger.error(f"Неизвестная модель '{selected_model}' для пользователя {username}")
                
        except Exception as e:
            error_message = f"❌ Произошла ошибка при обработке запроса: {str(e)}"
            keyboard = [[InlineKeyboardButton("🔄 Вернуться к выбору модели", callback_data="back_to_menu")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await processing_message.edit_text(error_message, reply_markup=reply_markup)
            logger.error(f"Ошибка для пользователя {username}: {e}", exc_info=True)
            self.stats['errors'] += 1
    
    async def handle_yandex_request(self, update: Update, processing_message, user_message: str, username: str) -> None:
        """Обработка запроса к Yandex GPT"""
        if not self.yandex_model:
            await processing_message.edit_text("❌ Yandex GPT недоступна")
            logger.error(f"Попытка использовать недоступную Yandex GPT для пользователя {username}")
            return
        
        try:
            api_logger.info(f"Отправка запроса в Yandex GPT для пользователя {username}")
            
            # Формируем сообщения для Yandex GPT с актуальной датой
            from datetime import datetime
            current_date = datetime.now().strftime("%Y-%m-%d")
            current_year = datetime.now().year
            
            # Проверяем тип запроса
            weather_keywords = ['погод', 'температур', 'градус', 'тепло', 'холодно', 'дожд', 'снег']
            map_keywords = ['карт', 'адрес', 'координат', 'местоположен', 'как добраться', 'где находится', 'где ', 'остановк', 'магазин', 'универмаг']
            # Расширенный список для веб-поиска - включаем больше случаев
            search_keywords = [
                'сейчас', 'новост', 'актуальн', 'текущ', 'последн',
                'что там', 'как там', 'что с', 'что происходит', 
                'где', 'когда', 'кто', 'какой', 'какая', 'какие',
                '2024', '2025', 'год', 'месяц',
                'президент', 'правительств', 'министр', 'выбор', 'победил',
                'эмануэль', 'макрон', 'трамп', 'путин', 'байден',
                'франц', 'росси', 'америк', 'сша', 'украин',
                'событи', 'ситуаци', 'положени', 'состояни',
                'подал', 'ушел', 'уволи', 'назначи', 'избра'
            ]
            
            needs_weather = any(keyword in user_message.lower() for keyword in weather_keywords)
            needs_map = any(keyword in user_message.lower() for keyword in map_keywords)
            needs_search = any(keyword in user_message.lower() for keyword in search_keywords)
            
            web_context = ""
            
            # Проверяем погоду
            if needs_weather:
                api_logger.info(f"🌤️ Запрос погоды для Yandex GPT: {user_message}")
                # Пытаемся извлечь название города
                import re
                city_match = re.search(r'в\s+([А-Яа-яA-Za-z\-]+)', user_message)
                if not city_match:
                    city_match = re.search(r'погод[аые]\s+([А-Яа-яA-Za-z\-]+)', user_message)
                
                if city_match:
                    city = city_match.group(1)
                    weather_info = get_weather(city)
                    if weather_info:
                        web_context = weather_info
                        api_logger.info(f"✅ Получена погода для {city}")
            
            # Проверяем карты
            if needs_map and not web_context:
                api_logger.info(f"🗺️ Запрос карт для Yandex GPT: {user_message}")
                import re
                location_match = re.search(r'(?:карт[аыу]|адрес|координат[ыа]|где находится|как добраться|где)\s+(.+)', user_message, re.IGNORECASE)
                if location_match:
                    location = location_match.group(1).strip('?!.')
                    maps_info = get_maps_info(location)
                    if maps_info:
                        web_context = maps_info
                        api_logger.info(f"✅ Найдено местоположение на карте: {location}")
                    else:
                        api_logger.info(f"⚠️ Nominatim не нашёл местоположение, будет использован веб-поиск")
            
            # Для новостных запросов приоритет — RSS ленты (быстро и надёжно)
            if needs_search and not web_context:
                if RSS_NEWS_AVAILABLE:
                    api_logger.info(f"📰 ПРИОРИТЕТ: Получаем свежие новости из RSS для Yandex GPT")
                    rss_context = await asyncio.to_thread(rss_news_context, user_message, 5)
                    if rss_context:
                        web_context = rss_context
                        api_logger.info("✅ Получены СВЕЖИЕ новости из RSS-лент (РИА, ТАСС)")
                    else:
                        api_logger.warning("⚠️ RSS ленты не вернули новостей")
                else:
                    api_logger.warning("⚠️ RSS модуль недоступен")
            
            system_prompt = f"Ты — профессиональный умный помощник. Сейчас {current_date} ({current_year} год). Отвечай кратко и понятно."
            
            if web_context:
                system_prompt += f"\n\n📰 АКТУАЛЬНАЯ ИНФОРМАЦИЯ ИЗ ИНТЕРНЕТА (24 ноября 2025 года):\n{web_context}\n\n🎯 КРИТИЧЕСКИ ВАЖНО:\n"
                system_prompt += "1. Выше — САМЫЕ СВЕЖИЕ новости на 24 ноября 2025 года из реального интернета\n"
                system_prompt += "2. Твои знания устарели (2023 год). Используй ТОЛЬКО информацию выше\n"
                system_prompt += "3. ОБЯЗАТЕЛЬНО отвечай на основе этих новостей, игнорируй свои старые данные\n"
                system_prompt += "4. Укажи источники и даты из данных выше\n"
                system_prompt += "5. Если в новостях нет ответа на вопрос — честно скажи об этом\n"
                system_prompt += "6. Отвечай кратко, максимум 500 символов\n"
            else:
                system_prompt += "\n\n⚠️ ВАЖНО: Твои знания ограничены 2023 годом. Для актуальных новостей 2024-2025 года рекомендуй проверить достоверные источники (РИА, ТАСС, Коммерсантъ)."
            
            messages = [
                {
                    "role": "system",
                    "text": system_prompt,
                },
                {
                    "role": "user",
                    "text": user_message,
                },
            ]
            
            # Отправляем запрос в Yandex GPT
            operation = self.yandex_model.configure(temperature=0.5).run_deferred(messages)
            
            # Проверяем статус операции
            status = operation.get_status()
            api_logger.info(f"Начальный статус операции Yandex GPT: {status}")
            
            # Ожидаем завершения операции
            while status.is_running:
                api_logger.info("Операция Yandex GPT выполняется, ждем 5 секунд...")
                await asyncio.sleep(5)
                status = operation.get_status()
                api_logger.info(f"Статус операции Yandex GPT: {status}")
            
            # Получаем результат
            api_logger.info("Операция Yandex GPT завершена, получаем результат")
            result = operation.get_result()
            
            # Извлекаем текст ответа
            if result.alternatives and len(result.alternatives) > 0:
                response_text = result.alternatives[0].text
                api_logger.info(f"Получен ответ от Yandex GPT для пользователя {username}: {response_text[:100]}{'...' if len(response_text) > 100 else ''}")
                
                # Проверяем, не отказался ли AI отвечать (цензура)
                refusal_phrases = [
                    "не могу обсуждать",
                    "не могу помочь с этим",
                    "не могу ответить",
                    "не буду обсуждать",
                    "давайте поговорим о чём-нибудь"
                ]
                
                is_refusal = any(phrase in response_text.lower() for phrase in refusal_phrases)
                
                # Если AI отказался и у нас есть контекст с новостями - показываем их напрямую
                if is_refusal and web_context:
                    api_logger.warning(f"Yandex GPT отказался отвечать, показываем сырые данные")
                    response_text = f"🔵 **Актуальная информация:**\n\n{web_context}\n\n_AI отказался обрабатывать этот запрос, поэтому показаны найденные данные напрямую._"
                else:
                    # Добавляем префикс модели
                    response_text = f"🔵 **Yandex GPT:**\n\n{response_text}"
                
                # Создаем кнопку возврата в меню
                keyboard = [[InlineKeyboardButton("🔄 Вернуться к выбору модели", callback_data="back_to_menu")]]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                # Отправляем ответ пользователю с кнопкой
                await processing_message.edit_text(response_text, parse_mode='Markdown', reply_markup=reply_markup)
                self.stats['yandex_requests'] += 1
                logger.info(f"Ответ Yandex GPT отправлен пользователю {username}")
            else:
                error_message = "❌ Извините, не удалось получить ответ от Yandex GPT. Попробуйте еще раз."
                keyboard = [[InlineKeyboardButton("🔄 Вернуться к выбору модели", callback_data="back_to_menu")]]
                reply_markup = InlineKeyboardMarkup(keyboard)
                await processing_message.edit_text(error_message, reply_markup=reply_markup)
                logger.error(f"Пустой ответ от Yandex GPT для пользователя {username}")
                
        except Exception as e:
            error_message = f"❌ Ошибка при работе с Yandex GPT: {str(e)}"
            keyboard = [[InlineKeyboardButton("🔄 Вернуться к выбору модели", callback_data="back_to_menu")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await processing_message.edit_text(error_message, reply_markup=reply_markup)
            logger.error(f"Ошибка Yandex GPT для пользователя {username}: {e}", exc_info=True)
            self.stats['errors'] += 1
    
    async def handle_giga_request(self, update: Update, processing_message, user_message: str, username: str) -> None:
        """Обработка запроса к GigaChat"""
        if not self.giga_client:
            await processing_message.edit_text("❌ GigaChat недоступен")
            logger.error(f"Попытка использовать недоступную GigaChat для пользователя {username}")
            return
        
        try:
            api_logger.info(f"Отправка запроса в GigaChat для пользователя {username}")
            
            # Формируем промпт для GigaChat с актуальной датой
            from datetime import datetime
            current_date = datetime.now().strftime("%Y-%m-%d")
            current_year = datetime.now().year
            
            # Проверяем тип запроса
            weather_keywords = ['погод', 'температур', 'градус', 'тепло', 'холодно', 'дожд', 'снег']
            map_keywords = ['карт', 'адрес', 'координат', 'местоположен', 'как добраться', 'где находится', 'где ', 'остановк', 'магазин', 'универмаг']
            # Расширенный список для веб-поиска - включаем больше случаев
            search_keywords = [
                'сейчас', 'новост', 'актуальн', 'текущ', 'последн',
                'что там', 'как там', 'что с', 'что происходит', 
                'где', 'когда', 'кто', 'какой', 'какая', 'какие',
                '2024', '2025', 'год', 'месяц',
                'президент', 'правительств', 'министр', 'выбор', 'победил',
                'эмануэль', 'макрон', 'трамп', 'путин', 'байден',
                'франц', 'росси', 'америк', 'сша', 'украин',
                'событи', 'ситуаци', 'положени', 'состояни',
                'подал', 'ушел', 'уволи', 'назначи', 'избра'
            ]
            
            needs_weather = any(keyword in user_message.lower() for keyword in weather_keywords)
            needs_map = any(keyword in user_message.lower() for keyword in map_keywords)
            needs_search = any(keyword in user_message.lower() for keyword in search_keywords)
            
            web_context = ""
            
            # Проверяем погоду
            if needs_weather:
                api_logger.info(f"🌤️ Запрос погоды для GigaChat: {user_message}")
                # Пытаемся извлечь название города
                import re
                # Ищем "в [город]" или "погода [город]"
                city_match = re.search(r'в\s+([А-Яа-яA-Za-z\-]+)', user_message)
                if not city_match:
                    city_match = re.search(r'погод[аые]\s+([А-Яа-яA-Za-z\-]+)', user_message)
                
                if city_match:
                    city = city_match.group(1)
                    weather_info = get_weather(city)
                    if weather_info:
                        web_context = weather_info
                        api_logger.info(f"✅ Получена погода для {city}")
            
            # Проверяем карты
            if needs_map and not web_context:
                api_logger.info(f"🗺️ Запрос карт для GigaChat: {user_message}")
                # Пытаемся извлечь местоположение
                import re
                location_match = re.search(r'(?:карт[аыу]|адрес|координат[ыа]|где находится|как добраться|где)\s+(.+)', user_message, re.IGNORECASE)
                if location_match:
                    location = location_match.group(1).strip('?!.')
                    maps_info = get_maps_info(location)
                    if maps_info:
                        web_context = maps_info
                        api_logger.info(f"✅ Найдено местоположение на карте: {location}")
                    else:
                        api_logger.info(f"⚠️ Nominatim не нашёл местоположение, будет использован веб-поиск")
            
            # Для новостных запросов приоритет — RSS ленты (быстро и надёжно)
            if needs_search and not web_context:
                if RSS_NEWS_AVAILABLE:
                    api_logger.info(f"📰 ПРИОРИТЕТ: Получаем свежие новости из RSS для GigaChat")
                    rss_context = await asyncio.to_thread(rss_news_context, user_message, 5)
                    if rss_context:
                        web_context = rss_context
                        api_logger.info("✅ Получены СВЕЖИЕ новости из RSS-лент (РИА, ТАСС)")
                    else:
                        api_logger.warning("⚠️ RSS ленты не вернули новостей")
                else:
                    api_logger.warning("⚠️ RSS модуль недоступен")
            
            if web_context:
                prompt = f"""Текущая дата: {current_date} ({current_year} год)

📰 АКТУАЛЬНАЯ ИНФОРМАЦИЯ ИЗ ИНТЕРНЕТА (24 ноября 2025 года):
{web_context}

🎯 КРИТИЧЕСКИ ВАЖНО:
1. Пользователь {username} спросил: "{user_message}"
2. Выше — САМЫЕ СВЕЖИЕ новости на 24 ноября 2025 года из реального интернета
3. Твои знания устарели (2023 год). Используй ТОЛЬКО информацию выше
4. ОБЯЗАТЕЛЬНО отвечай на основе этих новостей, игнорируй свои старые данные
5. Укажи источники и даты из данных выше
6. Если в новостях нет ответа — честно скажи об этом
7. Добавь эмодзи для лучшего восприятия

Максимум 600 символов. Отвечай кратко и по делу!
"""
            else:
                prompt = f"""Текущая дата: {current_date} ({current_year} год)

Ты умный помощник в Telegram-боте. Пользователь {username} написал: "{user_message}"

⚠️ ВАЖНЫЕ ПРАВИЛА:
✅ Сейчас {current_year} год - учитывай это при ответах
✅ Твои знания ограничены 2023 годом
✅ Для актуальных новостей 2024-2025 рекомендуй проверить РИА, ТАСС, Коммерсантъ
✅ Используй эмодзи для лучшего восприятия

Ответь дружелюбно. Максимум 500 символов.
"""
            
            # Отправляем запрос к GigaChat
            response = self.giga_client.chat(prompt)
            
            # Извлекаем ответ
            if response and response.choices:
                ai_response = response.choices[0].message.content
                api_logger.info(f"Получен ответ от GigaChat для пользователя {username}: {ai_response[:100]}{'...' if len(ai_response) > 100 else ''}")
                
                # Проверяем, не отказался ли AI отвечать (цензура)
                refusal_phrases = [
                    "не могу обсуждать",
                    "не могу помочь с этим",
                    "не могу ответить",
                    "не буду обсуждать",
                    "давайте поговорим о чём-нибудь"
                ]
                
                is_refusal = any(phrase in ai_response.lower() for phrase in refusal_phrases)
                
                # Если AI отказался и у нас есть контекст с новостями - показываем их напрямую
                if is_refusal and web_context:
                    api_logger.warning(f"GigaChat отказался отвечать, показываем сырые данные")
                    ai_response = f"🟢 **Актуальная информация:**\n\n{web_context}\n\n_AI отказался обрабатывать этот запрос, поэтому показаны найденные данные напрямую._"
                else:
                    # Обрезаем ответ если он слишком длинный
                    if len(ai_response) > 4000:
                        ai_response = ai_response[:4000] + "..."
                    
                    # Добавляем префикс модели
                    ai_response = f"🟢 **GigaChat:**\n\n{ai_response}"
                
                # Создаем кнопку возврата в меню
                keyboard = [[InlineKeyboardButton("🔄 Вернуться к выбору модели", callback_data="back_to_menu")]]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await processing_message.edit_text(ai_response, parse_mode='Markdown', reply_markup=reply_markup)
                self.stats['giga_requests'] += 1
                logger.info(f"Ответ GigaChat отправлен пользователю {username}")
                
            else:
                keyboard = [[InlineKeyboardButton("🔄 Вернуться к выбору модели", callback_data="back_to_menu")]]
                reply_markup = InlineKeyboardMarkup(keyboard)
                await processing_message.edit_text("❌ Не удалось получить ответ от GigaChat. Попробуйте еще раз.", reply_markup=reply_markup)
                logger.error(f"Пустой ответ от GigaChat для пользователя {username}")
                self.stats['errors'] += 1
                
        except Exception as e:
            error_message = f"❌ Ошибка при работе с GigaChat: {str(e)}"
            keyboard = [[InlineKeyboardButton("🔄 Вернуться к выбору модели", callback_data="back_to_menu")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await processing_message.edit_text(error_message, reply_markup=reply_markup)
            logger.error(f"Ошибка GigaChat для пользователя {username}: {e}", exc_info=True)
            self.stats['errors'] += 1
    
    async def error_handler(self, update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Обработчик ошибок"""
        logger.error(f"Произошла ошибка: {context.error}", exc_info=context.error)
        self.stats['errors'] += 1
    
    def run(self):
        """Запуск бота"""
        logger.info("=" * 50)
        logger.info("ЗАПУСК ОБЪЕДИНЕННОГО TELEGRAM БОТА")
        logger.info("=" * 50)
        
        # Проверяем доступность моделей
        if self.yandex_model:
            logger.info("✅ Yandex GPT доступен")
        else:
            logger.warning("❌ Yandex GPT недоступен")
        
        # Для GigaChat проверяем наличие клиента и пытаемся сделать тестовый запрос
        gigachat_available = False
        if self.giga_client:
            try:
                # Пытаемся сделать простой тестовый запрос
                test_response = self.giga_client.chat("тест")
                gigachat_available = True
                logger.info("✅ GigaChat доступен и работает")
            except Exception as e:
                logger.warning(f"❌ GigaChat недоступен: {e}")
                gigachat_available = False
        else:
            logger.warning("❌ GigaChat недоступен - клиент не инициализирован")
        
        if not self.yandex_model and not gigachat_available:
            logger.error("❌ Ни одна модель не доступна!")
        
        logger.info("Бот запущен и готов к работе!")
        print("🤖 Объединенный Telegram бот запущен!")
        print("✅ Конфигурация загружена")
        print("📝 Логи сохраняются в папку logs/")
        
        # Запускаем бота
        self.application.run_polling(allowed_updates=Update.ALL_TYPES)

def main():
    """Основная функция"""
    try:
        logger.info("Запуск main() функции")
        bot = UnifiedBot()
        bot.run()
    except KeyboardInterrupt:
        logger.info("Бот остановлен пользователем (Ctrl+C)")
        print("\n🛑 Бот остановлен пользователем")
    except Exception as e:
        logger.error(f"Критическая ошибка: {e}", exc_info=True)
        print(f"❌ Ошибка: {e}")

if __name__ == "__main__":
    main()
