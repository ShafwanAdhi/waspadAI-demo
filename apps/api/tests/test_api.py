import io
from datetime import datetime, timezone

from fastapi.testclient import TestClient
from PIL import Image

from app.config import get_settings
from app.main import app


def png_payload(width: int = 640, height: int = 480) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), color=(238, 232, 219)).save(buffer, format="PNG")
    return buffer.getvalue()


def community_payload() -> list[dict]:
    now = datetime.now(timezone.utc).isoformat()
    return [
        {
            "schema_version": "1.0",
            "record_type": "COMMUNITY_VERIFIED_EVIDENCE",
            "community_post_id": "11111111-1111-4111-8111-111111111111",
            "case_id": "22222222-2222-4222-8222-222222222222",
            "revision": 1,
            "content_hash": "a" * 64,
            "status": "VERIFIED_EVIDENCE",
            "title": "Bantuan Rp5 juta dibantah komunitas",
            "verified_claim": "Pemerintah memberikan bantuan Rp5 juta",
            "stance": "REFUTES",
            "evidence_summary": "Tidak ada program resmi bantuan Rp5 juta pada kanal pemerintah yang diperiksa komunitas.",
            "redacted_text": "Klaim bantuan Rp5 juta beredar melalui pesan berantai.",
            "published_at": now,
            "verified_at": now,
            "sources": [
                {
                    "title": "Rujukan publik",
                    "url": "https://example.com/community/bantuan-rp5-juta",
                    "publisher": "Komunitas WaspadAI",
                    "published_at": now,
                }
            ],
        }
    ]


def test_health_reports_production_runtime() -> None:
    with TestClient(app) as client:
        response = client.get("/api/health")
        assert response.status_code == 200
        assert response.json()["mode"] == "LIVE"
        assert response.json()["rulebook_rag"]["status"] == "ready"
        assert response.json()["rulebook_rag"]["rule_count"] >= 255
        assert response.json()["input_types"] == ["IMAGE", "TEXT"]
        assert response.json()["output_modes"] == ["STRUCTURED", "NARRATIVE", "BOTH"]
        assert response.json()["community_evidence"]["status"] == "ready"
        assert response.json()["community_evidence"]["database_access"] is False
        assert response.json()["debug_trace"]["enabled"] is True


def test_api_root_points_to_health_and_documentation() -> None:
    with TestClient(app) as client:
        response = client.get("/")

    assert response.status_code == 200
    assert response.json() == {
        "service": "WaspadAI API",
        "health": "/api/health",
        "documentation": "/api/docs",
    }


def test_live_image_verification_has_required_user_facing_sections() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/verify/image",
            files={"image": ("sample.png", png_payload(), "image/png")},
            data={"question": "Apakah aman?"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "LIVE"
    assert body["presentation"]["requested_mode"] == "STRUCTURED"
    assert body["presentation"]["structured"] is True
    assert body["presentation"]["narrative"] is None
    assert body["verdict"] in {"REFUTED", "UNVERIFIED"}
    assert body["risk_level"] in {"LOW", "MEDIUM", "HIGH", "CRITICAL", "UNKNOWN"}
    assert body["what_checked"]
    assert body["why"]
    assert body["evidence"]
    assert body["recommended_actions"]
    assert body["sources"]
    assert len(body["pipeline"]) == 5
    assert body["rulebook"]["selected_count"] > 0
    assert any(stage["key"] == "rulebook" for stage in body["pipeline"])
    assert body["input_summary"]["input_type"] == "IMAGE"
    assert body["dimensions"]["content_authenticity"] == "UNVERIFIED"


def test_rejects_non_image_payload() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/verify/image",
            files={"image": ("not-image.txt", b"hello", "text/plain")},
        )
    assert response.status_code == 415


def test_rejects_image_dimensions_outside_allowed_range(monkeypatch) -> None:
    monkeypatch.setenv("MAX_IMAGE_WIDTH", "1000")
    monkeypatch.setenv("MAX_IMAGE_HEIGHT", "1000")
    get_settings.cache_clear()

    with TestClient(app) as client:
        too_small = client.post(
            "/api/v1/verify/image",
            files={"image": ("tiny.png", png_payload(32, 32), "image/png")},
        )
        too_large = client.post(
            "/api/v1/verify/image",
            files={"image": ("large.png", png_payload(1200, 800), "image/png")},
        )

    assert too_small.status_code == 415
    assert "minimal" in too_small.json()["detail"]
    assert too_large.status_code == 415
    assert "maksimal" in too_large.json()["detail"]


