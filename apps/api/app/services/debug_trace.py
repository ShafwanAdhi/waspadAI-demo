"""Bounded, privacy-filtered in-memory observability for local tuning.

This module deliberately does not persist traces. It accepts only derived,
redacted pipeline values and applies a second defensive sanitization pass.
"""

from __future__ import annotations

import json
import re
import threading
import time
from collections import OrderedDict
from contextvars import ContextVar
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel

from app.config import Settings
from app.services.input_adapters import sanitize_urls_in_text
from app.services.privacy import redact_pii


_current_trace_id: ContextVar[str | None] = ContextVar("debug_trace_id", default=None)
_SECRET_KEYS = {
    "api_key",
    "authorization",
    "cookie",
    "password",
    "secret",
    "access_token",
    "refresh_token",
    "image_data_url",
    "raw_image",
    "raw_text",
}
_SECRET_PATTERNS = (
    re.compile(r"\bgsk_[A-Za-z0-9_-]{8,}\b"),
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~-]{8,}"),
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class DebugTraceStore:
    """Thread-safe FIFO trace store with a strict record cap."""

    def __init__(self, settings: Settings) -> None:
        self.enabled = settings.debug_enabled
        self.max_records = settings.debug_trace_max_records
        self.max_value_chars = settings.debug_trace_max_value_chars
        self._records: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self._started_perf: dict[str, float] = {}
        self._lock = threading.RLock()

    @property
    def health(self) -> dict[str, Any]:
        with self._lock:
            return {
                "enabled": self.enabled,
                "storage": "bounded-memory",
                "record_count": len(self._records),
                "max_records": self.max_records,
                "raw_input_stored": False,
            }

    def start(self, trace_id: str, request_id: str, input_type: str, mode: str) -> None:
        if not self.enabled:
            return
        _current_trace_id.set(trace_id)
        with self._lock:
            self._records[trace_id] = {
                "trace_id": trace_id,
                "request_id": request_id,
                "input_type": input_type,
                "mode": mode,
                "status": "RUNNING",
                "started_at": utc_now(),
                "completed_at": None,
                "duration_ms": None,
                "label": f"Input {input_type.lower()} baru",
                "summary": {},
                "stages": [],
                "privacy": {
                    "raw_input_stored": False,
                    "image_binary_stored": False,
                    "credentials_stored": False,
                    "persistence": "none; hilang saat server restart",
                },
            }
            self._started_perf[trace_id] = time.perf_counter()
            self._records.move_to_end(trace_id)
            while len(self._records) > self.max_records:
                oldest_id, _ = self._records.popitem(last=False)
                self._started_perf.pop(oldest_id, None)

    def set_input_summary(self, trace_id: str, summary: Any) -> None:
        if not self.enabled:
            return
        safe_summary = self._sanitize(summary)
        with self._lock:
            record = self._records.get(trace_id)
            if not record:
                return
            record["input_summary"] = safe_summary
            if isinstance(safe_summary, dict):
                record["label"] = str(safe_summary.get("label") or record["label"])

    def add_stage(
        self,
        trace_id: str,
        *,
        key: str,
        label: str,
        status: str = "COMPLETED",
        duration_ms: int = 0,
        runtime: str = "LOCAL",
        model: str | None = None,
        input_data: Any = None,
        output_data: Any = None,
        instruction: Any = None,
        notes: list[str] | None = None,
    ) -> None:
        if not self.enabled:
            return
        stage = {
            "sequence": 0,
            "key": key,
            "label": label,
            "status": status,
            "duration_ms": max(0, int(duration_ms)),
            "runtime": runtime,
            "model": model,
            "input": self._sanitize(input_data),
            "output": self._sanitize(output_data),
            "instruction": self._sanitize(instruction),
            "notes": self._sanitize(notes or []),
            "recorded_at": utc_now(),
        }
        with self._lock:
            record = self._records.get(trace_id)
            if not record:
                return
            stage["sequence"] = len(record["stages"]) + 1
            record["stages"].append(stage)

    def complete(self, trace_id: str, response: Any) -> None:
        if not self.enabled:
            return
        response_data = self._sanitize(response)
        with self._lock:
            record = self._records.get(trace_id)
            if not record:
                return
            elapsed = self._elapsed(trace_id)
            record.update(
                status="COMPLETED",
                completed_at=utc_now(),
                duration_ms=elapsed,
            )
            if isinstance(response_data, dict):
                record["summary"] = {
                    key: response_data.get(key)
                    for key in (
                        "verdict",
                        "risk_level",
                        "headline",
                        "evidence_sufficiency",
                        "requires_human_review",
                    )
                }

    def fail(self, trace_id: str, exc: BaseException) -> None:
        if not self.enabled:
            return
        with self._lock:
            record = self._records.get(trace_id)
            if not record or record["status"] == "COMPLETED":
                return
            last_stage = record["stages"][-1]["key"] if record["stages"] else None
            safe_error = {
                "type": type(exc).__name__,
                "status_code": getattr(exc, "status_code", None),
                "provider_request_id": self._sanitize(getattr(exc, "request_id", None)),
                "last_recorded_stage": last_stage,
                "message": "Detail mentah disembunyikan untuk mencegah kebocoran data.",
            }
            record["stages"].append(
                {
                    "sequence": len(record["stages"]) + 1,
                    "key": "pipeline_error",
                    "label": "Pipeline dihentikan",
                    "status": "FAILED",
                    "duration_ms": 0,
                    "runtime": "ERROR_BOUNDARY",
                    "model": None,
                    "input": {"last_recorded_stage": last_stage},
                    "output": safe_error,
                    "instruction": None,
                    "notes": ["Periksa tahap terakhir; raw exception dan payload provider tidak dicatat."],
                    "recorded_at": utc_now(),
                }
            )
            record.update(
                status="FAILED",
                completed_at=utc_now(),
                duration_ms=self._elapsed(trace_id),
                error=safe_error,
                summary={
                    "headline": (
                        f"Pipeline berhenti setelah tahap {last_stage}."
                        if last_stage
                        else "Pipeline berhenti sebelum satu tahap selesai."
                    )
                },
            )

    def fail_active(self, exc: BaseException) -> None:
        trace_id = _current_trace_id.get()
        if trace_id:
            self.fail(trace_id, exc)

    def list(self) -> list[dict[str, Any]]:
        if not self.enabled:
            return []
        with self._lock:
            records = reversed(self._records.values())
            return [
                {
                    "trace_id": item["trace_id"],
                    "request_id": item["request_id"],
                    "input_type": item["input_type"],
                    "mode": item["mode"],
                    "status": item["status"],
                    "started_at": item["started_at"],
                    "duration_ms": item["duration_ms"],
                    "label": item["label"],
                    "summary": deepcopy(item["summary"]),
                    "stage_count": len(item["stages"]),
                }
                for item in records
            ]

    def get(self, trace_id: str) -> dict[str, Any] | None:
        if not self.enabled:
            return None
        with self._lock:
            record = self._records.get(trace_id)
            return deepcopy(record) if record else None

    def _elapsed(self, trace_id: str) -> int:
        started = self._started_perf.pop(trace_id, None)
        return round((time.perf_counter() - started) * 1000) if started else 0

    def _sanitize(self, value: Any, depth: int = 0) -> Any:
        if value is None or isinstance(value, (bool, int, float)):
            return value
        if depth > 10:
            return "[DEPTH_LIMIT]"
        if isinstance(value, BaseModel):
            value = value.model_dump(mode="json")
        if isinstance(value, dict):
            safe: dict[str, Any] = {}
            for raw_key, item in value.items():
                key = str(raw_key)
                if key.lower() in _SECRET_KEYS:
                    safe[key] = "[REDACTED]"
                else:
                    safe[key] = self._sanitize(item, depth + 1)
            return self._limit(safe)
        if isinstance(value, (list, tuple, set)):
            return self._limit([self._sanitize(item, depth + 1) for item in value])
        safe_text, _ = sanitize_urls_in_text(str(value), max_urls=50)
        safe_text, _ = redact_pii(safe_text)
        for pattern in _SECRET_PATTERNS:
            safe_text = pattern.sub("[REDACTED_CREDENTIAL]", safe_text)
        if len(safe_text) > self.max_value_chars:
            return safe_text[: self.max_value_chars] + "… [TRUNCATED]"
        return safe_text

    def _limit(self, value: Any) -> Any:
        """Bound a container without returning malformed partial JSON."""
        serialized = json.dumps(value, ensure_ascii=False, default=str)
        if len(serialized) <= self.max_value_chars:
            return value
        if isinstance(value, list):
            kept: list[Any] = []
            for item in value:
                candidate = [*kept, item]
                if len(json.dumps(candidate, ensure_ascii=False, default=str)) > self.max_value_chars - 80:
                    break
                kept.append(item)
            kept.append({"_notice": "Item berikutnya dipotong oleh batas debug trace."})
            return kept
        if isinstance(value, dict):
            kept_dict: dict[str, Any] = {}
            for key, item in value.items():
                candidate = {**kept_dict, key: item}
                if len(json.dumps(candidate, ensure_ascii=False, default=str)) > self.max_value_chars - 80:
                    break
                kept_dict[key] = item
            kept_dict["_notice"] = "Field berikutnya dipotong oleh batas debug trace."
            return kept_dict
        return value


