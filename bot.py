from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from config import get_settings
from documents import create_ceremony_prompt_txt, create_ceremony_script_txt, create_questionnaire_docx
from email_sender import EmailNotConfiguredError, send_result_email
from openai_service import OpenAIServiceError, generate_ceremony_script, transcribe_audio
from questionnaire import QUESTIONNAIRE_VERSION, QUESTIONS, format_question, question_count, remaining_count
from storage import Session, Storage


logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

settings = get_settings()
storage = Storage(settings.database_path)


HELP_TEXT = """
Команды:
/start - начать или продолжить короткую анкету для церемонии
/resume - показать текущий вопрос
/edit НОМЕР - изменить ответ на вопрос, например /edit 3
/export - сформировать документы после завершения анкеты
/reset - начать заново
/help - помощь
""".strip()


def _session(chat_id: int) -> Session:
    return storage.get_or_create(chat_id, version=QUESTIONNAIRE_VERSION)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    logger.info("Received /start from chat_id=%s", chat_id)
    session = _session(chat_id)
    if session.completed:
        await update.message.reply_text(
            "Анкета уже заполнена. Можно отправить /export, изменить вопрос через /edit НОМЕР или начать заново через /reset."
        )
        return
    await update.message.reply_text(
        "Начинаем короткую анкету для церемонии. Можно отвечать текстом или голосовым сообщением."
    )
    await update.message.reply_text(format_question(session.current_index))


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.info("Received /help from chat_id=%s", update.effective_chat.id)
    await update.message.reply_text(HELP_TEXT)


