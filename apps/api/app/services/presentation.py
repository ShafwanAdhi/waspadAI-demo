from app.schemas import Evidence, NarrativePresentation, RecommendedAction, RiskLevel, VerdictLabel


VERDICT_LABELS = {
    "SUPPORTED": "didukung bukti",
    "REFUTED": "terbantahkan",
    "MISLEADING": "menyesatkan",
    "PARTLY_TRUE": "sebagian benar",
    "OUTDATED": "sudah tidak berlaku",
    "UNVERIFIED": "belum terverifikasi",
    "SATIRE": "satire",
    "OPINION": "opini",
}

RISK_LABELS = {
    "CRITICAL": "sangat tinggi",
    "HIGH": "tinggi",
    "MEDIUM": "sedang",
    "LOW": "rendah",
    "UNKNOWN": "belum diketahui",
}

def build_narrative_presentation(
    *,
    verdict: VerdictLabel,
    risk_level: RiskLevel,
    headline: str,
    why: list[str],
    evidence: list[Evidence],
    evidence_sufficiency_label: str,
    recommended_actions: list[RecommendedAction],
    uncertainty: str,
    requires_human_review: bool,
) -> NarrativePresentation:
    """Create a user-facing narrative locally from the canonical response."""
    paragraphs = [
        _opening(headline, verdict, risk_level),
        _risk_warning(risk_level),
        _reasoning(why),
        _next_step(recommended_actions),
        _uncertainty(uncertainty, requires_human_review),
    ]
    cleaned = [item for item in (_clean_text(paragraph) for paragraph in paragraphs) if item]
    return NarrativePresentation(
        text="\n\n".join(cleaned),
        summary=_clean_text(_summary(headline, verdict, risk_level)),
        paragraphs=cleaned,
    )


def _summary(headline: str, verdict_label: VerdictLabel, risk_level: RiskLevel) -> str:
    verdict = VERDICT_LABELS[verdict_label]
    risk = _risk_phrase(risk_level)
    if risk:
        return f"{headline}. Statusnya {verdict}, dengan {risk}."
    return f"{headline} Statusnya {verdict}."


def _opening(headline: str, verdict_label: VerdictLabel, risk_level: RiskLevel) -> str:
    verdict = VERDICT_LABELS[verdict_label]
    risk = _risk_phrase(risk_level)
    if risk:
        return f"Hasil pemeriksaan: {headline}. Secara keseluruhan, informasi ini {verdict}, dengan {risk}."
    return f"Hasil pemeriksaan: {headline} Secara keseluruhan, informasi ini {verdict}."


def _risk_warning(risk_level: RiskLevel) -> str:
    if risk_level == "CRITICAL":
        return (
            "Peringatan penting: kasus ini memiliki risiko sangat tinggi. "
            "Jangan kirim uang, OTP, PIN, password, data pribadi, atau pasang aplikasi dari instruksi tersebut."
        )
    if risk_level == "HIGH":
        return (
            "Peringatan: ada risiko tinggi pada kasus ini. "
            "Tunda tindakan sensitif sampai informasi dikonfirmasi lewat kanal resmi."
        )
    return ""


def _reasoning(why: list[str]) -> str:
    if not why:
        return ""
    reasons = _sentence_join([_public_text(item) for item in why[:3]])
    return f"Alasan utamanya: {reasons}"


def _next_step(actions: list[RecommendedAction]) -> str:
    if not actions:
        return ""
    first = actions[0]
    return f"Langkah paling aman sekarang: {first.title}. {first.detail}"


def _uncertainty(uncertainty: str, requires_human_review: bool) -> str:
    safe_uncertainty = _public_text(uncertainty)
    if requires_human_review:
        return (
            f"Karena kasus ini masih perlu review manusia, jangan jadikan hasil ini satu-satunya dasar keputusan. "
            f"{safe_uncertainty}"
        )
    return safe_uncertainty


def _risk_phrase(risk_level: RiskLevel) -> str:
    if risk_level == "CRITICAL":
        return "risiko sangat tinggi"
    if risk_level == "HIGH":
        return "risiko tinggi"
    return ""


def _public_text(value: str) -> str:
    replacements = {
        "Evidence": "Bukti",
        "evidence": "bukti",
        "verdict": "putusan",
        "claim": "klaim",
        "review manual": "review manusia",
    }
    output = value
    for source, replacement in replacements.items():
        output = output.replace(source, replacement)
    return output


def _sentence_join(items: list[str]) -> str:
    sentences = [_ensure_sentence(item.strip()) for item in items if item.strip()]
    return " ".join(sentences)


def _ensure_sentence(value: str) -> str:
    if value.endswith((".", "!", "?")):
        return value
    return f"{value}."


def _clean_text(value: str) -> str:
    return " ".join(value.split())
