import asyncio
import shutil
from datetime import datetime, timezone

from app.config import Settings
from app.schemas import (
    CaseContext,
    Evidence,
    PlannedClaim,
    VerificationDecision,
)
from app.services.evidence_store import LocalVerifiedEvidenceStore
from app.services.input_adapters import build_text_case
from app.services.pipeline import (
    _enforce_scam_message_decision,
    _enforce_rulebook_safety,
    calculate_evidence_sufficiency,
    prepare_evidence_for_decision,
)
from app.services.pipeline import _fallback_verification_decision
from app.services.planner_guardrails import deterministic_fallback_plan
from app.services.rag import RulebookLoadError, RulebookRAG
from app.services.signal_extraction import extract_case_signals
from scripts.evaluate_rulebook import evaluate
from scripts.compile_rulebooks import RULEBOOK_DIR, compile_rulebooks


def case_context(text: str, impersonation: bool = False) -> CaseContext:
    case, _ = build_text_case(
        text=text,
        question="Apakah teks ini benar dan aman?",
        source_url=None,
        sender_context="UNKNOWN_NUMBER" if impersonation else "UNKNOWN",
        max_urls=10,
    )
    return case.model_copy(update={"possible_impersonation": impersonation})


def test_critical_otp_and_apk_rules_are_force_included():
    text = "Petugas BPJS meminta install APK lalu kirim OTP sekarang."
    signals = extract_case_signals(case_context(text, impersonation=True))
    rag = RulebookRAG(Settings())

    result = asyncio.run(rag.retrieve(text, signals))

    assert signals.secret_request_detected is True
    assert signals.suspicious_executable_received is True
    assert {"ATO-R004", "ATO-R006", "GOV-R008", "GOV-R009"} <= set(
        result.trace.forced_rule_ids
    )
    assert {"DO_NOT_SHARE_SECRET", "DO_NOT_INSTALL"} <= set(result.forced_actions)
    forced_matches = [item for item in result.matches if "DETERMINISTIC" in item.match_types]
    assert forced_matches
    assert all("case_is_scam" in item.does_not_prove for item in forced_matches if item.chunk_type == "critical_indicator")


def test_negated_educational_text_does_not_fire_secret_or_apk_trigger():
    text = "Petugas resmi tidak pernah meminta OTP. Jangan instal APK dari pesan."
    signals = extract_case_signals(case_context(text))
    rag = RulebookRAG(Settings())

    result = asyncio.run(rag.retrieve(text, signals))

    assert signals.secret_request_detected is False
    assert signals.suspicious_executable_received is False
    assert "ATO-R004" not in result.trace.forced_rule_ids
    assert "ATO-R006" not in result.trace.forced_rule_ids
    assert signals.extraction_notes
    assert {item.polarity for item in signals.action_signals} == {"NEGATED_WARNING"}


def test_government_payment_trigger_requires_suspicious_destination():
    normal = "Bayar pajak melalui kanal resmi pemerintah."
    suspicious = "Petugas pajak meminta transfer ke rekening pribadi malam ini."
    rag = RulebookRAG(Settings())

    normal_result = asyncio.run(rag.retrieve(normal, extract_case_signals(case_context(normal))))
    suspicious_result = asyncio.run(
        rag.retrieve(
            suspicious,
            extract_case_signals(case_context(suspicious, impersonation=True)),
        )
    )

    assert "GOV-R010" not in normal_result.trace.forced_rule_ids
    assert "GOV-R010" in suspicious_result.trace.forced_rule_ids
    assert "VERIFY_PAYMENT_REASON_CHANNEL_AND_BENEFICIARY" in suspicious_result.forced_actions


