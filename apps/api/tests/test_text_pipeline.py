import asyncio
from datetime import datetime, timezone

from app.config import Settings
from app.schemas import (
    CommunityEvidenceRecord,
    Evidence,
    PlannedClaim,
    PlannerOutput,
    RecommendedAction,
    RetrievalPlan,
    VerificationDecision,
)
from app.services.pipeline import FactCheckPipeline


class FakeGroqService:
    provider_name = "fake-search"
    configured = True

    def __init__(self):
        self.plan_calls = 0
        self.verify_calls = 0

    async def plan(self, case, signals, rulebook, escalation=False):
        self.plan_calls += 1
        assert case.input_type == "TEXT"
        assert case.safe_text
        assert "general_information_integrity" in signals.domains
        assert rulebook.matches
        return PlannerOutput(
            classification="FACTUAL_CLAIM",
            domains=signals.domains,
            attack_patterns=signals.attack_patterns,
            claims=[
                PlannedClaim(
                    id="claim_1",
                    text="Pemerintah memberikan bantuan Rp5 juta",
                    claim_type="FACTUAL",
                    verifiable=True,
                )
            ],
            requires_fresh_data=True,
            complexity="SIMPLE",
            potential_financial_risk=False,
            potential_identity_impersonation=False,
            contains_url=False,
            critical_checks=["official_program_check"],
            required_evidence=["current official program information"],
            preferred_sources=["responsible agency"],
            interim_risk="UNKNOWN",
            interim_actions=rulebook.forced_actions,
            applied_rule_ids=[item.rule_id for item in rulebook.matches[:4]],
            retrieval_plan=RetrievalPlan(
                web_search=True,
                domain_rag=[],
                community_rag=True,
                factcheck_rag=True,
            ),
            web_queries=["bantuan pemerintah Rp5 juta"],
        )

    async def search(self, planner):
        return [
            Evidence(
                id="web_1",
                claim_id="claim_1",
                source_type="government",
                publisher="Instansi Resmi",
                title="Informasi program resmi",
                url="https://example.go.id/program",
                published_at="2026-08-20",
                retrieved_at=datetime.now(timezone.utc).isoformat(),
                excerpt="Daftar program resmi yang berlaku.",
                relevance=0.91,
                authority=1.0,
                recency=0.98,
                stance="REFUTES",
                verification_status="VERIFIED",
            )
        ]

    async def verify_and_generate(self, planner, evidence, sufficiency, rulebook):
        self.verify_calls += 1
        return VerificationDecision(
            claims=[],
            overall_verdict="UNVERIFIED" if sufficiency < 0.58 else "REFUTED",
            risk_level="LOW",
            evidence_sufficiency=sufficiency,
            requires_human_review=sufficiency < 0.58,
            headline="Pemeriksaan teks selesai",
            what_checked=[planner.claims[0].text],
            why=["Evidence dipetakan ke klaim atomik."],
            recommended_actions=[
                RecommendedAction(
                    code="VERIFY_VIA_OFFICIAL_CHANNEL",
                    title="Periksa sumber resmi",
                    detail="Bandingkan dengan kanal instansi terkait.",
                )
            ],
            uncertainty="Origin teks tempel tidak dapat diautentikasi tanpa URL sumber.",
        )


def test_live_text_uses_the_shared_rulebook_evidence_and_verifier_pipeline():
    pipeline = FactCheckPipeline(Settings(groq_api_key="test-key"))
    fake = FakeGroqService()
    pipeline.groq = fake
    pipeline.web_search = fake

    response = asyncio.run(
        pipeline.verify_text(
            text="Pemerintah disebut memberikan bantuan Rp5 juta pada tahun 2026.",
            question="Apakah kabar ini benar?",
            source_url=None,
            sender_context="FORWARDED",
        )
    )

    assert response.mode == "LIVE"
    assert response.input_summary.input_type == "TEXT"
    assert response.input_summary.content_type == "FORWARDED_MESSAGE"
    assert response.dimensions.source_authenticity == "UNVERIFIED"
    assert response.dimensions.content_authenticity == "NOT_APPLICABLE"
    assert [stage.key for stage in response.pipeline] == [
        "extraction",
        "rulebook",
        "planning",
        "retrieval",
        "verification",
    ]
    assert response.rulebook.selected_count > 0
    assert response.evidence


def test_narrative_output_mode_does_not_add_groq_calls():
    pipeline = FactCheckPipeline(Settings(groq_api_key="test-key"))
    fake = FakeGroqService()
    pipeline.groq = fake
    pipeline.web_search = fake

    response = asyncio.run(
        pipeline.verify_text(
            text="Pemerintah disebut memberikan bantuan Rp5 juta pada tahun 2026.",
            question="Apakah kabar ini benar?",
            source_url=None,
            sender_context="FORWARDED",
            output_mode="BOTH",
        )
    )

    assert fake.plan_calls == 1
    assert fake.verify_calls == 1
    assert response.presentation.requested_mode == "BOTH"
    assert response.presentation.narrative is not None


def test_request_scoped_community_evidence_does_not_add_groq_calls():
    pipeline = FactCheckPipeline(Settings(groq_api_key="test-key"))
    fake = FakeGroqService()
    pipeline.groq = fake
    pipeline.web_search = fake
    now = datetime.now(timezone.utc).isoformat()
    community = [
        CommunityEvidenceRecord(
            schema_version="1.0",
            record_type="COMMUNITY_VERIFIED_EVIDENCE",
            community_post_id="11111111-1111-4111-8111-111111111111",
            case_id="22222222-2222-4222-8222-222222222222",
            revision=1,
            content_hash="b" * 64,
            status="VERIFIED_EVIDENCE",
            title="Bantuan Rp5 juta dibantah komunitas",
            verified_claim="Pemerintah memberikan bantuan Rp5 juta",
            stance="REFUTES",
            evidence_summary="Komunitas menyatakan tidak ada program resmi bantuan Rp5 juta.",
            redacted_text="Klaim bantuan Rp5 juta beredar melalui pesan berantai.",
            published_at=now,
            verified_at=now,
            sources=[
                {
                    "title": "Rujukan publik",
                    "url": "https://example.com/community/bantuan-rp5-juta",
                    "publisher": "Komunitas WaspadAI",
                    "published_at": now,
                }
            ],
        )
    ]

    response = asyncio.run(
        pipeline.verify_text(
            text="Pemerintah disebut memberikan bantuan Rp5 juta pada tahun 2026.",
            question="Apakah kabar ini benar?",
            source_url=None,
            sender_context="FORWARDED",
            output_mode="BOTH",
            community_evidence=community,
        )
    )

    assert fake.plan_calls == 1
    assert fake.verify_calls == 1
    assert any(item.source_type == "community_verified" for item in response.evidence)
