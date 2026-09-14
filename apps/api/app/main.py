from contextlib import asynccontextmanager
from hashlib import sha256
from hmac import compare_digest
from pathlib import Path
from typing import Annotated
from uuid import uuid4

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from groq import AuthenticationError, RateLimitError

from app.config import get_settings
from app.schemas import (
    ExtensionInstallationRequest,
    ExtensionInstallationResponse,
    TextVerificationRequest,
    VerificationResponse,
)
from app.services.extension_gateway import ExtensionAuth, ExtensionGatewayError, ExtensionGatewayService
from app.services.image_processing import InvalidImageError, inspect_image
from app.services.input_adapters import InvalidTextInputError
from app.services.pipeline import FactCheckPipeline


STATIC_DIR = Path(__file__).resolve().parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    app.state.settings = settings
    app.state.pipeline = FactCheckPipeline(settings)
    app.state.extension_gateway = ExtensionGatewayService(settings)
    yield


app = FastAPI(
    title="WaspadAI API",
    version="0.6.0",
    description="API pemeriksaan multimodal berbasis bukti dan rulebook.",
    docs_url="/api/docs",
    redoc_url=None,
    lifespan=lifespan,
)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    return response


@app.middleware("http")
async def extension_cors(request: Request, call_next):
    if not _is_extension_path(request):
        return await call_next(request)

    settings = request.app.state.settings
    origin = request.headers.get("origin", "")
    allowed_origins = _allowed_extension_origins(settings)
    origin_allowed = origin in allowed_origins
    if request.method == "OPTIONS" and origin_allowed:
        response = JSONResponse(status_code=204, content=None)
    else:
        response = await call_next(request)

    if origin_allowed:
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Vary"] = "Origin"
        response.headers["Access-Control-Allow-Methods"] = "GET,POST,OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "Authorization,Content-Type"
        response.headers["Access-Control-Max-Age"] = "600"
    return response


@app.get("/", include_in_schema=False)
async def index() -> dict[str, str]:
    return {
        "service": "WaspadAI API",
        "health": "/api/health",
        "documentation": "/api/docs",
    }


@app.get("/debug", include_in_schema=False)
async def debug_page(request: Request) -> FileResponse:
    _debug_pipeline(request)
    return FileResponse(STATIC_DIR / "debug.html")


@app.get("/api/health")
async def health(request: Request) -> dict:
    settings = request.app.state.settings
    pipeline = request.app.state.pipeline
    return {
        "status": "ok",
        "mode": "LIVE",
        "ocr": "optional-local-tesseract",
        "architecture": "rulebook-guided-multimodal-pipeline",
        "input_types": ["IMAGE", "TEXT"],
        "planner_review": {
            "enabled": settings.planner_review_enabled,
            "model": settings.groq_escalation_model if settings.planner_review_enabled else None,
        },
        "web_search": pipeline.web_search.health,
        "rulebook_rag": pipeline.rulebook.health,
        "debug_trace": pipeline.debug_traces.health,
    }


@app.get("/api/extension/v1/health")
async def extension_health(request: Request) -> dict:
    gateway: ExtensionGatewayService = request.app.state.extension_gateway
    return gateway.health()


@app.get("/api/v1/debug/traces", include_in_schema=False)
async def list_debug_traces(request: Request) -> dict:
    pipeline = _debug_pipeline(request)
    items = pipeline.debug_traces.list()
    return {
        "items": items,
        "count": len(items),
        "retention": pipeline.debug_traces.health,
    }


@app.get("/api/v1/debug/traces/{trace_id}", include_in_schema=False)
async def get_debug_trace(trace_id: str, request: Request) -> dict:
    pipeline = _debug_pipeline(request)
    trace = pipeline.debug_traces.get(trace_id)
    if trace is None:
        raise HTTPException(status_code=404, detail="Trace tidak ditemukan atau sudah terhapus dari memori.")
    return trace


@app.get("/api/v1/debug/groq-rate-limits", include_in_schema=False)
async def get_groq_rate_limits(request: Request) -> dict:
    pipeline = _debug_pipeline(request)
    return pipeline.rate_limits.snapshot()


def _configured_internal_api_keys(settings) -> list[str]:
    return [
        item.strip()
        for item in settings.waspadai_api_keys.split(",")
        if item.strip()
    ]


