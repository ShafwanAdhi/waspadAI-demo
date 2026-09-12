from datetime import datetime, timezone

import pytest

from app.config import get_settings
from app.schemas import (
    ClaimAssessment,
    Evidence,
    RecommendedAction,
    VerificationDecision,
    VisionClaim,
    VisionOutput,
)
from app.services.planner_guardrails import deterministic_fallback_plan


class FakeGroqService:
    """Deterministic live-mode stand-in used only by tests."""

    def __init__(self, settings, rate_limits=None) -> None:
        self.settings = settings
        self.rate_limits = rate_limits

    async def understand_image(
        self,
        image_data_url,
        ocr,
        metadata,
        redacted_ocr_text,
        user_query,
    ):
        return VisionOutput(
            content_type="image",
            platform=None,
            visual_summary=(
                redacted_ocr_text[:600]
                or "Gambar uji berisi klaim yang perlu diverifikasi."
            ),
            visual_entities=["informasi uji"],
            possible_impersonation=False,
            visible_urls=[],
            claims=[
                VisionClaim(
                    text="Informasi pada gambar uji perlu diverifikasi",
                    verifiable=True,
                )
            ],
            vision_confidence=0.82,
        )

    async def plan(self, case, signals, rulebook, escalation=False):
        return deterministic_fallback_plan(case, signals, rulebook, self.settings)

    async def review_plan(self, case, signals, rulebook, draft, validation_issues):
        return draft

    async def verify_and_generate(self, planner, evidence, sufficiency, rulebook):
        low_evidence = sufficiency < self.settings.evidence_sufficiency_threshold
        return VerificationDecision(
            claims=[
                ClaimAssessment(
                    claim_id=claim.id,
                    verdict="UNVERIFIED" if low_evidence else "REFUTED",
                    supporting_evidence=[],
                    refuting_evidence=[
                        item.id for item in evidence if item.claim_id == claim.id
                    ][:2],
                    contradiction_level="NONE",
                    reason="Keputusan uji dibuat dari evidence deterministik.",
                )
                for claim in planner.claims
            ],
            overall_verdict="UNVERIFIED" if low_evidence else "REFUTED",
            risk_level=planner.interim_risk if planner.interim_risk != "UNKNOWN" else "LOW",
            evidence_sufficiency=sufficiency,
            requires_human_review=low_evidence,
            headline="Pemeriksaan live uji selesai",
            what_checked=[claim.text for claim in planner.claims],
            why=["Evidence uji dipetakan ke klaim atomik melalui pipeline live."],
            recommended_actions=[
                RecommendedAction(
                    code="VERIFY_VIA_OFFICIAL_CHANNEL",
                    title="Periksa sumber resmi",
                    detail="Bandingkan informasi dengan kanal resmi yang ditemukan sendiri.",
                )
            ],
            uncertainty="Ini respons deterministik untuk test, bukan panggilan provider nyata.",
        )


class FakeWebSearchService:
    provider_name = "fake-search"
    configured = True
    health = {
        "provider": provider_name,
        "configured": True,
        "retrieval_mode": "TEST",
        "uses_groq_compound": False,
    }

    def __init__(self, settings) -> None:
        self.settings = settings

    async def search(self, planner):
        now = datetime.now(timezone.utc).isoformat()
        evidence = []
        for claim in planner.claims[:4]:
            evidence.append(
                Evidence(
                    id=f"fake_web_{claim.id}",
                    claim_id=claim.id,
                    source_type="government",
                    publisher="Sumber Resmi Uji",
                    title=f"Referensi resmi untuk {claim.id}",
                    url=f"https://example.go.id/{claim.id}",
                    published_at="2026-08-20",
                    retrieved_at=now,
                    excerpt="Sumber uji terverifikasi yang dipakai untuk menjaga test tetap deterministik.",
                    relevance=0.9,
                    authority=1.0,
                    recency=0.95,
                    stance="REFUTES",
                    verification_status="VERIFIED",
                )
            )
        return evidence

@pytest.fixture(autouse=True)
def force_live_test_mode(monkeypatch: pytest.MonkeyPatch):
    """Keep tests deterministic while exercising the live pipeline wiring."""
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("GROQ_API_KEY", "test-key-not-real")
    monkeypatch.setattr(
        "app.services.pipeline.GroqFactCheckService",
        FakeGroqService,
    )
    monkeypatch.setattr(
        "app.services.pipeline.TavilyWebSearchService",
        FakeWebSearchService,
    )
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
