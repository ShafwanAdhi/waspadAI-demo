"""Export the FastAPI contract consumed by the Next.js frontend."""

from __future__ import annotations

import json
import sys
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(API_ROOT))

from app.main import app


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
OUTPUT_FILE = REPOSITORY_ROOT / "contracts" / "openapi.json"


def main() -> None:
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_FILE.write_text(
        json.dumps(app.openapi(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"OpenAPI contract written to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
