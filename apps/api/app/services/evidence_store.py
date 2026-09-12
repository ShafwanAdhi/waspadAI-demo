import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path

from app.schemas import Evidence, PlannedClaim


DATA_FILE = Path(__file__).resolve().parent.parent / "data" / "knowledge_base.json"
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
}


class LocalVerifiedEvidenceStore:
    """Small verified evidence corpus, deliberately separate from rulebook RAG."""

    def __init__(self, data_file: Path = DATA_FILE) -> None:
        self.data_file = data_file
        self.documents = json.loads(data_file.read_text(encoding="utf-8"))

    async def retrieve_domain(
        self,
        claims: list[PlannedClaim],
        domains: list[str],
        limit_per_claim: int = 2,
    ) -> list[Evidence]:
        return self._retrieve(claims, domains, community_only=False, limit_per_claim=limit_per_claim)

    async def retrieve_community(
        self,
        claims: list[PlannedClaim],
        limit_per_claim: int = 2,
    ) -> list[Evidence]:
        return self._retrieve(claims, [], community_only=True, limit_per_claim=limit_per_claim)

    def _retrieve(
        self,
        claims: list[PlannedClaim],
        domains: list[str],
        community_only: bool,
        limit_per_claim: int,
    ) -> list[Evidence]:
        normalized_domains = {item.casefold() for item in domains}
        now = datetime.now(timezone.utc).isoformat()
        evidence: list[Evidence] = []

        for claim in claims:
            query_tokens = _tokens(claim.text)
            ranked: list[tuple[float, dict]] = []
            for document in self.documents:
                if document.get("verification_status") != "VERIFIED":
                    continue
                is_community = document.get("source_type") == "community_verified"
                if community_only != is_community:
                    continue
                document_tokens = _tokens(
                    " ".join(
                        [
                            document.get("title", ""),
                            document.get("content", ""),
                            document.get("domain", ""),
                        ]
                    )
                )
                overlap = len(query_tokens & document_tokens) / max(1, len(query_tokens))
                domain_matches = document.get("domain", "").casefold() in normalized_domains
                domain_bonus = 0.2 if domain_matches else 0.0
                score = min(1.0, overlap * 1.6 + domain_bonus)
                min_score = 0.18 if domain_matches else 0.24
                if score >= min_score:
                    ranked.append((score, document))

            ranked.sort(key=lambda item: (item[0], item[1].get("authority_level", 0)), reverse=True)
            for score, document in ranked[:limit_per_claim]:
                evidence.append(
                    Evidence(
                        id=f"local_{document['document_id']}_{claim.id}",
                        claim_id=claim.id,
                        source_type=document["source_type"],
                        publisher=document["publisher"],
                        title=document["title"],
                        url=document["url"],
                        published_at=document.get("published_at"),
                        retrieved_at=now,
                        excerpt=document["content"],
                        relevance=round(score, 3),
                        authority=float(document["authority_level"]),
                        recency=_recency(document.get("published_at")),
                        stance="CONTEXT",
                        verification_status="VERIFIED",
                    )
                )
        return evidence


def _tokens(text: str) -> set[str]:
    return {
        token.casefold()
        for token in TOKEN_PATTERN.findall(text)
        if len(token) > 2 and token.casefold() not in STOPWORDS
    }


def _recency(published_at: str | None) -> float:
    if not published_at:
        return 0.7
    try:
        published = datetime.fromisoformat(published_at).replace(tzinfo=timezone.utc)
        age_days = max(0, (datetime.now(timezone.utc) - published).days)
        return round(max(0.25, math.exp(-age_days / 1460)), 3)
    except ValueError:
        return 0.5
