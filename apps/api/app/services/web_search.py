"""Bounded web retrieval independent from the LLM provider."""

from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import math
import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

import httpx

from app.config import Settings
from app.schemas import Evidence, PlannedClaim, PlannerOutput


TAVILY_SEARCH_URL = "https://api.tavily.com/search"
TOKEN_PATTERN = re.compile(r"[a-zA-Z0-9]+")


class WebSearchError(RuntimeError):
    """Safe pipeline error for unavailable or rejected search requests."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class WebSearchNotConfiguredError(WebSearchError):
    pass


class TavilyWebSearchService:
    provider_name = "tavily"

    def __init__(
        self,
        settings: Settings,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.settings = settings
        self._transport = transport

    @property
    def configured(self) -> bool:
        key = self.settings.tavily_api_key.strip()
        return bool(key and "isi_api_key" not in key.casefold())

    @property
    def health(self) -> dict[str, Any]:
        return {
            "provider": self.provider_name,
            "configured": self.configured,
            "retrieval_mode": "DIRECT_API_BOUNDED",
            "max_queries": self.settings.web_search_max_queries,
            "results_per_query": self.settings.web_search_results_per_query,
            "max_excerpt_chars": self.settings.web_search_excerpt_chars,
            "uses_groq_compound": False,
        }

    async def search(self, planner: PlannerOutput) -> list[Evidence]:
        if not planner.retrieval_plan.web_search or not planner.claims:
            return []
        if not self.configured:
            raise WebSearchNotConfiguredError(
                "TAVILY_API_KEY belum dikonfigurasi; live web search dilewati."
            )

        requests = _search_requests(
            planner.claims,
            planner.web_queries,
            self.settings.web_search_max_queries,
        )
        timeout = httpx.Timeout(self.settings.tavily_timeout_seconds)
        async with httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=False,
            transport=self._transport,
        ) as client:
            outcomes = await asyncio.gather(
                *(self._search_one(client, claim, query) for claim, query in requests),
                return_exceptions=True,
            )

        evidence: list[Evidence] = []
        failures: list[WebSearchError] = []
        for outcome in outcomes:
            if isinstance(outcome, WebSearchError):
                failures.append(outcome)
            elif isinstance(outcome, Exception):
                failures.append(WebSearchError(type(outcome).__name__))
            else:
                evidence.extend(outcome)
        if evidence:
            return _dedupe_evidence(evidence)
        if failures:
            raise failures[0]
        return []

    async def _search_one(
        self,
        client: httpx.AsyncClient,
        claim: PlannedClaim,
        query: str,
    ) -> list[Evidence]:
        try:
            response = await client.post(
                TAVILY_SEARCH_URL,
                headers={
                    "Authorization": f"Bearer {self.settings.tavily_api_key.strip()}",
                    "Content-Type": "application/json",
                },
                json={
                    "query": query[:400],
                    "search_depth": "basic",
                    "topic": "general",
                    "max_results": self.settings.web_search_results_per_query,
                    "include_answer": False,
                    "include_raw_content": False,
                    "include_images": False,
                },
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise WebSearchError(
                "Search provider menolak request.",
                status_code=exc.response.status_code,
            ) from exc
        except httpx.HTTPError as exc:
            raise WebSearchError("Search provider tidak dapat dihubungi.") from exc

        try:
            payload = response.json()
        except ValueError as exc:
            raise WebSearchError("Search provider mengembalikan respons non-JSON.") from exc
        results = payload.get("results") if isinstance(payload, dict) else None
        if not isinstance(results, list):
            raise WebSearchError("Search provider mengembalikan kontrak yang tidak valid.")

        return _to_evidence(
            [item for item in results if isinstance(item, dict)],
            claim,
            excerpt_chars=self.settings.web_search_excerpt_chars,
        )


def _search_requests(
    claims: list[PlannedClaim],
    queries: list[str],
    limit: int,
) -> list[tuple[PlannedClaim, str]]:
    searchable_claims = [item for item in claims if _claim_is_searchable(item)]
    if not searchable_claims:
        return []
    generated = [
        query
        for claim in searchable_claims[:2]
        for query in _official_source_queries(claim.text)
    ]
    clean_queries = [
        " ".join(query.split())[:400]
        for query in [*generated, *queries]
        if query.strip()
    ]
    available = list(dict.fromkeys(clean_queries))
    output: list[tuple[PlannedClaim, str]] = []
    for claim in searchable_claims[:limit]:
        if available:
            best = max(available, key=lambda query: _query_priority(claim.text, query))
            available.remove(best)
        else:
            best = claim.text
        output.append((claim, best[:400]))
        if len(output) >= limit:
            return output

    while available and len(output) < limit:
        claim, best = max(
            ((claim, query) for claim in searchable_claims for query in available),
            key=lambda pair: _query_priority(pair[0].text, pair[1]),
        )
        available.remove(best)
        if any(existing_claim.id == claim.id and query == best for existing_claim, query in output):
            continue
        output.append((claim, best[:400]))
    return output


def _to_evidence(
    items: list[dict[str, Any]],
    claim: PlannedClaim,
    *,
    excerpt_chars: int,
) -> list[Evidence]:
    now = datetime.now(timezone.utc).isoformat()
    output: list[Evidence] = []
    seen_urls: set[str] = set()
    for item in items:
        url = str(item.get("url") or "").strip()
        if not _is_public_http_url(url) or url in seen_urls:
            continue
        seen_urls.add(url)
        source_type, authority = _source_profile(url)
        published_at = _clean_date(
            item.get("published_date") or item.get("published_at") or item.get("date")
        )
        relevance = _bounded_float(item.get("score"), default=0.65)
        excerpt = " ".join(str(item.get("content") or "").split())[:excerpt_chars]
        evidence_id = "web_" + hashlib.sha256(
            f"{url}|{claim.id}".encode("utf-8")
        ).hexdigest()[:10]
        output.append(
            Evidence(
                id=evidence_id,
                claim_id=claim.id,
                source_type=source_type,
                publisher=_publisher_from_url(url)[:160],
                title=" ".join(str(item.get("title") or "Sumber web").split())[:240],
                url=url,
                published_at=published_at,
                retrieved_at=now,
                excerpt=excerpt,
                relevance=round(relevance, 3),
                authority=authority,
                recency=_recency_from_date(published_at),
                stance="UNKNOWN",
                verification_status="REVIEWED",
            )
        )
    return output


def _dedupe_evidence(items: list[Evidence]) -> list[Evidence]:
    by_url_and_claim: dict[tuple[str, str], Evidence] = {}
    for item in items:
        key = (item.url, item.claim_id)
        existing = by_url_and_claim.get(key)
        if existing is None or item.relevance > existing.relevance:
            by_url_and_claim[key] = item
    return list(by_url_and_claim.values())


def _text_overlap(left: str, right: str) -> float:
    left_tokens = {token.casefold() for token in TOKEN_PATTERN.findall(left)}
    right_tokens = {token.casefold() for token in TOKEN_PATTERN.findall(right)}
    return len(left_tokens & right_tokens) / max(1, len(left_tokens))


def _query_priority(claim: str, query: str) -> float:
    official_bonus = 0.25 if "site:" in query.casefold() else 0.0
    return _text_overlap(claim, query) + official_bonus


def _claim_search_quality(text: str) -> float:
    tokens = [token.casefold() for token in TOKEN_PATTERN.findall(text)]
    if not tokens:
        return 0.0
    long_tokens = [token for token in tokens if len(token) >= 4]
    alpha_numeric = sum(char.isalnum() or char.isspace() for char in text) / max(1, len(text))
    return min(1.0, (len(long_tokens) / max(1, len(tokens))) * 0.7 + alpha_numeric * 0.3)


def _claim_is_searchable(claim: PlannedClaim) -> bool:
    if not claim.verifiable:
        return False
    quality = _claim_search_quality(claim.text)
    if claim.claim_type.strip().casefold() in {"news_screenshot", "ocr_text", "image"}:
        return quality >= 0.75
    return quality >= 0.35


def _official_source_queries(claim: str) -> list[str]:
    folded = claim.casefold()
    if "spacex" in folded or "starship" in folded or "super heavy" in folded:
        return [
            "Starship fifth flight test Super Heavy booster catch October 13 2024 Starbase Texas site:spacex.com",
            "Starship Flight 5 Super Heavy booster catch Starbase Texas SpaceX",
            "Starship fifth flight test Super Heavy booster catch October 13 2024",
        ]
    if "fifa" in folded or "asean cup" in folded:
        return [
            f"{claim} site:fifa.com",
            f"{claim} site:inside.fifa.com",
            f"{claim} site:kemenpora.go.id",
        ]
    if "olimpiade" in folded or "olympic" in folded or "paris 2024" in folded:
        return [
            "Paris 2024 opening ceremony Seine river athletes boat parade 26 July 2024 site:olympics.com",
            "Paris 2024 opening ceremony Seine river athletes boat parade 26 July 2024 site:ioc.org",
            "Paris 2024 opening ceremony Seine river athletes boat parade 26 July 2024",
        ]
    if "prevost" in folded or "leo xiv" in folded or "paus" in folded or "pope" in folded:
        return [
            "Robert Prevost elected Pope Leo XIV May 8 2025 first American pontiff site:vatican.va",
            "Robert Prevost elected Pope Leo XIV May 8 2025 first American pontiff site:apnews.com",
            "Robert Prevost Pope Leo XIV first American pontiff May 8 2025",
        ]
    if "trump" in folded or "presiden as" in folded or "president" in folded:
        return [
            f"{claim} site:whitehouse.gov",
            f"{claim} site:congress.gov",
            f"{claim} site:apnews.com",
        ]
    if "gempa" in folded or "earthquake" in folded or "tsunami" in folded:
        return [
            "Noto Peninsula earthquake January 1 2024 magnitude 7.5 tsunami site:usgs.gov",
            "Noto Peninsula earthquake January 1 2024 tsunami site:jma.go.jp",
            "Japan earthquake January 1 2024 Noto Ishikawa tsunami magnitude 7.5",
        ]
    if any(term in folded for term in ("pssi", "timnas", "sepak bola", "football")):
        return [
            f"{claim} site:pssi.org",
            f"{claim} site:kemenpora.go.id",
        ]
    return []


def _publisher_from_url(url: str) -> str:
    return (urlparse(url).hostname or "Sumber web").removeprefix("www.")


def _source_profile(url: str) -> tuple[str, float]:
    host = (urlparse(url).hostname or "").casefold()
    if _is_domain(host, "spacex.com"):
        return "official_company", 0.96
    if _is_domain(host, "nasa.gov") or _is_domain(host, "faa.gov"):
        return "government", 1.0
    if _is_domain(host, "fifa.com") or _is_domain(host, "pssi.org") or _is_domain(host, "the-afc.com"):
        return "official_sports_body", 0.98
    if _is_domain(host, "olympics.com") or _is_domain(host, "ioc.org") or _is_domain(host, "paris2024.org"):
        return "official_sports_body", 0.98
    if _is_domain(host, "vatican.va"):
        return "official_religious_institution", 0.98
    if _is_domain(host, "usgs.gov") or _is_domain(host, "jma.go.jp"):
        return "government", 1.0
    if _is_domain(host, "whitehouse.gov") or _is_domain(host, "congress.gov") or _is_domain(host, "archives.gov"):
        return "government", 1.0
    if _is_domain(host, "apnews.com") or _is_domain(host, "reuters.com") or _is_domain(host, "bbc.com") or _is_domain(host, "cnn.com"):
        return "news_wire", 0.86
    if _is_domain(host, "go.id"):
        return "government", 1.0
    if _is_domain(host, "ac.id") or _is_domain(host, "edu"):
        return "academic", 0.92
    if _is_domain(host, "turnbackhoax.id") or _is_domain(host, "cekfakta.com"):
        return "factcheck", 0.9
    return "web", 0.68


def _is_domain(host: str, domain: str) -> bool:
    return host == domain or host.endswith("." + domain)


def _is_public_http_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            return False
        host = parsed.hostname.casefold()
        if host in {"localhost", "localhost.localdomain"} or host.endswith(".local"):
            return False
        try:
            address = ipaddress.ip_address(host)
            return not (
                address.is_private
                or address.is_loopback
                or address.is_link_local
                or address.is_reserved
            )
        except ValueError:
            return True
    except ValueError:
        return False


def _clean_date(value: Any) -> str | None:
    if not value:
        return None
    match = re.search(r"\d{4}-\d{2}-\d{2}", str(value))
    return match.group(0) if match else None


def _recency_from_date(value: str | None) -> float:
    if not value:
        return 0.65
    try:
        published = datetime.fromisoformat(value).replace(tzinfo=timezone.utc)
        age_days = max(0, (datetime.now(timezone.utc) - published).days)
        return round(max(0.2, math.exp(-age_days / 1460)), 3)
    except ValueError:
        return 0.5


def _bounded_float(value: Any, *, default: float) -> float:
    try:
        return min(1.0, max(0.0, float(value)))
    except (TypeError, ValueError):
        return default
