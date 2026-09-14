import io
import json
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from PIL import Image

from app.config import get_settings
from app.main import app


def png_payload(width: int = 640, height: int = 480) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), color=(238, 232, 219)).save(buffer, format="PNG")
    return buffer.getvalue()


def configure_extension_store(monkeypatch, tmp_path, **overrides) -> None:
    monkeypatch.setenv("EXTENSION_INSTALLATION_STORE_PATH", str(tmp_path / "installations.json"))
    for key, value in overrides.items():
        monkeypatch.setenv(key, str(value))
    get_settings.cache_clear()


def register_extension(client: TestClient) -> str:
    response = client.post(
        "/api/extension/v1/installations",
        json={"extension_version": "0.1.0"},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["installation_id"].startswith("inst_")
    assert body["token_type"] == "Bearer"
    assert body["installation_token"]
    return body["installation_token"]


def test_health_reports_production_runtime() -> None:
    with TestClient(app) as client:
        response = client.get("/api/health")
        assert response.status_code == 200
        assert response.json()["mode"] == "LIVE"
        assert response.json()["rulebook_rag"]["status"] == "ready"
        assert response.json()["rulebook_rag"]["rule_count"] >= 255
        assert response.json()["input_types"] == ["IMAGE", "TEXT"]
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


def test_extension_installation_registration_and_rate_limit(monkeypatch, tmp_path) -> None:
    configure_extension_store(monkeypatch, tmp_path, EXTENSION_REGISTRATION_IP_LIMIT_PER_HOUR=1)

    with TestClient(app) as client:
        first = client.post(
            "/api/extension/v1/installations",
            json={"extension_version": "0.1.0"},
        )
        second = client.post(
            "/api/extension/v1/installations",
            json={"extension_version": "0.1.0"},
        )

    assert first.status_code == 201
    assert second.status_code == 429
    assert second.headers["retry-after"]
    assert second.json()["error"]["code"] == "RATE_LIMITED"


def test_extension_token_missing_invalid_and_internal_rejection(monkeypatch, tmp_path) -> None:
    configure_extension_store(monkeypatch, tmp_path)
    monkeypatch.setenv("WASPADAI_API_KEYS", "internal-secret")
    get_settings.cache_clear()

    with TestClient(app) as client:
        token = register_extension(client)
        missing = client.post(
            "/api/extension/v1/verify/text",
            json={"text": "Teks ini cukup panjang untuk diperiksa dari extension."},
        )
        invalid = client.post(
            "/api/extension/v1/verify/text",
            headers={"Authorization": "Bearer token-yang-salah"},
            json={"text": "Teks ini cukup panjang untuk diperiksa dari extension."},
        )
        internal = client.post(
            "/api/internal/v1/verify/text",
            headers={"Authorization": f"Bearer {token}"},
            json={"text": "Teks ini cukup panjang untuk endpoint internal."},
        )

    assert missing.status_code == 401
    assert missing.json()["error"]["code"] == "INVALID_INSTALLATION_TOKEN"
    assert invalid.status_code == 401
    assert invalid.json()["error"]["code"] == "INVALID_INSTALLATION_TOKEN"
    assert internal.status_code == 401


def test_extension_token_refresh_keeps_installation_and_old_token_overlap(
    monkeypatch,
    tmp_path,
) -> None:
    configure_extension_store(monkeypatch, tmp_path, EXTENSION_TOKEN_OVERLAP_SECONDS=60)

    with TestClient(app) as client:
        old_token = register_extension(client)
        refresh = client.post(
            "/api/extension/v1/installations/refresh",
            headers={"Authorization": f"Bearer {old_token}"},
        )
        new_token = refresh.json()["installation_token"]
        old_still_valid = client.post(
            "/api/extension/v1/verify/text",
            headers={"Authorization": f"Bearer {old_token}"},
            json={"text": "Teks ini cukup panjang untuk memastikan token lama overlap."},
        )
        new_valid = client.post(
            "/api/extension/v1/verify/text",
            headers={"Authorization": f"Bearer {new_token}"},
            json={"text": "Teks ini cukup panjang untuk memastikan token baru aktif."},
        )

    assert refresh.status_code == 200
    assert refresh.json()["installation_id"]
    assert new_token != old_token
    assert old_still_valid.status_code == 200
    assert new_valid.status_code == 200


def test_extension_token_expired_and_blocked(monkeypatch, tmp_path) -> None:
    store_path = tmp_path / "installations.json"
    configure_extension_store(monkeypatch, tmp_path)

    with TestClient(app) as client:
        token = register_extension(client)

    store = json.loads(store_path.read_text(encoding="utf-8"))
    record = next(iter(store["installations"].values()))
    record["token_expires_at"] = (
        datetime.now(timezone.utc) - timedelta(minutes=1)
    ).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    store_path.write_text(json.dumps(store), encoding="utf-8")

    with TestClient(app) as client:
        expired = client.post(
            "/api/extension/v1/verify/text",
            headers={"Authorization": f"Bearer {token}"},
            json={"text": "Teks ini cukup panjang untuk token expired."},
        )

    record["token_expires_at"] = (
        datetime.now(timezone.utc) + timedelta(days=1)
    ).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    record["blocked"] = True
    store_path.write_text(json.dumps(store), encoding="utf-8")

    with TestClient(app) as client:
        blocked = client.post(
            "/api/extension/v1/verify/text",
            headers={"Authorization": f"Bearer {token}"},
            json={"text": "Teks ini cukup panjang untuk token blocked."},
        )

    assert expired.status_code == 401
    assert expired.json()["error"]["code"] == "INSTALLATION_TOKEN_EXPIRED"
    assert blocked.status_code == 403
    assert blocked.json()["error"]["code"] == "INSTALLATION_BLOCKED"


def test_extension_text_verification_supports_page_context(monkeypatch, tmp_path) -> None:
    configure_extension_store(monkeypatch, tmp_path)

    with TestClient(app) as client:
        token = register_extension(client)
        response = client.post(
            "/api/extension/v1/verify/text",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "text": "Pemerintah disebut memberikan bantuan Rp5 juta untuk semua pemilik KTP.",
                "question": "Apakah informasi ini benar dan aman?",
                "source_url": "https://example.com/artikel?utm_source=tracking#frag",
                "sender_context": "SOCIAL_MEDIA",
                "page_context": {
                    "title": "Posting viral bantuan",
                    "before": "Unggahan ramai dibagikan hari ini.",
                    "after": "Komentar meminta pembaca segera klik link.",
                },
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "COMPLETED"
    assert "data" not in body
    assert body["input_summary"]["source_url"] == "https://example.com/artikel"


def test_extension_page_context_validation_errors_use_public_envelope(
    monkeypatch,
    tmp_path,
) -> None:
    configure_extension_store(monkeypatch, tmp_path)

    with TestClient(app) as client:
        token = register_extension(client)
        empty_context = client.post(
            "/api/extension/v1/verify/text",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "text": "Teks ini cukup panjang untuk pemeriksaan extension.",
                "page_context": {},
            },
        )
        too_long_title = client.post(
            "/api/extension/v1/verify/text",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "text": "Teks ini cukup panjang untuk pemeriksaan extension.",
                "page_context": {"title": "x" * 301},
            },
        )

    assert empty_context.status_code == 422
    assert empty_context.json()["error"]["code"] == "VALIDATION_ERROR"
    assert too_long_title.status_code == 422
    assert too_long_title.json()["error"]["code"] == "VALIDATION_ERROR"