def test_retrieval_is_phase_aware_and_cached():
    text = "Pesan BPJS melalui WhatsApp meminta klik tautan untuk bantuan."
    signals = extract_case_signals(case_context(text, impersonation=True))
    rag = RulebookRAG(Settings())

    first = asyncio.run(rag.retrieve(text, signals))
    second = asyncio.run(rag.retrieve(text, signals))

    phases = {item.phase for item in first.matches}
    assert {"DETECTION", "INVESTIGATION", "DECISION", "RESPONSE"} <= phases
    assert first.trace.cache_hit is False
    assert second.trace.cache_hit is True
    assert second.trace.corpus_versions == [
        "RB-ATO-001@1.2.0",
        "RB-GOV-001@1.2.0",
        "RB-INF-001@1.0.0",
    ]


def test_verified_evidence_store_maps_results_per_claim():
    store = LocalVerifiedEvidenceStore()
    claims = [
        PlannedClaim(id="claim_1", text="Portal resmi bantuan sosial", claim_type="FACTUAL", verifiable=True),
        PlannedClaim(id="claim_2", text="Laporkan rekening penipuan", claim_type="FACTUAL", verifiable=True),
    ]

    evidence = asyncio.run(store.retrieve_domain(claims, ["social_assistance", "finance"]))

    assert {item.claim_id for item in evidence} == {"claim_1", "claim_2"}
    assert len({item.id for item in evidence}) == len(evidence)
    assert all(item.stance == "CONTEXT" for item in evidence)


def test_verified_evidence_store_filters_cross_domain_noise():
    store = LocalVerifiedEvidenceStore()
    claims = [
        PlannedClaim(
            id="claim_1",
            text="Indonesia menjadi tuan rumah pertama FIFA ASEAN Cup 2026",
            claim_type="FACTUAL_CLAIM",
            verifiable=True,
        )
    ]

    evidence = asyncio.run(store.retrieve_domain(claims, ["general_information_integrity"]))

    assert all("Anti-Scam" not in item.publisher for item in evidence)


def test_context_evidence_cannot_inflate_sufficiency():
    claims = [
        PlannedClaim(id="claim_1", text="Klaim satu", claim_type="FACTUAL", verifiable=True),
    ]
    context = [_evidence("context", "claim_1", "CONTEXT", "Instansi A")]

    assert calculate_evidence_sufficiency(context, claims) <= 0.35


def test_multiple_reviewed_search_results_can_establish_evidence_coverage():
    claims = [
        PlannedClaim(id="claim_1", text="Klaim satu", claim_type="FACTUAL", verifiable=True),
    ]
    evidence = [
        _evidence("search-a", "claim_1", "UNKNOWN", "Instansi A").model_copy(
            update={"verification_status": "REVIEWED"}
        ),
        _evidence("search-b", "claim_1", "UNKNOWN", "Media B").model_copy(
            update={"verification_status": "REVIEWED"}
        ),
    ]

    assert calculate_evidence_sufficiency(evidence, claims) >= 0.58


def test_single_official_reviewed_source_can_unlock_primary_claim():
    claims = [
        PlannedClaim(
            id="claim_1",
            text="Indonesia menjadi tuan rumah pertama FIFA ASEAN Cup 2026",
            claim_type="FACTUAL_CLAIM",
            verifiable=True,
        )
    ]
    evidence = [
        _evidence("fifa", "claim_1", "UNKNOWN", "fifa.com").model_copy(
            update={
                "source_type": "official_sports_body",
                "url": "https://www.fifa.com/en/news/articles/asean-cup-everything-you-need-to-know",
                "verification_status": "REVIEWED",
                "authority": 0.98,
                "relevance": 0.91,
            }
        )
    ]

    assert calculate_evidence_sufficiency(evidence, claims) >= 0.58


def test_non_material_ocr_claim_does_not_lower_primary_coverage():
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
    evidence = [
        _evidence("fifa", "claim_1", "UNKNOWN", "fifa.com").model_copy(
            update={
                "source_type": "official_sports_body",
                "verification_status": "REVIEWED",
                "authority": 0.98,
                "relevance": 0.91,
            }
        )
    ]

    assert calculate_evidence_sufficiency(evidence, claims) >= 0.58


