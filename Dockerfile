# Dockerfile для Telegram бота с Yandex GPT и GigaChat
FROM python:3.11-slim

# Устанавливаем рабочую директорию
WORKDIR /app

# Копируем requirements.txt и устанавливаем зависимости
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем весь код приложения
COPY unified_bot.py .
COPY multi_search.py .
COPY rss_news.py .
COPY certs/ ./certs/

# Создаём директории для логов
RUN mkdir -p logs

# Переменные окружения будут передаваться через docker-compose или -e
# ENV TELEGRAM_TOKEN=your_token
# ENV YANDEX_FOLDER_ID=your_folder_id
# ENV YANDEX_API_KEY=your_api_key
# ENV GIGA_KEY=your_giga_key
# ENV OPENWEATHER_API_KEY=your_weather_key

# Запускаем бота
CMD ["python", "-u", "unified_bot.py"]

