from __future__ import annotations

import hashlib
import json
import math
import re
import time
from collections import Counter, OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from app.config import Settings
from app.schemas import CaseSignals, RuleMatch, RulebookResult, RulebookTrace


TOKEN_PATTERN = re.compile(r"\b[\w.-]+\b", re.UNICODE)
STOPWORDS = {
    "yang", "dan", "atau", "dari", "untuk", "dengan", "dalam", "pada",
    "adalah", "harus", "dapat", "tidak", "agent", "user", "rule",
}
VECTOR_DIMENSION = 384
RETRIEVAL_MODE = "BM25+HASHED_SUBWORD+METADATA+DETERMINISTIC"
PHASE_BY_CHUNK = {
    "attack_pattern": "DETECTION",
    "critical_indicator": "DETECTION",
    "red_flag": "DETECTION",
    "verification_question": "INVESTIGATION",
    "investigation_step": "INVESTIGATION",
    "search_template": "INVESTIGATION",
    "evidence_requirement": "DECISION",
    "decision_guidance": "DECISION",
    "safe_action": "RESPONSE",
    "do_not_do": "RESPONSE",
    "escalation_rule": "RESPONSE",
}
PHASE_QUOTAS = {"DETECTION": 3, "INVESTIGATION": 5, "DECISION": 2, "RESPONSE": 2}
SIGNAL_QUERY_TERMS = {
    "secret_request_detected": ("otp", "pin", "password", "credential", "authentication secret"),
    "suspicious_executable_received": ("apk", "executable", "malicious attachment", "install application"),
    "remote_access_requested": ("remote access", "remote control", "accessibility permission"),
    "screen_share_requested": ("screen sharing", "share screen"),
    "payment_requested": ("payment", "transfer", "beneficiary", "rekening"),
    "safe_account_transfer_requested": ("rekening aman", "safe account", "payment diversion"),
    "government_context": ("government", "pemerintah", "official procedure", "layanan publik"),
    "authority": ("authority impersonation", "claimed identity"),
    "threat": ("threat", "fear", "coercion"),
    "urgency": ("urgency", "deadline", "segera"),
    "synthetic_media_possible": ("deepfake", "voice clone", "synthetic impersonation"),
    "information_integrity_context": ("fact checking", "klaim", "source", "evidence", "konteks"),
    "source_provenance_missing": ("copy paste", "provenance", "origin", "sumber asli"),
    "quote_or_attribution_present": ("kutipan", "attribution", "speaker", "ucapan"),
    "temporal_claim_present": ("tanggal", "temporal", "outdated", "event date"),
    "numeric_claim_present": ("angka", "statistik", "denominator", "metode"),
}


class RulebookLoadError(RuntimeError):
    """Raised when compiled rulebook artifacts are missing or inconsistent."""


@dataclass(frozen=True)
class _IndexedRule:
    payload: dict[str, Any]
    term_frequency: Counter[str]
    tokens: frozenset[str]
    document_length: int
    subword_vector: tuple[float, ...]


