from datetime import datetime, timezone

from app.schemas import Evidence, RecommendedAction
from app.services.presentation import build_narrative_presentation


def _evidence(stance: str = "SUPPORTS") -> Evidence:
    return Evidence(
        id="ev_1",
        claim_id="claim_1",
        source_type="government",
        publisher="Instansi Resmi",
        title="Rilis resmi",
        url="https://example.go.id/rilis",
        published_at="2026-09-01",
        retrieved_at=datetime.now(timezone.utc).isoformat(),
        excerpt="Rilis resmi terkait klaim.",
        relevance=0.9,
        authority=1.0,
        recency=0.95,
        stance=stance,
        verification_status="VERIFIED",
    )


def _action() -> RecommendedAction:
    return RecommendedAction(
        code="VERIFY_OFFICIAL",
        title="Cek kanal resmi",
        detail="Bandingkan informasi dengan situs atau akun resmi terkait.",
    )


def test_narrative_omits_low_risk_from_public_text() -> None:
    narrative = build_narrative_presentation(
        verdict="SUPPORTED",
        risk_level="LOW",
        headline="Klaim jadwal acara didukung bukti",
        why=["Evidence resmi mendukung klaim utama."],
        evidence=[_evidence()],
        evidence_sufficiency_label="Bukti kuat - skor kecukupan, bukan probabilitas kebenaran",
        recommended_actions=[_action()],
        uncertainty="Evidence konsisten dari sumber resmi.",
        requires_human_review=False,
    )

    assert "tingkat risikonya rendah" not in narrative.text
    assert "risiko rendah" not in narrative.text
    assert "Bukti resmi" in narrative.text
    assert "skor kecukupan" not in narrative.text
    assert "probabilitas" not in narrative.text


def test_narrative_shows_warning_for_high_and_critical_risk() -> None:
    high = build_narrative_presentation(
        verdict="UNVERIFIED",
        risk_level="HIGH",
        headline="Pesan meminta tindakan sensitif",
        why=["Ada permintaan OTP."],
        evidence=[],
        evidence_sufficiency_label="Bukti belum cukup - verdict dikunci sebagai belum terverifikasi",
        recommended_actions=[_action()],
        uncertainty="Identitas pengirim belum dapat dipastikan.",
        requires_human_review=True,
    )
    critical = build_narrative_presentation(
        verdict="UNVERIFIED",
        risk_level="CRITICAL",
        headline="Pesan meminta OTP dan transfer",
        why=["Ada permintaan OTP dan transfer segera."],
        evidence=[],
        evidence_sufficiency_label="Bukti belum cukup",
        recommended_actions=[_action()],
        uncertainty="Identitas pengirim belum dapat dipastikan.",
        requires_human_review=True,
    )

    assert "Peringatan: ada risiko tinggi" in high.text
    assert "Peringatan penting: kasus ini memiliki risiko sangat tinggi" in critical.text
    assert "OTP" in critical.text


def test_narrative_omits_medium_risk_from_public_text() -> None:
    narrative = build_narrative_presentation(
        verdict="MISLEADING",
        risk_level="MEDIUM",
        headline="Klaim kehilangan konteks penting",
        why=["Sebagian informasi benar, tetapi detail utama dipelintir."],
        evidence=[_evidence("REFUTES")],
        evidence_sufficiency_label="Bukti cukup - tetap periksa konteks dan waktu",
        recommended_actions=[_action()],
        uncertainty="Bukti cukup untuk konteks utama.",
        requires_human_review=False,
    )

    assert "risiko sedang" not in narrative.text
    assert "dengan risiko" not in narrative.text


def test_narrative_groups_social_sources_as_context() -> None:
    official = _evidence().model_copy(update={"publisher": "Kemenpora", "url": "https://kemenpora.go.id/rilis"})
    social = _evidence().model_copy(
        update={
            "id": "ev_2",
            "publisher": "Instagram",
            "url": "https://instagram.com/p/abc",
            "source_type": "social_media",
            "authority": 0.35,
        }
    )

    narrative = build_narrative_presentation(
        verdict="SUPPORTED",
        risk_level="LOW",
        headline="Klaim didukung bukti resmi",
        why=["Sumber resmi mendukung klaim."],
        evidence=[official, social],
        evidence_sufficiency_label="Bukti cukup",
        recommended_actions=[_action()],
        uncertainty="Bukti utama berasal dari sumber resmi.",
        requires_human_review=False,
    )

    assert "sumber resmi/primer seperti Kemenpora" in narrative.text
    assert "konteks media sosial seperti Instagram" in narrative.text


def test_unverified_narrative_uses_non_final_language() -> None:
    narrative = build_narrative_presentation(
        verdict="UNVERIFIED",
        risk_level="LOW",
        headline="Klaim foto belum dapat dipastikan",
        why=["Bukti yang tersedia belum mencakup seluruh konteks visual."],
        evidence=[_evidence("CONTEXT")],
        evidence_sufficiency_label="Bukti belum cukup - verdict dikunci sebagai belum terverifikasi",
        recommended_actions=[_action()],
        uncertainty="Bukti belum lengkap untuk menyimpulkan isi ruangan secara menyeluruh.",
        requires_human_review=True,
    )

    assert "terbantahkan" not in narrative.text
    assert "belum boleh dianggap sebagai kesimpulan final" in narrative.text
    assert "Bukti belum cukup untuk memastikan klaim" in narrative.text
