import io
import json
from html.parser import HTMLParser

from fastapi.testclient import TestClient
from PIL import Image

from app.config import Settings, get_settings
from app.main import app
from app.services.debug_trace import DebugTraceStore


class IdCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.ids: set[str] = set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        element_id = dict(attrs).get("id")
        if element_id:
            self.ids.add(element_id)


def _png_payload() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (320, 240), color=(238, 232, 219)).save(buffer, format="PNG")
    return buffer.getvalue()


def _submit_private_text(client: TestClient):
    return client.post(
        "/api/v1/verify/text",
        json={
            "text": (
                "Hubungi user@example.com dan gunakan kode OTP 123456 untuk "
                "memeriksa klaim bantuan pemerintah Rp5 juta malam ini."
            ),
            "question": "Apakah pesan dari nomor tidak dikenal ini aman?",
            "source_url": "https://example.com/news?token=trace-secret#section",
            "sender_context": "UNKNOWN_NUMBER",
        },
    )


def test_debug_page_has_readable_trace_workspace() -> None:
    with TestClient(app) as client:
        response = client.get("/debug")

    assert response.status_code == 200
    parser = IdCollector()
    parser.feed(response.text)
    assert {
        "debugStatus",
        "traceSearch",
        "inputFilter",
        "statusFilter",
        "refreshButton",
        "traceList",
        "traceDetail",
        "stageTimeline",
        "privacyBanner",
    } <= parser.ids
    assert 'name="robots" content="noindex,nofollow"' in response.text


def test_text_trace_covers_every_shared_stage_and_redacts_private_values() -> None:
    with TestClient(app) as client:
        response = _submit_private_text(client)
        assert response.status_code == 200
        trace_id = response.json()["trace_id"]
        listing = client.get("/api/v1/debug/traces")
        detail = client.get(f"/api/v1/debug/traces/{trace_id}")

    assert listing.status_code == 200
    assert listing.json()["items"][0]["trace_id"] == trace_id
    body = detail.json()
    keys = [stage["key"] for stage in body["stages"]]
    assert keys == [
        "text_input_adapter",
        "signal_extraction",
        "rulebook_retrieval",
        "investigation_planner",
        "planner_validation",
        "planner_review",
        "web_search",
        "domain_evidence",
        "community_evidence",
        "evidence_aggregation",
        "post_retrieval_guardrail",
        "verifier",
        "response_builder",
    ]
    planner = next(stage for stage in body["stages"] if stage["key"] == "investigation_planner")
    assert planner["instruction"]["role"] == "Investigation Planner · 20B First Pass"
    assert planner["instruction"]["execution"] == "ACTIVE"
    review = next(stage for stage in body["stages"] if stage["key"] == "planner_review")
    assert review["status"] in {"COMPLETED", "SKIPPED"}
    assert review["instruction"]["role"] == "Senior Investigation Plan Reviewer"
    serialized = json.dumps(body, ensure_ascii=False)
    assert "user@example.com" not in serialized
    assert "123456" not in serialized
    assert "gsk_" not in serialized
    assert "trace-secret" not in serialized
    assert body["privacy"]["raw_input_stored"] is False


def test_image_trace_includes_ocr_vision_and_shared_pipeline() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/verify/image",
            files={"image": ("sample.png", _png_payload(), "image/png")},
            data={"question": "Apakah gambar ini benar?"},
        )
        trace = client.get(f"/api/v1/debug/traces/{response.json()['trace_id']}").json()

    keys = {stage["key"] for stage in trace["stages"]}
    assert {"image_preprocessing", "vision_understanding", "case_adapter"} <= keys
    assert {
        "signal_extraction",
        "rulebook_retrieval",
        "investigation_planner",
        "planner_validation",
        "planner_review",
        "evidence_aggregation",
        "verifier",
        "response_builder",
    } <= keys
    vision = next(stage for stage in trace["stages"] if stage["key"] == "vision_understanding")
    assert vision["status"] == "COMPLETED"
    assert vision["instruction"]["role"] == "Vision Understanding"


def test_trace_store_is_fifo_bounded_and_defensively_sanitized() -> None:
    settings = Settings(
        _env_file=None,
        app_env="development",
        debug_trace_enabled=True,
        debug_trace_max_records=2,
    )
    store = DebugTraceStore(settings)
    for index in range(3):
        store.start(f"trace_{index}", f"req_{index}", "TEXT", "LIVE")
    store.add_stage(
        "trace_2",
        key="privacy_test",
        label="Privacy test",
        input_data={
            "api_key": "gsk_supersecretvalue",
            "raw_text": "private input",
            "message": "OTP 998877 dikirim ke private@example.com",
            "reference": "https://example.com/item?session=should_disappear#fragment",
        },
    )
    store.fail("trace_2", RuntimeError("provider payload with gsk_should_never_appear"))

    assert [item["trace_id"] for item in store.list()] == ["trace_2", "trace_1"]
    assert store.get("trace_0") is None
    serialized = json.dumps(store.get("trace_2"), ensure_ascii=False)
    assert "supersecretvalue" not in serialized
    assert "private input" not in serialized
    assert "998877" not in serialized
    assert "private@example.com" not in serialized
    assert "should_disappear" not in serialized
    assert "should_never_appear" not in serialized
    assert store.get("trace_2")["stages"][-1]["key"] == "pipeline_error"
    assert store.get("trace_2")["stages"][-1]["output"]["type"] == "RuntimeError"


def test_debug_routes_are_disabled_in_production(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("DEBUG_TRACE_ENABLED", "true")
    get_settings.cache_clear()
    try:
        with TestClient(app) as client:
            assert client.get("/debug").status_code == 404
            assert client.get("/api/v1/debug/traces").status_code == 404
            assert client.get("/api/health").json()["debug_trace"]["enabled"] is False
    finally:
        get_settings.cache_clear()
