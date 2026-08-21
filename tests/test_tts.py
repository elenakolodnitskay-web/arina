import base64
import struct
import wave
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from openai import APIConnectionError

from llm import tts
from llm.client import LLMUnavailableError

_FAKE_REQUEST = httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions")


def make_chunk(audio_data: str | None, transcript: str | None = None):
    if audio_data is None and transcript is None:
        audio = None
    else:
        audio = {}
        if audio_data is not None:
            audio["data"] = audio_data
        if transcript is not None:
            audio["transcript"] = transcript
    return SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(audio=audio))])


async def fake_stream(*chunks):
    for chunk in chunks:
        yield chunk


def make_fake_client(create: AsyncMock) -> SimpleNamespace:
    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))


@pytest.fixture(autouse=True)
def no_real_sleep(monkeypatch):
    monkeypatch.setattr(tts.asyncio, "sleep", AsyncMock())


@pytest.mark.asyncio
async def test_synthesize_speech_returns_valid_wav(monkeypatch):
    # "AAAAAA==" -> валидные base64-байты (просто нулевые сэмплы), достаточно для
    # проверки, что итоговый файл — корректный WAV-контейнер. Транскрипт должен
    # дословно совпасть с текстом — иначе синтез считается неудачным (см. tts.py).
    create = AsyncMock(
        return_value=fake_stream(
            make_chunk("AAAAAA==", "Привет"), make_chunk("AAAAAA==", "!")
        )
    )
    monkeypatch.setattr(tts, "_client", lambda: make_fake_client(create))

    result = await tts.synthesize_speech("Привет!")

    assert result.startswith(b"RIFF")
    with wave.open(BytesIO(result), "rb") as wf:
        assert wf.getnchannels() == 1
        assert wf.getsampwidth() == 2
        assert wf.getframerate() == tts.SAMPLE_RATE


@pytest.mark.asyncio
async def test_synthesize_speech_passes_verbatim_readback_system_prompt(monkeypatch):
    create = AsyncMock(
        return_value=fake_stream(make_chunk("AAAAAA==", "Записала: позвонить маме."))
    )
    monkeypatch.setattr(tts, "_client", lambda: make_fake_client(create))

    await tts.synthesize_speech("Записала: позвонить маме.")

    kwargs = create.await_args.kwargs
    assert kwargs["modalities"] == ["text", "audio"]
    assert kwargs["audio"] == {"voice": tts.VOICE, "format": "pcm16"}
    assert kwargs["temperature"] == 0
    assert kwargs["messages"][1]["content"] == "Записала: позвонить маме."
    assert "дословно" in kwargs["messages"][0]["content"]
    assert kwargs["max_completion_tokens"] > 0


@pytest.mark.asyncio
async def test_synthesize_speech_trims_trailing_silence(monkeypatch):
    # Транскрипт приходит отдельной волной ДО аудио-данных (проверено живьём) —
    # поэтому нельзя обрывать поток по совпадению транскрипта, только читать
    # весь ответ целиком и обрезать тишину в конце уже по PCM-сэмплам. Блоки
    # анализа — по SILENCE_BLOCK_MS сэмплов, поэтому и "речь", и "тишина" здесь
    # должны быть заметно длиннее одного блока, иначе громкий фрагмент просто
    # усредняется внутри одного блока с тишиной и не даёт показательного среза.
    def flat_block(amplitude: int, n: int) -> bytes:
        return struct.pack(f"<{n}h", *([amplitude] * n))

    loud = flat_block(3000, tts.SAMPLE_RATE)  # 1 секунда "речи" громче порога
    silence = flat_block(0, tts.SAMPLE_RATE * 5)  # 5 секунд тишины после неё
    pcm = loud + silence

    audio_b64 = base64.b64encode(pcm).decode()
    create = AsyncMock(return_value=fake_stream(make_chunk(audio_b64, "Привет!")))
    monkeypatch.setattr(tts, "_client", lambda: make_fake_client(create))

    result = await tts.synthesize_speech("Привет!")

    with wave.open(BytesIO(result), "rb") as wf:
        trimmed_frames = wf.getnframes()
    # Отрезали заметно больше половины — почти весь "хвост" тишины ушёл,
    # осталась речь + небольшой отступ (SILENCE_TAIL_PADDING_MS).
    original_frames = len(pcm) // 2
    assert trimmed_frames < original_frames / 2


@pytest.mark.asyncio
async def test_synthesize_speech_raises_when_no_audio_returned(monkeypatch):
    create = AsyncMock(return_value=fake_stream(make_chunk(None, "Привет")))
    monkeypatch.setattr(tts, "_client", lambda: make_fake_client(create))

    with pytest.raises(LLMUnavailableError, match="не вернула аудио"):
        await tts.synthesize_speech("Привет!")


@pytest.mark.asyncio
async def test_synthesize_speech_retries_then_succeeds(monkeypatch):
    create = AsyncMock(
        side_effect=[
            APIConnectionError(request=_FAKE_REQUEST),
            fake_stream(make_chunk("AAAAAA==", "Привет!")),
        ]
    )
    monkeypatch.setattr(tts, "_client", lambda: make_fake_client(create))

    result = await tts.synthesize_speech("Привет!")

    assert result.startswith(b"RIFF")
    assert create.await_count == 2


@pytest.mark.asyncio
async def test_synthesize_speech_raises_russian_error_after_exhausting_retries(monkeypatch):
    create = AsyncMock(side_effect=APIConnectionError(request=_FAKE_REQUEST))
    monkeypatch.setattr(tts, "_client", lambda: make_fake_client(create))

    with pytest.raises(LLMUnavailableError, match="проблема с сетью"):
        await tts.synthesize_speech("Привет!")

    assert create.await_count == tts.MAX_RETRIES


@pytest.mark.asyncio
async def test_synthesize_speech_retries_on_paraphrase_then_succeeds(monkeypatch):
    # Первая попытка — модель ответила по смыслу вместо дословного чтения
    # (несовпадающий транскрипт), вторая — прочитала верно.
    create = AsyncMock(
        side_effect=[
            fake_stream(make_chunk("AAAAAA==", "Рад слышать, что у тебя всё хорошо.")),
            fake_stream(make_chunk("AAAAAA==", "Привет!")),
        ]
    )
    monkeypatch.setattr(tts, "_client", lambda: make_fake_client(create))

    result = await tts.synthesize_speech("Привет!")

    assert result.startswith(b"RIFF")
    assert create.await_count == 2


@pytest.mark.asyncio
async def test_synthesize_speech_raises_after_exhausting_retries_on_persistent_paraphrase(monkeypatch):
    # side_effect со списком — на каждую попытку свой (ещё не израсходованный)
    # генератор, иначе повторный вызов create() получил бы уже исчерпанный поток.
    create = AsyncMock(
        side_effect=[
            fake_stream(make_chunk("AAAAAA==", "Рад слышать, что у тебя всё хорошо."))
            for _ in range(tts.MAX_RETRIES)
        ]
    )
    monkeypatch.setattr(tts, "_client", lambda: make_fake_client(create))

    with pytest.raises(LLMUnavailableError, match="точно озвучить"):
        await tts.synthesize_speech("Привет!")

    assert create.await_count == tts.MAX_RETRIES