def _require_internal_api_key(
    request: Request,
    x_waspadai_api_key: Annotated[str | None, Header()] = None,
) -> None:
    settings = request.app.state.settings
    configured_keys = _configured_internal_api_keys(settings)
    if not configured_keys:
        raise HTTPException(
            status_code=503,
            detail="WASPADAI_API_KEYS belum dikonfigurasi untuk API internal.",
        )

    supplied_key = (x_waspadai_api_key or "").strip()
    if not supplied_key:
        raise HTTPException(status_code=401, detail="Header X-Waspadai-API-Key wajib diisi.")

    if not any(compare_digest(supplied_key, expected_key) for expected_key in configured_keys):
        raise HTTPException(status_code=401, detail="API key internal tidak valid.")


def _extension_auth(
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
) -> ExtensionAuth:
    gateway: ExtensionGatewayService = request.app.state.extension_gateway
    return gateway.authenticate(authorization, _request_ip_hash(request))


@app.post(
    "/api/extension/v1/installations",
    response_model=ExtensionInstallationResponse,
    status_code=201,
)
async def create_extension_installation(
    request: Request,
    payload: ExtensionInstallationRequest,
) -> ExtensionInstallationResponse:
    gateway: ExtensionGatewayService = request.app.state.extension_gateway
    response = gateway.create_installation(payload.extension_version, _request_ip_hash(request))
    return ExtensionInstallationResponse(**response)


@app.post("/api/extension/v1/installations/refresh", response_model=ExtensionInstallationResponse)
async def refresh_extension_installation(
    request: Request,
    auth: Annotated[ExtensionAuth, Depends(_extension_auth)],
) -> ExtensionInstallationResponse:
    gateway: ExtensionGatewayService = request.app.state.extension_gateway
    response = gateway.refresh_installation(auth, _request_ip_hash(request))
    return ExtensionInstallationResponse(**response)


@app.post("/api/extension/v1/verify/text", response_model=VerificationResponse)
async def verify_extension_text(
    request: Request,
    payload: TextVerificationRequest,
    auth: Annotated[ExtensionAuth, Depends(_extension_auth)],
) -> VerificationResponse:
    gateway: ExtensionGatewayService = request.app.state.extension_gateway
    async with gateway.verification_slot(auth, _request_ip_hash(request), "TEXT"):
        return await _verify_text(request, payload)


@app.post("/api/extension/v1/verify/image", response_model=VerificationResponse)
async def verify_extension_image(
    request: Request,
    auth: Annotated[ExtensionAuth, Depends(_extension_auth)],
    image: UploadFile = File(...),
    question: str = Form("Apakah informasi dalam gambar ini benar dan aman ditindaklanjuti?"),
) -> VerificationResponse:
    gateway: ExtensionGatewayService = request.app.state.extension_gateway
    async with gateway.verification_slot(auth, _request_ip_hash(request), "IMAGE"):
        return await _verify_image(request, image, question)


@app.post("/api/v1/verify/image", response_model=VerificationResponse)
async def verify_image(
    request: Request,
    image: UploadFile = File(...),
    question: str = Form("Apakah informasi dalam gambar ini benar dan aman ditindaklanjuti?"),
) -> VerificationResponse:
    return await _verify_image(request, image, question)


@app.post("/api/internal/v1/verify/image", response_model=VerificationResponse)
async def verify_internal_image(
    request: Request,
    _: Annotated[None, Depends(_require_internal_api_key)],
    image: UploadFile = File(...),
    question: str = Form("Apakah informasi dalam gambar ini benar dan aman ditindaklanjuti?"),
) -> VerificationResponse:
    return await _verify_image(request, image, question)


@app.post("/api/v1/verify/text", response_model=VerificationResponse)
async def verify_text(
    request: Request,
    payload: TextVerificationRequest,
) -> VerificationResponse:
    return await _verify_text(request, payload)


@app.post("/api/internal/v1/verify/text", response_model=VerificationResponse)
async def verify_internal_text(
    request: Request,
    payload: TextVerificationRequest,
    _: Annotated[None, Depends(_require_internal_api_key)],
) -> VerificationResponse:
    return await _verify_text(request, payload)


