from roaring_kittens.telegram.handlers.onboarding import (
    generate_invite_code, looks_like_invite, looks_like_tinkoff_token,
)


def test_invite_code_format_roundtrip():
    code = generate_invite_code()
    assert len(code) == 20                            # INV- + 16 hex (2^64)
    assert looks_like_invite(code) is True
    assert looks_like_invite(code.lower()) is True    # регистр не важен
    assert looks_like_invite("INV-ABC123") is False   # старый короткий формат — нет
    assert looks_like_invite("HELLO") is False
    assert looks_like_invite("INV-" + "Z" * 16) is False  # не hex


def test_token_shape():
    assert looks_like_tinkoff_token("t.AbCdEf123456789012345") is True
    assert looks_like_tinkoff_token("привет") is False
    assert looks_like_tinkoff_token("t.short") is False
