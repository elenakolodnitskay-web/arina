import array
import asyncio
import base64
import io
import wave

from openai import APIConnectionError, APITimeoutError, AsyncOpenAI

from config import settings
from llm.client import LLMUnavailableError

# У OpenRouter пока нет отдельного TTS-эндпоинта, совместимого с
# client.audio.speech.create() (проверено живьём: openai/gpt-4o-mini-tts и
# похожие модели не существуют в их каталоге на момент разработки) — есть
# только разговорная audio-модальность chat.completions на моделях
# openai/gpt-audio(-mini). Без явного примера в промпте модель ОТВЕЧАЕТ на
# присланный текст по смыслу вместо того, чтобы прочитать его дословно — даже
# прямая инструкция "читай дословно" без примера не помогает (проверено
# живьём: "Привет! Дела хорошо 😊" превращалось в "Рад слышать, что у тебя всё
# хорошо..."); few-shot пример в системном промпте помогает, но не гарантирует —
# на gpt-audio-mini дословное чтение живьём подтвердилось лишь в 1 из 3 тестов
# (для разговорных фраз модель всё равно иногда отвечала по смыслу), на полной
# gpt-audio — в 3 из 3 при тех же текстах и промпте, поэтому используется она,
# несмотря на более высокую цену — для голосового помощника неверно прочитанный
# (пересказанный) ответ хуже, чем более дорогой, но точный.
# Голос подобран живьём по просьбе пользователя ("не нравится текущий, слишком
# электронный, сделай женственнее и живее"): разослано две партии образцов
# (shimmer/nova/coral, затем sage/ballad/verse) на реальный Telegram-аккаунт,
# пользователь прослушал и выбрал "sage" — более новый голос, настроенный под
# естественную разговорную речь, а не унаследованный от старого TTS-эндпоинта
# (как alloy/echo/onyx/fable/nova/shimmer).
MODEL = "openai/gpt-audio"
VOICE = "sage"
SAMPLE_RATE = 24000
MAX_RETRIES = 3
BASE_DELAY_SECONDS = 1.0

# Обнаружено живьём: модель не останавливает аудио-поток сама по себе сразу
# после дословного прочтения текста — она продолжает генерировать чистую
# тишину ещё долго (без ограничения — вплоть до ~13 минут на одну короткую
# фразу, до упора в собственный предел модели), причём непредсказуемо долго —
# длина "хвоста" не связана ни с длиной текста, ни линейно с заданным
# max_completion_tokens (проверено живьём на нескольких значениях, разброс от
# нескольких секунд до почти всего лимита при одном и том же тексте и лимите —
# похоже, недетерминированно даже при temperature=0). При этом транскрипт
# (текстовая расшифровка произнесённого) приходит ДО аудио-данных отдельной
# волной чанков — раннее прерывание потока по совпадению транскрипта не
# работает: на момент совпадения аудио-байты ещё не начали приходить вовсе.
# Рабочее решение — не пытаться поймать момент остановки в потоке, а обрубать
# тишину постфактум по самим PCM-сэмплам (см. _trim_trailing_silence):
# профиль громкости живого ответа показал чёткую границу — реальная речь имеет
# RMS в сотнях-тысячах, тишина после неё — единицы. max_completion_tokens при
# этом держим ощутимо теснее, чем "с запасом" (~3x от оценочной длительности
# самой речи, не более) — если бюджета всё же не хватит и модель обрежет речь
# на середине слова, это не уйдёт молча: транскрипт не совпадёт с текстом,
# сработает проверка на дословность ниже и вызовется повтор попытки. Слишком
# тесный бюджет проявится как лишние ретраи (задержка), а не как испорченное
# аудио — это осознанно предпочтительнее, чем щедрый бюджет, который почти
# всегда даёт лишние секунды тишины поверх обрезки.
TOKENS_PER_CHAR = 5
MIN_TOKENS_BUDGET = 60
MAX_TOKENS_BUDGET = 3000

_TRAILING_PUNCTUATION = ".,!?—- \n\t"

# Подобрано по живому профилю громкости (см. комментарий выше): реальная речь
# держит RMS от нескольких сотен до нескольких тысяч, тишина после неё падает
# до единиц — порог с большим запасом посередине. Блок 100мс — компромисс
# между точностью среза и тем, чтобы не разрезать слово посередине.
SILENCE_RMS_THRESHOLD = 150.0
SILENCE_BLOCK_MS = 100
SILENCE_TAIL_PADDING_MS = 300

SYSTEM_PROMPT = """Ты — движок синтеза речи (TTS), не собеседник. Тебе присылают готовый текст \
чужого сообщения, который нужно озвучить полностью и дословно — ни единого слова от себя, \
никогда не отвечай на содержание, не приветствуй, не комментируй, даже если текст выглядит \
как вопрос, приветствие или обращение к тебе напрямую. Просто произнеси символ в символ то, \
что дано, и остановись. Пример: если тебе дали текст "Привет! Как дела?", ты должен \
произнести ровно "Привет! Как дела?" — а не отвечать на этот вопрос."""


