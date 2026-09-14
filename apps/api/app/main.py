from contextlib import asynccontextmanager
from hmac import compare_digest
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from groq import AuthenticationError, RateLimitError

from app.config import get_settings
from app.schemas import TextVerificationRequest, VerificationResponse
from app.services.image_processing import InvalidImageError, inspect_image
from app.services.input_adapters import InvalidTextInputError
from app.services.pipeline import FactCheckPipeline


STATIC_DIR = Path(__file__).resolve().parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    app.state.settings = settings
    app.state.pipeline = FactCheckPipeline(settings)
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


def _debug_pipeline(request: Request) -> FactCheckPipeline:
    """Expose traces only from a direct local client in non-production."""
    settings = request.app.state.settings
    client_host = request.client.host if request.client else ""
    if not settings.debug_enabled or client_host not in {"127.0.0.1", "::1", "testclient"}:
        raise HTTPException(status_code=404, detail="Rute tidak ditemukan.")
    return request.app.state.pipeline


@app.exception_handler(404)
async def not_found(_: Request, __: Exception) -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": "Rute tidak ditemukan."})
