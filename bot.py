from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from telegram import BotCommand, Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from config import get_settings
from documents import create_ceremony_script_docx, create_ceremony_script_html, create_questionnaire_docx
from email_sender import EmailNotConfiguredError, send_result_email
from openai_service import OpenAIServiceError, generate_ceremony_script, transcribe_audio
from questionnaire import (
    QUESTIONNAIRE_VERSION,
    QUESTIONS,
    format_answers_review,
    format_question,
    format_question_for_edit,
    question_count,
    remaining_count,
)
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
/export - показать финальную анкету перед подтверждением
/confirm - подтвердить анкету и передать материалы ведущему
/reset - начать заново
/help - помощь
""".strip()

CONFIRM_WORDS = {"подтверждаю", "подтвердить", "все верно", "всё верно", "готово", "да"}

PREPARING_EXPORT_TEXT = (
    "Спасибо, анкета заполнена. Я бережно собираю ваши ответы в материалы для церемонии, "
    "это займет немного времени."
)

FINAL_SUCCESS_TEXT = (
    "Готово. Анкета принята, а материалы уже переданы ведущему.\n\n"
    "Спасибо, что так подробно рассказали вашу историю. Теперь можно выдохнуть, "
    "расслабиться и спокойно ждать день церемонии - дальше мы соберем из ваших ответов "
    "красивую, личную и теплую церемонию."
)

FINAL_FAILURE_TEXT = (
    "Пока не получилось подготовить материалы. Попробуйте отправить /export чуть позже "
    "или напишите ведущему."
)


def _session(chat_id: int) -> Session:
    return storage.get_or_create(chat_id, version=QUESTIONNAIRE_VERSION)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    logger.info("Received /start from chat_id=%s", chat_id)
    session = _session(chat_id)
    if session.status == "confirmed":
        await update.message.reply_text(
            "Материалы уже переданы ведущему. Если захотите заполнить новую анкету, отправьте /reset."
        )
        return
    if session.status == "review":
        await _show_review(update, session)
        return
    if session.status == "editing":
        await update.message.reply_text(format_question_for_edit(session.current_index))
        return
    if session.completed:
        await update.message.reply_text(
            "Анкета уже заполнена. Проверьте ответы и подтвердите отправку ведущему."
        )
        await _show_review(update, session)
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
    if session.status == "confirmed":
        await update.message.reply_text(
            "Материалы уже переданы ведущему. Если захотите заполнить новую анкету, отправьте /reset."
        )
        return
    if session.status == "review":
        await _show_review(update, session)
        return
    if session.status == "editing":
        await update.message.reply_text(format_question_for_edit(session.current_index))
        return
    if session.completed:
        await _show_review(update, session)
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
    if session.status == "confirmed":
        await update.message.reply_text(
            "Эта анкета уже передана ведущему. Если хотите заполнить новую версию, отправьте /reset."
        )
        return
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
    session.status = "editing" if session.answers else "collecting"
    storage.save(session)
    await update.message.reply_text("Хорошо, изменим этот ответ. Можно ответить текстом или голосом.")
    await update.message.reply_text(format_question_for_edit(session.current_index))


async def export(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    logger.info("Received /export from chat_id=%s", chat_id)
    session = _session(chat_id)
    if session.status == "confirmed":
        await update.message.reply_text(
            "Материалы уже переданы ведущему. Если захотите заполнить новую анкету, отправьте /reset."
        )
        return
    if not session.completed and session.status != "review":
        await update.message.reply_text(
            f"Для полной речи нужно закончить анкету. Осталось вопросов: {remaining_count(session.current_index)}."
        )
        await update.message.reply_text(format_question(session.current_index))
        return
    session.status = "review"
    storage.save(session)
    await _show_review(update, session)


async def confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    logger.info("Received /confirm from chat_id=%s", chat_id)
    session = _session(chat_id)
    if session.status == "confirmed":
        await update.message.reply_text(
            "Материалы уже переданы ведущему. Если захотите заполнить новую анкету, отправьте /reset."
        )
        return
    if session.status != "review" or not session.completed:
        await update.message.reply_text("Сначала нужно заполнить анкету до конца.")
        if not session.completed:
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
    session = _session(chat_id)
    if session.status == "review":
        await _handle_review_text(update, context, session, text)
        return
    await _store_answer(update, context, text)


async def handle_voice_answer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    logger.info("Received voice/audio answer from chat_id=%s", chat_id)
    if not settings.openai_api_key:
        logger.error("Cannot transcribe voice answer from chat_id=%s: OPENAI_API_KEY is empty", chat_id)
        await update.message.reply_text("Пока не получается принять голосовой ответ. Пожалуйста, ответьте текстом.")
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
    except Exception:
        logger.exception("Voice transcription failed")
        await update.message.reply_text("Не получилось разобрать голосовое сообщение. Пожалуйста, ответьте текстом.")
        return

    await update.message.reply_text(f"Я записал ответ так:\n\n{text}")
    await _store_answer(update, context, text)


async def _store_answer(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str) -> None:
    chat_id = update.effective_chat.id
    session = _session(chat_id)
    if session.status == "confirmed":
        await update.message.reply_text(
            "Материалы уже переданы ведущему. Если захотите заполнить новую анкету, отправьте /reset."
        )
        return
    if session.status == "review":
        await _handle_review_text(update, context, session, text)
        return
    if session.completed and session.status != "editing":
        await update.message.reply_text(
            "Анкета уже заполнена. Проверьте ответы и подтвердите отправку ведущему."
        )
        await _show_review(update, session)
        return

    question = QUESTIONS[session.current_index]
    session.answers[question.key] = text

    if session.status == "editing":
        session.completed = True
        session.status = "review"
        storage.save(session)
        await update.message.reply_text("Ответ обновлен. Вот новый финальный вариант анкеты.")
        await _show_review(update, session)
        return

    session.current_index += 1

    if session.current_index >= question_count():
        session.completed = True
        session.status = "review"
        storage.save(session)
        await _show_review(update, session)
        return

    session.status = "collecting"
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


async def _handle_review_text(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    session: Session,
    text: str,
) -> None:
    normalized = text.strip().lower().replace("ё", "е")
    normalized_confirm_words = {word.replace("ё", "е") for word in CONFIRM_WORDS}
    if normalized in normalized_confirm_words:
        await _export_session(update, context, session)
        return

    try:
        number = int(normalized)
    except ValueError:
        await update.message.reply_text(
            "Напишите номер вопроса, который хотите изменить, или отправьте /confirm, если все верно."
        )
        return

    if number < 1 or number > question_count():
        await update.message.reply_text(f"Номер должен быть от 1 до {question_count()}.")
        return

    session.current_index = number - 1
    session.status = "editing"
    session.completed = False
    storage.save(session)
    await update.message.reply_text(format_question_for_edit(session.current_index))


async def _show_review(update: Update, session: Session) -> None:
    await _reply_long_text(update, format_answers_review(session.answers))


async def _reply_long_text(update: Update, text: str) -> None:
    chunk_size = 3800
    chunks: list[str] = []
    current = ""
    for paragraph in text.split("\n\n"):
        addition = paragraph if not current else f"\n\n{paragraph}"
        if len(current) + len(addition) <= chunk_size:
            current += addition
        else:
            if current:
                chunks.append(current)
            if len(paragraph) <= chunk_size:
                current = paragraph
            else:
                chunks.extend(paragraph[index : index + chunk_size] for index in range(0, len(paragraph), chunk_size))
                current = ""
    if current:
        chunks.append(current)

    for chunk in chunks:
        await update.message.reply_text(chunk)


async def _export_session(update: Update, context: ContextTypes.DEFAULT_TYPE, session: Session) -> None:
    if not settings.openai_api_key:
        logger.error("Cannot export session %s: OPENAI_API_KEY is empty", session.chat_id)
        await update.message.reply_text(FINAL_FAILURE_TEXT)
        return

    await update.message.reply_text(PREPARING_EXPORT_TEXT)
    try:
        script_text = await asyncio.to_thread(
            generate_ceremony_script,
            settings.openai_api_key,
            settings.openai_text_model,
            session.answers,
        )
    except OpenAIServiceError as exc:
        logger.exception("OpenAI did not return ceremony script: %s", exc)
        await update.message.reply_text(FINAL_FAILURE_TEXT)
        return
    except Exception:
        logger.exception("Ceremony generation failed")
        await update.message.reply_text(FINAL_FAILURE_TEXT)
        return

    try:
        docx_path = create_questionnaire_docx(session.answers, settings.output_dir, session.chat_id)
        script_html_path = create_ceremony_script_html(script_text, session.answers, settings.output_dir, session.chat_id)
        script_docx_path = create_ceremony_script_docx(script_text, session.answers, settings.output_dir, session.chat_id)

        target_chat_id = settings.export_chat_id or session.chat_id
        caption = f"Анкета от чата {session.chat_id}"
        with docx_path.open("rb") as docx_file:
            await context.bot.send_document(
                chat_id=target_chat_id,
                document=docx_file,
                filename=docx_path.name,
                caption=caption,
            )
        with script_html_path.open("rb") as script_html_file:
            await context.bot.send_document(
                chat_id=target_chat_id,
                document=script_html_file,
                filename=script_html_path.name,
                caption="Текст для церемонии - HTML",
            )
        with script_docx_path.open("rb") as script_docx_file:
            await context.bot.send_document(
                chat_id=target_chat_id,
                document=script_docx_file,
                filename=script_docx_path.name,
                caption="Текст для церемонии - DOCX для печати",
            )
    except Exception:
        logger.exception("Failed to create or send export files")
        await update.message.reply_text(FINAL_FAILURE_TEXT)
        return

    try:
        send_result_email(
            settings.yandex_smtp_login,
            settings.yandex_smtp_app_password,
            settings.result_email,
            [docx_path, script_html_path, script_docx_path],
        )
    except EmailNotConfiguredError:
        logger.info("Email is not configured; skipping email delivery for chat_id=%s", session.chat_id)
    except Exception:
        logger.exception("Failed to send email")
    else:
        logger.info("Export email sent to %s for chat_id=%s", settings.result_email, session.chat_id)

    session.status = "confirmed"
    session.completed = True
    storage.save(session)
    await update.message.reply_text(FINAL_SUCCESS_TEXT)


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.exception("Telegram handler failed. update=%s", update, exc_info=context.error)


async def setup_bot_commands(application: Application) -> None:
    await application.bot.set_my_commands(
        [
            BotCommand("start", "Начать или продолжить анкету"),
            BotCommand("resume", "Показать текущий вопрос"),
            BotCommand("edit", "Изменить ответ по номеру вопроса"),
            BotCommand("export", "Показать финальную анкету"),
            BotCommand("confirm", "Подтвердить и передать ведущему"),
            BotCommand("reset", "Заполнить новую анкету"),
            BotCommand("help", "Помощь"),
        ]
    )


def main() -> None:
    if not settings.telegram_bot_token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is empty. Add it to .env.")

    application = Application.builder().token(settings.telegram_bot_token).post_init(setup_bot_commands).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("resume", resume))
    application.add_handler(CommandHandler("reset", reset))
    application.add_handler(CommandHandler("edit", edit))
    application.add_handler(CommandHandler("export", export))
    application.add_handler(CommandHandler("confirm", confirm))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_answer))
    application.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, handle_voice_answer))
    application.add_error_handler(error_handler)
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
