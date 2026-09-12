import asyncio

from app.config import Settings
from app.schemas import (
    CaseContext,
    PlannedClaim,
    PlannerOutput,
    RetrievalPlan,
    RulebookResult,
    RulebookTrace,
    VisionClaim,
)
from app.services.groq_service import ModelOutputError
from app.services.input_adapters import build_text_case
import app.services.pipeline as pipeline_module
from app.services.pipeline import FactCheckPipeline
from app.services.planner_guardrails import (
    compact_case_payload,
    deterministic_fallback_plan,
    validate_and_repair_plan,
)
from app.services.rag import RulebookRAG
from app.services.signal_extraction import extract_case_signals


def _settings(**overrides):
    return Settings(
        _env_file=None,
        groq_api_key="test-key",
        **overrides,
    )


def _bank_case():
    case, _ = build_text_case(
        text=(
            "Saya dari customer service bank. Kirimkan kode OTP sekarang "
            "agar rekening tidak diblokir."
        ),
        question="Apakah pesan ini benar dan aman?",
        source_url=None,
        sender_context="UNKNOWN_NUMBER",
        max_urls=10,
    )
    return case


def test_guardrail_drops_ungrounded_claim_and_forces_high_risk_escalation():
    settings = _settings()
    case = _bank_case()
    signals = extract_case_signals(case)
    rulebook = asyncio.run(RulebookRAG(settings).retrieve(case.safe_text, signals))
    proposed = deterministic_fallback_plan(case, signals, rulebook, settings)
    proposed.classification = "FACTUAL_CLAIM"
    proposed.complexity = "MEDIUM"
    proposed.claims = [
        proposed.claims[0].model_copy(
            update={"id": "invented", "text": "Pesan ini sudah terverifikasi aman."}
        )
    ]
    proposed.interim_risk = "LOW"

    result = validate_and_repair_plan(case, signals, rulebook, proposed, settings)

    assert result.plan.classification == "SCAM_MESSAGE"
    assert result.plan.complexity == "HIGH"
    assert result.plan.interim_risk == "HIGH"
    assert result.dropped_claims == 1
    assert all("terverifikasi aman" not in claim.text for claim in result.plan.claims)
    assert any("OTP" in claim.text for claim in result.plan.claims)
    assert "SECRET_REQUEST" in result.escalation_reasons
    assert result.should_escalate is True
    assert "DO_NOT_SHARE_SECRET" in result.plan.interim_actions


def test_compact_case_payload_enforces_character_budget():
    case, _ = build_text_case(
        text=("Klaim bantuan Rp5 juta dibagikan hari ini. " * 700),
        question="Apa klaim materialnya?",
        source_url=None,
        sender_context="FORWARDED",
        max_urls=10,
    )

    payload = compact_case_payload(case, max_chars=2000)

    assert len(payload["text_excerpts"]) <= 2000
    assert "safe_text" not in payload
    assert payload["summary"]


