"""Evaluate the live GPT-OSS 20B investigation planner against a labelled set."""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import time
from pathlib import Path
from typing import Any

from groq import APIStatusError

from app.config import PROJECT_ROOT, Settings
from app.services.groq_service import GroqFactCheckService, ModelOutputError
from app.services.input_adapters import build_text_case
from app.services.rag import RulebookRAG
from app.services.rate_limits import GroqRateLimitMonitor
from app.services.signal_extraction import extract_case_signals


DEFAULT_CASES = PROJECT_ROOT / "evaluation" / "planner_cases.json"
DEFAULT_OUTPUT = PROJECT_ROOT / "evaluation" / "planner_results.json"


def _normalise(value: str) -> str:
    normalised = re.sub(r"\s+", " ", re.sub(r"[^a-z0-9%]+", " ", value.casefold())).strip()
    bilingual_terms = (
        ("customer service", "customer service"),
        ("newly announced", "baru diumumkan"),
        ("current date", "tanggal sekarang"),
        ("two weeks", "dua minggu"),
        ("in effect", "berlaku"),
        ("cross check", "bandingkan"),
        ("temporal validity", "validitas waktu"),
        ("official", "resmi"),
        ("government", "pemerintah"),
        ("schools", "sekolah"),
        ("school", "sekolah"),
        ("closed", "ditutup"),
        ("closure", "penutupan"),
        ("announced", "diumumkan"),
        ("today", "hari ini"),
        ("updates", "pembaruan"),
        ("update", "pembaruan"),
        ("verify", "verifikasi"),
        ("check", "cek"),
        ("source", "sumber"),
        ("statistics", "statistik"),
        ("methodology", "metodologi"),
        ("identity", "identitas"),
        ("sender", "pengirim"),
        ("channel", "kanal"),
        ("authenticity", "autentisitas"),
        ("unemployment", "pengangguran"),
    )
    for source, target in bilingual_terms:
        normalised = normalised.replace(source, target)
    return normalised


def _matches_slots(value: str, slots: list[list[str]]) -> bool:
    normalised = _normalise(value)
    return all(any(_normalise(term) in normalised for term in alternatives) for alternatives in slots)


def _coverage(items: list[str], expectations: list[dict[str, Any]]) -> tuple[int, int, list[str]]:
    joined = "\n".join(items)
    missing = [
        expectation["label"]
        for expectation in expectations
        if not _matches_slots(joined, expectation["slots"])
    ]
    return len(expectations) - len(missing), len(expectations), missing


def _claim_metrics(claims: list[str], expected: list[dict[str, Any]]) -> dict[str, Any]:
    matched_expected = {
        index
        for index, expectation in enumerate(expected)
        if any(_matches_slots(claim, expectation["slots"]) for claim in claims)
    }
    matched_generated = sum(
        1
        for claim in claims
        if any(_matches_slots(claim, expectation["slots"]) for expectation in expected)
    )
    return {
        "expected": len(expected),
        "generated": len(claims),
        "matched_expected": len(matched_expected),
        "matched_generated": matched_generated,
        "missing": [
            expectation["label"]
            for index, expectation in enumerate(expected)
            if index not in matched_expected
        ],
    }


def _safe_ratio(numerator: int, denominator: int) -> float:
    if denominator == 0:
        return 1.0 if numerator == 0 else 0.0
    return numerator / denominator


def _false_positive_rate(false_positives: int, negative_cases: int) -> float | None:
    if negative_cases == 0:
        return None
    return round(false_positives / negative_cases, 4)


def _score_case(case_data: dict[str, Any], planner: Any) -> dict[str, Any]:
    expected = case_data["expected"]
    claim_texts = [claim.text for claim in planner.claims]
    claim_score = _claim_metrics(claim_texts, expected["claims"])
    critical_found, critical_total, missing_checks = _coverage(
        planner.critical_checks,
        expected["critical_checks"],
    )
    query_found, query_total, missing_queries = _coverage(
        planner.web_queries,
        expected["query_concepts"],
    )
    missing_domains = [
        domain for domain in expected["required_domains"] if domain not in planner.domains
    ]
    missing_domain_rag = [
        domain
        for domain in expected["domain_rag"]
        if domain not in planner.retrieval_plan.domain_rag
    ]
    retrieval_checks = [
        planner.retrieval_plan.web_search == expected["web_search"],
        not missing_domain_rag,
        planner.retrieval_plan.factcheck_rag == expected["factcheck_rag"],
    ]
    predicted_escalation = planner.complexity == "HIGH"
    return {
        "classification_correct": planner.classification in expected["classifications"],
        "required_domains_found": len(expected["required_domains"]) - len(missing_domains),
        "required_domains_total": len(expected["required_domains"]),
        "missing_domains": missing_domains,
        "claim_metrics": claim_score,
        "critical_checks_found": critical_found,
        "critical_checks_total": critical_total,
        "missing_critical_checks": missing_checks,
        "retrieval_checks_passed": sum(retrieval_checks),
        "retrieval_checks_total": len(retrieval_checks),
        "retrieval_details": {
            "web_search_expected": expected["web_search"],
            "web_search_actual": planner.retrieval_plan.web_search,
            "missing_domain_rag": missing_domain_rag,
            "factcheck_rag_expected": expected["factcheck_rag"],
            "factcheck_rag_actual": planner.retrieval_plan.factcheck_rag,
        },
        "query_concepts_found": query_found,
        "query_concepts_total": query_total,
        "missing_query_concepts": missing_queries,
        "should_escalate": expected["should_escalate"],
        "predicted_escalation": predicted_escalation,
        "escalation_correct": predicted_escalation == expected["should_escalate"],
    }


