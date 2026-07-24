# Wedding Ceremony Bot

Telegram-бот для короткой анкеты свадебной церемонии. Пользователь отвечает текстом или голосом, бот сохраняет ответы, распознает голос через OpenAI API и после завершения анкеты генерирует полный текст церемонии для ведущего.

## Запуск

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe bot.py
```

Локальный фоновый запуск на Windows:

```cmd
run_background.cmd
```

## Настройки `.env`

```env
TELEGRAM_BOT_TOKEN=...
OPENAI_API_KEY=...
OPENAI_TEXT_MODEL=gpt-5
OPENAI_TRANSCRIBE_MODEL=gpt-4o-mini-transcribe
RESULT_EMAIL=mkshow@yandex.ru
YANDEX_SMTP_LOGIN=mkshow@yandex.ru
YANDEX_SMTP_APP_PASSWORD=...
EXPORT_CHAT_ID=-1004429435070
DATABASE_PATH=data/wedding_bot.sqlite3
OUTPUT_DIR=outputs
VOICE_DIR=data/voice
```

`.env` не попадает в GitHub.

## Команды бота

- `/start` - начать или продолжить короткую анкету.
- `/resume` - показать текущий вопрос.
- `/edit НОМЕР` - изменить ответ, например `/edit 3`.
- `/export` - сформировать документы после завершения анкеты.
- `/reset` - начать заново.
- `/help` - помощь.

## Что делает экспорт

После завершения анкеты бот отправляет в группу:

- `.docx` с заполненной анкетой;
- `.txt` с исходным промптом;
- `.txt` с полным текстом церемонии для ведущего.

Если анкета не закончена, `/export` покажет, сколько вопросов осталось, и не будет генерировать финальную речь.

## Автономная работа

Для постоянной работы бот нужно перенести на VPS/сервер и запустить как службу, например через `systemd` или Docker Compose. Важно сохранить `.env`, базу `data/` и папку `outputs/` вне Git.
