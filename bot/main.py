import logging

from telegram import BotCommand, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from bot.handlers.documents_flow import (
    CONFIRM_CALLBACK,
    REFORMULATE_CALLBACK,
    create_document,
    handle_confirm_document,
    handle_reformulate_document,
)
from bot.handlers.free_chat import (
    handle_context_correction,
    handle_message,
    handle_unsupported_message,
    handle_voice_message,
)
from bot.handlers.email_flow import (
    CONFIRM_CALLBACK as EMAIL_CONFIRM_CALLBACK,
    REFORMULATE_CALLBACK as EMAIL_REFORMULATE_CALLBACK,
    handle_confirm_email,
    handle_reformulate_email,
)
from bot.handlers.onboarding import cancel, delete_my_data, help_command, receive_profile, start
from bot.handlers.relay_flow import (
    CONFIRM_CALLBACK as RELAY_CONFIRM_CALLBACK,
    REFORMULATE_CALLBACK as RELAY_REFORMULATE_CALLBACK,
    handle_confirm_relay,
    handle_reformulate_relay,
)
from bot.handlers.tasks_flow import (
    create_task,
    handle_cancel_task,
    handle_complete_task,
    handle_edit_task_button,
    list_completed_tasks,
    list_tasks,
)
from bot.states import OnboardingState
from config import settings
from core.scheduler import get_scheduler
from max_bot.webhook import start_webhook_server

# Только технические события (какой хендлер сработал, ошибки) — текст сообщений
# пользователя и другие персональные данные в лог не попадают (152-ФЗ, см. CLAUDE.md).
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logging.getLogger("httpx").setLevel(logging.WARNING)
# openai SDK на DEBUG логирует тела запросов — а через них проходит текст сообщений
# пользователя (промпты к LLM). Держим WARNING, чтобы это не могло утечь в лог.
logging.getLogger("openai").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

BOT_COMMANDS = [
    BotCommand("start", "Начать работу с Ариной"),
    BotCommand("help", "Что умеет Арина"),
    BotCommand("task", "Поставить задачу или напоминание"),
    BotCommand("tasks", "Показать активные задачи"),
    BotCommand("tasks_done", "Показать выполненные задачи"),
    BotCommand("document", "Сгенерировать письмо или документ"),
    BotCommand("delete_my_data", "Удалить все мои данные"),
]


async def _on_startup(application: Application) -> None:
    await application.bot.set_my_commands(BOT_COMMANDS)
    get_scheduler().start()
    if settings.max_bot_token:
        await start_webhook_server()


async def _on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("Unhandled exception while processing an update", exc_info=context.error)
    if isinstance(update, Update) and update.effective_chat is not None:
        try:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="Что-то пошло не так на нашей стороне. Попробуйте ещё раз чуть позже.",
            )
        except Exception:
            logger.error("Failed to notify the user about the error")


def build_application() -> Application:
    application = Application.builder().token(settings.telegram_bot_token).post_init(_on_startup).build()

    onboarding_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            OnboardingState.AWAITING_PROFILE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_profile)
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    application.add_handler(onboarding_handler)
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("delete_my_data", delete_my_data))
    application.add_handler(CommandHandler("task", create_task))
    application.add_handler(CommandHandler("tasks", list_tasks))
    application.add_handler(CommandHandler("tasks_done", list_completed_tasks))
    application.add_handler(CallbackQueryHandler(handle_cancel_task, pattern=r"^cancel_task:"))
    application.add_handler(CallbackQueryHandler(handle_complete_task, pattern=r"^complete_task:"))
    application.add_handler(CallbackQueryHandler(handle_edit_task_button, pattern=r"^edit_task:"))
    application.add_handler(CommandHandler("document", create_document))
    application.add_handler(CallbackQueryHandler(handle_confirm_document, pattern=rf"^{CONFIRM_CALLBACK}$"))
    application.add_handler(
        CallbackQueryHandler(handle_reformulate_document, pattern=rf"^{REFORMULATE_CALLBACK}$")
    )
    application.add_handler(
        CallbackQueryHandler(handle_confirm_relay, pattern=rf"^{RELAY_CONFIRM_CALLBACK}$")
    )
    application.add_handler(
        CallbackQueryHandler(handle_reformulate_relay, pattern=rf"^{RELAY_REFORMULATE_CALLBACK}$")
    )
    application.add_handler(
        CallbackQueryHandler(handle_confirm_email, pattern=rf"^{EMAIL_CONFIRM_CALLBACK}$")
    )
    application.add_handler(
        CallbackQueryHandler(handle_reformulate_email, pattern=rf"^{EMAIL_REFORMULATE_CALLBACK}$")
    )
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, handle_voice_message))
    application.add_handler(CallbackQueryHandler(handle_context_correction, pattern=r"^set_context:"))
    # Ловит любые другие форматы (видео-кружок, стикер, фото...) — иначе бот молчит,
    # не давая понять, что сообщение вообще дошло, но не распознано.
    application.add_handler(MessageHandler(filters.ALL, handle_unsupported_message))
    application.add_error_handler(_on_error)
    return application


def main() -> None:
    application = build_application()
    # Явно запрашиваем все типы обновлений — без этого возможна ситуация, когда
    # Telegram присылает только те типы, что были ранее сохранены как allowed_updates
    # для этого бота (если когда-то были заданы вручную/другим клиентом).
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