class RulebookRAG:
    """Deterministic, auditable hybrid retriever for investigation policy rules."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        if settings.rulebook_candidate_k < settings.rulebook_max_rules:
            raise RulebookLoadError(
                "RULEBOOK_CANDIDATE_K harus lebih besar atau sama dengan RULEBOOK_MAX_RULES."
            )
        self.compiled_dir = Path(settings.rulebook_compiled_dir)
        self._rules = self._load_jsonl(self.compiled_dir / "rules.jsonl")
        self._sources = self._load_json(self.compiled_dir / "sources.json")
        self._triggers = self._load_json(self.compiled_dir / "deterministic_triggers.json")
        self._manifest = self._load_json(self.compiled_dir / "manifest.json")
        if not isinstance(self._manifest, dict):
            raise RulebookLoadError("Manifest rulebook tidak valid.")
        self._rule_by_id = {rule["id"]: rule for rule in self._rules}
        self._validate_loaded_corpus()
        self._index = self._build_index(self._rules)
        self._document_frequency = self._build_document_frequency(self._index)
        self._average_document_length = max(
            1.0,
            sum(item.document_length for item in self._index) / max(1, len(self._index)),
        )
        self._cache: OrderedDict[str, RulebookResult] = OrderedDict()
        self._corpus_hash = self._calculate_corpus_hash()

    @property
    def health(self) -> dict[str, Any]:
        return {
            "status": "ready",
            "retrieval_mode": RETRIEVAL_MODE,
            "rule_count": len(self._rules),
            "source_count": len(self._sources),
            "deterministic_trigger_count": len(self._triggers),
            "corpus_versions": self._corpus_versions(),
            "corpus_hash": self._corpus_hash,
        }

    async def retrieve(
        self,
        query: str,
        signals: CaseSignals,
        phases: Iterable[str] | None = None,
    ) -> RulebookResult:
        started = time.perf_counter()
        requested_phases = tuple(phases or PHASE_QUOTAS.keys())
        cache_key = self._cache_key(query, signals, requested_phases)
        cached = self._cache.get(cache_key)
        if cached is not None:
            self._cache.move_to_end(cache_key)
            trace = cached.trace.model_copy(update={"cache_hit": True, "duration_ms": _elapsed_ms(started)})
            return cached.model_copy(update={"trace": trace}, deep=True)

        trigger_context = signals.model_dump()
        trigger_context["secret_type"] = signals.requested_secrets
        fired = self._evaluate_triggers(
            trigger_context,
            {"PRE_RETRIEVAL_SIGNAL", "POST_ACTION_STATE"},
        )
        forced_rule_ids = _unique(
            rule_id for trigger in fired for rule_id in trigger.get("force_rule_ids", [])
        )
        forced_actions = _unique(
            action for trigger in fired for action in trigger.get("force_actions", [])
        )

        expanded_query = self._expanded_query(query, signals)
        query_tokens = _tokenize(expanded_query)
        query_vector = _subword_vector(expanded_query)
        raw_scores: list[tuple[float, float, _IndexedRule, list[str]]] = []
        for item in self._index:
            chunk_type = item.payload.get("chunk_type")
            phase = PHASE_BY_CHUNK.get(chunk_type)
            if not phase or phase not in requested_phases or chunk_type == "deterministic_trigger":
                continue
            raw_scores.append(
                (
                    self._bm25(query_tokens, item),
                    max(0.0, _cosine(query_vector, item.subword_vector)),
                    item,
                    self._matched_signals(signals, item.tokens),
                )
            )

        max_bm25 = max((row[0] for row in raw_scores), default=1.0) or 1.0
        ranked: list[tuple[float, _IndexedRule, list[str], list[str]]] = []
        for bm25, subword, item, matched_signals in raw_scores:
            domain_match = item.payload.get("domain") in signals.domains
            metadata_score = min(1.0, len(matched_signals) * 0.16 + (0.35 if domain_match else 0.0))
            severity_boost = 0.04 if item.payload.get("severity") == "CRITICAL" and matched_signals else 0.0
            final_score = min(
                1.0,
                0.5 * (bm25 / max_bm25)
                + 0.27 * subword
                + 0.19 * metadata_score
                + severity_boost,
            )
            if final_score < self.settings.rulebook_min_score:
                continue
            match_types: list[str] = []
            if bm25 > 0:
                match_types.append("BM25")
            if subword >= 0.12:
                match_types.append("SUBWORD")
            if metadata_score > 0:
                match_types.append("METADATA")
            ranked.append((final_score, item, match_types, matched_signals))

        ranked.sort(
            key=lambda row: (
                row[0],
                _severity_weight(row[1].payload.get("severity")),
                row[1].payload["id"],
            ),
            reverse=True,
        )
        candidate_count = len(ranked)
        selected = self._select_phase_aware(
            ranked[: self.settings.rulebook_candidate_k],
            requested_phases,
        )

        match_by_id: OrderedDict[str, RuleMatch] = OrderedDict()
        for rule_id in forced_rule_ids:
            payload = self._rule_by_id[rule_id]
            match_by_id[rule_id] = self._to_match(
                payload,
                score=1.0,
                match_types=["DETERMINISTIC"],
                matched_signals=self._matched_signals(
                    signals,
                    frozenset(_tokenize(_searchable_text(payload))),
                ),
            )
        for score, item, match_types, matched_signals in selected:
            if item.payload["id"] not in match_by_id:
                match_by_id[item.payload["id"]] = self._to_match(
                    item.payload,
                    score,
                    match_types,
                    matched_signals,
                )

        if not match_by_id:
            for rule_id in self._fallback_rule_ids(signals):
                payload = self._rule_by_id[rule_id]
                match_by_id[rule_id] = self._to_match(
                    payload,
                    score=0.1,
                    match_types=["SAFE_FALLBACK"],
                    matched_signals=[],
                )

        result = RulebookResult(
            matches=list(match_by_id.values()),
            forced_actions=forced_actions,
            trace=RulebookTrace(
                corpus_versions=self._corpus_versions(),
                retrieval_mode=RETRIEVAL_MODE,
                candidate_count=candidate_count,
                selected_count=len(match_by_id),
                forced_rule_ids=forced_rule_ids,
                cache_hit=False,
                duration_ms=_elapsed_ms(started),
            ),
        )
        self._remember(cache_key, result)
        return result.model_copy(deep=True)

    def post_retrieval_guardrails(
        self,
        result: RulebookResult,
        evidence_sufficiency: float,
        reputation_result: str = "NOT_CHECKED",
        signals: CaseSignals | None = None,
    ) -> RulebookResult:
        domains = (
            signals.domains
            if signals is not None
            else _unique(match.domain for match in result.matches)
        )
        fired = self._evaluate_triggers(
            {
                "evidence_sufficiency": evidence_sufficiency,
                "evidence_sufficiency_low": (
                    evidence_sufficiency < self.settings.evidence_sufficiency_threshold
                ),
                "reputation_result": reputation_result,
                "domains": domains,
            },
            {"POST_RETRIEVAL_GUARDRAIL"},
        )
        rule_ids = _unique(
            rule_id for item in fired for rule_id in item.get("force_rule_ids", [])
        )
        actions = _unique(
            [
                *result.forced_actions,
                *(action for item in fired for action in item.get("force_actions", [])),
            ]
        )
        existing = OrderedDict((match.rule_id, match) for match in result.matches)
        for rule_id in rule_ids:
            if rule_id not in existing:
                existing[rule_id] = self._to_match(
                    self._rule_by_id[rule_id],
                    score=1.0,
                    match_types=["DETERMINISTIC"],
                    matched_signals=["post_retrieval_guardrail"],
                )
        trace = result.trace.model_copy(
            update={
                "forced_rule_ids": _unique([*result.trace.forced_rule_ids, *rule_ids]),
                "selected_count": len(existing),
            }
        )
        return result.model_copy(
            update={"matches": list(existing.values()), "forced_actions": actions, "trace": trace},
            deep=True,
        )

    def _load_jsonl(self, path: Path) -> list[dict[str, Any]]:
        if not path.is_file():
            raise RulebookLoadError(
                f"Artefak {path.name} tidak ditemukan. Jalankan: python -m scripts.compile_rulebooks"
            )
        try:
            return [
                json.loads(line)
                for line in path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
        except (OSError, json.JSONDecodeError) as exc:
            raise RulebookLoadError(f"Artefak {path.name} tidak dapat dibaca.") from exc

    def _load_json(self, path: Path) -> Any:
        if not path.is_file():
            raise RulebookLoadError(
                f"Artefak {path.name} tidak ditemukan. Jalankan: python -m scripts.compile_rulebooks"
            )
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RulebookLoadError(f"Artefak {path.name} tidak dapat dibaca.") from exc

    def _validate_loaded_corpus(self) -> None:
        rule_ids = [item.get("id") for item in self._rules]
        if not rule_ids or len(rule_ids) != len(set(rule_ids)):
            raise RulebookLoadError("Rulebook kosong atau memiliki duplicate rule ID.")
        source_ids = {item.get("source_id") for item in self._sources}
        for rule in self._rules:
            unknown = set(rule.get("source_ids", [])) - source_ids
            if unknown:
                raise RulebookLoadError(f"{rule.get('id')}: source tidak dikenal {sorted(unknown)}")
        for trigger in self._triggers:
            missing = set(trigger.get("force_rule_ids", [])) - set(rule_ids)
            if missing:
                raise RulebookLoadError(
                    f"{trigger.get('trigger_id')}: rule tidak dikenal {sorted(missing)}"
                )
        canonical_dir = self.compiled_dir.parent
        for source_file in self._manifest.get("source_files", []):
            source_path = canonical_dir / str(source_file.get("name", ""))
            if not source_path.is_file():
                continue
            actual_hash = hashlib.sha256(source_path.read_bytes()).hexdigest()
            if actual_hash != source_file.get("sha256"):
                raise RulebookLoadError(
                    f"Corpus {source_path.name} berubah setelah compile. "
                    "Jalankan: python -m scripts.compile_rulebooks"
                )

    def _build_index(self, rules: list[dict[str, Any]]) -> list[_IndexedRule]:
        output: list[_IndexedRule] = []
        for payload in rules:
            text = _searchable_text(payload)
            tokens = _tokenize(text)
            output.append(
                _IndexedRule(
                    payload=payload,
                    term_frequency=Counter(tokens),
                    tokens=frozenset(tokens),
                    document_length=max(1, len(tokens)),
                    subword_vector=_subword_vector(text),
                )
            )
        return output

    @staticmethod
    def _build_document_frequency(index: list[_IndexedRule]) -> Counter[str]:
        frequency: Counter[str] = Counter()
        for item in index:
            frequency.update(item.tokens)
        return frequency

    def _bm25(self, query_tokens: list[str], item: _IndexedRule) -> float:
        score = 0.0
        document_count = len(self._index)
        k1 = 1.5
        b = 0.75
        for token in set(query_tokens):
            term_frequency = item.term_frequency.get(token, 0)
            if not term_frequency:
                continue
            document_frequency = self._document_frequency[token]
            inverse_document_frequency = math.log(
                1 + (document_count - document_frequency + 0.5) / (document_frequency + 0.5)
            )
            denominator = term_frequency + k1 * (
                1 - b + b * item.document_length / self._average_document_length
            )
            score += inverse_document_frequency * term_frequency * (k1 + 1) / denominator
        return score

    def _select_phase_aware(
        self,
        ranked: list[tuple[float, _IndexedRule, list[str], list[str]]],
        phases: tuple[str, ...],
    ) -> list[tuple[float, _IndexedRule, list[str], list[str]]]:
        selected: list[tuple[float, _IndexedRule, list[str], list[str]]] = []
        selected_ids: set[str] = set()
        remaining = self.settings.rulebook_max_rules
        for phase in phases:
            quota = min(PHASE_QUOTAS.get(phase, 2), remaining)
            phase_items = [
                item
                for item in ranked
                if PHASE_BY_CHUNK.get(item[1].payload.get("chunk_type")) == phase
            ]
            for item in phase_items[:quota]:
                if item[1].payload["id"] not in selected_ids:
                    selected.append(item)
                    selected_ids.add(item[1].payload["id"])
                    remaining -= 1
        if remaining > 0:
            for item in ranked:
                if item[1].payload["id"] in selected_ids:
                    continue
                selected.append(item)
                selected_ids.add(item[1].payload["id"])
                remaining -= 1
                if remaining <= 0:
                    break
        return selected

    def _evaluate_triggers(
        self,
        context: dict[str, Any],
        stages: set[str],
    ) -> list[dict[str, Any]]:
        return [
            trigger
            for trigger in self._triggers
            if trigger.get("stage") in stages
            and _condition_matches(trigger["condition"], context)
        ]

    def _expanded_query(self, query: str, signals: CaseSignals) -> str:
        additions = list(signals.domains) + list(signals.attack_patterns) + list(signals.channels)
        for field, terms in SIGNAL_QUERY_TERMS.items():
            if getattr(signals, field):
                additions.extend(terms)
        additions.extend(signals.requested_actions)
        additions.extend(signals.requested_secrets)
        return " ".join([query, *additions]).strip()

    @staticmethod
    def _matched_signals(signals: CaseSignals, rule_tokens: frozenset[str]) -> list[str]:
        matched: list[str] = []
        for field, terms in SIGNAL_QUERY_TERMS.items():
            if getattr(signals, field) and any(
                token in rule_tokens for token in _tokenize(" ".join(terms))
            ):
                matched.append(field)
        for pattern in signals.attack_patterns:
            if set(_tokenize(pattern)) & rule_tokens:
                matched.append(f"attack_pattern:{pattern}")
        return _unique(matched)

    def _to_match(
        self,
        payload: dict[str, Any],
        score: float,
        match_types: list[str],
        matched_signals: list[str],
    ) -> RuleMatch:
        return RuleMatch(
            rule_id=payload["id"],
            rulebook_id=payload["rulebook_id"],
            rulebook_version=payload["rulebook_version"],
            domain=payload["domain"],
            chunk_type=payload["chunk_type"],
            phase=PHASE_BY_CHUNK.get(payload["chunk_type"], "INVESTIGATION"),
            title=payload["title"],
            content=payload["content"],
            severity=payload.get("severity"),
            source_ids=payload.get("source_ids", []),
            match_types=match_types,
            matched_signals=matched_signals,
            retrieval_score=round(max(0.0, min(1.0, score)), 4),
            agent_action=payload.get("agent_action"),
            caveat=payload.get("caveat"),
            does_not_prove=payload.get("does_not_prove", []),
        )

    def _fallback_rule_ids(self, signals: CaseSignals) -> list[str]:
        output = ["INF-R003", "INF-R014"]
        if "impersonation_phishing_ato" in signals.domains:
            output.extend(["ATO-R002", "ATO-R035"])
        if signals.government_context:
            output.append("GOV-R016")
        return [rule_id for rule_id in output if rule_id in self._rule_by_id]

    def _cache_key(self, query: str, signals: CaseSignals, phases: tuple[str, ...]) -> str:
        payload = {
            "query": " ".join(_tokenize(query)),
            "signals": signals.model_dump(),
            "phases": phases,
            "corpus": self._corpus_hash,
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()

    def _remember(self, key: str, value: RulebookResult) -> None:
        self._cache[key] = value.model_copy(deep=True)
        self._cache.move_to_end(key)
        while len(self._cache) > self.settings.rulebook_cache_size:
            self._cache.popitem(last=False)

    def _corpus_versions(self) -> list[str]:
        versions = {
            f"{item.get('rulebook_id')}@{item.get('version')}"
            for item in self._manifest.get("rulebooks", [])
        }
        return sorted(versions)

    def _calculate_corpus_hash(self) -> str:
        digest = hashlib.sha256()
        for rule in sorted(self._rules, key=lambda item: item["id"]):
            digest.update(
                json.dumps(rule, ensure_ascii=False, sort_keys=True).encode("utf-8")
            )
        return digest.hexdigest()[:16]


def _searchable_text(payload: dict[str, Any]) -> str:
    return " ".join(
        str(value or "")
        for value in (
            payload.get("title"),
            payload.get("content"),
            payload.get("domain"),
            payload.get("chunk_type"),
            payload.get("trigger_description"),
            payload.get("agent_action"),
            payload.get("caveat"),
        )
    )


def _tokenize(text: str) -> list[str]:
    return [
        token.casefold().strip(".-")
        for token in TOKEN_PATTERN.findall(text or "")
        if len(token.strip(".-")) > 1
        and token.casefold().strip(".-") not in STOPWORDS
    ]


def _subword_vector(text: str) -> tuple[float, ...]:
    vector = [0.0] * VECTOR_DIMENSION
    tokens = _tokenize(text)
    features = list(tokens)
    features.extend(f"{left}_{right}" for left, right in zip(tokens, tokens[1:]))
    for token in tokens:
        padded = f"^{token}$"
        features.extend(
            padded[index : index + 3]
            for index in range(max(0, len(padded) - 2))
        )
    for feature in features:
        raw = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
        index = int.from_bytes(raw[:4], "big") % VECTOR_DIMENSION
        sign = 1.0 if raw[4] & 1 else -1.0
        vector[index] += sign
    norm = math.sqrt(sum(value * value for value in vector))
    if norm:
        vector = [value / norm for value in vector]
    return tuple(vector)


def _cosine(left: tuple[float, ...], right: tuple[float, ...]) -> float:
    return sum(a * b for a, b in zip(left, right))


def _condition_matches(condition: dict[str, Any], context: dict[str, Any]) -> bool:
    if "all" in condition:
        return all(_condition_matches(item, context) for item in condition["all"])
    if "any" in condition:
        return any(_condition_matches(item, context) for item in condition["any"])
    if "not" in condition:
        return not _condition_matches(condition["not"], context)

    actual = context.get(condition.get("field"))
    operator = condition.get("operator")
    expected = condition.get("value")
    if operator == "exists":
        return (actual is not None) is bool(expected)
    if operator == "eq":
        return expected in actual if isinstance(actual, list) else actual == expected
    if operator == "neq":
        return expected not in actual if isinstance(actual, list) else actual != expected
    if operator == "in":
        expected_values = expected if isinstance(expected, list) else [expected]
        return (
            bool(set(actual) & set(expected_values))
            if isinstance(actual, list)
            else actual in expected_values
        )
    if operator == "not_in":
        expected_values = expected if isinstance(expected, list) else [expected]
        return (
            not bool(set(actual) & set(expected_values))
            if isinstance(actual, list)
            else actual not in expected_values
        )
    if operator == "contains":
        return expected in actual if isinstance(actual, (str, list, tuple, set)) else False
    try:
        if operator == "gt":
            return actual > expected
        if operator == "gte":
            return actual >= expected
        if operator == "lt":
            return actual < expected
        if operator == "lte":
            return actual <= expected
    except TypeError:
        return False
    return False


def _severity_weight(value: str | None) -> int:
    return {"CRITICAL": 4, "HIGH": 3, "MEDIUM": 2, "LOW": 1}.get(value or "", 0)


def _unique(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


def _elapsed_ms(started: float) -> int:
    return max(0, round((time.perf_counter() - started) * 1000))
