"""Observe Groq rate-limit response headers without spending extra requests."""

from __future__ import annotations

import re
import threading
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

from app.config import Settings


_DURATION_PATTERN = re.compile(
    r"^\s*(?:(?P<days>\d+(?:\.\d+)?)d)?"
    r"(?:(?P<hours>\d+(?:\.\d+)?)h)?"
    r"(?:(?P<minutes>\d+(?:\.\d+)?)m)?"
    r"(?:(?P<seconds>\d+(?:\.\d+)?)s)?\s*$",
    re.IGNORECASE,
)

# Published Groq limits checked on 2026-08-23. `None` means Groq displays "-"
# or does not publish that dimension for the selected plan/model.
_PUBLISHED_LIMITS: dict[str, dict[str, dict[str, int | None]]] = {
    "free": {
        "qwen/qwen3.6-27b": {"rpm": 30, "rpd": 1_000, "tpm": 8_000, "tpd": 200_000},
        "openai/gpt-oss-20b": {"rpm": 30, "rpd": 1_000, "tpm": 8_000, "tpd": 200_000},
        "openai/gpt-oss-120b": {"rpm": 30, "rpd": 1_000, "tpm": 8_000, "tpd": 200_000},
    },
    "developer": {
        "qwen/qwen3.6-27b": {"rpm": 1_000, "rpd": None, "tpm": 250_000, "tpd": None},
        "openai/gpt-oss-20b": {"rpm": 1_000, "rpd": None, "tpm": 250_000, "tpd": None},
        "openai/gpt-oss-120b": {"rpm": 1_000, "rpd": None, "tpm": 250_000, "tpd": None},
    },
}


class GroqRateLimitMonitor:
    """Latest per-model quota snapshot observed from Groq response headers."""

    def __init__(self, settings: Settings) -> None:
        self.reference_plan = settings.groq_rate_limit_reference_plan
        self._lock = threading.RLock()
        self._models = _configured_models(settings)
        self._observed: dict[str, dict[str, Any]] = {}

    def observe(
        self,
        model: str,
        headers: Mapping[str, str],
        *,
        status_code: int,
    ) -> None:
        normalized = {str(key).lower(): str(value) for key, value in headers.items()}
        now = datetime.now(timezone.utc)
        token_reset_seconds = _duration_seconds(normalized.get("x-ratelimit-reset-tokens"))
        request_reset_seconds = _duration_seconds(normalized.get("x-ratelimit-reset-requests"))
        retry_after_seconds = _numeric_seconds(normalized.get("retry-after"))
        snapshot = {
            "observed_at": now.isoformat(),
            "status_code": status_code,
            "source": "groq-response-headers",
            "requests": {
                "scope": "RPD",
                "limit": _integer(normalized.get("x-ratelimit-limit-requests")),
                "remaining": _integer(normalized.get("x-ratelimit-remaining-requests")),
                "reset_raw": normalized.get("x-ratelimit-reset-requests"),
                "reset_at": _future_iso(now, request_reset_seconds),
            },
            "tokens": {
                "scope": "TPM",
                "limit": _integer(normalized.get("x-ratelimit-limit-tokens")),
                "remaining": _integer(normalized.get("x-ratelimit-remaining-tokens")),
                "reset_raw": normalized.get("x-ratelimit-reset-tokens"),
                "reset_at": _future_iso(now, token_reset_seconds),
            },
            "retry_after_seconds": retry_after_seconds,
        }
        with self._lock:
            self._observed[model] = snapshot

    def snapshot(self) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        with self._lock:
            items = []
            for model, roles in self._models.items():
                observed = deepcopy(self._observed.get(model))
                item: dict[str, Any] = {
                    "model": model,
                    "roles": roles,
                    "observed": observed is not None,
                    "reference_limits": deepcopy(
                        _PUBLISHED_LIMITS[self.reference_plan].get(
                            model,
                            {"rpm": None, "rpd": None, "tpm": None, "tpd": None},
                        )
                    ),
                }
                if observed:
                    observed["age_seconds"] = max(
                        0,
                        round((now - datetime.fromisoformat(observed["observed_at"])).total_seconds()),
                    )
                    for dimension in ("requests", "tokens"):
                        reset_in_seconds = _seconds_until(
                            observed[dimension].get("reset_at"), now
                        )
                        observed[dimension]["reset_in_seconds"] = reset_in_seconds
                        window_elapsed = (
                            observed[dimension].get("reset_at") is not None
                            and reset_in_seconds == 0
                        )
                        observed[dimension]["window_state"] = (
                            "RESET_ELAPSED_AWAITING_OBSERVATION"
                            if window_elapsed
                            else "ACTIVE"
                        )
                        if window_elapsed:
                            observed[dimension]["last_observed_remaining"] = observed[
                                dimension
                            ].get("remaining")
                            observed[dimension]["remaining"] = None
                    item.update(observed)
                items.append(item)
            return {
                "mode": "LIVE",
                "models": items,
                "observed_model_count": sum(1 for item in items if item["observed"]),
                "updated_at": now.isoformat(),
                "measurement": "passive-response-headers",
                "reference_plan": self.reference_plan.upper(),
                "reference_source": "https://console.groq.com/docs/rate-limits",
                "does_not_make_provider_request": True,
                "scope_notice": (
                    "RPM/RPD/TPM/TPD adalah jatah referensi plan. Header aktual hanya "
                    "memberikan remaining RPD dan TPM. Setelah reset, jatah tetap tampil "
                    "sementara remaining menunggu respons model berikutnya."
                ),
            }


def _configured_models(settings: Settings) -> dict[str, list[str]]:
    entries = [
        (settings.groq_vision_model, "Vision understanding"),
        (settings.groq_planner_model, "Investigation planner"),
        (settings.groq_final_model, "Verifier & response generator"),
    ]
    if settings.planner_review_enabled:
        entries.append((settings.groq_escalation_model, "Planner escalation"))
    models: dict[str, list[str]] = {}
    for model, role in entries:
        roles = models.setdefault(model, [])
        if role not in roles:
            roles.append(role)
    return models


def _integer(value: str | None) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _numeric_seconds(value: str | None) -> float | None:
    try:
        return max(0.0, float(value)) if value is not None else None
    except (TypeError, ValueError):
        return _duration_seconds(value)


def _duration_seconds(value: str | None) -> float | None:
    if not value:
        return None
    match = _DURATION_PATTERN.fullmatch(value)
    if not match or not any(match.groupdict().values()):
        return None
    units = {key: float(raw or 0) for key, raw in match.groupdict().items()}
    return max(
        0.0,
        units["days"] * 86_400
        + units["hours"] * 3_600
        + units["minutes"] * 60
        + units["seconds"],
    )


def _future_iso(now: datetime, seconds: float | None) -> str | None:
    return (now + timedelta(seconds=seconds)).isoformat() if seconds is not None else None


def _seconds_until(value: str | None, now: datetime) -> int | None:
    if not value:
        return None
    try:
        return max(0, round((datetime.fromisoformat(value) - now).total_seconds()))
    except ValueError:
        return None
