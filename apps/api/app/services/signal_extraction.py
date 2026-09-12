import re
from urllib.parse import urlsplit

from app.schemas import CanonicalActionSignal, CaseContext, CaseSignals


CLAUSE_SPLIT = re.compile(r"[.!?;\n]+")
NEGATION_PATTERN = re.compile(
    r"\b(?:jangan|tidak\s+pernah|tak\s+pernah|dilarang|hindari|waspadai|"
    r"jaga\s+kerahasiaan|bukan|tanpa)\b",
    re.I,
)
REQUEST_PATTERN = re.compile(
    r"\b(?:minta|meminta|diminta|memohon|mengarahkan|kirim(?:kan)?|beri(?:kan)?|memberikan|bagikan|share|masukkan|input|isi|"
    r"sebutkan|masuk(?:kan)?|install|instal|unduh|download|buka|jalankan|"
    r"transfer|bayar|setor|klik|scan|hubungi)\b",
    re.I,
)
SECRET_PATTERNS = {
    "OTP": re.compile(r"\b(?:otp|one[ -]?time password|kode verifikasi)\b", re.I),
    "PIN": re.compile(r"\bpin\b", re.I),
    "PASSWORD": re.compile(r"\b(?:password|kata sandi)\b", re.I),
    "CVV": re.compile(r"\b(?:cvv|cvc)\b", re.I),
    "RECOVERY_CODE": re.compile(r"\b(?:recovery code|kode pemulihan)\b", re.I),
    "SEED_PHRASE": re.compile(r"\b(?:seed phrase|frasa pemulihan)\b", re.I),
    "PRIVATE_KEY": re.compile(r"\bprivate key\b", re.I),
}
GOVERNMENT_PATTERN = re.compile(
    r"\b(?:pemerintah|kementerian|kemensos|kemenkeu|komdigi|djp|pajak|bpjs|"
    r"dukcapil|ojk|iasc|polri|polisi|pemprov|pemda|bansos|subsidi|blt|"
    r"pejabat|petugas|dinas|layanan publik|kejaksaan|kejari|kejati|tilang|etilang|e-tilang)\b",
    re.I,
)
AUTHORITY_PATTERN = re.compile(
    r"\b(?:petugas|pejabat|bank|pemerintah|kementerian|polisi|atasan|customer service|cs|"
    r"whatsapp|wingstop|kejaksaan|kejari|kejati|resmi)\b",
    re.I,
)
THREAT_PATTERN = re.compile(
    r"\b(?:diblokir|blokir|ditangkap|pidana|denda|hukuman|ditutup|dibekukan|"
    r"hangus|kehilangan|tunggakan|pelanggaran|sanksi|diperberat|permanen)\b",
    re.I,
)
URGENCY_PATTERN = re.compile(
    r"\b(?:sekarang|segera|hari ini|malam ini|terakhir|darurat|dalam \d+ (?:menit|jam)|"
    r"sebelum terlambat|batas waktu)\b",
    re.I,
)