async def _verify_image(
    request: Request,
    image: UploadFile,
    question: str,
) -> VerificationResponse:
    settings = request.app.state.settings
    max_bytes = settings.max_upload_mb * 1024 * 1024
    payload = await image.read(max_bytes + 1)
    await image.close()

    if not payload:
        raise HTTPException(status_code=400, detail="Pilih gambar terlebih dahulu.")
    if len(payload) > max_bytes:
        raise HTTPException(status_code=413, detail=f"Ukuran gambar maksimal {settings.max_upload_mb} MB.")
    if len(question.strip()) > settings.max_image_question_chars:
        raise HTTPException(
            status_code=422,
            detail=f"Pertanyaan maksimal {settings.max_image_question_chars} karakter.",
        )
    if not settings.groq_api_key.strip():
        raise HTTPException(status_code=503, detail="GROQ_API_KEY belum diisi pada file .env.")

    try:
        pil_image, metadata = inspect_image(payload, settings)
        return await request.app.state.pipeline.verify_image(
            image=pil_image,
            metadata=metadata,
            filename=image.filename or "gambar",
            question=question.strip(),
        )
    except InvalidImageError as exc:
        request.app.state.pipeline.debug_traces.fail_active(exc)
        raise HTTPException(status_code=415, detail=str(exc)) from exc
    except RateLimitError as exc:
        request.app.state.pipeline.debug_traces.fail_active(exc)
        retry_after = exc.response.headers.get("retry-after", "15")
        try:
            wait_seconds = max(1, round(float(retry_after)))
        except (TypeError, ValueError):
            wait_seconds = 15
        raise HTTPException(
            status_code=429,
            detail=f"Batas pemakaian Groq sementara tercapai. Tunggu sekitar {wait_seconds} detik lalu coba lagi.",
            headers={"Retry-After": str(wait_seconds)},
        ) from exc
    except AuthenticationError as exc:
        request.app.state.pipeline.debug_traces.fail_active(exc)
        raise HTTPException(
            status_code=502,
            detail="API key Groq ditolak. Periksa kembali GROQ_API_KEY pada file .env.",
        ) from exc
    except HTTPException:
        raise
    except Exception as exc:
        request.app.state.pipeline.debug_traces.fail_active(exc)
        # Raw image/OCR content and credentials are intentionally never included.
        raise HTTPException(
            status_code=502,
            detail=f"Pipeline pemeriksaan gagal pada layanan eksternal ({type(exc).__name__}). Coba lagi.",
        ) from exc


async def _verify_text(
    request: Request,
    payload: TextVerificationRequest,
) -> VerificationResponse:
    settings = request.app.state.settings
    text = payload.text.strip()
    question = payload.question.strip()
    if len(text) < settings.min_text_chars:
        raise HTTPException(
            status_code=422,
            detail=f"Teks minimal {settings.min_text_chars} karakter.",
        )
    if len(text) > settings.max_text_chars:
        raise HTTPException(
            status_code=413,
            detail=f"Teks maksimal {settings.max_text_chars:,} karakter.",
        )
    if not question:
        question = "Apakah isi teks ini benar dan aman ditindaklanjuti?"
    if not settings.groq_api_key.strip():
        raise HTTPException(status_code=503, detail="GROQ_API_KEY belum diisi pada file .env.")

    try:
        return await request.app.state.pipeline.verify_text(
            text=text,
            question=question,
            source_url=payload.source_url,
            sender_context=payload.sender_context,
            page_context=payload.page_context,
        )
    except InvalidTextInputError as exc:
        request.app.state.pipeline.debug_traces.fail_active(exc)
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RateLimitError as exc:
        request.app.state.pipeline.debug_traces.fail_active(exc)
        retry_after = exc.response.headers.get("retry-after", "15")
        try:
            wait_seconds = max(1, round(float(retry_after)))
        except (TypeError, ValueError):
            wait_seconds = 15
        raise HTTPException(
            status_code=429,
            detail=f"Batas pemakaian Groq sementara tercapai. Tunggu sekitar {wait_seconds} detik lalu coba lagi.",
            headers={"Retry-After": str(wait_seconds)},
        ) from exc
    except AuthenticationError as exc:
        request.app.state.pipeline.debug_traces.fail_active(exc)
        raise HTTPException(
            status_code=502,
            detail="API key Groq ditolak. Periksa kembali GROQ_API_KEY pada file .env.",
        ) from exc
    except HTTPException:
        raise
    except Exception as exc:
        request.app.state.pipeline.debug_traces.fail_active(exc)
        # Raw text and credentials are intentionally never included in errors.
        raise HTTPException(
            status_code=502,
            detail=f"Pipeline pemeriksaan gagal pada layanan eksternal ({type(exc).__name__}). Coba lagi.",
        ) from exc


