import ipaddress
import re
from urllib.parse import urlsplit, urlunsplit

from app.schemas import (
    CaseContext,
    PageContext,
    SenderContext,
    TextContentType,
    VisionClaim,
    VisionOutput,
)
from app.services.privacy import normalize_text, redact_pii


URL_PATTERN = re.compile(r"(?i)\b(?:https?://|www\.)[^\s<>{}\[\]\"']+")
TRAILING_URL_PUNCTUATION = ".,;:!?)]}"


class InvalidTextInputError(ValueError):
    pass


def build_text_case(
    text: str,
    question: str,
    source_url: str | None,
    sender_context: SenderContext,
    max_urls: int,
    page_context: PageContext | None = None,
) -> tuple[CaseContext, list[str]]:
    normalized = normalize_text(text)
    if len(normalized) < 10:
        raise InvalidTextInputError("Teks minimal 10 karakter setelah dinormalisasi.")

    sanitized_text, embedded_urls = sanitize_urls_in_text(normalized, max_urls=max_urls)
    if _is_url_only_text(normalized):
        if not embedded_urls:
            raise InvalidTextInputError("Teks hanya berisi URL yang tidak aman atau tidak valid.")
        sanitized_text = "URL untuk diperiksa: " + ", ".join(embedded_urls[:max_urls])
    safe_text, text_pii = redact_pii(sanitized_text)
    safe_question, question_pii = _safe_free_text(question, limit=500)
    safe_page_context, page_context_pii = _safe_page_context(page_context)
    safe_source_url = sanitize_source_url(source_url)
    urls = _unique([*(embedded_urls[:max_urls]), *([safe_source_url] if safe_source_url else [])])[
        :max_urls
    ]
    content_type = infer_text_content_type(safe_text, sender_context)

    return (
        CaseContext(
            input_type="TEXT",
            content_type=content_type,
            safe_text=safe_text,
            question=safe_question,
            page_context=safe_page_context,
            source_url=safe_source_url,
            sender_context=sender_context,
            platform=_infer_platform(safe_text, sender_context),
            summary=_text_summary(safe_text),
            entities=[],
            possible_impersonation=_possible_text_impersonation(safe_text),
            urls=urls,
            seed_claims=[],
            extraction_confidence=1.0,
            extraction_method="LOCAL_TEXT",
            source_character_count=len(normalized),
            language=_infer_language(safe_text),
        ),
        _unique([*text_pii, *question_pii, *page_context_pii]),
    )


def build_image_case(
    vision: VisionOutput,
    redacted_ocr_text: str,
    question: str,
    source_character_count: int,
    max_urls: int,
) -> tuple[CaseContext, list[str]]:
    safe_question, question_pii = _safe_free_text(question, limit=500)
    safe_summary, summary_pii = _safe_free_text(vision.visual_summary, limit=1200)
    safe_entities: list[str] = []
    pii_types: list[str] = [*question_pii, *summary_pii]
    for entity in vision.visual_entities[:40]:
        safe_entity, entity_pii = _safe_free_text(entity, limit=160)
        if safe_entity:
            safe_entities.append(safe_entity)
        pii_types.extend(entity_pii)

    safe_claims: list[VisionClaim] = []
    for claim in vision.claims[:12]:
        safe_claim, claim_pii = _safe_free_text(claim.text, limit=700)
        pii_types.extend(claim_pii)
        if safe_claim:
            safe_claims.append(VisionClaim(text=safe_claim, verifiable=claim.verifiable))

    safe_ocr, ocr_urls = sanitize_urls_in_text(redacted_ocr_text, max_urls=max_urls)
    visible_urls = [sanitize_source_url(value, reject_invalid=False) for value in vision.visible_urls]
    urls = _unique([*ocr_urls, *(value for value in visible_urls if value)])[:max_urls]
    return (
        CaseContext(
            input_type="IMAGE",
            content_type=vision.content_type[:80] or "unknown_image",
            safe_text=safe_ocr,
            question=safe_question,
            page_context=None,
            source_url=None,
            sender_context="NOT_APPLICABLE",
            platform=(vision.platform or "")[:80] or None,
            summary=safe_summary,
            entities=_unique(safe_entities),
            possible_impersonation=vision.possible_impersonation,
            urls=urls,
            seed_claims=safe_claims,
            extraction_confidence=vision.vision_confidence,
            extraction_method="OCR_VISION",
            source_character_count=max(0, source_character_count),
            language=_infer_language("\n".join((safe_ocr, safe_summary))),
        ),
        _unique(pii_types),
    )


def sanitize_source_url(value: str | None, reject_invalid: bool = True) -> str | None:
    raw = (value or "").strip().rstrip(TRAILING_URL_PUNCTUATION)
    if not raw:
        return None
    candidate = f"https://{raw}" if raw.casefold().startswith("www.") else raw
    try:
        parsed = urlsplit(candidate)
        host = (parsed.hostname or "").casefold().rstrip(".")
        if parsed.scheme.casefold() not in {"http", "https"} or not host:
            raise ValueError
        if parsed.username or parsed.password or not _public_host(host):
            raise ValueError
        try:
            port = parsed.port
        except ValueError as exc:
            raise ValueError from exc
        netloc = host if port is None else f"{host}:{port}"
        path = re.sub(r"/{2,}", "/", parsed.path or "/")
        # Query strings and fragments often carry tracking IDs, email addresses,
        # session tokens, or secrets; they are intentionally not sent downstream.
        return urlunsplit((parsed.scheme.casefold(), netloc, path, "", ""))
    except (TypeError, ValueError):
        if reject_invalid:
            raise InvalidTextInputError(
                "source_url harus berupa URL HTTP(S) publik yang valid."
            )
        return None