def extract_case_signals(
    case: CaseContext,
) -> CaseSignals:
    text = "\n".join(
        value
        for value in (
            case.safe_text,
            case.summary,
            " ".join(case.entities),
            " ".join(claim.text for claim in case.seed_claims),
            case.question,
        )
        if value
    )
    clauses = [item.strip() for item in CLAUSE_SPLIT.split(text) if item.strip()]

    requested_secrets = sorted(
        secret
        for secret, pattern in SECRET_PATTERNS.items()
        if any(_positive_request(clause, pattern) for clause in clauses)
    )
    secret_request = bool(requested_secrets)
    executable = any(
        _positive_request(clause, re.compile(r"\b(?:apk|\.apk|exe|executable|aplikasi)\b", re.I))
        for clause in clauses
    )
    remote_access = any(
        _positive_request(clause, re.compile(r"\b(?:remote access|remote control|akses jarak jauh|anydesk|teamviewer)\b", re.I))
        for clause in clauses
    )
    screen_share = any(
        _positive_request(clause, re.compile(r"\b(?:screen sharing|share screen|bagikan layar|berbagi layar)\b", re.I))
        for clause in clauses
    )
    payment = any(_positive_payment_request(clause) for clause in clauses)
    safe_account = bool(re.search(r"\b(?:rekening|akun) aman\b", text, re.I)) and payment
    government = bool(GOVERNMENT_PATTERN.search(text))
    authority = bool(AUTHORITY_PATTERN.search(text)) or case.possible_impersonation
    threat = bool(THREAT_PATTERN.search(text))
    urgency = bool(URGENCY_PATTERN.search(text))
    personal_destination = bool(
        re.search(r"\b(?:rekening|wallet|dompet digital) (?:pribadi|personal)\b|\ba\.?n\.?\s+[A-Z]", text, re.I)
    )

    user_action_state = _user_action_state(text)
    requested_actions: list[str] = []
    if secret_request:
        requested_actions.append("SHARE_SECRET")
    if executable:
        requested_actions.append("INSTALL_OR_RUN_EXECUTABLE")
    if remote_access:
        requested_actions.append("GRANT_REMOTE_ACCESS")
    if screen_share:
        requested_actions.append("SHARE_SCREEN")
    if payment:
        requested_actions.append("MAKE_PAYMENT")
    if case.urls or re.search(r"\b(?:https?://|www\.|klik (?:link|tautan))", text, re.I):
        requested_actions.append("OPEN_LINK")

    attack_patterns: list[str] = []
    interaction_risk = bool(requested_actions) or case.possible_impersonation
    if case.possible_impersonation or (authority and interaction_risk):
        attack_patterns.append("authority_impersonation")
    if secret_request:
        attack_patterns.append("credential_theft")
    if executable:
        attack_patterns.append("malicious_attachment")
    if remote_access or screen_share:
        attack_patterns.append("remote_access")
    if payment:
        attack_patterns.append("payment_diversion")
    if urgency and interaction_risk:
        attack_patterns.append("urgency")
    if threat and interaction_risk:
        attack_patterns.append("fear")
    if _suspicious_link_domain(text, case.urls):
        attack_patterns.append("suspicious_link_domain")
    if re.search(r"\b(?:deepfake|voice clone|tiruan suara|tiruan wajah|ai generatif)\b", text, re.I):
        attack_patterns.append("deepfake_impersonation")

    channels = [
        name
        for name, pattern in (
            ("whatsapp", r"\b(?:whatsapp|wa)\b"),
            ("telegram", r"\btelegram\b"),
            ("sms", r"\bsms\b"),
            ("email", r"\b(?:email|e-mail)\b"),
            ("phone", r"\b(?:telepon|panggilan|call)\b"),
            ("social_media", r"\b(?:instagram|facebook|tiktok|media sosial)\b"),
            ("web", r"\b(?:website|situs|https?://|www\.)"),
        )
        if re.search(pattern, text, re.I)
    ]
    domains = ["general_information_integrity"]
    if government:
        domains.insert(0, "government_public_service")
    if attack_patterns or case.possible_impersonation:
        domains.append("impersonation_phishing_ato")

    notes: list[str] = []
    negated_secret_types = sorted(
        secret
        for secret, pattern in SECRET_PATTERNS.items()
        if any(NEGATION_PATTERN.search(clause) and pattern.search(clause) for clause in clauses)
    )
    if negated_secret_types:
        notes.append("Negated/educational secret mention was not treated as a request.")
    if not text.strip():
        notes.append("No usable text signal; retrieval must use safe fallback rules.")

    action_signals: list[CanonicalActionSignal] = []
    if secret_request:
        action_signals.append(
            _action_signal("SHARE_SECRET", ",".join(requested_secrets), "REQUEST", 0.9, case)
        )
    if executable:
        action_signals.append(
            _action_signal("INSTALL_OR_RUN", "EXECUTABLE", "REQUEST", 0.86, case)
        )
    if remote_access:
        action_signals.append(
            _action_signal("GRANT_REMOTE_ACCESS", "DEVICE_CONTROL", "REQUEST", 0.88, case)
        )
    if screen_share:
        action_signals.append(
            _action_signal("SHARE_SCREEN", "SCREEN_CONTENT", "REQUEST", 0.88, case)
        )
    if payment:
        action_signals.append(
            _action_signal("MAKE_PAYMENT", "MONEY", "REQUEST", 0.82, case)
        )
    for secret in negated_secret_types:
        action_signals.append(
            _action_signal("SHARE_SECRET", secret, "NEGATED_WARNING", 0.92, case)
        )
    observed_action = {
        "LINK_CLICKED": ("OPEN_LINK", "LINK"),
        "CREDENTIAL_ENTERED": ("ENTER_CREDENTIAL", "CREDENTIAL"),
        "OTP_SHARED": ("SHARE_SECRET", "OTP"),
        "APK_INSTALLED": ("INSTALL_OR_RUN", "APK"),
        "REMOTE_ACCESS_GRANTED": ("GRANT_REMOTE_ACCESS", "DEVICE_CONTROL"),
        "PAYMENT_SENT": ("MAKE_PAYMENT", "MONEY"),
        "ACCOUNT_TAKEOVER_SUSPECTED": ("LOSE_ACCOUNT_CONTROL", "ACCOUNT"),
    }.get(user_action_state)
    if observed_action:
        action_signals.append(
            _action_signal(*observed_action, "OBSERVED_ACTION", 0.88, case)
        )

    return CaseSignals(
        domains=list(dict.fromkeys(domains)),
        attack_patterns=list(dict.fromkeys(attack_patterns)),
        channels=channels,
        requested_actions=requested_actions,
        requested_secrets=requested_secrets,
        user_action_state=user_action_state,
        government_context=government,
        secret_request_detected=secret_request,
        suspicious_executable_received=executable,
        remote_access_requested=remote_access,
        screen_share_requested=screen_share,
        payment_requested=payment,
        safe_account_transfer_requested=safe_account,
        authority=authority,
        threat=threat,
        urgency=urgency,
        sensitive_action_requested=bool(requested_actions),
        synthetic_media_possible="deepfake_impersonation" in attack_patterns,
        information_integrity_context=True,
        source_url_present=bool(case.source_url),
        source_provenance_missing=(case.input_type == "TEXT" and not case.source_url),
        quote_or_attribution_present=bool(
            re.search(
                r"[\"“”‘’]|\b(?:menurut|ujar|kata|dikutip|mengatakan|menyebutkan)\b",
                text,
                re.I,
            )
        ),
        temporal_claim_present=bool(
            re.search(
                r"\b(?:hari ini|kemarin|besok|sekarang|tahun lalu|minggu ini|bulan ini|"
                r"20\d{2}|\d{1,2}[/-]\d{1,2}[/-]\d{2,4})\b",
                text,
                re.I,
            )
        ),
        numeric_claim_present=bool(
            re.search(r"(?:\b\d+(?:[.,]\d+)?\s*%|\bRp\s*[\d.,]+|\b\d{2,}\b)", text, re.I)
        ),
        payment_destination_type="PERSONAL" if personal_destination else "UNKNOWN",
        beneficiary_status="UNVERIFIED" if personal_destination else "UNKNOWN",
        reputation_result="NOT_CHECKED",
        action_signals=action_signals,
        extraction_notes=notes,
    )


