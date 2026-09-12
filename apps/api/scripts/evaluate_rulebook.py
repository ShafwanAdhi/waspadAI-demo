"""Run the deterministic rulebook safety benchmark."""

import asyncio
import json
from pathlib import Path

from app.config import PROJECT_ROOT, Settings
from app.services.rag import RulebookRAG
from app.services.input_adapters import build_text_case
from app.services.signal_extraction import extract_case_signals


CASES_FILE = PROJECT_ROOT / "rulebook" / "evaluation_cases.json"


def _case(text: str, possible_impersonation: bool):
    case, _ = build_text_case(
        text=text,
        question="Apakah teks ini benar dan aman?",
        source_url=None,
        sender_context="UNKNOWN_NUMBER" if possible_impersonation else "UNKNOWN",
        max_urls=10,
    )
    return case.model_copy(update={"possible_impersonation": possible_impersonation})


async def evaluate() -> dict:
    cases = json.loads(CASES_FILE.read_text(encoding="utf-8"))
    rag = RulebookRAG(Settings())
    expected_total = 0
    expected_found = 0
    forbidden_hits: list[dict[str, str]] = []
    missing_expected: list[dict[str, str]] = []
    full_phase_cases = 0

    for case in cases:
        text = case["text"]
        signals = extract_case_signals(
            _case(text, bool(case.get("possible_impersonation")))
        )
        result = await rag.retrieve(text, signals)
        forced = set(result.trace.forced_rule_ids)
        expected = set(case.get("expected_forced_rules", []))
        forbidden = set(case.get("forbidden_forced_rules", []))
        expected_total += len(expected)
        expected_found += len(expected & forced)
        for rule_id in sorted(expected - forced):
            missing_expected.append({"case_id": case["case_id"], "rule_id": rule_id})
        for rule_id in sorted(forbidden & forced):
            forbidden_hits.append({"case_id": case["case_id"], "rule_id": rule_id})
        if {"DETECTION", "INVESTIGATION", "DECISION", "RESPONSE"} <= {
            item.phase for item in result.matches
        }:
            full_phase_cases += 1

    metrics = {
        "case_count": len(cases),
        "critical_rule_recall": round(expected_found / max(1, expected_total), 4),
        "forbidden_trigger_hits": forbidden_hits,
        "missing_expected": missing_expected,
        "phase_coverage_rate": round(full_phase_cases / max(1, len(cases)), 4),
    }
    return metrics


def main() -> None:
    metrics = asyncio.run(evaluate())
    print(json.dumps(metrics, ensure_ascii=False, indent=2))
    if metrics["critical_rule_recall"] < 1.0:
        raise SystemExit("Critical-rule recall benchmark failed.")
    if metrics["forbidden_trigger_hits"]:
        raise SystemExit("Forbidden deterministic trigger benchmark failed.")
    if metrics["phase_coverage_rate"] < 0.9:
        raise SystemExit("Phase-aware retrieval benchmark failed.")


if __name__ == "__main__":
    main()
