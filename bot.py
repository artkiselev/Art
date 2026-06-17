from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from config import get_settings
from documents import create_ceremony_prompt_txt, create_questionnaire_docx
from email_sender import EmailNotConfiguredError, send_result_email
from questionnaire import QUESTIONS, format_question, question_count
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
/start - начать или продолжить анкету
/resume - показать текущий вопрос
/edit НОМЕР - изменить ответ на вопрос, например /edit 3
/export - сформировать файл и отправить на почту
/reset - начать заново
/help - помощь
""".strip()


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    logger.info("Received /start from chat_id=%s", chat_id)
    session = storage.get_or_create(chat_id)
    if session.completed:
        await update.message.reply_text(
            "Анкета уже заполнена. Можно отправить /export, изменить вопрос через /edit НОМЕР или начать заново через /reset."
        )
        return
    await update.message.reply_text(
        "Начинаем свадебную анкету. Ответы можно писать свободным текстом, прогресс сохраняется после каждого сообщения."
    )
    await update.message.reply_text(format_question(session.current_index))


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.info("Received /help from chat_id=%s", update.effective_chat.id)
    await update.message.reply_text(HELP_TEXT)


async def resume(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    logger.info("Received /resume from chat_id=%s", chat_id)
    session = storage.get_or_create(chat_id)
    if session.completed:
        await update.message.reply_text("Анкета заполнена. Отправьте /export, чтобы сформировать файл заново.")
        return
    await update.message.reply_text(format_question(session.current_index))


async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    logger.info("Received /reset from chat_id=%s", chat_id)
    storage.reset(chat_id)
    session = storage.get_or_create(chat_id)
    await update.message.reply_text("Анкета сброшена. Начинаем заново.")
    await update.message.reply_text(format_question(session.current_index))


async def edit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    logger.info("Received /edit from chat_id=%s args=%s", chat_id, context.args)
    session = storage.get_or_create(chat_id)
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
    await update.message.reply_text("Хорошо, изменим этот ответ.")
    await update.message.reply_text(format_question(session.current_index))


async def export(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    logger.info("Received /export from chat_id=%s", chat_id)
    session = storage.get_or_create(chat_id)
    await _export_session(update, session)


async def handle_answer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    logger.info("Received text answer from chat_id=%s", chat_id)
    session = storage.get_or_create(chat_id)
    text = update.message.text.strip()
    if not text:
        await update.message.reply_text("Пожалуйста, отправьте ответ текстом.")
        return

    if session.completed:
        await update.message.reply_text(
            "Анкета уже заполнена. Для изменения используйте /edit НОМЕР, для файла - /export."
        )
        return

    question = QUESTIONS[session.current_index]
    session.answers[question.key] = text
    session.current_index += 1

    if session.current_index >= question_count():
        session.completed = True
        storage.save(session)
        await update.message.reply_text("Анкета заполнена. Сейчас сформирую файл.")
        await _export_session(update, session)
        return

    storage.save(session)
    await update.message.reply_text("Ответ сохранен.")
    await update.message.reply_text(format_question(session.current_index))


async def _export_session(update: Update, session: Session) -> None:
    docx_path = create_questionnaire_docx(session.answers, settings.output_dir, session.chat_id)
    prompt_path = create_ceremony_prompt_txt(session.answers, settings.output_dir, session.chat_id)

    await update.message.reply_document(document=docx_path.open("rb"), filename=docx_path.name)
    await update.message.reply_document(document=prompt_path.open("rb"), filename=prompt_path.name)

    try:
        send_result_email(
            settings.yandex_smtp_login,
            settings.yandex_smtp_app_password,
            settings.result_email,
            [docx_path, prompt_path],
        )
    except EmailNotConfiguredError:
        await update.message.reply_text(
            "Файлы готовы и отправлены сюда. Почта пока не настроена: добавьте YANDEX_SMTP_APP_PASSWORD в .env."
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
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_answer))
    application.add_error_handler(error_handler)
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