def test_spacex_location_mismatch_can_unlock_misleading_evidence():
    claims = [
        PlannedClaim(
            id="claim_1",
            text="SpaceX berhasil menangkap booster Starship di Florida pada 13 Oktober 2024",
            claim_type="FACTUAL_CLAIM",
            verifiable=True,
        ),
        PlannedClaim(
            id="claim_2",
            text="Booster Super Heavy ditangkap menggunakan lengan mekanis menara peluncuran di Bogor, Jawa Barat",
            claim_type="FACTUAL_CLAIM",
            verifiable=True,
        ),
        PlannedClaim(
            id="claim_3",
            text="Keberhasilan tersebut menjadi bagian dari penerbangan uji kelima sistem Starship",
            claim_type="FACTUAL_CLAIM",
            verifiable=True,
        ),
    ]
    evidence = [
        _evidence("spacex", "claim_1", "UNKNOWN", "SpaceX").model_copy(
            update={
                "source_type": "official_company",
                "authority": 0.96,
                "relevance": 0.88,
                "title": "Starship's fifth flight test",
                "excerpt": "On October 13, 2024, Super Heavy returned to the launch site at Starbase, Texas and was caught by the launch tower chopsticks during Starship's fifth flight test.",
            }
        )
    ]

    prepared = prepare_evidence_for_decision(evidence, claims)

    assert any(item.claim_id == "claim_1" and item.stance == "REFUTES" for item in prepared)
    assert any(item.claim_id == "claim_2" and item.stance == "REFUTES" for item in prepared)
    assert any(item.claim_id == "claim_3" and item.stance == "SUPPORTS" for item in prepared)
    assert calculate_evidence_sufficiency(prepared, claims) >= 0.58


def test_prevost_evidence_is_remapped_across_atomic_claims():
    claims = [
        PlannedClaim(id="claim_1", text="Robert Prevost terpilih sebagai Paus Leo XIV", claim_type="FACTUAL_CLAIM", verifiable=True),
        PlannedClaim(id="claim_2", text="Kardinal Robert Prevost terpilih pada 8 Mei 2025", claim_type="FACTUAL_CLAIM", verifiable=True),
        PlannedClaim(id="claim_3", text="Robert Prevost menjadi paus pertama asal Amerika Serikat", claim_type="FACTUAL_CLAIM", verifiable=True),
        PlannedClaim(id="claim_4", text="Robert Prevost menggunakan nama Leo XIV", claim_type="FACTUAL_CLAIM", verifiable=True),
    ]
    evidence = [
        _evidence("ap", "claim_2", "UNKNOWN", "apnews.com").model_copy(
            update={
                "source_type": "news_wire",
                "authority": 0.86,
                "relevance": 0.91,
                "title": "Conclave elects Robert Prevost to be Pope, the first American pontiff",
                "excerpt": "Cardinal Robert Prevost was elected pope on May 8, 2025, became the first American pontiff, and took the name Leo XIV.",
            }
        )
    ]

    prepared = prepare_evidence_for_decision(evidence, claims)
    covered = {item.claim_id for item in prepared if item.stance == "SUPPORTS"}

    assert covered == {"claim_1", "claim_2", "claim_3", "claim_4"}
    assert calculate_evidence_sufficiency(prepared, claims) >= 0.58


def test_off_topic_earthquake_evidence_is_removed():
    claims = [
        PlannedClaim(
            id="claim_1",
            text="Gempa berkekuatan magnitudo 8,1 mengguncang wilayah Hokkaido, Jepang, pada 1 Januari 2024.",
            claim_type="FACTUAL_CLAIM",
            verifiable=True,
        ),
        PlannedClaim(
            id="claim_2",
            text="Gempa dangkal tersebut memicu peringatan tsunami dan menyebabkan kerusakan di pesisir Jepang.",
            claim_type="FACTUAL_CLAIM",
            verifiable=True,
        ),
    ]
    evidence = [
        _evidence("kepulauan-seribu", "claim_2", "UNKNOWN", "instagram.com").model_copy(
            update={
                "authority": 0.68,
                "relevance": 0.51,
                "title": "Gempa magnitudo 5,9 mengguncang Kepulauan Seribu",
                "excerpt": "Gempa magnitudo 5,9 mengguncang Kepulauan Seribu, Jakarta, Sabtu 12 September 2026 dan tidak berpotensi tsunami.",
            }
        )
    ]

    prepared = prepare_evidence_for_decision(evidence, claims)

    assert prepared == []


