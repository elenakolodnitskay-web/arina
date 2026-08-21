from core import document_files, pdf_extract


def test_extract_text_from_pdf_returns_readable_content():
    pdf_bytes = document_files.build_pdf("Счёт на оплату", "Уважаемый клиент,\n\nОплатите счёт до пятницы.")

    text = pdf_extract.extract_text_from_pdf(pdf_bytes)

    assert "Счёт на оплату" in text
    assert "Оплатите счёт до пятницы" in text


def test_extract_text_from_pdf_truncates_to_max_chars(monkeypatch):
    monkeypatch.setattr(pdf_extract, "MAX_EXTRACTED_CHARS", 20)
    pdf_bytes = document_files.build_pdf("Заголовок", "Очень длинный текст, который точно длиннее лимита.")

    text = pdf_extract.extract_text_from_pdf(pdf_bytes)

    assert len(text) <= 20
