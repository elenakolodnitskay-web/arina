from db.crypto import decrypt_text, encrypt_text


def test_encrypt_decrypt_roundtrip():
    plaintext = "встреча с клиентом в 15:00"
    token = encrypt_text(plaintext)

    assert token != plaintext
    assert decrypt_text(token) == plaintext


def test_encrypt_is_not_deterministic():
    plaintext = "повторяющийся текст"
    assert encrypt_text(plaintext) != encrypt_text(plaintext)