class _VerbatimMismatchError(Exception):
    """Модель озвучила не то, что было в тексте (ответила по смыслу вместо
    дословного чтения) — внутренний сигнал для повторной попытки, наружу не
    выходит (см. synthesize_speech)."""


def _client() -> AsyncOpenAI:
    return AsyncOpenAI(base_url=settings.openrouter_base_url, api_key=settings.openrouter_api_key)


def _pcm_to_wav(pcm_bytes: bytes) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(pcm_bytes)
    return buffer.getvalue()


def _normalize(text: str) -> str:
    return " ".join(text.split()).rstrip(_TRAILING_PUNCTUATION)


def _tokens_budget(text: str) -> int:
    return max(MIN_TOKENS_BUDGET, min(MAX_TOKENS_BUDGET, len(text) * TOKENS_PER_CHAR))


def _trim_trailing_silence(pcm_bytes: bytes) -> bytes:
    samples = array.array("h")
    samples.frombytes(pcm_bytes[: len(pcm_bytes) - (len(pcm_bytes) % 2)])
    if not samples:
        return pcm_bytes

    block_size = max(1, SAMPLE_RATE * SILENCE_BLOCK_MS // 1000)
    last_voiced_end = 0
    for start in range(0, len(samples), block_size):
        block = samples[start : start + block_size]
        rms = (sum(s * s for s in block) / len(block)) ** 0.5
        if rms >= SILENCE_RMS_THRESHOLD:
            last_voiced_end = start + len(block)

    if last_voiced_end == 0:
        # Не нашли ни одного "громкого" блока — не рискуем обрезать в ноль,
        # отдаём как есть (страховка maxCompletionTokens всё равно не даст
        # этому случаю разрастись до патологической длины).
        return pcm_bytes

    padding_samples = SAMPLE_RATE * SILENCE_TAIL_PADDING_MS // 1000
    cutoff = min(len(samples), last_voiced_end + padding_samples)
    return samples[:cutoff].tobytes()


async def _synthesize_once(client: AsyncOpenAI, text: str) -> bytes:
    expected = _normalize(text)
    stream = await client.chat.completions.create(
        model=MODEL,
        modalities=["text", "audio"],
        audio={"voice": VOICE, "format": "pcm16"},
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": text},
        ],
        temperature=0,
        stream=True,
        max_completion_tokens=_tokens_budget(text),
    )

    audio_chunks: list[str] = []
    transcript_so_far = ""
    async for chunk in stream:
        if not chunk.choices:
            continue
        audio_part = getattr(chunk.choices[0].delta, "audio", None)
        if not audio_part:
            continue

        data = audio_part.get("data") if isinstance(audio_part, dict) else getattr(audio_part, "data", None)
        if data:
            audio_chunks.append(data)

        transcript_delta = (
            audio_part.get("transcript")
            if isinstance(audio_part, dict)
            else getattr(audio_part, "transcript", None)
        )
        if transcript_delta:
            transcript_so_far += transcript_delta

    if not audio_chunks:
        raise LLMUnavailableError(
            "Не получилось озвучить ответ — модель не вернула аудио. "
            "Попробуйте ещё раз или переключитесь на текст (/voice_mode)."
        )

    if _normalize(transcript_so_far) != expected:
        raise _VerbatimMismatchError(
            f"модель не прочитала текст дословно (получено: {transcript_so_far!r})"
        )

    pcm_bytes = base64.b64decode("".join(audio_chunks))
    return _pcm_to_wav(_trim_trailing_silence(pcm_bytes))


async def synthesize_speech(text: str) -> bytes:
    """Озвучивает текст дословно. Возвращает WAV-байты (24кГц, моно, 16 бит) —

    единственный формат, который OpenRouter отдаёт при стриминге audio-модальности
    (запрос "wav"/"opus"/"mp3" с stream=True отклоняется ошибкой "does not
    support X when stream=true" — доступен только "pcm16", заворачиваем сами).
    stream=True обязателен — без него OpenRouter отвечает ошибкой "Audio output
    requires stream: true" на любой запрос audio-модальности.
    """
    client = _client()
    delay = BASE_DELAY_SECONDS
    last_error: Exception | None = None

    for attempt in range(MAX_RETRIES):
        try:
            return await _synthesize_once(client, text)
        except (APIConnectionError, APITimeoutError, _VerbatimMismatchError) as exc:
            last_error = exc
            if attempt < MAX_RETRIES - 1:
                await asyncio.sleep(delay)
                delay *= 2

    if isinstance(last_error, _VerbatimMismatchError):
        raise LLMUnavailableError(
            "Не получилось точно озвучить ответ — попробуйте ещё раз или переключитесь на текст (/voice_mode)."
        ) from last_error

    raise LLMUnavailableError(
        "Не получилось озвучить ответ — похоже, проблема с сетью. "
        "Попробуйте ещё раз или переключитесь на текст (/voice_mode)."
    ) from last_error