async def resume(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    logger.info("Received /resume from chat_id=%s", chat_id)
    session = _session(chat_id)
    if session.completed:
        await update.message.reply_text("Анкета заполнена. Отправьте /export, чтобы сформировать документы.")
        return
    await update.message.reply_text(format_question(session.current_index))


async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    logger.info("Received /reset from chat_id=%s", chat_id)
    storage.reset(chat_id)
    session = _session(chat_id)
    await update.message.reply_text("Анкета сброшена. Начинаем заново.")
    await update.message.reply_text(format_question(session.current_index))


async def edit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    logger.info("Received /edit from chat_id=%s args=%s", chat_id, context.args)
    session = _session(chat_id)
    if not context.args:
        await update.message.reply_text("Укажите номер вопроса: например /edit 3")
        return
    try:
        number = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Номер вопроса должен быть числом.")
        return
    if number < 1 or number > question_count():
        await update.message.reply_text(f"Номер должен быть от 1 до {question_count()}.")
        return
    session.current_index = number - 1
    session.completed = False
    storage.save(session)
    await update.message.reply_text("Хорошо, изменим этот ответ. Можно ответить текстом или голосом.")
    await update.message.reply_text(format_question(session.current_index))


async def export(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    logger.info("Received /export from chat_id=%s", chat_id)
    session = _session(chat_id)
    if not session.completed:
        await update.message.reply_text(
            f"Для полной речи нужно закончить анкету. Осталось вопросов: {remaining_count(session.current_index)}."
        )
        await update.message.reply_text(format_question(session.current_index))
        return
    await _export_session(update, context, session)


async def handle_text_answer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    logger.info("Received text answer from chat_id=%s", chat_id)
    text = update.message.text.strip()
    if not text:
        await update.message.reply_text("Пожалуйста, отправьте ответ текстом или голосовым сообщением.")
        return
    await _store_answer(update, context, text)


async def handle_voice_answer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    logger.info("Received voice/audio answer from chat_id=%s", chat_id)
    if not settings.openai_api_key:
        await update.message.reply_text("Для голосовых ответов нужен OPENAI_API_KEY в файле .env.")
        return

    await update.message.reply_text("Слушаю голосовое и перевожу в текст...")
    try:
        audio_path = await _download_audio(update, context)
        text = await asyncio.to_thread(
            transcribe_audio,
            settings.openai_api_key,
            settings.openai_transcribe_model,
            audio_path,
        )
    except Exception as exc:
        logger.exception("Voice transcription failed")
        await update.message.reply_text(f"Не получилось распознать голосовое: {exc}")
        return

    await update.message.reply_text(f"Я записал ответ так:\n\n{text}")
    await _store_answer(update, context, text)


async def _store_answer(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str) -> None:
    chat_id = update.effective_chat.id
    session = _session(chat_id)
    if session.completed:
        await update.message.reply_text(
            "Анкета уже заполнена. Для изменения используйте /edit НОМЕР, для документов - /export."
        )
        return

    question = QUESTIONS[session.current_index]
    session.answers[question.key] = text
    session.current_index += 1

    if session.current_index >= question_count():
        session.completed = True
        storage.save(session)
        await update.message.reply_text("Анкета заполнена. Сейчас подготовлю полную речь ведущего и документы.")
        await _export_session(update, context, session)
        return

    storage.save(session)
    await update.message.reply_text("Ответ сохранен.")
    await update.message.reply_text(format_question(session.current_index))


async def _download_audio(update: Update, context: ContextTypes.DEFAULT_TYPE) -> Path:
    settings.voice_dir.mkdir(parents=True, exist_ok=True)
    message = update.message
    media = message.voice or message.audio
    if media is None:
        raise RuntimeError("В сообщении нет голосового или аудиофайла.")

    suffix = ".ogg" if message.voice else Path(message.audio.file_name or "audio.m4a").suffix or ".m4a"
    file_name = f"{message.chat_id}_{message.message_id}{suffix}"
    target_path = settings.voice_dir / file_name
    telegram_file = await context.bot.get_file(media.file_id)
    await telegram_file.download_to_drive(custom_path=str(target_path))
    return target_path


async def _export_session(update: Update, context: ContextTypes.DEFAULT_TYPE, session: Session) -> None:
    if not settings.openai_api_key:
        await update.message.reply_text("Не могу создать финальную речь: добавьте OPENAI_API_KEY в .env.")
        return

    await update.message.reply_text("Генерирую полный текст церемонии. Это может занять немного времени.")
    try:
        script_text = await asyncio.to_thread(
            generate_ceremony_script,
            settings.openai_api_key,
            settings.openai_text_model,
            session.answers,
        )
    except OpenAIServiceError as exc:
        await update.message.reply_text(f"OpenAI не вернул текст церемонии: {exc}")
        return
    except Exception as exc:
        logger.exception("Ceremony generation failed")
        await update.message.reply_text(f"Не получилось создать речь церемонии: {exc}")
        return

    docx_path = create_questionnaire_docx(session.answers, settings.output_dir, session.chat_id)
    prompt_path = create_ceremony_prompt_txt(session.answers, settings.output_dir, session.chat_id)
    script_path = create_ceremony_script_txt(script_text, session.answers, settings.output_dir, session.chat_id)

    target_chat_id = settings.export_chat_id or session.chat_id
    caption = f"Готовая церемониальная анкета от чата {session.chat_id}"
    with docx_path.open("rb") as docx_file:
        await context.bot.send_document(
            chat_id=target_chat_id,
            document=docx_file,
            filename=docx_path.name,
            caption=caption,
        )
    with prompt_path.open("rb") as prompt_file:
        await context.bot.send_document(
            chat_id=target_chat_id,
            document=prompt_file,
            filename=prompt_path.name,
        )
    with script_path.open("rb") as script_file:
        await context.bot.send_document(
            chat_id=target_chat_id,
            document=script_file,
            filename=script_path.name,
        )
    if settings.export_chat_id and settings.export_chat_id != session.chat_id:
        await update.message.reply_text("Файлы сформированы и отправлены в группу.")

    try:
        send_result_email(
            settings.yandex_smtp_login,
            settings.yandex_smtp_app_password,
            settings.result_email,
            [docx_path, prompt_path, script_path],
        )
    except EmailNotConfiguredError:
        await update.message.reply_text(
            "Файлы готовы. Почта пока не настроена: добавьте YANDEX_SMTP_APP_PASSWORD в .env."
        )
    except Exception as exc:
        logger.exception("Failed to send email")
        await update.message.reply_text(f"Файлы готовы, но письмо не отправилось: {exc}")
    else:
        await update.message.reply_text(f"Файлы отправлены на {settings.result_email}.")


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.exception("Telegram handler failed. update=%s", update, exc_info=context.error)


def main() -> None:
    if not settings.telegram_bot_token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is empty. Add it to .env.")

    application = Application.builder().token(settings.telegram_bot_token).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("resume", resume))
    application.add_handler(CommandHandler("reset", reset))
    application.add_handler(CommandHandler("edit", edit))
    application.add_handler(CommandHandler("export", export))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_answer))
    application.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, handle_voice_answer))
    application.add_error_handler(error_handler)
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
