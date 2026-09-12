"""Compile paragraph-first rulebooks into validated runtime artifacts."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parent.parent
RULEBOOK_DIR = PROJECT_ROOT / "rulebook"
COMPILED_DIR = RULEBOOK_DIR / "compiled"
TRIGGER_FILE = RULEBOOK_DIR / "deterministic_triggers.json"

HEADER_KEYS = {
    "rulebook_id",
    "domain",
    "version",
    "status",
    "country",
    "language",
    "last_reviewed",
}
CHUNK_ID_RE = re.compile(
    r"^((?:[A-Z]{3})-(?:AP|R|Q|I|SQ|SA|EV|DT)\d{3}|ATO-STATE-\d{3})"
    r"(?:\s+-\s+(.+))?$"
)
SOURCE_ID_RE = re.compile(r"^([A-Z]{3}-S\d{3})$")
SECTION_RE = re.compile(r"^\d+(?:\.\d+)?\.\s+")
UNDERLINE_RE = re.compile(r"^[=-]{3,}$")
ID_KEYS = {
    "pattern_id",
    "rule_id",
    "question_id",
    "step_id",
    "query_template_id",
    "action_id",
    "evidence_rule_id",
    "trigger_id",
}
ALLOWED_CHUNK_TYPES = {
    "attack_pattern",
    "critical_indicator",
    "red_flag",
    "verification_question",
    "investigation_step",
    "search_template",
    "evidence_requirement",
    "decision_guidance",
    "safe_action",
    "do_not_do",
    "escalation_rule",
    "deterministic_trigger",
}
ALLOWED_SEVERITIES = {"CRITICAL", "HIGH", "MEDIUM", "LOW"}
ALLOWED_ORIGINS = {"SOURCE_DERIVED", "HEURISTIC_SYNTHESIS", "ARCHITECTURE_RULE"}
ALLOWED_FRESHNESS = {"stable_rule", "periodic_review", "recheck_required", "temporal_fact"}
ALLOWED_STAGES = {"PRE_RETRIEVAL_SIGNAL", "POST_RETRIEVAL_GUARDRAIL", "POST_ACTION_STATE"}


class RulebookValidationError(ValueError):
    """Raised when the canonical corpus cannot be compiled safely."""


@dataclass(frozen=True)
class ParsedRulebook:
    header: dict[str, str]
    rules: list[dict[str, Any]]
    sources: list[dict[str, Any]]


def _parse_pairs(line: str) -> dict[str, str]:
    output: dict[str, str] = {}
    for part in line.split("|"):
        key, separator, value = part.strip().partition("=")
        if separator:
            output[key.strip()] = value.strip()
    return output


def _find_header(lines: list[str], path: Path) -> dict[str, str]:
    for line in lines[:12]:
        values = _parse_pairs(line)
        if "rulebook_id" in values:
            missing = HEADER_KEYS - values.keys()
            if missing:
                raise RulebookValidationError(f"{path.name}: header missing {sorted(missing)}")
            return values
    raise RulebookValidationError(f"{path.name}: rulebook header not found")


def _body_until_next_identifier(lines: list[str], start: int) -> tuple[list[str], int]:
    body: list[str] = []
    index = start
    while index < len(lines):
        stripped = lines[index].strip()
        if CHUNK_ID_RE.match(stripped) or SOURCE_ID_RE.match(stripped) or SECTION_RE.match(stripped):
            break
        if stripped and not UNDERLINE_RE.match(stripped):
            body.append(stripped)
        index += 1
    return body, index


def _default_title(identifier: str, body: list[str]) -> str:
    if body:
        first = body[0]
        for prefix in ("Trigger.", "Agent action.", "Caveat.", "Observed signal.", "Forced action."):
            if first.startswith(prefix):
                first = first[len(prefix) :].strip()
        return first[:180] or identifier
    return identifier


def _extract_prefixed(body: list[str], prefix: str) -> str | None:
    for line in body:
        if line.startswith(prefix):
            return line[len(prefix) :].strip()
    return None


def _parse_rule(
    identifier: str,
    heading_title: str | None,
    metadata: dict[str, str],
    body: list[str],
    header: dict[str, str],
) -> dict[str, Any]:
    chunk_type = metadata.get("chunk_type")
    if identifier.startswith("ATO-STATE-"):
        chunk_type = "safe_action"
    if not chunk_type:
        raise RulebookValidationError(f"{identifier}: chunk_type missing")

    source_ids = [item.strip() for item in metadata.get("source_ids", "").split(",") if item.strip()]
    severity = metadata.get("severity")
    origin = metadata.get("origin")
    freshness = metadata.get("freshness")
    stage = metadata.get("stage")
    content_lines = [
        line
        for line in body
        if not line.startswith(("Trigger.", "Agent action.", "Caveat."))
    ]
    content = "\n".join(content_lines).strip() or "\n".join(body).strip()
    if not content:
        raise RulebookValidationError(f"{identifier}: content missing")

    does_not_prove: list[str] = []
    if chunk_type in {"attack_pattern", "critical_indicator", "red_flag"}:
        does_not_prove = ["case_is_scam", "sender_identity_is_false", "factual_claim_is_false"]

    return {
        "id": identifier,
        "rulebook_id": header["rulebook_id"],
        "rulebook_version": header["version"],
        "domain": header["domain"],
        "chunk_type": chunk_type,
        "title": heading_title or _default_title(identifier, body),
        "content": content,
        "severity": severity,
        "rule_origin": origin,
        "freshness_dependency": freshness,
        "source_ids": source_ids,
        "status": header["status"],
        "country": header["country"],
        "language": header["language"],
        "trigger_description": _extract_prefixed(body, "Trigger.") or _extract_prefixed(body, "Observed signal."),
        "agent_action": _extract_prefixed(body, "Agent action.") or _extract_prefixed(body, "Forced action."),
        "caveat": _extract_prefixed(body, "Caveat."),
        "does_not_prove": does_not_prove,
        "stage": stage,
    }


def _parse_source(identifier: str, metadata: dict[str, str], body: list[str]) -> dict[str, Any]:
    def required(prefix: str) -> str:
        value = _extract_prefixed(body, prefix)
        if not value:
            raise RulebookValidationError(f"{identifier}: {prefix.rstrip('.')} missing")
        return value

    return {
        "source_id": identifier,
        "institution": metadata.get("institution", ""),
        "year": metadata.get("year", ""),
        "source_type": metadata.get("source_type", ""),
        "document": required("Document."),
        "url": required("URL."),
        "rag_relevance": required("RAG relevance."),
    }


def parse_rulebook(path: Path) -> ParsedRulebook:
    lines = path.read_text(encoding="utf-8").splitlines()
    header = _find_header(lines, path)
    rules: list[dict[str, Any]] = []
    sources: list[dict[str, Any]] = []
    index = 0

    while index < len(lines):
        stripped = lines[index].strip()
        chunk_match = CHUNK_ID_RE.match(stripped)
        source_match = SOURCE_ID_RE.match(stripped)
        if not chunk_match and not source_match:
            index += 1
            continue

        identifier = (chunk_match or source_match).group(1)
        title = chunk_match.group(2) if chunk_match else None
        metadata: dict[str, str] = {}
        body_start = index + 1
        while body_start < len(lines) and (not lines[body_start].strip() or UNDERLINE_RE.match(lines[body_start].strip())):
            body_start += 1
        if body_start < len(lines):
            candidate = _parse_pairs(lines[body_start].strip())
            if ID_KEYS & candidate.keys() or "source_id" in candidate or "state" in candidate:
                metadata = candidate
                body_start += 1
        body, next_index = _body_until_next_identifier(lines, body_start)

        if source_match:
            sources.append(_parse_source(identifier, metadata, body))
        else:
            rules.append(_parse_rule(identifier, title, metadata, body, header))
        index = max(next_index, index + 1)

    return ParsedRulebook(header=header, rules=rules, sources=sources)


def _walk_condition(condition: dict[str, Any], trigger_id: str) -> None:
    branches = [key for key in ("all", "any", "not") if key in condition]
    if branches:
        if len(branches) != 1:
            raise RulebookValidationError(f"{trigger_id}: condition must have one logical operator")
        value = condition[branches[0]]
        children = value if isinstance(value, list) else [value]
        if not children:
            raise RulebookValidationError(f"{trigger_id}: logical condition cannot be empty")
        for child in children:
            if not isinstance(child, dict):
                raise RulebookValidationError(f"{trigger_id}: invalid nested condition")
            _walk_condition(child, trigger_id)
        return

    if not isinstance(condition.get("field"), str) or not condition["field"]:
        raise RulebookValidationError(f"{trigger_id}: condition field missing")
    if condition.get("operator") not in {"eq", "neq", "in", "not_in", "contains", "exists", "gt", "gte", "lt", "lte"}:
        raise RulebookValidationError(f"{trigger_id}: invalid condition operator")


def validate(
    parsed: list[ParsedRulebook],
    triggers: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rules = [rule for book in parsed for rule in book.rules]
    sources = [source for book in parsed for source in book.sources]
    rule_ids = [rule["id"] for rule in rules]
    source_ids = [source["source_id"] for source in sources]

    if len(rule_ids) != len(set(rule_ids)):
        raise RulebookValidationError("duplicate rule/chunk ID found")
    if len(source_ids) != len(set(source_ids)):
        raise RulebookValidationError("duplicate source ID found")

    known_rules = set(rule_ids)
    known_sources = set(source_ids)
    for rule in rules:
        if rule["chunk_type"] not in ALLOWED_CHUNK_TYPES:
            raise RulebookValidationError(f"{rule['id']}: invalid chunk_type {rule['chunk_type']}")
        if rule["severity"] and rule["severity"] not in ALLOWED_SEVERITIES:
            raise RulebookValidationError(f"{rule['id']}: invalid severity")
        if rule["rule_origin"] and rule["rule_origin"] not in ALLOWED_ORIGINS:
            raise RulebookValidationError(f"{rule['id']}: invalid origin")
        if rule["freshness_dependency"] and rule["freshness_dependency"] not in ALLOWED_FRESHNESS:
            raise RulebookValidationError(f"{rule['id']}: invalid freshness")
        if rule["stage"] and rule["stage"] not in ALLOWED_STAGES:
            raise RulebookValidationError(f"{rule['id']}: invalid trigger stage")
        unknown_sources = set(rule["source_ids"]) - known_sources
        if unknown_sources:
            raise RulebookValidationError(f"{rule['id']}: unknown sources {sorted(unknown_sources)}")

    for source in sources:
        if not source["institution"] or not source["source_type"]:
            raise RulebookValidationError(f"{source['source_id']}: incomplete metadata")
        if not source["url"].startswith("https://"):
            raise RulebookValidationError(f"{source['source_id']}: source URL must use HTTPS")

    corpus_trigger_ids = {rule["id"] for rule in rules if rule["chunk_type"] == "deterministic_trigger"}
    registry_trigger_ids: set[str] = set()
    for trigger in triggers:
        trigger_id = trigger.get("trigger_id")
        if not isinstance(trigger_id, str):
            raise RulebookValidationError("trigger_id missing")
        if trigger_id in registry_trigger_ids:
            raise RulebookValidationError(f"{trigger_id}: duplicate trigger registry entry")
        registry_trigger_ids.add(trigger_id)
        if trigger_id not in corpus_trigger_ids:
            raise RulebookValidationError(f"{trigger_id}: trigger missing from canonical corpus")
        if trigger.get("stage") not in ALLOWED_STAGES:
            raise RulebookValidationError(f"{trigger_id}: invalid stage")
        _walk_condition(trigger.get("condition", {}), trigger_id)
        missing_rules = set(trigger.get("force_rule_ids", [])) - known_rules
        if missing_rules:
            raise RulebookValidationError(f"{trigger_id}: unknown forced rules {sorted(missing_rules)}")
        if not trigger.get("force_actions"):
            raise RulebookValidationError(f"{trigger_id}: force_actions cannot be empty")

    missing_registry = corpus_trigger_ids - registry_trigger_ids
    if missing_registry:
        raise RulebookValidationError(f"structured definitions missing for {sorted(missing_registry)}")
    return rules, sources


def compile_rulebooks(output_dir: Path = COMPILED_DIR) -> dict[str, Any]:
    paths = sorted(RULEBOOK_DIR.glob("rulebook_*.txt"))
    if not paths:
        raise RulebookValidationError("no canonical rulebook files found")
    parsed = [parse_rulebook(path) for path in paths]
    triggers = json.loads(TRIGGER_FILE.read_text(encoding="utf-8"))
    rules, sources = validate(parsed, triggers)

    output_dir.mkdir(parents=True, exist_ok=True)
    rules_path = output_dir / "rules.jsonl"
    sources_path = output_dir / "sources.json"
    triggers_path = output_dir / "deterministic_triggers.json"
    manifest_path = output_dir / "manifest.json"

    rules_path.write_text(
        "".join(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n" for item in rules),
        encoding="utf-8",
    )
    sources_path.write_text(json.dumps(sources, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    triggers_path.write_text(json.dumps(triggers, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    manifest = {
        "schema_version": "1.0.0",
        "rulebooks": [book.header for book in parsed],
        "source_files": [
            {
                "name": path.name,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
            for path in [*paths, TRIGGER_FILE]
        ],
        "rule_count": len(rules),
        "source_count": len(sources),
        "deterministic_trigger_count": len(triggers),
        "separation_invariant": "RULE_CONTEXT_IS_NOT_EVIDENCE",
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def main() -> None:
    manifest = compile_rulebooks()
    print(
        "Rulebook valid: "
        f"{manifest['rule_count']} chunks, "
        f"{manifest['source_count']} sources, "
        f"{manifest['deterministic_trigger_count']} deterministic triggers."
    )


if __name__ == "__main__":
    main()
