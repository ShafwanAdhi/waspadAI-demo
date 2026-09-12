import hashlib
import re
import unicodedata


PII_PATTERNS: list[tuple[str, re.Pattern[str], str]] = [
    ("EMAIL", re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I), "[EMAIL DIHAPUS]"),
    ("NIK", re.compile(r"(?<!\d)\d{16}(?!\d)"), "[NIK DIHAPUS]"),
    (
        "PHONE_NUMBER",
        re.compile(r"(?<!\d)(?:\+62|62|0)8[1-9](?:[\s.-]?\d){7,11}(?!\d)"),
        "[NOMOR TELEPON DIHAPUS]",
    ),
    (
        "OTP",
        re.compile(r"(?i)(?:(?:kode\s*)?otp|verification\s*code|kode\s*verifikasi)\D{0,12}\b\d{4,8}\b"),
        "[KODE OTP DIHAPUS]",
    ),
    (
        "CARD_NUMBER",
        re.compile(r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)"),
        "[NOMOR KARTU/REKENING DIHAPUS]",
    ),
]


def normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value or "")
    lines: list[str] = []
    seen: set[str] = set()
    for raw_line in normalized.splitlines():
        line = re.sub(r"\s+", " ", raw_line).strip()
        key = line.casefold()
        if line and key not in seen:
            lines.append(line)
            seen.add(key)
    return "\n".join(lines)


def redact_pii(value: str) -> tuple[str, list[str]]:
    redacted = value or ""
    found: list[str] = []
    for pii_type, pattern, replacement in PII_PATTERNS:
        if pattern.search(redacted):
            found.append(pii_type)
            redacted = pattern.sub(replacement, redacted)
    return redacted, found


def safe_content_hash(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()[:16]