def sanitize_urls_in_text(value: str, max_urls: int) -> tuple[str, list[str]]:
    urls: list[str] = []

    def replace(match: re.Match[str]) -> str:
        raw = match.group(0)
        trailing = raw[len(raw.rstrip(TRAILING_URL_PUNCTUATION)) :]
        clean = sanitize_source_url(raw, reject_invalid=False)
        if clean and clean not in urls and len(urls) < max_urls:
            urls.append(clean)
        return (clean or "[URL TIDAK AMAN DIHAPUS]") + trailing

    return URL_PATTERN.sub(replace, value or ""), urls


def infer_text_content_type(text: str, sender_context: SenderContext) -> TextContentType:
    lowered = text.casefold()
    if lowered.startswith("url untuk diperiksa:"):
        return "URL_ONLY"
    if sender_context == "UNKNOWN_NUMBER":
        return "UNKNOWN_SENDER_MESSAGE"
    if sender_context == "FORWARDED" or re.search(r"\bditeruskan berkali-kali\b", lowered):
        return "FORWARDED_MESSAGE"
    if sender_context == "SOCIAL_MEDIA" or re.search(
        r"\b(?:caption|thread|tweet|postingan|unggahan|instagram|facebook|tiktok)\b",
        lowered,
    ):
        return "SOCIAL_MEDIA_CAPTION"
    if re.search(r"\b(?:satire|parodi|humor|lelucon)\b", lowered):
        return "SATIRE"
    if re.search(r"\b(?:menurut saya|menurutku|saya rasa|saya pikir|opini|pendapat)\b", lowered):
        return "OPINION"
    if re.search(r"\b(?:promo|diskon|beli sekarang|gratis ongkir|harga spesial|iklan)\b", lowered):
        return "ADVERTISEMENT"
    if sender_context == "KNOWN_CONTACT":
        return "PERSONAL_MESSAGE"
    if len(text) >= 1200 and re.search(
        r"\b(?:dilaporkan|menurut|narasumber|wartawan|redaksi|diterbitkan)\b",
        lowered,
    ):
        return "NEWS_ARTICLE"
    if len(text) >= 450:
        return "NEWS_EXCERPT"
    if text.rstrip().endswith("?"):
        return "QUESTION"
    return "CLAIM_ONLY" if text.strip() else "UNKNOWN"


def _safe_free_text(value: str, limit: int) -> tuple[str, list[str]]:
    normalized = normalize_text((value or "")[:limit])
    sanitized, _ = sanitize_urls_in_text(normalized, max_urls=10)
    return redact_pii(sanitized)


def _safe_page_context(page_context: PageContext | None) -> tuple[PageContext | None, list[str]]:
    if page_context is None:
        return None, []
    pii_types: list[str] = []
    values: dict[str, str | None] = {}
    for key, limit in (("title", 300), ("before", 500), ("after", 500)):
        value = getattr(page_context, key)
        if value is None:
            values[key] = None
            continue
        safe_value, value_pii = _safe_free_text(value, limit=limit)
        values[key] = safe_value or None
        pii_types.extend(value_pii)
    if not any(values.values()):
        return None, pii_types
    return PageContext(**values), pii_types


def _is_url_only_text(value: str) -> bool:
    compact = normalize_text(value)
    if not compact:
        return False
    without_urls = URL_PATTERN.sub("", compact)
    without_punctuation = without_urls.strip(" \t\r\n.,;:!?()[]{}<>\"'")
    return not without_punctuation


def _text_summary(text: str) -> str:
    compact = re.sub(r"\s+", " ", text).strip()
    return compact[:600]


def _infer_platform(text: str, sender_context: SenderContext) -> str | None:
    for platform, pattern in (
        ("whatsapp", r"\b(?:whatsapp|wa)\b"),
        ("telegram", r"\btelegram\b"),
        ("sms", r"\bsms\b"),
        ("email", r"\b(?:email|e-mail)\b"),
        ("instagram", r"\binstagram\b"),
        ("facebook", r"\bfacebook\b"),
        ("tiktok", r"\btiktok\b"),
    ):
        if re.search(pattern, text, re.I):
            return platform
    if sender_context == "SOCIAL_MEDIA":
        return "social_media"
    return None


def _possible_text_impersonation(text: str) -> bool:
    claimed_identity = re.search(
        r"\b(?:kami dari|saya dari|mengatasnamakan|petugas|customer service|cs|"
        r"bank|kementerian|pemerintah|polisi|pajak|bpjs|whatsapp|wingstop|"
        r"kejaksaan|kejari|kejati|resmi)\b",
        text,
        re.I,
    )
    requested_action = re.search(
        r"\b(?:klik|kirim|bagikan|transfer|bayar|instal|install|masukkan|hubungi)\b",
        text,
        re.I,
    )
    return bool(claimed_identity and requested_action)


def _infer_language(text: str) -> str:
    tokens = set(re.findall(r"[a-zA-Z]+", text.casefold()))
    markers = {"yang", "dan", "ini", "untuk", "dengan", "dari", "tidak", "apakah"}
    return "id" if len(tokens & markers) >= 2 else "und"


def _public_host(host: str) -> bool:
    if host in {"localhost", "localhost.localdomain"} or host.endswith(".local"):
        return False
    try:
        address = ipaddress.ip_address(host)
        return not (
            address.is_private
            or address.is_loopback
            or address.is_link_local
            or address.is_reserved
            or address.is_multicast
        )
    except ValueError:
        return "." in host and not host.startswith(".")


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))
