# Wedding Bot

Telegram-бот для сбора свадебной анкеты пары. Бот задает вопросы по очереди, сохраняет прогресс, формирует Word-файл, отдельный промпт для подготовки текста церемонии через Codex и готовый план церемонии.

## Быстрый запуск через Codex

1. Установите зависимости:

   ```powershell
   .venv\Scripts\python.exe -m pip install -r requirements.txt
   ```

2. Создайте `.env` по примеру `.env.example`.

3. Запустите бот:

   ```powershell
   .\run_bot.ps1
   ```

Для фонового запуска через Codex/Windows можно использовать:

```powershell
.venv\Scripts\python.exe run_background.py
```

Или через Windows CMD:

```cmd
run_background.cmd
```

Если виртуального окружения еще нет, создайте его:

```powershell
python -m venv .venv
```

## Настройки

- `TELEGRAM_BOT_TOKEN` - токен Telegram-бота от BotFather.
- `RESULT_EMAIL` - адрес, куда отправлять готовые файлы.
- `YANDEX_SMTP_LOGIN` - логин почты Яндекса.
- `YANDEX_SMTP_APP_PASSWORD` - пароль приложения Яндекса для SMTP.
- `EXPORT_CHAT_ID` - чат/группа, куда бот отправляет готовые `.docx` и `.txt` после `/export`.
- `DATABASE_PATH` - путь к SQLite-базе с прогрессом.
- `OUTPUT_DIR` - папка для готовых файлов.

Обычный пароль от почты для SMTP использовать не нужно. Нужен пароль приложения.

## Команды бота

- `/start` - начать или продолжить анкету.
- `/resume` - показать текущий вопрос.
- `/edit НОМЕР` - изменить ответ на вопрос, например `/edit 3`.
- `/export` - сформировать файл и отправить на почту.
- `/reset` - начать заново.
- `/help` - помощь.

## Автономная работа

Чтобы бот работал постоянно:

1. Разместите проект на VPS.
2. Установите Python и зависимости.
3. Создайте `.env` на сервере.
4. Запустите бот через `systemd` или Docker Compose.
5. Настройте автоперезапуск и резервное копирование папок `data/` и `outputs/`.

Пример `systemd`-службы:

```ini
[Unit]
Description=Wedding Telegram Bot
After=network.target

[Service]
WorkingDirectory=/opt/wedding-bot
ExecStart=/opt/wedding-bot/.venv/bin/python bot.py
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
```
