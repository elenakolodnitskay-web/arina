import pytest

from llm.json_parse import extract_json


def test_extract_json_parses_plain_json():
    assert extract_json('{"a": 1}') == {"a": 1}


def test_extract_json_finds_block_inside_surrounding_text():
    raw = 'Конечно, вот ответ:\n{"a": 1, "b": "текст"}\nНадеюсь, это поможет!'
    assert extract_json(raw) == {"a": 1, "b": "текст"}


def test_extract_json_finds_block_wrapped_in_markdown_fence():
    raw = '```json\n{"a": 1}\n```'
    assert extract_json(raw) == {"a": 1}


def test_extract_json_raises_on_response_without_json():
    with pytest.raises(ValueError, match="Не удалось найти JSON"):
        extract_json("непонятно что, без единой фигурной скобки")