def test_live_text_verification_has_image_feature_parity() -> None:
    with TestClient(app) as client:
        image_response = client.post(
            "/api/v1/verify/image",
            files={"image": ("sample.png", png_payload(), "image/png")},
            data={"question": "Apakah aman?"},
        )
        text_response = client.post(
            "/api/v1/verify/text",
            json={
                "text": (
                    "Pesan diteruskan menyebut pemerintah memberi bantuan Rp5 juta "
                    "dan meminta penerima menghubungi WhatsApp malam ini."
                ),
                "question": "Apakah berita ini benar?",
                "sender_context": "FORWARDED",
            },
        )

    assert text_response.status_code == 200
    image_body = image_response.json()
    text_body = text_response.json()
    assert set(text_body) == set(image_body)
    assert text_body["input_summary"]["input_type"] == "TEXT"
    assert text_body["input_summary"]["content_type"] == "FORWARDED_MESSAGE"
    assert text_body["dimensions"]["content_authenticity"] == "NOT_APPLICABLE"
    assert text_body["what_checked"]
    assert text_body["why"]
    assert text_body["evidence"]
    assert text_body["recommended_actions"]
    assert text_body["sources"]
    assert len(text_body["pipeline"]) == 5
    assert text_body["rulebook"]["selected_count"] > 0


def test_text_verification_can_return_narrative_presentation() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/verify/text",
            json={
                "text": "Pesan mengaku dari bank dan meminta penerima mengirim OTP agar akun tidak diblokir.",
                "question": "Apakah pesan ini aman?",
                "sender_context": "UNKNOWN_NUMBER",
                "output_mode": "NARRATIVE",
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["presentation"]["requested_mode"] == "NARRATIVE"
    assert body["presentation"]["structured"] is False
    assert "Hasil pemeriksaan:" in body["presentation"]["narrative"]["text"]
    assert body["headline"] in body["presentation"]["narrative"]["summary"]


def test_image_verification_can_return_both_presentations() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/verify/image",
            files={"image": ("sample.png", png_payload(), "image/png")},
            data={"question": "Apakah aman?", "output_mode": "BOTH"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["presentation"]["requested_mode"] == "BOTH"
    assert body["presentation"]["structured"] is True
    assert body["presentation"]["narrative"]["paragraphs"]


def test_url_only_text_is_accepted_as_url_context() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/verify/text",
            json={"text": "https://example.com/klaim?utm_source=test#bagian"},
        )

    assert response.status_code == 200
    summary = response.json()["input_summary"]
    assert summary["content_type"] == "URL_ONLY"
    assert summary["excerpt"].startswith("URL untuk diperiksa: https://example.com/klaim")
    assert summary["urls_detected"] == 1


def test_private_url_only_text_is_rejected() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/verify/text",
            json={"text": "http://127.0.0.1/private"},
        )

    assert response.status_code == 422
    assert "URL" in response.json()["detail"]


def test_removed_extension_routes_are_not_available() -> None:
    with TestClient(app) as client:
        installation = client.post(
            "/api/extension/v1/installations",
            json={"extension_version": "0.1.0"},
        )
        verification = client.post(
            "/api/extension/v1/verify/text",
            json={"text": "Teks ini cukup panjang untuk diperiksa."},
        )

    assert installation.status_code == 404
    assert verification.status_code == 404


def test_internal_text_verification_requires_configured_api_key(
    monkeypatch,
) -> None:
    monkeypatch.setenv("WASPADAI_API_KEYS", "")
    get_settings.cache_clear()

    with TestClient(app) as client:
        response = client.post(
            "/api/internal/v1/verify/text",
            json={"text": "Teks ini cukup panjang untuk diperiksa oleh endpoint internal."},
        )

    assert response.status_code == 503
    assert "WASPADAI_API_KEYS" in response.json()["detail"]


def test_internal_text_verification_rejects_missing_or_invalid_api_key(
    monkeypatch,
) -> None:
    monkeypatch.setenv("WASPADAI_API_KEYS", "alpha-secret,beta-secret")
    get_settings.cache_clear()

    with TestClient(app) as client:
        missing = client.post(
            "/api/internal/v1/verify/text",
            json={"text": "Teks ini cukup panjang untuk diperiksa oleh endpoint internal."},
        )
        invalid = client.post(
            "/api/internal/v1/verify/text",
            headers={"X-Waspadai-API-Key": "wrong-secret"},
            json={"text": "Teks ini cukup panjang untuk diperiksa oleh endpoint internal."},
        )

    assert missing.status_code == 401
    assert invalid.status_code == 401


