# Бот для освоения спичага с пола

## Запуск на сервере
1. Создай бота у @BotFather и получи токен.
2. `cp .env.example .env` и впиши `BOT_TOKEN` (и свой id в `ALLOWED_USER_IDS`).
3. `docker compose up -d --build`

Без Docker: `pip install -r requirements.txt && BOT_TOKEN=... python bot.py`

## Файлы
- `exercises.py` — позы человечка и упражнения (текст, подходы, уровень 1–5). Правь тут.
- `program.py` — логика программы: фазы, уровни, разгрузка, тесты.
- `figures.py` — генерация GIF-анимаций (`python figures.py` — перерисовать все в `media/`).
- `bot.py` — Telegram: кнопки, настройки, напоминания.
- `db.py` — SQLite (`data/bot.db`).

После изменения анимаций увеличь `MEDIA_VER` в `bot.py`, чтобы Telegram не отдавал старые из кэша.
