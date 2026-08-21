import io

from pypdf import PdfReader

# Извлечение текста из входящего PDF (Фаза 30) — только текстовый слой (pypdf), без
# OCR: для отсканированных PDF без текстового слоя вернёт пустую строку — вызывающий
# код должен объяснить пользователю и предложить прислать вместо этого фото (тогда
# сработает llm/vision.py). Не сеть, не LLM — синхронная функция.
MAX_EXTRACTED_CHARS = 6000


def extract_text_from_pdf(pdf_bytes: bytes) -> str:
    reader = PdfReader(io.BytesIO(pdf_bytes))
    pages_text = [page.extract_text() or "" for page in reader.pages]
    text = "\n\n".join(p for p in pages_text if p.strip())
    return text[:MAX_EXTRACTED_CHARS]