def test_internal_text_verification_accepts_valid_api_key(monkeypatch) -> None:
    monkeypatch.setenv("WASPADAI_API_KEYS", "alpha-secret,beta-secret")
    get_settings.cache_clear()

    with TestClient(app) as client:
        response = client.post(
            "/api/internal/v1/verify/text",
            headers={"X-Waspadai-API-Key": "beta-secret"},
            json={"text": "Teks ini cukup panjang untuk diperiksa oleh endpoint internal."},
        )

    assert response.status_code == 200
    assert response.json()["mode"] == "LIVE"


def test_public_text_rejects_community_evidence_payload() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/verify/text",
            json={
                "text": "Pemerintah disebut memberikan bantuan Rp5 juta pada tahun 2026.",
                "community_evidence": community_payload(),
            },
        )

    assert response.status_code == 422


def test_internal_text_accepts_request_scoped_community_evidence(monkeypatch) -> None:
    monkeypatch.setenv("WASPADAI_API_KEYS", "community-secret")
    get_settings.cache_clear()

    with TestClient(app) as client:
        response = client.post(
            "/api/internal/v1/verify/text",
            headers={"X-Waspadai-API-Key": "community-secret"},
            json={
                "text": "Pemerintah disebut memberikan bantuan Rp5 juta pada tahun 2026.",
                "output_mode": "BOTH",
                "community_evidence": community_payload(),
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert any(item["source_type"] == "community_verified" for item in body["evidence"])
    assert body["presentation"]["requested_mode"] == "BOTH"


def test_internal_image_verification_requires_valid_api_key(monkeypatch) -> None:
    monkeypatch.setenv("WASPADAI_API_KEYS", "image-secret")
    get_settings.cache_clear()

    with TestClient(app) as client:
        rejected = client.post(
            "/api/internal/v1/verify/image",
            files={"image": ("sample.png", png_payload(), "image/png")},
        )
        accepted = client.post(
            "/api/internal/v1/verify/image",
            headers={"X-Waspadai-API-Key": "image-secret"},
            files={"image": ("sample.png", png_payload(), "image/png")},
            data={"question": "Apakah aman?"},
        )

    assert rejected.status_code == 401
    assert accepted.status_code == 200


def test_internal_image_accepts_request_scoped_community_evidence(monkeypatch) -> None:
    import json

    monkeypatch.setenv("WASPADAI_API_KEYS", "image-secret")
    get_settings.cache_clear()

    payload = community_payload()
    payload[0]["verified_claim"] = "Informasi pada gambar uji perlu diverifikasi"
    payload[0]["evidence_summary"] = "Komunitas telah menandai gambar uji sebagai perlu verifikasi lanjutan."
    payload[0]["stance"] = "CONTEXT"
    with TestClient(app) as client:
        response = client.post(
            "/api/internal/v1/verify/image",
            headers={"X-Waspadai-API-Key": "image-secret"},
            files={"image": ("sample.png", png_payload(), "image/png")},
            data={
                "question": "Apakah aman?",
                "community_evidence_json": json.dumps(payload),
            },
        )

    assert response.status_code == 200
    assert response.json()["mode"] == "LIVE"


def test_text_input_redacts_pii_and_sanitizes_source_url() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/verify/text",
            json={
                "text": "Hubungi saya di user@example.com untuk memeriksa kabar bantuan ini.",
                "question": "Apakah kode OTP 123456 ini aman dibagikan?",
                "source_url": "https://example.com/berita?token=rahasia#bagian",
                "sender_context": "UNKNOWN_NUMBER",
            },
        )

    assert response.status_code == 200
    summary = response.json()["input_summary"]
    assert {"EMAIL", "OTP"} <= set(summary["pii_types_redacted"])
    assert summary["source_url"] == "https://example.com/berita"
    assert "user@example.com" not in summary["excerpt"]


def test_rejects_too_short_or_private_source_text() -> None:
    with TestClient(app) as client:
        too_short = client.post("/api/v1/verify/text", json={"text": "pendek"})
        private_url = client.post(
            "/api/v1/verify/text",
            json={"text": "Teks ini cukup panjang untuk diperiksa." , "source_url": "http://127.0.0.1/private"},
        )

    assert too_short.status_code == 422
    assert private_url.status_code == 422
