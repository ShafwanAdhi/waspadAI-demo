"""Run one synthetic live request and print provider errors without credentials."""

import asyncio
import argparse
import io
import traceback

from groq import APIStatusError
from PIL import Image, ImageDraw, ImageFont

from app.config import Settings
from app.services.image_processing import inspect_image
from app.services.pipeline import FactCheckPipeline


async def verify_image(pipeline: FactCheckPipeline):
    buffer = io.BytesIO()
    diagnostic_image = Image.new("RGB", (1000, 700), "white")
    draw = ImageDraw.Draw(diagnostic_image)
    try:
        font = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 36)
    except OSError:
        font = ImageFont.load_default()
    lines = [
        "PEMERINTAH MEMBERIKAN BANTUAN RP5 JUTA",
        "DAFTAR SEBELUM MALAM INI",
        "KLIK bansos-gratis.example",
    ]
    for index, line in enumerate(lines):
        draw.text((55, 100 + index * 90), line, fill="black", font=font)
    diagnostic_image.save(buffer, "PNG")
    image, metadata = inspect_image(buffer.getvalue())
    return await pipeline.verify_image(
        image,
        metadata,
        "diagnostic.png",
        "Apakah gambar ini memuat klaim yang dapat diverifikasi?",
    )


async def verify_text(pipeline: FactCheckPipeline):
    return await pipeline.verify_text(
        text=(
            "Pesan berantai menyebut Kementerian Sosial membuka bantuan Rp5 juta "
            "untuk seluruh pemilik KTP mulai hari ini. Pendaftaran disebut hanya "
            "tersedia selama dua jam melalui WhatsApp. Penerima diminta membayar "
            "biaya administrasi Rp150.000 ke rekening pribadi serta mengirim foto "
            "KTP dan kode OTP untuk konfirmasi pencairan."
        ),
        question="Apakah isi pesan ini benar dan aman ditindaklanjuti?",
        source_url=None,
        sender_context="FORWARDED",
    )


async def main(input_type: str) -> None:
    pipeline = FactCheckPipeline(Settings())

    try:
        result = (
            await verify_text(pipeline)
            if input_type == "text"
            else await verify_image(pipeline)
        )
        print(
            {
                "ok": True,
                "input_type": input_type.upper(),
                "verdict": result.verdict,
                "evidence": len(result.evidence),
                "rules": result.rulebook.selected_count,
                "rulebook_versions": result.rulebook.corpus_versions,
                "planning": next(
                    (stage.detail for stage in result.pipeline if stage.key == "planning"),
                    None,
                ),
            }
        )
    except APIStatusError as exc:
        print(
            {
                "ok": False,
                "type": type(exc).__name__,
                "status": exc.status_code,
                "message": str(exc),
                "body": getattr(exc.response, "text", "")[:3000],
            }
        )
        traceback.print_exc()
    except Exception as exc:
        print({"ok": False, "type": type(exc).__name__, "message": str(exc)})
        traceback.print_exc()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run one redacted live pipeline diagnostic.")
    parser.add_argument("--input", choices=("image", "text"), default="image")
    args = parser.parse_args()
    asyncio.run(main(args.input))
