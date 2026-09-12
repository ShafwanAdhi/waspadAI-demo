from app.services.privacy import normalize_text, redact_pii


def test_redacts_common_sensitive_fields() -> None:
    text = "Hubungi 081234567890, OTP 123456, email saya user@example.com"
    redacted, kinds = redact_pii(text)
    assert "081234567890" not in redacted
    assert "123456" not in redacted
    assert "user@example.com" not in redacted
    assert {"PHONE_NUMBER", "OTP", "EMAIL"}.issubset(kinds)


def test_normalization_deduplicates_lines() -> None:
    assert normalize_text(" Info  baru \nInfo baru\nBaris dua ") == "Info baru\nBaris dua"