def _zero_scores(case_data: dict[str, Any]) -> dict[str, Any]:
    expected = case_data["expected"]
    return {
        "classification_correct": False,
        "required_domains_found": 0,
        "required_domains_total": len(expected["required_domains"]),
        "missing_domains": expected["required_domains"],
        "claim_metrics": {
            "expected": len(expected["claims"]),
            "generated": 0,
            "matched_expected": 0,
            "matched_generated": 0,
            "missing": [item["label"] for item in expected["claims"]],
        },
        "critical_checks_found": 0,
        "critical_checks_total": len(expected["critical_checks"]),
        "missing_critical_checks": [item["label"] for item in expected["critical_checks"]],
        "retrieval_checks_passed": 0,
        "retrieval_checks_total": 3,
        "retrieval_details": {"unavailable_because_schema_invalid": True},
        "query_concepts_found": 0,
        "query_concepts_total": len(expected["query_concepts"]),
        "missing_query_concepts": [item["label"] for item in expected["query_concepts"]],
        "should_escalate": expected["should_escalate"],
        "predicted_escalation": False,
        "escalation_correct": not expected["should_escalate"],
    }


def _aggregate(results: list[dict[str, Any]], case_count: int) -> dict[str, Any]:
    valid = [result for result in results if result["status"] == "OK"]
    scores = [result["scores"] for result in results]
    expected_escalations = sum(score["should_escalate"] for score in scores)
    detected_escalations = sum(
        score["should_escalate"] and score["predicted_escalation"] for score in scores
    )
    false_escalations = sum(
        not score["should_escalate"] and score["predicted_escalation"] for score in scores
    )
    non_escalation_cases = sum(not score["should_escalate"] for score in scores)
    expected_claims = sum(score["claim_metrics"]["expected"] for score in scores)
    generated_claims = sum(score["claim_metrics"]["generated"] for score in scores)
    matched_expected = sum(score["claim_metrics"]["matched_expected"] for score in scores)
    matched_generated = sum(score["claim_metrics"]["matched_generated"] for score in scores)
    return {
        "case_count": case_count,
        "completed_cases": len(valid),
        "schema_validity_rate": round(_safe_ratio(len(valid), case_count), 4),
        "classification_accuracy": round(
            _safe_ratio(sum(score["classification_correct"] for score in scores), len(scores)), 4
        ),
        "claim_recall": round(_safe_ratio(matched_expected, expected_claims), 4),
        "claim_precision_proxy": round(_safe_ratio(matched_generated, generated_claims), 4),
        "required_domain_recall": round(
            _safe_ratio(
                sum(score["required_domains_found"] for score in scores),
                sum(score["required_domains_total"] for score in scores),
            ),
            4,
        ),
        "critical_check_recall": round(
            _safe_ratio(
                sum(score["critical_checks_found"] for score in scores),
                sum(score["critical_checks_total"] for score in scores),
            ),
            4,
        ),
        "retrieval_plan_accuracy": round(
            _safe_ratio(
                sum(score["retrieval_checks_passed"] for score in scores),
                sum(score["retrieval_checks_total"] for score in scores),
            ),
            4,
        ),
        "query_usefulness_proxy": round(
            _safe_ratio(
                sum(score["query_concepts_found"] for score in scores),
                sum(score["query_concepts_total"] for score in scores),
            ),
            4,
        ),
        "escalation_recall": round(_safe_ratio(detected_escalations, expected_escalations), 4),
        "escalation_false_positive_rate": _false_positive_rate(
            false_escalations, non_escalation_cases
        ),
    }


