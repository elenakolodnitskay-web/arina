import os

import pytest

from llm.classify import classify_message
from tests.calibration.dataset import CALIBRATION_SET

pytestmark = pytest.mark.skipif(
    not os.environ.get("RUN_CALIBRATION"),
    reason="Обращается к настоящей LLM — запускать явно (RUN_CALIBRATION=1 pytest tests/calibration), не в обычном прогоне",
)


@pytest.mark.asyncio
async def test_calibration_accuracy():
    correct = 0
    lines = []

    for case in CALIBRATION_SET:
        result = await classify_message(case["text"])
        is_correct = result.context == case["expected"]
        correct += int(is_correct)
        mark = "OK" if is_correct else "MISS"
        lines.append(
            f"[{mark}] ожидалось={case['expected'].value} получено={result.context.value} "
            f"(увер.={result.confidence:.2f}) — {case['text']}"
        )

    accuracy = correct / len(CALIBRATION_SET)
    report = "\n".join(lines) + f"\n\nТочность: {accuracy:.0%} ({correct}/{len(CALIBRATION_SET)})"
    print("\n" + report)

    # Порог обсуждается по факту первых прогонов (см. Фазу 3 в Plan.md) — 0.7 как
    # временная нижняя граница, не финальное решение.
    assert accuracy >= 0.7, report
