import logging

from telegram.ext import Application, CommandHandler, ConversationHandler, MessageHandler, filters

from bot.handlers.onboarding import cancel, delete_my_data, receive_profile, start
from bot.states import OnboardingState
from config import settings

# Только технические события (какой хендлер сработал, ошибки) — текст сообщений
# пользователя и другие персональные данные в лог не попадают (152-ФЗ, см. CLAUDE.md).
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logging.getLogger("httpx").setLevel(logging.WARNING)


def build_application() -> Application:
    application = Application.builder().token(settings.telegram_bot_token).build()

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
    application.add_handler(CommandHandler("delete_my_data", delete_my_data))
    return application


def main() -> None:
    application = build_application()
    application.run_polling()


if __name__ == "__main__":
    main()
