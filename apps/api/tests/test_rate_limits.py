import asyncio
from types import SimpleNamespace
import json
from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import app
from app.schemas import (
    Evidence,
    PlannedClaim,
    PlannerOutput,
    RetrievalPlan,
    RulebookResult,
    RulebookTrace,
)
from app.services.groq_service import GroqFactCheckService
from app.services.rate_limits import GroqRateLimitMonitor


def _live_settings() -> Settings:
    return Settings(
        _env_file=None,
        groq_api_key="test-key-not-a-real-credential",
        groq_vision_model="qwen/qwen3.6-27b",
        groq_final_model="qwen/qwen3.6-27b",
    )


def test_monitor_parses_groq_headers_and_merges_duplicate_model_roles() -> None:
    monitor = GroqRateLimitMonitor(_live_settings())
    monitor.observe(
        "qwen/qwen3.6-27b",
        {
            "x-ratelimit-limit-requests": "1000",
            "x-ratelimit-remaining-requests": "998",
            "x-ratelimit-reset-requests": "1h2m3s",
            "x-ratelimit-limit-tokens": "8000",
            "x-ratelimit-remaining-tokens": "7312",
            "x-ratelimit-reset-tokens": "7.66s",
        },
        status_code=200,
    )

    snapshot = monitor.snapshot()
    qwen = next(item for item in snapshot["models"] if item["model"] == "qwen/qwen3.6-27b")
    assert qwen["roles"] == ["Vision understanding", "Verifier & response generator"]
    assert qwen["reference_limits"] == {
        "rpm": 30,
        "rpd": 1000,
        "tpm": 8000,
        "tpd": 200000,
    }
    assert qwen["tokens"]["scope"] == "TPM"
    assert qwen["tokens"]["remaining"] == 7312
    assert 6 <= qwen["tokens"]["reset_in_seconds"] <= 8
    assert qwen["requests"]["scope"] == "RPD"
    assert 3721 <= qwen["requests"]["reset_in_seconds"] <= 3723
    assert snapshot["does_not_make_provider_request"] is True
    assert snapshot["reference_plan"] == "FREE"


def test_developer_reference_uses_published_rpm_tpm_and_marks_unpublished_values() -> None:
    settings = _live_settings().model_copy(
        update={"groq_rate_limit_reference_plan": "developer"}
    )
    snapshot = GroqRateLimitMonitor(settings).snapshot()
    qwen = next(item for item in snapshot["models"] if item["model"] == "qwen/qwen3.6-27b")

    assert snapshot["reference_plan"] == "DEVELOPER"
    assert qwen["reference_limits"] == {
        "rpm": 1000,
        "rpd": None,
        "tpm": 250000,
        "tpd": None,
    }
    assert "groq/compound" not in {item["model"] for item in snapshot["models"]}


def test_monitor_keeps_retry_after_from_429_snapshot() -> None:
    monitor = GroqRateLimitMonitor(_live_settings())
    monitor.observe(
        "openai/gpt-oss-20b",
        {"retry-after": "2.5", "x-ratelimit-remaining-tokens": "0"},
        status_code=429,
    )
    planner = next(
        item for item in monitor.snapshot()["models"]
        if item["model"] == "openai/gpt-oss-20b"
    )
    assert planner["status_code"] == 429
    assert planner["retry_after_seconds"] == 2.5


def test_elapsed_window_hides_stale_remaining_until_next_observation() -> None:
    monitor = GroqRateLimitMonitor(_live_settings())
    monitor.observe(
        "openai/gpt-oss-20b",
        {
            "x-ratelimit-limit-requests": "1000",
            "x-ratelimit-remaining-requests": "997",
            "x-ratelimit-reset-requests": "2h",
            "x-ratelimit-limit-tokens": "8000",
            "x-ratelimit-remaining-tokens": "120",
            "x-ratelimit-reset-tokens": "0s",
        },
        status_code=200,
    )

    planner = next(
        item for item in monitor.snapshot()["models"]
        if item["model"] == "openai/gpt-oss-20b"
    )
    assert planner["tokens"]["window_state"] == "RESET_ELAPSED_AWAITING_OBSERVATION"
    assert planner["tokens"]["remaining"] is None
    assert planner["tokens"]["last_observed_remaining"] == 120
    assert planner["requests"]["window_state"] == "ACTIVE"
    assert planner["requests"]["remaining"] == 997


def test_groq_wrapper_captures_headers_without_extra_provider_call() -> None:
    settings = _live_settings()
    monitor = GroqRateLimitMonitor(settings)
    service = GroqFactCheckService(settings, monitor)
    calls = 0

    class FakeRawResponse:
        headers = {
            "x-ratelimit-limit-requests": "1000",
            "x-ratelimit-remaining-requests": "999",
            "x-ratelimit-reset-requests": "10m",
            "x-ratelimit-limit-tokens": "8000",
            "x-ratelimit-remaining-tokens": "7900",
            "x-ratelimit-reset-tokens": "3s",
        }
        status_code = 200

        async def parse(self):
            return {"ok": True}

    async def create(**_):
        nonlocal calls
        calls += 1
        return FakeRawResponse()

    service.client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(
                with_raw_response=SimpleNamespace(create=create)
            )
        )
    )
    result = asyncio.run(service._completion(model="openai/gpt-oss-20b", messages=[]))

    assert result == {"ok": True}
    assert calls == 1
    planner = next(
        item for item in monitor.snapshot()["models"]
        if item["model"] == "openai/gpt-oss-20b"
    )
    assert planner["tokens"]["remaining"] == 7900