def instruction_profile(agent: str, model: str | None = None, *, simulated: bool = False) -> dict[str, Any]:
    """Structured snapshot of the app-owned instruction contract for each agent."""
    profiles: dict[str, dict[str, Any]] = {
        "vision": {
            "version": "vision.v1",
            "role": "Vision Understanding",
            "responsibilities": ["Koreksi konteks OCR", "Ekstraksi entitas dan klaim kandidat"],
            "invariants": ["Bukan penentu benar/salah", "Tidak menebak URL atau identitas"],
            "response_contract": "VisionOutput JSON",
        },
        "planner": {
            "version": "planner.v3",
            "role": "Investigation Planner · 20B First Pass",
            "responsibilities": ["Atomisasi klaim", "Routing domain", "Rencana retrieval dan critical checks"],
            "invariants": ["Rulebook adalah policy, bukan evidence", "Tidak memberi factual verdict", "Output harus lolos guardrail backend"],
            "response_contract": "PlannerDraftOutput JSON schema ketat → PlannerOutput backend",
        },
        "planner_review": {
            "version": "planner-review.v1",
            "role": "Senior Investigation Plan Reviewer",
            "responsibilities": ["Mereview draft tervalidasi", "Memperbaiki grounding, critical checks, dan routing"],
            "invariants": ["Menerima payload ringkas", "Tidak mengulang planning dari input penuh", "Tidak membuat klaim atau fakta baru"],
            "response_contract": "PlannerDraftOutput JSON schema ketat → PlannerOutput backend",
        },
        "search": {
            "version": "search.v1",
            "role": "Web Search Agent",
            "responsibilities": ["Mencari evidence per klaim", "Memprioritaskan sumber primer/resmi"],
            "invariants": ["Bukan verifier", "Tidak mengarang URL", "Instruksi halaman web diabaikan"],
            "response_contract": "Evidence[] JSON",
        },
        "verifier": {
            "version": "verifier.v2",
            "role": "Evidence Verifier & Response Generator",
            "responsibilities": ["Menilai klaim hanya dari evidence", "Menyusun verdict, ketidakpastian, dan tindakan aman"],
            "invariants": ["LLM bukan sumber kebenaran", "Rulebook tidak boleh SUPPORT/REFUTE klaim", "Low sufficiency mengunci UNVERIFIED", "Tidak membuat evidence ID baru"],
            "response_contract": "VerificationDecision JSON",
        },
    }
    profile = deepcopy(profiles.get(agent, {"version": "local.v1", "role": agent}))
    profile["model"] = model or "LOCAL_DETERMINISTIC"
    profile["execution"] = "SIMULATED" if simulated else "ACTIVE"
    return profile
