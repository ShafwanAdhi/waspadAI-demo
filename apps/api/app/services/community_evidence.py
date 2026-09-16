import math
import re
from datetime import datetime, timezone

from app.schemas import CommunityEvidenceRecord, Evidence, PlannedClaim


TOKEN_PATTERN = re.compile(r"[a-zA-Z0-9]+")
STOPWORDS = {
    "yang",
    "dan",
    "atau",
    "di",
    "ke",
    "dari",
    "ini",
    "itu",
    "untuk",
    "dengan",
    "apakah",
    "adalah",
    "pada",
    "melalui",
    "klaim",
    "berita",
}


def community_records_to_evidence(
    records: list[CommunityEvidenceRecord],
    claims: list[PlannedClaim],
) -> list[Evidence]:
    """Convert request-scoped community posts into bounded verifier evidence."""
    now = datetime.now(timezone.utc).isoformat()
    evidence: list[Evidence] = []
    seen_hashes: set[str] = set()

    for record in records:
        if record.content_hash in seen_hashes:
            continue
        seen_hashes.add(record.content_hash)
        source = record.sources[0]
        record_text = _record_text(record)
        record_tokens = _tokens(record_text)
        for claim in claims:
            if not claim.verifiable:
                continue
            relevance = _relevance(claim.text, record_tokens, record_text)
            if relevance < 0.24:
                continue
            evidence.append(
                Evidence(
                    id=f"community_{record.content_hash[:16]}_{claim.id}"[:64],
                    claim_id=claim.id,
                    source_type="community_verified",
                    publisher="Komunitas WaspadAI",
                    title=record.title,
                    url=source.url,
                    published_at=record.published_at,
                    retrieved_at=now,
                    excerpt=_excerpt(record),
                    relevance=relevance,
                    authority=0.78,
                    recency=_recency(record.verified_at or record.published_at),
                    stance=record.stance,
                    verification_status="VERIFIED",
                )
            )
    return _limit_community_evidence(evidence)


def community_evidence_trace(records: list[CommunityEvidenceRecord], evidence: list[Evidence]) -> dict:
    return {
        "received_records": len(records),
        "accepted_records": len({item.id.split("_")[1] for item in evidence}),
        "accepted_evidence": len(evidence),
        "max_records": 5,
        "source": "REQUEST_PAYLOAD",
        "raw_text_stored": False,
    }


def _record_text(record: CommunityEvidenceRecord) -> str:
    return " ".join(
        item
        for item in [
            record.title,
            record.verified_claim,
            record.evidence_summary,
            record.redacted_text or "",
            " ".join(source.title for source in record.sources),
            " ".join(source.publisher or "" for source in record.sources),
        ]
        if item
    )


def _excerpt(record: CommunityEvidenceRecord) -> str:
    parts = [
        f"Klaim komunitas terverifikasi: {record.verified_claim}",
        f"Ringkasan bukti: {record.evidence_summary}",
    ]
    if record.redacted_text:
        parts.append(f"Konteks teredaksi: {record.redacted_text[:600]}")
    return "\n".join(parts)[:1200]


def _relevance(claim_text: str, record_tokens: set[str], record_text: str) -> float:
    claim_tokens = _tokens(claim_text)
    if not claim_tokens:
        return 0.0
    overlap = len(claim_tokens & record_tokens) / max(1, len(claim_tokens))
    phrase_bonus = 0.18 if claim_text.casefold() in record_text.casefold() else 0.0
    return round(min(0.92, overlap * 1.25 + phrase_bonus), 3)


def _tokens(text: str) -> set[str]:
    return {
        token.casefold()
        for token in TOKEN_PATTERN.findall(text)
        if len(token) > 2 and token.casefold() not in STOPWORDS
    }


def _recency(value: str | None) -> float:
    if not value:
        return 0.65
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        age_days = max(0, (datetime.now(timezone.utc) - parsed).days)
        return round(max(0.25, math.exp(-age_days / 1460)), 3)
    except ValueError:
        return 0.5


def _limit_community_evidence(evidence: list[Evidence]) -> list[Evidence]:
    ranked = sorted(
        evidence,
        key=lambda item: (item.relevance, item.recency),
        reverse=True,
    )
    per_claim: dict[str, int] = {}
    output: list[Evidence] = []
    for item in ranked:
        if per_claim.get(item.claim_id, 0) >= 2:
            continue
        output.append(item)
        per_claim[item.claim_id] = per_claim.get(item.claim_id, 0) + 1
        if len(output) >= 5:
            break
    return output