def test_extension_text_rate_limit_per_installation(monkeypatch, tmp_path) -> None:
    configure_extension_store(monkeypatch, tmp_path, EXTENSION_TEXT_INSTALLATION_LIMIT_PER_MINUTE=1)

    with TestClient(app) as client:
        token = register_extension(client)
        first = client.post(
            "/api/extension/v1/verify/text",
            headers={"Authorization": f"Bearer {token}"},
            json={"text": "Teks ini cukup panjang untuk request pertama."},
        )
        second = client.post(
            "/api/extension/v1/verify/text",
            headers={"Authorization": f"Bearer {token}"},
            json={"text": "Teks ini cukup panjang untuk request kedua."},
        )

    assert first.status_code == 200
    assert second.status_code == 429
    assert second.headers["retry-after"]
    assert second.json()["error"]["code"] == "RATE_LIMITED"


def test_extension_image_validation_uses_public_error_envelope(monkeypatch, tmp_path) -> None:
    configure_extension_store(monkeypatch, tmp_path)

    with TestClient(app) as client:
        token = register_extension(client)
        bad_media = client.post(
            "/api/extension/v1/verify/image",
            headers={"Authorization": f"Bearer {token}"},
            files={"image": ("not-image.txt", b"hello", "text/plain")},
        )
        arbitrary_url = client.post(
            "/api/extension/v1/verify/image",
            headers={"Authorization": f"Bearer {token}"},
            data={"image_url": "https://example.com/image.png"},
        )

    assert bad_media.status_code == 415
    assert bad_media.json()["error"]["code"] == "UNSUPPORTED_MEDIA_TYPE"
    assert arbitrary_url.status_code == 422
    assert arbitrary_url.json()["error"]["code"] == "VALIDATION_ERROR"


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