@app.exception_handler(ExtensionGatewayError)
async def extension_gateway_error(_: Request, exc: ExtensionGatewayError) -> JSONResponse:
    headers = {}
    if exc.retry_after_seconds is not None:
        headers["Retry-After"] = str(exc.retry_after_seconds)
    return _extension_error_response(
        status_code=exc.status_code,
        code=exc.code,
        message=exc.message,
        retry_after_seconds=exc.retry_after_seconds,
        headers=headers,
    )


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    if _is_extension_path(request):
        return _extension_error_response(
            status_code=422,
            code="VALIDATION_ERROR",
            message="Request atau field tidak valid.",
        )
    return JSONResponse(status_code=422, content={"detail": exc.errors()})


@app.exception_handler(HTTPException)
async def http_error(request: Request, exc: HTTPException) -> JSONResponse:
    if _is_extension_path(request):
        retry_after = _retry_after_seconds(exc.headers)
        return _extension_error_response(
            status_code=exc.status_code,
            code=_extension_error_code(exc.status_code),
            message=_public_extension_message(exc),
            retry_after_seconds=retry_after,
            headers=exc.headers,
        )
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
        headers=exc.headers,
    )


def _debug_pipeline(request: Request) -> FactCheckPipeline:
    """Expose traces only from a direct local client in non-production."""
    settings = request.app.state.settings
    client_host = request.client.host if request.client else ""
    if not settings.debug_enabled or client_host not in {"127.0.0.1", "::1", "testclient"}:
        raise HTTPException(status_code=404, detail="Rute tidak ditemukan.")
    return request.app.state.pipeline


def _request_ip_hash(request: Request) -> str:
    forwarded_for = request.headers.get("x-forwarded-for", "")
    raw_ip = forwarded_for.split(",", 1)[0].strip()
    if not raw_ip and request.client:
        raw_ip = request.client.host
    return sha256((raw_ip or "unknown").encode("utf-8")).hexdigest()


def _is_extension_path(request: Request) -> bool:
    return request.url.path.startswith("/api/extension/v1/")


def _allowed_extension_origins(settings) -> set[str]:
    return {
        item.strip()
        for item in settings.extension_allowed_origins.split(",")
        if item.strip()
    }


def _retry_after_seconds(headers: dict[str, str] | None) -> int | None:
    if not headers:
        return None
    value = headers.get("Retry-After") or headers.get("retry-after")
    if value is None:
        return None
    try:
        return max(1, int(float(value)))
    except ValueError:
        return None


def _extension_error_code(status_code: int) -> str:
    return {
        401: "INVALID_INSTALLATION_TOKEN",
        403: "INSTALLATION_BLOCKED",
        413: "PAYLOAD_TOO_LARGE",
        415: "UNSUPPORTED_MEDIA_TYPE",
        422: "VALIDATION_ERROR",
        429: "RATE_LIMITED",
        502: "UPSTREAM_FAILURE",
        503: "SERVICE_UNAVAILABLE",
    }.get(status_code, "SERVICE_UNAVAILABLE")


def _public_extension_message(exc: HTTPException) -> str:
    if isinstance(exc.detail, str) and exc.detail.strip():
        return exc.detail
    return "Request extension tidak dapat diproses."


def _extension_error_response(
    status_code: int,
    code: str,
    message: str,
    retry_after_seconds: int | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    request_id = f"req_{uuid4().hex[:12]}"
    error: dict[str, object] = {
        "code": code,
        "message": message,
        "request_id": request_id,
    }
    if retry_after_seconds is not None:
        error["retry_after_seconds"] = retry_after_seconds
    return JSONResponse(
        status_code=status_code,
        content={"error": error},
        headers=headers,
    )


@app.exception_handler(404)
async def not_found(_: Request, __: Exception) -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": "Rute tidak ditemukan."})
