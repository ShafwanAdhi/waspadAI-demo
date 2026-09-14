from __future__ import annotations

import hashlib
import json
import secrets
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Lock
from typing import Any, AsyncIterator, Literal

from app.config import Settings


ExtensionModality = Literal["TEXT", "IMAGE"]


class ExtensionGatewayError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        status_code: int,
        retry_after_seconds: int | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.retry_after_seconds = retry_after_seconds


@dataclass(slots=True)
class ExtensionAuth:
    installation_id: str
    extension_version: str


class FixedWindowRateLimiter:
    def __init__(self) -> None:
        self._windows: dict[str, tuple[float, int]] = {}
        self._lock = Lock()

    def check(self, key: str, limit: int, window_seconds: int) -> int | None:
        now = time.time()
        with self._lock:
            start, count = self._windows.get(key, (now, 0))
            if now - start >= window_seconds:
                start, count = now, 0
            if count >= limit:
                return max(1, int(window_seconds - (now - start)))
            self._windows[key] = (start, count + 1)
            return None


class ExtensionGatewayService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.store_path = Path(settings.extension_installation_store_path)
        self._lock = Lock()
        self._rate_limiter = FixedWindowRateLimiter()
        self._active_requests: dict[str, int] = {}
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.store_path.exists():
            self._write_store({"installations": {}})

    def health(self) -> dict[str, Any]:
        return {
            "status": "ok",
            "auth": "anonymous_installation_bearer",
            "token_lifetime_days": self.settings.extension_token_lifetime_days,
            "rate_limits": {
                "registration_per_ip_per_hour": self.settings.extension_registration_ip_limit_per_hour,
                "text_per_installation_per_minute": self.settings.extension_text_installation_limit_per_minute,
                "image_per_installation_per_minute": self.settings.extension_image_installation_limit_per_minute,
                "verify_per_ip_per_minute": self.settings.extension_ip_verify_limit_per_minute,
                "concurrent_per_installation": self.settings.extension_concurrent_requests_per_installation,
            },
        }

    def create_installation(self, extension_version: str, ip_hash: str) -> dict[str, str]:
        retry_after = self._rate_limiter.check(
            f"register:ip:{ip_hash}",
            self.settings.extension_registration_ip_limit_per_hour,
            3600,
        )
        if retry_after is not None:
            raise ExtensionGatewayError(
                "RATE_LIMITED",
                "Batas pembuatan instalasi sementara tercapai.",
                429,
                retry_after,
            )

        token = _new_token()
        expires_at = _utcnow() + timedelta(days=self.settings.extension_token_lifetime_days)
        installation_id = f"inst_{secrets.token_hex(12)}"
        now = _iso(_utcnow())
        record = {
            "installation_id": installation_id,
            "extension_version": extension_version[:80] or "unknown",
            "token_hash": _token_hash(token),
            "token_expires_at": _iso(expires_at),
            "previous_token_hash": None,
            "previous_token_valid_until": None,
            "blocked": False,
            "created_at": now,
            "updated_at": now,
            "last_seen_at": now,
            "last_ip_hash": ip_hash,
        }
        with self._lock:
            store = self._read_store()
            store["installations"][installation_id] = record
            self._write_store(store)
        return _installation_response(installation_id, token, expires_at)

    def authenticate(self, authorization: str | None, ip_hash: str) -> ExtensionAuth:
        token = _bearer_token(authorization)
        token_hash = _token_hash(token)
        now = _utcnow()
        with self._lock:
            store = self._read_store()
            for record in store["installations"].values():
                if not _record_matches_token(record, token_hash, now):
                    continue
                if record.get("blocked"):
                    raise ExtensionGatewayError(
                        "INSTALLATION_BLOCKED",
                        "Instalasi extension diblokir.",
                        403,
                    )
                expires_at = _parse_utc(record["token_expires_at"])
                if now >= expires_at:
                    raise ExtensionGatewayError(
                        "INSTALLATION_TOKEN_EXPIRED",
                        "Token instalasi sudah kedaluwarsa.",
                        401,
                    )
                record["last_seen_at"] = _iso(now)
                record["last_ip_hash"] = ip_hash
                self._write_store(store)
                return ExtensionAuth(
                    installation_id=record["installation_id"],
                    extension_version=record.get("extension_version") or "unknown",
                )
        raise ExtensionGatewayError(
            "INVALID_INSTALLATION_TOKEN",
            "Token instalasi tidak valid.",
            401,
        )

    def refresh_installation(self, auth: ExtensionAuth, ip_hash: str) -> dict[str, str]:
        token = _new_token()
        expires_at = _utcnow() + timedelta(days=self.settings.extension_token_lifetime_days)
        previous_valid_until = _utcnow() + timedelta(seconds=self.settings.extension_token_overlap_seconds)
        with self._lock:
            store = self._read_store()
            record = store["installations"].get(auth.installation_id)
            if not record:
                raise ExtensionGatewayError(
                    "INVALID_INSTALLATION_TOKEN",
                    "Token instalasi tidak valid.",
                    401,
                )
            if record.get("blocked"):
                raise ExtensionGatewayError(
                    "INSTALLATION_BLOCKED",
                    "Instalasi extension diblokir.",
                    403,
                )
            record["previous_token_hash"] = record["token_hash"]
            record["previous_token_valid_until"] = _iso(previous_valid_until)
            record["token_hash"] = _token_hash(token)
            record["token_expires_at"] = _iso(expires_at)
            record["updated_at"] = _iso(_utcnow())
            record["last_seen_at"] = _iso(_utcnow())
            record["last_ip_hash"] = ip_hash
            self._write_store(store)
        return _installation_response(auth.installation_id, token, expires_at)

    @asynccontextmanager
    async def verification_slot(
        self,
        auth: ExtensionAuth,
        ip_hash: str,
        modality: ExtensionModality,
    ) -> AsyncIterator[None]:
        ip_retry_after = self._rate_limiter.check(
            f"verify:ip:{ip_hash}",
            self.settings.extension_ip_verify_limit_per_minute,
            60,
        )
        if ip_retry_after is not None:
            raise ExtensionGatewayError(
                "RATE_LIMITED",
                "Batas verifikasi dari IP ini sementara tercapai.",
                429,
                ip_retry_after,
            )

        limit = (
            self.settings.extension_text_installation_limit_per_minute
            if modality == "TEXT"
            else self.settings.extension_image_installation_limit_per_minute
        )
        installation_retry_after = self._rate_limiter.check(
            f"verify:{modality.lower()}:installation:{auth.installation_id}",
            limit,
            60,
        )
        if installation_retry_after is not None:
            raise ExtensionGatewayError(
                "RATE_LIMITED",
                "Batas verifikasi instalasi sementara tercapai.",
                429,
                installation_retry_after,
            )

        with self._lock:
            active = self._active_requests.get(auth.installation_id, 0)
            if active >= self.settings.extension_concurrent_requests_per_installation:
                raise ExtensionGatewayError(
                    "RATE_LIMITED",
                    "Terlalu banyak verifikasi bersamaan untuk instalasi ini.",
                    429,
                    10,
                )
            self._active_requests[auth.installation_id] = active + 1
        try:
            yield
        finally:
            with self._lock:
                active = self._active_requests.get(auth.installation_id, 0)
                if active <= 1:
                    self._active_requests.pop(auth.installation_id, None)
                else:
                    self._active_requests[auth.installation_id] = active - 1

    def _read_store(self) -> dict[str, Any]:
        try:
            return json.loads(self.store_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"installations": {}}

    def _write_store(self, store: dict[str, Any]) -> None:
        temp_path = self.store_path.with_suffix(".tmp")
        temp_path.write_text(json.dumps(store, indent=2, sort_keys=True), encoding="utf-8")
        temp_path.replace(self.store_path)


def _new_token() -> str:
    return secrets.token_urlsafe(48)


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _bearer_token(authorization: str | None) -> str:
    value = (authorization or "").strip()
    prefix = "Bearer "
    if not value.startswith(prefix):
        raise ExtensionGatewayError(
            "INVALID_INSTALLATION_TOKEN",
            "Header Authorization Bearer wajib diisi.",
            401,
        )
    token = value[len(prefix) :].strip()
    if not token:
        raise ExtensionGatewayError(
            "INVALID_INSTALLATION_TOKEN",
            "Token instalasi tidak valid.",
            401,
        )
    return token


def _record_matches_token(record: dict[str, Any], token_hash: str, now: datetime) -> bool:
    if record.get("token_hash") == token_hash:
        return True
    if record.get("previous_token_hash") != token_hash:
        return False
    valid_until = record.get("previous_token_valid_until")
    return bool(valid_until and now < _parse_utc(valid_until))


def _installation_response(
    installation_id: str,
    token: str,
    expires_at: datetime,
) -> dict[str, str]:
    return {
        "installation_id": installation_id,
        "installation_token": token,
        "token_type": "Bearer",
        "expires_at": _iso(expires_at),
    }


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
