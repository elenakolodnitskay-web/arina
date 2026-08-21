import io

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from config import settings
from core.tariffs import Feature, feature_unavailable_message, has_feature
from db.models import ReplyMode, User
from db.session import SessionLocal
from llm.client import LLMUnavailableError
from llm.tts import synthesize_speech

VOICE_CALLBACK = "voice_mode:voice"
TEXT_CALLBACK = "voice_mode:text"

MODE_KEYBOARD = InlineKeyboardMarkup(
    [
        [
            InlineKeyboardButton("Голосом", callback_data=VOICE_CALLBACK),
            InlineKeyboardButton("Текстом", callback_data=TEXT_CALLBACK),
        ]
    ]
)


async def voice_mode_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    telegram_id = update.effective_user.id
    if telegram_id not in settings.allowed_user_ids_list:
        return

    await update.message.reply_text("Как отвечать — голосом или текстом?", reply_markup=MODE_KEYBOARD)


async def handle_voice_mode_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    telegram_id = query.from_user.id
    mode = ReplyMode.voice if query.data == VOICE_CALLBACK else ReplyMode.text

    with SessionLocal() as session:
        user = session.query(User).filter_by(telegram_id=telegram_id).one_or_none()
        if user is None:
            await query.answer("Не нашла ваш профиль — напишите /start.", show_alert=True)
            return
        # Переключение на текст не ограничено тарифом ни при каких условиях —
        # ограничивать имеет смысл только включение голоса.
        if mode == ReplyMode.voice and not has_feature(user.tariff, Feature.voice):
            await query.answer()
            await query.edit_message_text(feature_unavailable_message(Feature.voice))
            return
        user.reply_mode = mode
        session.commit()

    await query.answer()
    label = "голосом" if mode == ReplyMode.voice else "текстом"
    await query.edit_message_text(f"Буду отвечать {label}.")


async def send_reply(update: Update, text: str, reply_mode: ReplyMode, **kwargs) -> None:
    """Отправляет ответ голосом или текстом — в зависимости от сохранённого
    режима (/voice_mode), независимо от того, как пришёл вопрос (текстом или
    голосом). Известное упрощение: доп. параметры вроде `reply_markup`
    (инлайн-кнопки «Рабочее»/«Личное» для коррекции контекста) применимы только
    к текстовому ответу — при отправке голосом они молча отбрасываются, кнопок
    под голосовым сообщением не будет (поправить контекст в голосовом режиме
    можно тем же текстовым сообщением позже).
    """
    if reply_mode != ReplyMode.voice:
        await update.message.reply_text(text, **kwargs)
        return

    try:
        audio_bytes = await synthesize_speech(text)
    except LLMUnavailableError as exc:
        await update.message.reply_text(str(exc))
        return

    audio_file = io.BytesIO(audio_bytes)
    audio_file.name = "reply.wav"
    await update.message.reply_voice(voice=audio_file)