def _positive_request(clause: str, object_pattern: re.Pattern[str]) -> bool:
    if not object_pattern.search(clause) or not REQUEST_PATTERN.search(clause):
        return False
    return not NEGATION_PATTERN.search(clause)


def _positive_payment_request(clause: str) -> bool:
    if NEGATION_PATTERN.search(clause):
        return False
    if re.search(r"\b(?:saya|aku|kami) (?:sudah|telah)\b", clause, re.I):
        return False
    return bool(
        re.search(
            r"\b(?:transfer(?:lah)?|bayar(?:lah)?|setor(?:kan)?|kirim(?:kan)? uang|"
            r"lakukan pembayaran|rekening tujuan|biaya administrasi|biaya pencairan)\b",
            clause,
            re.I,
        )
    )


def _user_action_state(text: str) -> str:
    patterns = (
        ("ACCOUNT_TAKEOVER_SUSPECTED", r"\b(?:akun saya diambil|kehilangan akses akun|akun dibajak)\b"),
        ("PAYMENT_SENT", r"\b(?:sudah|telah) (?:transfer|bayar|mengirim uang)\b"),
        ("REMOTE_ACCESS_GRANTED", r"\b(?:sudah|telah) (?:memberi|memberikan) (?:remote access|akses jarak jauh)\b"),
        ("APK_INSTALLED", r"\b(?:sudah|telah) (?:install|instal|menginstal)\b"),
        ("OTP_SHARED", r"\b(?:sudah|telah) (?:kirim|memberi|memberikan|bagikan) (?:kode )?otp\b"),
        ("CREDENTIAL_ENTERED", r"\b(?:sudah|telah) (?:memasukkan|input|mengisi) (?:password|kata sandi|pin|credential)\b"),
        ("LINK_CLICKED", r"\b(?:sudah|telah) (?:klik|membuka) (?:link|tautan)\b"),
    )
    for state, pattern in patterns:
        if re.search(pattern, text, re.I):
            return state
    return "NO_ACTION"


def _suspicious_link_domain(text: str, urls: list[str]) -> bool:
    if not urls:
        return False
    folded = text.casefold()
    expected_domains: list[str] = []
    if re.search(r"\b(?:whatsapp|wa)\b", folded):
        expected_domains.extend(["whatsapp.com", "whatsapp.net"])
    if "wingstop" in folded:
        expected_domains.extend(["wingstop.co.id", "wingstop.id", "wingstop.com"])
    if re.search(r"\b(?:kejaksaan|kejari|kejati|tilang|etilang|e-tilang)\b", folded):
        expected_domains.extend(["kejaksaan.go.id", "etilang.kejaksaan.go.id"])

    for url in urls:
        host = _hostname(url)
        if not host:
            continue
        if _looks_like_typosquat(host):
            return True
        if re.search(r"\b(?:kejaksaan|kejari|kejati|tilang|etilang|e-tilang)\b", folded) and not host.endswith(".go.id"):
            return True
        if expected_domains and not any(_is_domain(host, domain) for domain in expected_domains):
            return True
    return False


def _hostname(url: str) -> str:
    try:
        return (urlsplit(url).hostname or "").casefold().rstrip(".")
    except ValueError:
        return ""


def _is_domain(host: str, domain: str) -> bool:
    return host == domain or host.endswith("." + domain)


def _looks_like_typosquat(host: str) -> bool:
    compact = host.replace("-", "").replace(".", "")
    return bool(
        "whastapp" in compact
        or "whatapp" in compact
        or "kejaksaaangoh" in compact
        or "kejaksaan-goh" in host
    )


def _action_signal(
    action: str,
    object_name: str,
    polarity: str,
    confidence: float,
    case: CaseContext,
) -> CanonicalActionSignal:
    return CanonicalActionSignal(
        actor="external_party",
        action=action,
        object=object_name,
        target="user",
        polarity=polarity,
        modality_source="TEXT" if case.input_type == "TEXT" else "FUSED_TEXT",
        extraction_confidence=confidence,
    )