def test_low_sufficiency_does_not_erase_evidence_backed_refutation() -> None:
    settings = _live_settings()
    service = GroqFactCheckService(settings, GroqRateLimitMonitor(settings))
    evidence = [
        Evidence(
            id="web_refute",
            claim_id="claim_1",
            source_type="government",
            publisher="NASA",
            title="Astronauts returned on SpaceX Crew-9",
            url="https://nasa.gov/example",
            published_at="2025-03-18",
            retrieved_at=datetime.now(timezone.utc).isoformat(),
            excerpt="Williams and Wilmore returned to Earth aboard SpaceX Crew-9, while Starliner returned uncrewed.",
            relevance=0.9,
            authority=1.0,
            recency=0.9,
            stance="REFUTES",
            verification_status="REVIEWED",
        )
    ]
    planner = PlannerOutput(
        classification="FACTUAL_CLAIM",
        domains=["general_information_integrity"],
        attack_patterns=[],
        claims=[
            PlannedClaim(
                id="claim_1",
                text="Suni Williams dan Butch Wilmore kembali menggunakan Boeing Starliner",
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
        web_queries=[],
    )
    rulebook = RulebookResult(
        matches=[],
        forced_actions=[],
        trace=RulebookTrace(
            corpus_versions=[],
            retrieval_mode="TEST",
            candidate_count=0,
            selected_count=0,
            forced_rule_ids=[],
            cache_hit=False,
            duration_ms=0,
        ),
    )

    async def completion(**_):
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content=json.dumps(
                            {
                                "claims": [
                                    {
                                        "claim_id": "claim_1",
                                        "verdict": "REFUTED",
                                        "supporting_evidence": [],
                                        "refuting_evidence": ["web_refute"],
                                        "contradiction_level": "HIGH",
                                        "reason": "Evidence NASA membantah wahana kepulangan Starliner.",
                                    }
                                ],
                                "overall_verdict": "MISLEADING",
                                "risk_level": "MEDIUM",
                                "evidence_sufficiency": 0.57,
                                "requires_human_review": False,
                                "headline": "Klaim wahana kepulangan Starliner salah",
                                "what_checked": ["Wahana kepulangan astronaut"],
                                "why": ["Evidence menyatakan mereka kembali dengan SpaceX Crew-9."],
                                "recommended_actions": [
                                    {
                                        "code": "VERIFY_VIA_OFFICIAL_CHANNEL",
                                        "title": "Cek NASA",
                                        "detail": "Bandingkan dengan laporan misi NASA.",
                                    }
                                ],
                                "uncertainty": "Evidence cukup untuk membantah wahana, meski skor coverage konservatif.",
                            }
                        )
                    )
                )
            ]
        )

    service._completion = completion
    decision = asyncio.run(service.verify_and_generate(planner, evidence, 0.57, rulebook))

    assert decision.overall_verdict == "MISLEADING"
    assert decision.claims[0].verdict == "REFUTED"
    assert decision.claims[0].refuting_evidence == ["web_refute"]


def test_rate_limit_endpoint_is_passive_and_available_on_debug_page() -> None:
    with TestClient(app) as client:
        response = client.get("/api/v1/debug/groq-rate-limits")
        page = client.get("/debug")

    assert response.status_code == 200
    body = response.json()
    assert body["does_not_make_provider_request"] is True
    assert body["mode"] == "LIVE"
    assert body["observed_model_count"] == 0
    assert body["reference_plan"] == "FREE"
    assert {item["model"] for item in body["models"]} >= {
        "qwen/qwen3.6-27b",
        "openai/gpt-oss-20b",
    }
    assert "openai/gpt-oss-120b" not in {item["model"] for item in body["models"]}
    assert 'id="rateLimitList"' in page.text
    assert 'id="rateLimitStatus"' in page.text
    assert "Requests per minute" in page.text
    assert "Requests per day" in page.text
    assert "Tokens per minute" in page.text
    assert "Tokens per day" in page.text
    assert 'href="#groqCapacity"' in page.text
    assert page.text.index('id="groqCapacity"') < page.text.index('id="traceDetail"')


def test_rate_limit_monitor_lists_120b_only_when_planner_review_is_enabled() -> None:
    settings = _live_settings().model_copy(update={"planner_review_enabled": True})
    models = {item["model"] for item in GroqRateLimitMonitor(settings).snapshot()["models"]}

    assert "openai/gpt-oss-120b" in models