def test_guardrail_drops_raw_ocr_artifact_when_vision_claim_is_confident():
    settings = _settings()
    case = CaseContext(
        input_type="IMAGE",
        content_type="news_screenshot",
        safe_text="o i : aa RADAR BOGOR .) Insignesiasadi Ta Rona Perdana Fi ASEAN Gup 2026 pe",
        question='Apakah informasi "Indonesia menjadi tuan rumah FIFA ASEAN Cup 2026" benar?',
        source_url=None,
        sender_context="NOT_APPLICABLE",
        platform="Radar Bogor",
        summary="Teks besar menyatakan Indonesia menjadi tuan rumah pertama FIFA ASEAN Cup 2026.",
        entities=["Radar Bogor", "Indonesia", "FIFA ASEAN Cup 2026"],
        possible_impersonation=False,
        urls=[],
        seed_claims=[
            VisionClaim(
                text="Indonesia menjadi tuan rumah pertama FIFA ASEAN Cup 2026",
                verifiable=True,
            )
        ],
        extraction_confidence=0.95,
        extraction_method="OCR_VISION",
        source_character_count=78,
        language="id",
    )
    signals = extract_case_signals(case)
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
    proposed = PlannerOutput(
        classification="FACTUAL_CLAIM",
        domains=["general_information_integrity"],
        attack_patterns=[],
        claims=[
            PlannedClaim(
                id="claim_1",
                text="Indonesia menjadi tuan rumah pertama FIFA ASEAN Cup 2026",
                claim_type="FACTUAL_CLAIM",
                verifiable=True,
            ),
            PlannedClaim(
                id="claim_2",
                text=case.safe_text,
                claim_type="news_screenshot",
                verifiable=True,
            ),
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
        web_queries=["Indonesia host FIFA ASEAN Cup 2026 official announcement"],
    )

    result = validate_and_repair_plan(case, signals, rulebook, proposed, settings)

    assert [claim.text for claim in result.plan.claims] == [
        "Indonesia menjadi tuan rumah pertama FIFA ASEAN Cup 2026"
    ]
    assert result.dropped_claims == 1
    assert any(issue.startswith("OCR_ARTIFACT_CLAIM_DROPPED") for issue in result.issues)


class FailingPlannerGroq:
    provider_name = "failing-search"
    configured = True

    async def plan(self, case, signals, rulebook, escalation=False):
        raise ModelOutputError("invalid planner schema")

    async def review_plan(self, case, signals, rulebook, draft, validation_issues):
        raise ModelOutputError("invalid review schema")

    async def search(self, planner):
        raise ModelOutputError("search provider unavailable")

    async def verify_and_generate(self, planner, evidence, sufficiency, rulebook):
        raise ModelOutputError("invalid verifier schema")


def test_pipeline_retains_safe_plan_when_first_pass_and_review_fail():
    pipeline = FactCheckPipeline(_settings(planner_review_enabled=True))
    failing = FailingPlannerGroq()
    pipeline.groq = failing
    pipeline.web_search = failing

    response = asyncio.run(
        pipeline.verify_text(
            text="Petugas bank meminta saya mengirim OTP sekarang agar akun tidak diblokir.",
            question="Apakah aman?",
            source_url=None,
            sender_context="UNKNOWN_NUMBER",
        )
    )

    assert response.status == "COMPLETED"
    assert response.verdict == "MISLEADING"
    assert response.risk_level == "CRITICAL"
    assert response.headline == "Pesan patut diduga penipuan atau phishing"
    assert response.recommended_actions[0].code == "DO_NOT_SHARE_SECRET"
    planning = next(stage for stage in response.pipeline if stage.key == "planning")
    retrieval = next(stage for stage in response.pipeline if stage.key == "retrieval")
    verification = next(stage for stage in response.pipeline if stage.key == "verification")
    assert planning.status == "FALLBACK"
    assert retrieval.status == "FALLBACK"
    assert verification.status == "FALLBACK"
    assert "review 120B gagal" in planning.detail
    trace = pipeline.debug_traces.get(response.trace_id)
    first_pass = next(stage for stage in trace["stages"] if stage["key"] == "investigation_planner")
    review = next(stage for stage in trace["stages"] if stage["key"] == "planner_review")
    web_search = next(stage for stage in trace["stages"] if stage["key"] == "web_search")
    verifier = next(stage for stage in trace["stages"] if stage["key"] == "verifier")
    assert first_pass["status"] == "FALLBACK"
    assert review["status"] == "FALLBACK"
    assert web_search["status"] == "FALLBACK"
    assert verifier["status"] == "FALLBACK"
    assert first_pass["output"]["fallback_reason"]["raw_message_stored"] is False


class OversizedReviewGroq:
    def __init__(self):
        self.review_calls = 0

    async def plan(self, case, signals, rulebook, escalation=False):
        raise ModelOutputError("planner unavailable")

    async def review_plan(self, case, signals, rulebook, draft, validation_issues):
        self.review_calls += 1
        raise AssertionError("review_plan should be skipped by the token budget gate")

    async def search(self, planner):
        return []

    async def verify_and_generate(self, planner, evidence, sufficiency, rulebook):
        raise ModelOutputError("verifier unavailable")


def test_pipeline_skips_120b_review_when_token_budget_is_too_large(monkeypatch):
    pipeline = FactCheckPipeline(_settings(planner_review_enabled=True))
    fake_groq = OversizedReviewGroq()
    pipeline.groq = fake_groq
    monkeypatch.setattr(
        pipeline_module,
        "review_token_budget",
        lambda *_, **__: {
            "estimated_tokens": 9001,
            "limit": 6000,
            "max_completion_tokens": 700,
            "payload_chars": 1,
            "schema_chars": 1,
            "should_call": False,
        },
    )

    response = asyncio.run(
        pipeline.verify_text(
            text="Petugas bank meminta saya mengirim OTP sekarang agar akun tidak diblokir.",
            question="Apakah aman?",
            source_url=None,
            sender_context="UNKNOWN_NUMBER",
        )
    )

    assert response.status == "COMPLETED"
    assert fake_groq.review_calls == 0
    trace = pipeline.debug_traces.get(response.trace_id)
    review = next(stage for stage in trace["stages"] if stage["key"] == "planner_review")
    assert review["status"] == "SKIPPED"
    assert "melewati budget" in review["output"]["reason"]


def test_pipeline_keeps_120b_review_disabled_by_default(monkeypatch):
    pipeline = FactCheckPipeline(_settings())
    fake_groq = OversizedReviewGroq()
    pipeline.groq = fake_groq
    monkeypatch.setattr(
        pipeline_module,
        "review_token_budget",
        lambda *_, **__: {
            "estimated_tokens": 1000,
            "limit": 6000,
            "max_completion_tokens": 700,
            "payload_chars": 1,
            "schema_chars": 1,
            "should_call": True,
        },
    )

    response = asyncio.run(
        pipeline.verify_text(
            text="Petugas bank meminta saya mengirim OTP sekarang agar akun tidak diblokir.",
            question="Apakah aman?",
            source_url=None,
            sender_context="UNKNOWN_NUMBER",
        )
    )

    assert response.status == "COMPLETED"
    assert fake_groq.review_calls == 0
    trace = pipeline.debug_traces.get(response.trace_id)
    review = next(stage for stage in trace["stages"] if stage["key"] == "planner_review")
    assert review["status"] == "SKIPPED"
    assert review["input"]["review_enabled"] is False
    assert "nonaktif" in review["output"]["reason"]