async def _evaluate(args: argparse.Namespace) -> dict[str, Any]:
    settings = Settings()
    if not settings.groq_api_key.strip():
        raise SystemExit("GROQ_API_KEY belum dikonfigurasi.")
    cases = json.loads(args.cases.read_text(encoding="utf-8"))
    if args.case_id:
        cases = [case for case in cases if case["case_id"] == args.case_id]
        if not cases:
            raise SystemExit(f"case_id tidak ditemukan: {args.case_id}")
    if args.case_limit:
        cases = cases[: args.case_limit]

    rate_limits = GroqRateLimitMonitor(settings)
    service = GroqFactCheckService(settings, rate_limits)
    rag = RulebookRAG(settings)
    results: list[dict[str, Any]] = []

    for index, case_data in enumerate(cases):
        if index and args.delay_seconds:
            print(f"Menunggu {args.delay_seconds:.0f} detik agar bucket TPM pulih...", flush=True)
            await asyncio.sleep(args.delay_seconds)

        case, _ = build_text_case(
            text=case_data["text"],
            question=case_data["question"],
            source_url=case_data.get("source_url"),
            sender_context=case_data["sender_context"],
            max_urls=settings.max_case_urls,
        )
        signals = extract_case_signals(case)
        rule_query = "\n".join(
            value
            for value in (
                case.safe_text,
                case.summary,
                case.question,
                "\n".join(claim.text for claim in case.seed_claims),
            )
            if value
        )
        rulebook = await rag.retrieve(rule_query, signals)
        started = time.perf_counter()
        print(f"[{index + 1}/{len(cases)}] {case_data['case_id']}", flush=True)
        try:
            planner = await service.plan(case, signals, rulebook, escalation=False)
            elapsed_ms = round((time.perf_counter() - started) * 1000)
            results.append(
                {
                    "case_id": case_data["case_id"],
                    "status": "OK",
                    "duration_ms": elapsed_ms,
                    "scores": _score_case(case_data, planner),
                    "planner_output": planner.model_dump(mode="json"),
                }
            )
            print(f"  OK ({elapsed_ms} ms), classification={planner.classification}, complexity={planner.complexity}", flush=True)
        except (APIStatusError, ModelOutputError) as exc:
            elapsed_ms = round((time.perf_counter() - started) * 1000)
            results.append(
                {
                    "case_id": case_data["case_id"],
                    "status": "ERROR",
                    "duration_ms": elapsed_ms,
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                    "scores": _zero_scores(case_data),
                }
            )
            print(f"  ERROR ({type(exc).__name__}): {exc}", flush=True)

    payload = {
        "evaluated_model": settings.groq_planner_model,
        "evaluation_kind": "live_stage_level_planner",
        "metrics": _aggregate(results, len(cases)),
        "limitations": [
            "Kasus evaluasi sintetis dan belum mewakili distribusi pengguna produksi.",
            "Claim precision memakai pencocokan konsep berlabel, bukan penilaian semantik manusia.",
            "Query usefulness adalah coverage konsep query, bukan keberhasilan live web retrieval.",
            "Escalation ground truth adalah kebijakan risiko engineering yang perlu ditinjau manusia.",
        ],
        "results": results,
        "rate_limit_snapshot": rate_limits.snapshot(),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def _rescore(args: argparse.Namespace) -> dict[str, Any]:
    cases = json.loads(args.cases.read_text(encoding="utf-8"))
    if args.case_id:
        cases = [case for case in cases if case["case_id"] == args.case_id]
        if not cases:
            raise SystemExit(f"case_id tidak ditemukan: {args.case_id}")
    if args.case_limit:
        cases = cases[: args.case_limit]
    previous = json.loads(args.rescore_from.read_text(encoding="utf-8"))
    previous_by_id = {item["case_id"]: item for item in previous["results"]}
    results: list[dict[str, Any]] = []
    for case_data in cases:
        result = previous_by_id[case_data["case_id"]]
        if result["status"] == "OK":
            from app.schemas import PlannerOutput

            planner = PlannerOutput.model_validate(result["planner_output"])
            result["scores"] = _score_case(case_data, planner)
        else:
            result["scores"] = _zero_scores(case_data)
        results.append(result)
    previous["metrics"] = _aggregate(results, len(cases))
    previous["results"] = results
    args.output.write_text(json.dumps(previous, ensure_ascii=False, indent=2), encoding="utf-8")
    return previous


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--case-limit", type=int, default=0)
    parser.add_argument("--case-id")
    parser.add_argument("--delay-seconds", type=float, default=62.0)
    parser.add_argument("--rescore-from", type=Path)
    args = parser.parse_args()
    payload = _rescore(args) if args.rescore_from else asyncio.run(_evaluate(args))
    print(json.dumps(payload["metrics"], ensure_ascii=False, indent=2))
    print(f"Hasil lengkap: {args.output}")


if __name__ == "__main__":
    main()
