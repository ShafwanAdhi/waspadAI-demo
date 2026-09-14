"""Deterministic planning safeguards and compact escalation context.

The planner is allowed to propose an investigation plan, but it is not trusted to
decide its own escalation or to introduce claims that cannot be traced back to
the privacy-filtered case. These helpers keep that control in the backend.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any

from app.config import Settings
from app.schemas import (
    CaseContext,
    CaseSignals,
    PlannedClaim,
    PlannerOutput,
    RetrievalPlan,
    RulebookResult,
)


_CLAUSE_SPLIT = re.compile(r"(?<=[.!?])\s+|[;\n]+")
_TOKEN_PATTERN = re.compile(r"[a-z0-9%]+", re.I)
_NUMBER_PATTERN = re.compile(r"\b\d+(?:[.,]\d+)?\b")
_TEMPORAL_CONFLICT = re.compile(
    r"\b(?:berita lama|dibagikan kembali|beredar kembali|masih berlaku|"
    r"seolah(?:-olah)? baru|baru diumumkan|konteks lama|kedaluwarsa|outdated)\b",
    re.I,
)
_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "in",
    "is", "it", "of", "on", "or", "that", "the", "this", "to", "was", "were",
    "yang", "dan", "atau", "dari", "di", "ke", "ini", "itu", "untuk", "pada",
    "adalah", "sebagai", "dengan", "bahwa", "sebuah", "saya", "kami", "mereka",
}
_RISK_TERMS = re.compile(
    r"\b(?:otp|pin|password|cvv|apk|transfer|bayar|rekening|remote access|"
    r"anydesk|teamviewer|deepfake|whatsapp|bantuan|blokir|diblokir)\b",
    re.I,
)
_RISK_ORDER = {"UNKNOWN": 0, "LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}


@dataclass(slots=True)
class PlannerGuardrailResult:
    plan: PlannerOutput
    issues: list[str]
    escalation_reasons: list[str]
    dropped_claims: int
    added_claims: int
    fallback_used: bool

    @property
    def should_escalate(self) -> bool:
        return bool(self.escalation_reasons)

    def trace_payload(self) -> dict[str, Any]:
        return {
            "issues": self.issues,
            "escalation_reasons": self.escalation_reasons,
            "should_escalate": self.should_escalate,
            "dropped_claims": self.dropped_claims,
            "added_claims": self.added_claims,
            "fallback_used": self.fallback_used,
            "repaired_plan": self.plan,
        }


def compact_case_payload(case: CaseContext, max_chars: int) -> dict[str, Any]:
    return {
        "input_type": case.input_type,
        "content_type": case.content_type,
        "text_excerpts": _select_excerpts(case.safe_text, max_chars),
        "summary": case.summary[:800],
        "question": case.question[:400],
        "page_context": case.page_context.model_dump(mode="json") if case.page_context else None,
        "source_url": case.source_url,
        "sender_context": case.sender_context,
        "platform": case.platform,
        "entities": case.entities[:16],
        "possible_impersonation": case.possible_impersonation,
        "urls": case.urls[:6],
        "seed_claims": [claim.model_dump() for claim in case.seed_claims[:8]],
        "extraction_confidence": case.extraction_confidence,
        "language": case.language,
    }


def compact_signal_payload(signals: CaseSignals) -> dict[str, Any]:
    payload = signals.model_dump(mode="json")
    return {
        key: value
        for key, value in payload.items()
        if value not in (False, None, "", [], "UNKNOWN", "NO_ACTION", "NOT_CHECKED")
    }


def compact_rule_payload(
    rulebook: RulebookResult,
    max_rules: int,
    content_chars: int,
) -> list[dict[str, Any]]:
    ranked = sorted(
        rulebook.matches,
        key=lambda item: (
            "DETERMINISTIC" in item.match_types,
            item.severity == "CRITICAL",
            item.severity == "HIGH",
            item.retrieval_score,
        ),
        reverse=True,
    )
    return [
        {
            "rule_id": item.rule_id,
            "domain": item.domain,
            "phase": item.phase,
            "severity": item.severity,
            "guidance": item.content[:content_chars],
            "agent_action": item.agent_action,
            "caveat": item.caveat,
        }
        for item in ranked[:max_rules]
    ]


def deterministic_fallback_plan(
    case: CaseContext,
    signals: CaseSignals,
    rulebook: RulebookResult,
    settings: Settings,
) -> PlannerOutput:
    claims = _fallback_claims(case, settings.max_planned_claims)
    classification = _deterministic_classification(case, signals)
    checks, required_evidence, preferred_sources = _deterministic_investigation(signals)
    escalation_reasons = planner_escalation_reasons(case, signals, len(claims))
    web_search = bool(
        claims
        and classification not in {"OPINION", "PERSONAL_MESSAGE", "QUESTION"}
        and (any(claim.verifiable for claim in claims) or signals.sensitive_action_requested)
    )
    return PlannerOutput(
        classification=classification,
        domains=signals.domains,
        attack_patterns=signals.attack_patterns,
        claims=claims,
        requires_fresh_data=bool(
            signals.temporal_claim_present
            or signals.numeric_claim_present
            or signals.source_provenance_missing
        ),
        complexity="HIGH" if escalation_reasons else ("MEDIUM" if claims else "SIMPLE"),
        potential_financial_risk=signals.payment_requested,
        potential_identity_impersonation=(
            case.possible_impersonation or "authority_impersonation" in signals.attack_patterns
        ),
        contains_url=bool(case.urls or case.source_url),
        critical_checks=checks,
        required_evidence=required_evidence,
        preferred_sources=preferred_sources,
        interim_risk=_deterministic_risk(signals),
        interim_actions=list(dict.fromkeys(rulebook.forced_actions)),
        applied_rule_ids=[item.rule_id for item in rulebook.matches[:8]],
        retrieval_plan=RetrievalPlan(
            web_search=web_search,
            domain_rag=_retrieval_domains(case, signals),
            community_rag=False,
            factcheck_rag=web_search and classification in {"FACTUAL_CLAIM", "SCAM_MESSAGE"},
        ),
        web_queries=_fallback_queries(claims, signals) if web_search else [],
    )


def validate_and_repair_plan(
    case: CaseContext,
    signals: CaseSignals,
    rulebook: RulebookResult,
    proposed: PlannerOutput,
    settings: Settings,
    *,
    fallback_used: bool = False,
) -> PlannerGuardrailResult:
    plan = proposed.model_copy(deep=True)
    fallback = deterministic_fallback_plan(case, signals, rulebook, settings)
    issues: list[str] = []
    source_text = _claim_source(case)

    grounded: list[PlannedClaim] = []
    dropped = 0
    for claim in plan.claims:
        if not _claim_is_grounded(claim.text, source_text):
            dropped += 1
            issues.append(f"UNGROUNDED_CLAIM_DROPPED:{claim.id}")
        elif _claim_is_low_quality_ocr_artifact(case, claim.text):
            dropped += 1
            issues.append(f"OCR_ARTIFACT_CLAIM_DROPPED:{claim.id}")
        else:
            grounded.append(claim)

    added = 0
    for candidate in fallback.claims:
        if len(grounded) >= settings.max_planned_claims:
            break
        if not any(_claims_overlap(candidate.text, existing.text) for existing in grounded):
            grounded.append(candidate)
            added += 1
    if added:
        issues.append(f"SOURCE_CLAIMS_ADDED:{added}")
    plan.claims = [
        claim.model_copy(update={"id": f"claim_{index}"})
        for index, claim in enumerate(grounded[: settings.max_planned_claims], start=1)
    ]

    if fallback.classification == "SCAM_MESSAGE" and plan.classification != "SCAM_MESSAGE":
        plan.classification = "SCAM_MESSAGE"
        issues.append("CLASSIFICATION_OVERRIDDEN_BY_CRITICAL_SIGNALS")
    plan.domains = list(dict.fromkeys([*signals.domains, *plan.domains]))
    plan.attack_patterns = list(dict.fromkeys([*signals.attack_patterns, *plan.attack_patterns]))
    plan.potential_financial_risk = plan.potential_financial_risk or signals.payment_requested
    plan.potential_identity_impersonation = bool(
        plan.potential_identity_impersonation
        or case.possible_impersonation
        or "authority_impersonation" in signals.attack_patterns
    )
    plan.contains_url = plan.contains_url or bool(case.urls or case.source_url)
    plan.requires_fresh_data = plan.requires_fresh_data or fallback.requires_fresh_data
    plan.critical_checks = _merge(plan.critical_checks, fallback.critical_checks)
    plan.required_evidence = _merge(plan.required_evidence, fallback.required_evidence)
    plan.preferred_sources = _merge(plan.preferred_sources, fallback.preferred_sources)
    plan.interim_actions = _merge(rulebook.forced_actions, plan.interim_actions)
    if _RISK_ORDER[fallback.interim_risk] > _RISK_ORDER[plan.interim_risk]:
        plan.interim_risk = fallback.interim_risk
        issues.append("INTERIM_RISK_RAISED_BY_DETERMINISTIC_SIGNALS")

    allowed_rule_ids = {item.rule_id for item in rulebook.matches}
    plan.applied_rule_ids = [
        rule_id for rule_id in dict.fromkeys(plan.applied_rule_ids) if rule_id in allowed_rule_ids
    ]
    plan.retrieval_plan.domain_rag = _merge(
        _merge(signals.domains, plan.domains),
        plan.retrieval_plan.domain_rag,
    )
    if fallback.retrieval_plan.web_search and not plan.retrieval_plan.web_search:
        issues.append("WEB_SEARCH_FORCED_FOR_VERIFIABLE_OR_RISK_CLAIMS")
    plan.retrieval_plan.web_search = (
        plan.retrieval_plan.web_search or fallback.retrieval_plan.web_search
    )
    plan.retrieval_plan.factcheck_rag = (
        plan.retrieval_plan.factcheck_rag or fallback.retrieval_plan.factcheck_rag
    )
    if plan.retrieval_plan.web_search:
        plan.web_queries = _merge(plan.web_queries, fallback.web_queries)[:6]
    else:
        plan.web_queries = []

    escalation_reasons = planner_escalation_reasons(case, signals, len(plan.claims))
    if proposed.complexity == "HIGH":
        escalation_reasons.append("MODEL_REPORTED_HIGH_COMPLEXITY")
    if dropped:
        escalation_reasons.append("UNGROUNDED_PLANNER_CLAIM")
    if fallback_used:
        escalation_reasons.append("FIRST_PASS_MODEL_FAILURE")
    escalation_reasons = list(dict.fromkeys(escalation_reasons))
    if escalation_reasons:
        plan.complexity = "HIGH"

    return PlannerGuardrailResult(
        plan=plan,
        issues=list(dict.fromkeys(issues)),
        escalation_reasons=escalation_reasons,
        dropped_claims=dropped,
        added_claims=added,
        fallback_used=fallback_used,
    )


def planner_escalation_reasons(
    case: CaseContext,
    signals: CaseSignals,
    claim_count: int,
) -> list[str]:
    reasons: list[str] = []
    if signals.secret_request_detected:
        reasons.append("SECRET_REQUEST")
    if signals.suspicious_executable_received:
        reasons.append("EXECUTABLE_REQUEST")
    if signals.remote_access_requested or signals.screen_share_requested:
        reasons.append("DEVICE_ACCESS_REQUEST")
    if signals.safe_account_transfer_requested:
        reasons.append("SAFE_ACCOUNT_PAYMENT_PATTERN")
    elif signals.payment_requested and (
        signals.authority or case.possible_impersonation or signals.payment_destination_type == "PERSONAL"
    ):
        reasons.append("HIGH_RISK_PAYMENT")
    if signals.user_action_state != "NO_ACTION":
        reasons.append(f"USER_ALREADY_ACTED:{signals.user_action_state}")
    if signals.synthetic_media_possible and (signals.authority or signals.payment_requested):
        reasons.append("SYNTHETIC_MEDIA_WITH_AUTHORITY_OR_PAYMENT")
    if claim_count >= 5:
        reasons.append("MANY_MATERIAL_CLAIMS")
    if signals.temporal_claim_present and _TEMPORAL_CONFLICT.search(
        " ".join((case.safe_text, case.summary, case.question))
    ):
        reasons.append("TEMPORAL_CONTEXT_CONFLICT")
    return reasons


def _deterministic_classification(case: CaseContext, signals: CaseSignals) -> str:
    suspicious_link = "suspicious_link_domain" in signals.attack_patterns
    link_impersonation = (
        "OPEN_LINK" in signals.requested_actions
        and (signals.authority or case.possible_impersonation)
        and (signals.urgency or signals.threat or suspicious_link)
    )
    critical_scam = bool(
        signals.secret_request_detected
        or signals.suspicious_executable_received
        or signals.remote_access_requested
        or signals.screen_share_requested
        or signals.safe_account_transfer_requested
        or link_impersonation
        or (
            signals.payment_requested
            and (signals.authority or case.possible_impersonation)
        )
    )
    if critical_scam:
        return "SCAM_MESSAGE"
    return {
        "OPINION": "OPINION",
        "SATIRE": "SATIRE",
        "ADVERTISEMENT": "ADVERTISEMENT",
        "PERSONAL_MESSAGE": "PERSONAL_MESSAGE",
        "QUESTION": "QUESTION",
    }.get(case.content_type, "FACTUAL_CLAIM")


def _deterministic_risk(signals: CaseSignals) -> str:
    suspicious_link = "suspicious_link_domain" in signals.attack_patterns
    link_impersonation = (
        "OPEN_LINK" in signals.requested_actions
        and signals.authority
        and (signals.urgency or signals.threat or suspicious_link)
    )
    if signals.user_action_state in {
        "OTP_SHARED", "APK_INSTALLED", "REMOTE_ACCESS_GRANTED",
        "PAYMENT_SENT", "ACCOUNT_TAKEOVER_SUSPECTED",
    }:
        return "CRITICAL"
    if (
        signals.secret_request_detected
        or signals.suspicious_executable_received
        or signals.remote_access_requested
        or signals.screen_share_requested
        or signals.safe_account_transfer_requested
        or link_impersonation
        or (signals.payment_requested and signals.authority)
    ):
        return "HIGH"
    if signals.sensitive_action_requested or signals.synthetic_media_possible:
        return "MEDIUM"
    return "UNKNOWN"


def _deterministic_investigation(
    signals: CaseSignals,
) -> tuple[list[str], list[str], list[str]]:
    checks = ["Verifikasi sumber asli dan konteks publikasi."]
    evidence = ["Sumber primer yang secara eksplisit membahas klaim."]
    sources = ["Sumber primer atau penerbit asli"]
    if signals.government_context:
        checks.append("Verifikasi program, prosedur, dan kanal pada situs instansi pemerintah resmi.")
        evidence.append("Pengumuman resmi instansi pemerintah yang bertanggung jawab.")
        sources.append("Instansi pemerintah terkait")
    if signals.secret_request_detected:
        checks.append("Periksa apakah pihak resmi pernah meminta secret seperti OTP, PIN, atau password.")
        evidence.append("Kebijakan keamanan resmi mengenai permintaan kode rahasia.")
        sources.append("Penyedia layanan atau regulator resmi")
    if signals.suspicious_executable_received:
        checks.append("Periksa keaslian, tanda tangan, dan kanal distribusi resmi file atau aplikasi.")
        evidence.append("Daftar aplikasi dan kanal distribusi resmi.")
    if signals.payment_requested:
        checks.append("Verifikasi alasan pembayaran, nama beneficiary, dan rekening tujuan.")
        evidence.append("Prosedur pembayaran resmi dan identitas penerima dana.")
        sources.append("Bank, PJP, atau regulator")
    if signals.synthetic_media_possible:
        checks.append("Periksa sumber video asli, provenance, dan konsistensi visual atau audio.")
        evidence.append("Rekaman asli atau pernyataan resmi pihak yang ditampilkan.")
    if signals.temporal_claim_present:
        checks.append("Bandingkan tanggal publikasi, periode berlaku, dan informasi resmi terkini.")
        evidence.append("Sumber bertanggal yang menunjukkan status terbaru.")
    if signals.numeric_claim_present:
        checks.append("Verifikasi angka, satuan, denominator, periode, dan metodologi sumber primer.")
        evidence.append("Dataset atau laporan primer yang memuat angka dan metodologi.")
    return _merge([], checks), _merge([], evidence), _merge([], sources)


def _fallback_claims(case: CaseContext, limit: int) -> list[PlannedClaim]:
    candidates = [claim.text for claim in case.seed_claims if claim.text.strip()]
    if not _prefer_seed_claims_over_ocr(case):
        candidates.extend(_material_clauses(case.safe_text))
    if not candidates and case.summary.strip():
        candidates.extend(_material_clauses(case.summary))
    claims: list[PlannedClaim] = []
    for candidate in candidates:
        clean = re.sub(r"\s+", " ", candidate).strip(" -")[:500]
        if (
            len(clean) < 12
            or _claim_is_low_quality_ocr_artifact(case, clean)
            or any(_claims_overlap(clean, item.text) for item in claims)
        ):
            continue
        claims.append(
            PlannedClaim(
                id=f"claim_{len(claims) + 1}",
                text=clean,
                claim_type=case.content_type,
                verifiable=case.content_type not in {"OPINION", "PERSONAL_MESSAGE"},
            )
        )
        if len(claims) >= limit:
            break
    return claims


def _material_clauses(text: str) -> list[str]:
    clauses = [item.strip() for item in _CLAUSE_SPLIT.split(text or "") if len(item.strip()) >= 12]
    ranked = sorted(
        enumerate(clauses),
        key=lambda pair: (
            bool(_RISK_TERMS.search(pair[1])),
            bool(_NUMBER_PATTERN.search(pair[1])),
            -pair[0],
        ),
        reverse=True,
    )
    selected = {index for index, _ in ranked[:8]}
    return [clause for index, clause in enumerate(clauses) if index in selected]


def _fallback_queries(claims: list[PlannedClaim], signals: CaseSignals) -> list[str]:
    suffix = " sumber resmi"
    if signals.government_context:
        suffix = " situs pemerintah resmi"
    return [f"{claim.text[:180]}{suffix}" for claim in claims[:4] if claim.verifiable]


def _retrieval_domains(case: CaseContext, signals: CaseSignals) -> list[str]:
    domains = list(signals.domains)
    text = " ".join((case.safe_text, case.summary)).casefold()
    if signals.attack_patterns:
        domains.append("scam")
    if signals.payment_requested:
        domains.append("finance")
    if signals.government_context and re.search(r"\b(?:bansos|bantuan|subsidi|blt)\b", text):
        domains.append("social_assistance")
    return list(dict.fromkeys(domains))


def _claim_source(case: CaseContext) -> str:
    return " ".join(
        [
            case.safe_text,
            case.summary,
            *case.entities,
            *(claim.text for claim in case.seed_claims),
        ]
    )


def _claim_is_grounded(claim: str, source: str) -> bool:
    claim_tokens = _meaningful_tokens(claim)
    source_tokens = set(_meaningful_tokens(source))
    if not claim_tokens or not source_tokens:
        return False
    claim_numbers = set(_NUMBER_PATTERN.findall(claim))
    source_numbers = set(_NUMBER_PATTERN.findall(source))
    if not claim_numbers <= source_numbers:
        return False
    overlap = sum(token in source_tokens for token in claim_tokens)
    return overlap >= min(2, len(set(claim_tokens))) and overlap / len(claim_tokens) >= 0.42


def _prefer_seed_claims_over_ocr(case: CaseContext) -> bool:
    return (
        case.extraction_method == "OCR_VISION"
        and case.extraction_confidence >= 0.75
        and any(claim.verifiable and claim.text.strip() for claim in case.seed_claims)
    )


def _claim_is_low_quality_ocr_artifact(case: CaseContext, claim: str) -> bool:
    if not _prefer_seed_claims_over_ocr(case):
        return False
    clean_claim = _normalize_for_similarity(claim)
    clean_ocr = _normalize_for_similarity(case.safe_text)
    if not clean_claim or not clean_ocr:
        return False
    if clean_claim == clean_ocr:
        return True
    if len(clean_claim) >= 40 and SequenceMatcher(None, clean_claim, clean_ocr).ratio() >= 0.88:
        return True
    if any(_claims_overlap(claim, seed.text) for seed in case.seed_claims if seed.verifiable):
        return False
    tokens = _meaningful_tokens(claim)
    if len(tokens) < 4:
        return True
    seed_tokens = {
        token
        for seed in case.seed_claims
        if seed.verifiable
        for token in _meaningful_tokens(seed.text)
    }
    overlap = len(set(tokens) & seed_tokens) / max(1, len(set(tokens)))
    return overlap < 0.25 and SequenceMatcher(None, clean_claim, clean_ocr).ratio() >= 0.65


def _claims_overlap(left: str, right: str) -> bool:
    left_tokens = set(_meaningful_tokens(left))
    right_tokens = set(_meaningful_tokens(right))
    if not left_tokens or not right_tokens:
        return False
    return len(left_tokens & right_tokens) / min(len(left_tokens), len(right_tokens)) >= 0.55


def _meaningful_tokens(value: str) -> list[str]:
    return [token for token in _TOKEN_PATTERN.findall(value.casefold()) if token not in _STOPWORDS]


def _normalize_for_similarity(value: str) -> str:
    return " ".join(_TOKEN_PATTERN.findall(value.casefold()))


def _select_excerpts(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    clauses = _material_clauses(text)
    selected: list[str] = []
    size = 0
    for clause in clauses:
        remaining = max_chars - size
        if remaining <= 0:
            break
        selected.append(clause[:remaining])
        size += len(selected[-1]) + 1
    if size < max_chars // 2:
        selected.append(text[: max_chars - size])
    return "\n".join(selected)[:max_chars]


def _merge(first: list[str], second: list[str]) -> list[str]:
    return list(dict.fromkeys(item for item in [*first, *second] if item))