def test_fallback_verifier_can_refute_explicit_demotion_hoax():
    from app.schemas import PlannerOutput, RetrievalPlan

    claim = PlannedClaim(
        id="claim_1",
        text="Terjadi upacara penurunan jabatan Prabowo Subianto",
        claim_type="FACTUAL_CLAIM",
        verifiable=True,
    )
    planner = PlannerOutput(
        classification="FACTUAL_CLAIM",
        domains=["general_information_integrity"],
        attack_patterns=[],
        claims=[claim],
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
    evidence = [
        _evidence("setneg", "claim_1", "UNKNOWN", "setneg.go.id").model_copy(
            update={
                "verification_status": "REVIEWED",
                "authority": 1.0,
                "relevance": 0.82,
                "title": "Presiden Prabowo Pimpin Upacara Penurunan Bendera Merah Putih",
                "excerpt": "Upacara tersebut adalah penurunan bendera Merah Putih di Istana Merdeka, bukan penurunan jabatan.",
            }
        )
    ]

    decision = _fallback_verification_decision(planner, evidence, 0.82)

    assert decision.overall_verdict == "REFUTED"
    assert decision.claims[0].refuting_evidence == ["setneg"]
    assert decision.requires_human_review is False


def test_incomplete_claim_coverage_is_capped_below_threshold():
    claims = [
        PlannedClaim(id="claim_1", text="Klaim satu", claim_type="FACTUAL", verifiable=True),
        PlannedClaim(id="claim_2", text="Klaim dua", claim_type="FACTUAL", verifiable=True),
    ]
    evidence = [_evidence("support", "claim_1", "SUPPORTS", "Instansi A")]

    assert calculate_evidence_sufficiency(evidence, claims) <= 0.57


def test_rulebook_safety_benchmark_passes():
    metrics = asyncio.run(evaluate())

    assert metrics["critical_rule_recall"] == 1.0
    assert metrics["forbidden_trigger_hits"] == []
    assert metrics["phase_coverage_rate"] >= 0.9


def test_post_retrieval_guardrail_uses_runtime_threshold():
    text = "Informasi ini perlu diperiksa."
    signals = extract_case_signals(case_context(text))
    rag = RulebookRAG(
        Settings(evidence_sufficiency_threshold=0.75)
    )
    initial = asyncio.run(rag.retrieve(text, signals))

    guarded = rag.post_retrieval_guardrails(
        initial,
        evidence_sufficiency=0.7,
        signals=signals,
    )

    assert "INF-R014" in guarded.trace.forced_rule_ids
    assert "RETURN_UNVERIFIED" in guarded.forced_actions


def test_rulebook_can_raise_risk_and_action_but_not_change_factual_verdict():
    text = "Petugas bank meminta kirim OTP sekarang."
    signals = extract_case_signals(case_context(text, impersonation=True))
    rag = RulebookRAG(Settings())
    result = asyncio.run(rag.retrieve(text, signals))
    decision = VerificationDecision(
        claims=[],
        overall_verdict="REFUTED",
        risk_level="MEDIUM",
        evidence_sufficiency=0.9,
        requires_human_review=False,
        headline="Klaim dibantah",
        what_checked=[],
        why=[],
        recommended_actions=[],
        uncertainty="",
    )

    _enforce_rulebook_safety(decision, result)

    assert decision.overall_verdict == "REFUTED"
    assert decision.risk_level == "CRITICAL"
    assert "DO_NOT_SHARE_SECRET" in {item.code for item in decision.recommended_actions}


def test_impersonation_link_message_gets_scam_security_decision():
    text = (
        "Peringatan Resmi WhatsApp: Akun Anda melanggar ketentuan resmi, "
        "silakan buka www.whastapp-safe.com untuk memulihkan. Jika tidak ditangani "
        "dalam 6 jam, akun akan diblokir permanen."
    )
    case = case_context(text, impersonation=True)
    signals = extract_case_signals(case)
    rag = RulebookRAG(Settings())
    rulebook = asyncio.run(rag.retrieve(text, signals))
    planner = deterministic_fallback_plan(case, signals, rulebook, Settings())
    decision = VerificationDecision(
        claims=[],
        overall_verdict="UNVERIFIED",
        risk_level="UNKNOWN",
        evidence_sufficiency=0.1,
        requires_human_review=True,
        headline="Pemeriksaan belum dapat diselesaikan secara penuh",
        what_checked=[],
        why=[],
        recommended_actions=[],
        uncertainty="",
    )

    _enforce_scam_message_decision(decision, case, signals, planner)

    assert planner.classification == "SCAM_MESSAGE"
    assert "suspicious_link_domain" in signals.attack_patterns
    assert decision.overall_verdict == "MISLEADING"
    assert decision.risk_level == "HIGH"
    assert decision.requires_human_review is False
    assert decision.headline == "Pesan patut diduga penipuan atau phishing"
    assert decision.recommended_actions[0].code == "DO_NOT_OPEN_LINK"


def test_fake_kejaksaaan_tilang_link_is_government_scam_signal():
    text = (
        "PEMBERITAHUAN: Anda memiliki denda Tilang yang belum dibayar. "
        "Segera lanjuti melalui link https://kejaksaaan-goh.com agar sanksi tidak diperberat."
    )
    case = case_context(text, impersonation=True)
    signals = extract_case_signals(case)
    rag = RulebookRAG(Settings())
    rulebook = asyncio.run(rag.retrieve(text, signals))
    planner = deterministic_fallback_plan(case, signals, rulebook, Settings())

    assert signals.government_context is True
    assert "suspicious_link_domain" in signals.attack_patterns
    assert planner.classification == "SCAM_MESSAGE"
    assert planner.interim_risk == "HIGH"


def test_runtime_rejects_stale_compiled_corpus(tmp_path):
    isolated_rulebook = tmp_path / "rulebook"
    compiled_dir = isolated_rulebook / "compiled"
    isolated_rulebook.mkdir()
    for name in [
        *(path.name for path in RULEBOOK_DIR.glob("rulebook_*.txt")),
        "deterministic_triggers.json",
    ]:
        shutil.copy2(RULEBOOK_DIR / name, isolated_rulebook / name)
    compile_rulebooks(compiled_dir)
    canonical = isolated_rulebook / "rulebook_government_public_service.txt"
    canonical.write_text(canonical.read_text(encoding="utf-8") + "\nchanged\n", encoding="utf-8")

    try:
        RulebookRAG(Settings(rulebook_compiled_dir=compiled_dir))
    except RulebookLoadError as exc:
        assert "berubah setelah compile" in str(exc)
    else:
        raise AssertionError("Stale corpus should be rejected")


def _evidence(identifier: str, claim_id: str, stance: str, publisher: str) -> Evidence:
    return Evidence(
        id=identifier,
        claim_id=claim_id,
        source_type="government",
        publisher=publisher,
        title="Sumber resmi",
        url=f"https://example.go.id/{identifier}",
        published_at="2026-08-01",
        retrieved_at=datetime.now(timezone.utc).isoformat(),
        excerpt="Isi bukti yang relevan.",
        relevance=0.9,
        authority=1.0,
        recency=0.95,
        stance=stance,
        verification_status="VERIFIED",
    )
