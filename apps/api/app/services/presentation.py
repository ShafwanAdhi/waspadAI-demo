from urllib.parse import urlparse

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

PUBLIC_EVIDENCE_LABELS = {
    "Bukti kuat - skor kecukupan, bukan probabilitas kebenaran": "Bukti kuat dan relevan",
    "Bukti cukup - skor kecukupan, bukan probabilitas kebenaran": "Bukti cukup untuk mendukung kesimpulan",
    "Bukti cukup": "Bukti cukup untuk mendukung kesimpulan",
    "Bukti risiko cukup": "Bukti risiko cukup untuk memberi peringatan",
    "Bukti belum cukup - verdict dikunci sebagai belum terverifikasi": "Bukti belum cukup untuk memastikan klaim",
    "Bukti belum cukup - putusan dikunci sebagai belum terverifikasi": "Bukti belum cukup untuk memastikan klaim",
    "Bukti belum cukup": "Bukti belum cukup untuk memastikan klaim",
    "Perlu review manual": "Perlu review manusia",
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
        _evidence_context(verdict, evidence, evidence_sufficiency_label),
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


def _evidence_context(
    verdict: VerdictLabel,
    evidence: list[Evidence],
    evidence_sufficiency_label: str,
) -> str:
    public_label = _public_evidence_label(evidence_sufficiency_label)
    if evidence:
        decisive_count = len(
            [
                item
                for item in evidence
                if item.stance in {"SUPPORTS", "REFUTES"} and item.relevance >= 0.55
            ]
        )
        count_label = (
            f"{decisive_count} bukti relevan"
            if decisive_count
            else f"{len(evidence)} konteks bukti"
        )
        sources = _source_summary(evidence)
        stance_note = _stance_note(verdict)
        return (
            f"Sistem membandingkan klaim dengan {count_label}, termasuk {sources}. "
            f"{public_label}.{stance_note}"
        )
    return (
        "Belum ada bukti yang cukup kuat untuk memastikan klaim. "
        f"{public_label}."
    )


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


def _stance_note(verdict: VerdictLabel) -> str:
    if verdict == "UNVERIFIED":
        return " Karena buktinya belum cukup, hasil ini belum boleh dianggap sebagai kesimpulan final."
    if verdict == "REFUTED":
        return " Bukti yang ditemukan bertentangan dengan klaim utama."
    if verdict == "SUPPORTED":
        return " Bukti yang ditemukan mendukung klaim utama."
    if verdict == "MISLEADING":
        return " Bukti menunjukkan ada konteks penting yang hilang atau dipelintir."
    return ""


SOCIAL_DOMAINS = {
    "facebook.com",
    "instagram.com",
    "tiktok.com",
    "threads.net",
    "twitter.com",
    "x.com",
    "youtube.com",
}


def _source_summary(evidence: list[Evidence]) -> str:
    official = _unique_source_names(
        item
        for item in evidence
        if item.authority >= 0.85 or item.source_type.casefold() in {"government", "official", "primary"}
    )
    factcheck = _unique_source_names(
        item for item in evidence if "fact" in item.source_type.casefold()
    )
    social = _unique_source_names(item for item in evidence if _is_social_source(item))
    other = _unique_source_names(
        item
        for item in evidence
        if item.publisher not in {*official, *factcheck, *social}
    )
    parts = []
    if official:
        parts.append(f"sumber resmi/primer seperti {', '.join(official[:2])}")
    if factcheck:
        parts.append(f"sumber cek fakta seperti {', '.join(factcheck[:2])}")
    if other:
        parts.append(f"sumber pendukung seperti {', '.join(other[:2])}")
    if social:
        parts.append(f"konteks media sosial seperti {', '.join(social[:2])}")
    return "; ".join(parts) if parts else "sumber yang ditemukan"


def _unique_source_names(items) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()
    for item in items:
        name = item.publisher.strip() or _hostname(item.url)
        if not name or name in seen:
            continue
        names.append(name)
        seen.add(name)
    return names


def _is_social_source(item: Evidence) -> bool:
    host = _hostname(item.url)
    return any(host == domain or host.endswith(f".{domain}") for domain in SOCIAL_DOMAINS)


def _hostname(url: str) -> str:
    return urlparse(url).netloc.casefold().removeprefix("www.")


def _public_evidence_label(value: str) -> str:
    normalized = _clean_text(_public_text(value))
    return PUBLIC_EVIDENCE_LABELS.get(normalized, normalized.rstrip("."))


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
