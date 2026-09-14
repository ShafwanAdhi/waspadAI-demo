import io
import re
from datetime import datetime

from PIL import ExifTags, Image, UnidentifiedImageError

from app.config import Settings
from app.schemas import MediaMetadata, OCRBlock, OCRResult


Image.MAX_IMAGE_PIXELS = 30_000_000

ALLOWED_FORMATS = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}
URL_PATTERN = re.compile(r"(?i)\b(?:https?://|www\.)[^\s<>{}\[\]]+")
PHONE_PATTERN = re.compile(r"(?<!\d)(?:\+62|62|0)8[1-9](?:[\s.-]?\d){7,11}(?!\d)")


class InvalidImageError(ValueError):
    pass


def inspect_image(payload: bytes, settings: Settings) -> tuple[Image.Image, MediaMetadata]:
    try:
        image = Image.open(io.BytesIO(payload))
        image.load()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise InvalidImageError("File tidak dapat dibaca sebagai gambar yang aman.") from exc

    image_format = (image.format or "").upper()
    if image_format not in ALLOWED_FORMATS:
        raise InvalidImageError("Format gambar harus JPG, PNG, atau WEBP.")

    if image.width < settings.min_image_width or image.height < settings.min_image_height:
        raise InvalidImageError(
            f"Dimensi gambar minimal {settings.min_image_width}x{settings.min_image_height} piksel."
        )

    if image.width > settings.max_image_width or image.height > settings.max_image_height:
        raise InvalidImageError(
            f"Dimensi gambar maksimal {settings.max_image_width}x{settings.max_image_height} piksel."
        )

    if image.width * image.height > settings.max_image_pixels:
        raise InvalidImageError(
            f"Jumlah piksel gambar maksimal {settings.max_image_pixels:,} piksel."
        )

    exif = image.getexif()
    exif_values = {ExifTags.TAGS.get(key, str(key)): value for key, value in exif.items()} if exif else {}
    created_at = _safe_exif_text(exif_values.get("DateTimeOriginal") or exif_values.get("DateTime"))
    source_application = _safe_exif_text(exif_values.get("Software"))

    metadata = MediaMetadata(
        mime_type=ALLOWED_FORMATS[image_format],
        width=image.width,
        height=image.height,
        format=image_format,
        has_exif=bool(exif_values),
        created_at=created_at,
        source_application=source_application,
        provenance_status="NOT_FOUND",
        note="Tidak adanya metadata/provenance bukan bukti bahwa media palsu.",
    )
    return image, metadata


def _safe_exif_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text[:160] if text else None


def image_to_data_url(image: Image.Image, metadata: MediaMetadata) -> str:
    import base64

    buffer = io.BytesIO()
    prepared = image.copy()
    prepared.thumbnail((3200, 3200), Image.Resampling.LANCZOS)
    if metadata.format == "JPEG":
        if prepared.mode not in ("RGB", "L"):
            prepared = prepared.convert("RGB")
        prepared.save(buffer, format="JPEG", quality=92, optimize=True)
        mime_type = "image/jpeg"
    elif metadata.format == "WEBP":
        prepared.save(buffer, format="WEBP", quality=92, method=4)
        mime_type = "image/webp"
    else:
        prepared.save(buffer, format="PNG", optimize=True)
        mime_type = "image/png"
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def run_local_ocr(image: Image.Image, settings: Settings) -> OCRResult:
    try:
        import pytesseract
        from pytesseract import Output

        if settings.tesseract_cmd.strip():
            pytesseract.pytesseract.tesseract_cmd = settings.tesseract_cmd.strip()

        data = pytesseract.image_to_data(
            image,
            lang=settings.tesseract_lang,
            output_type=Output.DICT,
            config="--psm 6",
        )
        blocks: list[OCRBlock] = []
        words: list[str] = []
        for index, text in enumerate(data.get("text", [])):
            clean = str(text).strip()
            if not clean:
                continue
            try:
                confidence = max(0.0, float(data["conf"][index])) / 100
            except (ValueError, TypeError, KeyError):
                confidence = 0.0
            words.append(clean)
            blocks.append(
                OCRBlock(
                    text=clean,
                    bbox=[
                        int(data["left"][index]),
                        int(data["top"][index]),
                        int(data["width"][index]),
                        int(data["height"][index]),
                    ],
                    confidence=min(confidence, 1.0),
                )
            )
        raw_text = " ".join(words).strip()
        return OCRResult(
            status="OK" if raw_text else "EMPTY",
            raw_text=raw_text,
            blocks=blocks[:250],
            urls=URL_PATTERN.findall(raw_text),
            phone_numbers=PHONE_PATTERN.findall(raw_text),
            note="OCR hanya mengekstrak teks dan tidak menentukan kebenaran klaim.",
        )
    except (ImportError, RuntimeError, OSError) as exc:
        return OCRResult(
            status="UNAVAILABLE",
            raw_text="",
            blocks=[],
            urls=[],
            phone_numbers=[],
            note=f"OCR lokal tidak tersedia ({type(exc).__name__}); vision tetap dijalankan.",
        )
    except Exception as exc:  # pytesseract uses environment-specific exception types
        return OCRResult(
            status="FAILED",
            raw_text="",
            blocks=[],
            urls=[],
            phone_numbers=[],
            note=f"OCR lokal gagal ({type(exc).__name__}); vision tetap dijalankan.",
        )


def current_iso_date() -> str:
    return datetime.now().astimezone().date().isoformat()
