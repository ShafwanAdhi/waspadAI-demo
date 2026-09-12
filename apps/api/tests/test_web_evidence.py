import asyncio
import json

import httpx

from app.config import Settings
from app.schemas import PlannedClaim
from app.schemas import PlannerOutput, RetrievalPlan
from app.services.web_search import (
    TAVILY_SEARCH_URL,
    TavilyWebSearchService,
    WebSearchNotConfiguredError,
    _search_requests,
    _source_profile,
    _to_evidence,
)


def test_web_evidence_is_mapped_to_known_claim_and_deduped_per_claim():
    claim = PlannedClaim(
        id="claim_1",
        text="Pemerintah memberikan bantuan sosial",
        claim_type="FACTUAL_CLAIM",
        verifiable=True,
    )
    items = [
        {
            "url": "https://example.go.id/bansos",
            "title": "Informasi bantuan sosial pemerintah",
            "content": "Informasi resmi bantuan sosial.",
            "score": 0.9,
        },
        {
            "url": "https://example.go.id/bansos",
            "title": "Daftar domain resmi",
            "content": "Domain resmi untuk layanan tersebut.",
            "score": 0.8,
        },
    ]

    evidence = _to_evidence(items, claim, excerpt_chars=800)

    assert len(evidence) == 1
    assert evidence[0].claim_id == "claim_1"
    assert evidence[0].stance == "UNKNOWN"


def test_authority_profile_requires_real_go_id_boundary():
    assert _source_profile("https://pajak.go.id/info") == ("government", 1.0)
    assert _source_profile("https://evilgo.id/info") == ("web", 0.68)
    assert _source_profile("https://inside.fifa.com/news") == ("official_sports_body", 0.98)
    assert _source_profile("https://www.spacex.com/launches/mission") == ("official_company", 0.96)
    assert _source_profile("https://www.apnews.com/article/example") == ("news_wire", 0.86)


def test_search_requests_fan_out_primary_claim_to_official_sources():
    claims = [
        PlannedClaim(
            id="claim_1",
            text="Indonesia menjadi tuan rumah pertama FIFA ASEAN Cup 2026",
            claim_type="FACTUAL_CLAIM",
            verifiable=True,
        ),
        PlannedClaim(
            id="claim_2",
            text="o i aa RADAR BOGOR Insignesiasadi Ta Rona Perdana Fi ASEAN Gup 2026 pe",
            claim_type="news_screenshot",
            verifiable=True,
        ),
    ]

    requests = _search_requests(
        claims,
        [
            "Indonesia host FIFA ASEAN Cup 2026 official announcement",
            "FIFA ASEAN Cup 2026 host country",
            "Indonesia first host FIFA ASEAN Cup 2026 news",
        ],
        limit=3,
    )

    assert {claim.id for claim, _ in requests} == {"claim_1"}
    assert any("site:fifa.com" in query or "site:inside.fifa.com" in query for _, query in requests)


def _planner() -> PlannerOutput:
    return PlannerOutput(
        classification="FACTUAL_CLAIM",
        domains=["general_information_integrity"],
        attack_patterns=[],
        claims=[
            PlannedClaim(
                id="claim_1",
                text="Terjadi upacara penurunan jabatan presiden",
                claim_type="FACTUAL_CLAIM",
                verifiable=True,
            )
        ],
        requires_fresh_data=True,
        complexity="MEDIUM",
        potential_financial_risk=False,
        potential_identity_impersonation=False,
        contains_url=False,
        critical_checks=[],
        required_evidence=[],
        preferred_sources=[],
        interim_risk="UNKNOWN",
        interim_actions=[],
        applied_rule_ids=[],
        retrieval_plan=RetrievalPlan(
            web_search=True,
            domain_rag=[],
            community_rag=False,
            factcheck_rag=True,
        ),
        web_queries=["upacara penurunan jabatan presiden sumber resmi"],
    )


def test_tavily_search_bounds_request_and_maps_raw_results_to_evidence():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        assert request.url == TAVILY_SEARCH_URL
        assert request.headers["authorization"] == "Bearer tvly-test"
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "title": "Keterangan resmi Istana",
                        "url": "https://presidenri.go.id/siaran-pers/contoh",
                        "content": "Keterangan resmi mengenai agenda kenegaraan.",
                        "score": 0.93,
                        "published_date": "2026-09-11",
                    },
                    {
                        "title": "Private URL",
                        "url": "http://127.0.0.1/internal",
                        "content": "Tidak boleh lolos.",
                        "score": 1.0,
                    },
                ]
            },
        )

    settings = Settings(
        _env_file=None,
        tavily_api_key="tvly-test",
        web_search_max_queries=1,
        web_search_results_per_query=2,
        web_search_excerpt_chars=200,
    )
    service = TavilyWebSearchService(settings, transport=httpx.MockTransport(handler))
    evidence = asyncio.run(service.search(_planner()))

    assert captured["max_results"] == 2
    assert captured["include_answer"] is False
    assert captured["include_raw_content"] is False
    assert len(captured["query"]) <= 400
    assert len(evidence) == 1
    assert evidence[0].claim_id == "claim_1"
    assert evidence[0].source_type == "government"
    assert evidence[0].stance == "UNKNOWN"


def test_tavily_search_fails_locally_when_key_is_missing():
    service = TavilyWebSearchService(Settings(_env_file=None, tavily_api_key=""))

    try:
        asyncio.run(service.search(_planner()))
    except WebSearchNotConfiguredError as exc:
        assert exc.status_code is None
    else:
        raise AssertionError("Missing Tavily key should not make a provider request")
