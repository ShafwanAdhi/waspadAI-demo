from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


VerdictLabel = Literal[
    "SUPPORTED",
    "REFUTED",
    "MISLEADING",
    "PARTLY_TRUE",
    "OUTDATED",
    "UNVERIFIED",
    "SATIRE",
    "OPINION",
]
RiskLevel = Literal["CRITICAL", "HIGH", "MEDIUM", "LOW", "UNKNOWN"]
Stance = Literal["SUPPORTS", "REFUTES", "CONTEXT", "UNKNOWN"]
RetrievalPhase = Literal["DETECTION", "INVESTIGATION", "DECISION", "RESPONSE"]
InputType = Literal["IMAGE", "TEXT"]
TextContentType = Literal[
    "NEWS_ARTICLE",
    "NEWS_EXCERPT",
    "FORWARDED_MESSAGE",
    "UNKNOWN_SENDER_MESSAGE",
    "SOCIAL_MEDIA_CAPTION",
    "CLAIM_ONLY",
    "ADVERTISEMENT",
    "PERSONAL_MESSAGE",
    "OPINION",
    "SATIRE",
    "QUESTION",
    "URL_ONLY",
    "UNKNOWN",
]
SenderContext = Literal[
    "NOT_APPLICABLE",
    "UNKNOWN_NUMBER",
    "KNOWN_CONTACT",
    "FORWARDED",
    "SOCIAL_MEDIA",
    "UNKNOWN",
]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class OCRBlock(StrictModel):
    text: str
    bbox: list[int]
    confidence: float


class OCRResult(StrictModel):
    status: Literal["OK", "EMPTY", "UNAVAILABLE", "FAILED"]
    raw_text: str
    blocks: list[OCRBlock]
    urls: list[str]
    phone_numbers: list[str]
    note: str


class MediaMetadata(StrictModel):
    mime_type: str
    width: int
    height: int
    format: str
    has_exif: bool
    created_at: str | None
    source_application: str | None
    provenance_status: Literal["PRESENT", "NOT_FOUND", "NOT_CHECKED"]
    note: str


class VisionClaim(StrictModel):
    text: str
    verifiable: bool


class VisionOutput(StrictModel):
    content_type: str
    platform: str | None
    visual_summary: str
    visual_entities: list[str]
    possible_impersonation: bool
    visible_urls: list[str]
    claims: list[VisionClaim]
    vision_confidence: float = Field(ge=0, le=1)


class TextVerificationRequest(StrictModel):
    text: str = Field(min_length=10, max_length=25_000)
    question: str = Field(
        default="Apakah isi teks ini benar dan aman ditindaklanjuti?",
        max_length=500,
    )
    source_url: str | None = Field(default=None, max_length=2048)
    sender_context: SenderContext = "UNKNOWN"


class CaseContext(StrictModel):
    """Privacy-filtered, modality-neutral input consumed by the shared pipeline."""

    input_type: InputType
    content_type: str
    safe_text: str
    question: str
    source_url: str | None
    sender_context: SenderContext
    platform: str | None
    summary: str
    entities: list[str]
    possible_impersonation: bool
    urls: list[str]
    seed_claims: list[VisionClaim]
    extraction_confidence: float = Field(ge=0, le=1)
    extraction_method: Literal["OCR_VISION", "LOCAL_TEXT"]
    source_character_count: int = Field(ge=0)
    language: str


class CanonicalActionSignal(StrictModel):
    actor: str
    action: str
    object: str
    target: str
    polarity: Literal["REQUEST", "OBSERVED_ACTION", "NEGATED_WARNING"]
    modality_source: Literal["OCR", "VISION", "TEXT", "USER_QUESTION", "FUSED_TEXT"]
    extraction_confidence: float = Field(ge=0, le=1)


class CaseSignals(StrictModel):
    domains: list[str]
    attack_patterns: list[str]
    channels: list[str]
    requested_actions: list[str]
    requested_secrets: list[str]
    user_action_state: Literal[
        "NO_ACTION",
        "LINK_CLICKED",
        "CREDENTIAL_ENTERED",
        "OTP_SHARED",
        "APK_INSTALLED",
        "REMOTE_ACCESS_GRANTED",
        "PAYMENT_SENT",
        "ACCOUNT_TAKEOVER_SUSPECTED",
    ]
    government_context: bool
    secret_request_detected: bool
    suspicious_executable_received: bool
    remote_access_requested: bool
    screen_share_requested: bool
    payment_requested: bool
    safe_account_transfer_requested: bool
    authority: bool
    threat: bool
    urgency: bool
    sensitive_action_requested: bool
    synthetic_media_possible: bool
    information_integrity_context: bool
    source_url_present: bool
    source_provenance_missing: bool
    quote_or_attribution_present: bool
    temporal_claim_present: bool
    numeric_claim_present: bool
    payment_destination_type: Literal["PERSONAL", "OFFICIAL", "UNKNOWN"]
    beneficiary_status: Literal["VERIFIED", "UNVERIFIED", "MISMATCH", "UNKNOWN"]
    reputation_result: Literal["HIT", "NO_KNOWN_REPORT", "NOT_CHECKED"]
    action_signals: list[CanonicalActionSignal]
    extraction_notes: list[str]


class RuleMatch(StrictModel):
    rule_id: str
    rulebook_id: str
    rulebook_version: str
    domain: str
    chunk_type: str
    phase: RetrievalPhase
    title: str
    content: str
    severity: Literal["CRITICAL", "HIGH", "MEDIUM", "LOW"] | None
    source_ids: list[str]
    match_types: list[Literal["DETERMINISTIC", "BM25", "SUBWORD", "METADATA", "SAFE_FALLBACK"]]
    matched_signals: list[str]
    retrieval_score: float = Field(ge=0, le=1)
    agent_action: str | None
    caveat: str | None
    does_not_prove: list[str]


class RulebookTrace(StrictModel):
    corpus_versions: list[str]
    retrieval_mode: str
    candidate_count: int
    selected_count: int
    forced_rule_ids: list[str]
    cache_hit: bool
    duration_ms: int


class RulebookResult(StrictModel):
    matches: list[RuleMatch]
    forced_actions: list[str]
    trace: RulebookTrace


class PlannedClaim(StrictModel):
    id: str
    text: str
    claim_type: str
    verifiable: bool


class RetrievalPlan(StrictModel):
    web_search: bool
    domain_rag: list[str]
    community_rag: bool
    factcheck_rag: bool


class PlannerDraftOutput(StrictModel):
    """Compact model-owned fields; deterministic fields are added by the backend."""

    classification: Literal[
        "FACTUAL_CLAIM",
        "OPINION",
        "SATIRE",
        "SCAM_MESSAGE",
        "ADVERTISEMENT",
        "PERSONAL_MESSAGE",
        "QUESTION",
        "UNKNOWN",
    ]
    domains: list[str]
    attack_patterns: list[str]
    claims: list[PlannedClaim]
    complexity: Literal["SIMPLE", "MEDIUM", "HIGH"]
    critical_checks: list[str]
    required_evidence: list[str]
    preferred_sources: list[str]
    applied_rule_ids: list[str]
    retrieval_plan: RetrievalPlan
    web_queries: list[str]


class PlannerReviewPatch(StrictModel):
    """Small 120B-owned patch; backend merges and revalidates it."""

    accept_plan: bool
    classification_override: Literal[
        "FACTUAL_CLAIM",
        "OPINION",
        "SATIRE",
        "SCAM_MESSAGE",
        "ADVERTISEMENT",
        "PERSONAL_MESSAGE",
        "QUESTION",
        "UNKNOWN",
    ] | None
    complexity_override: Literal["SIMPLE", "MEDIUM", "HIGH"] | None
    drop_claim_ids: list[str]
    rewrite_claims: list[PlannedClaim]
    add_claims: list[PlannedClaim]
    add_domains: list[str]
    add_attack_patterns: list[str]
    add_critical_checks: list[str]
    add_required_evidence: list[str]
    add_preferred_sources: list[str]
    add_web_queries: list[str]
    force_web_search: bool | None
    force_factcheck_rag: bool | None
    risk_notes: list[str]
    reason: str


class PlannerOutput(StrictModel):
    classification: Literal[
        "FACTUAL_CLAIM",
        "OPINION",
        "SATIRE",
        "SCAM_MESSAGE",
        "ADVERTISEMENT",
        "PERSONAL_MESSAGE",
        "QUESTION",
        "UNKNOWN",
    ]
    domains: list[str]
    attack_patterns: list[str]
    claims: list[PlannedClaim]
    requires_fresh_data: bool
    complexity: Literal["SIMPLE", "MEDIUM", "HIGH"]
    potential_financial_risk: bool
    potential_identity_impersonation: bool
    contains_url: bool
    critical_checks: list[str]
    required_evidence: list[str]
    preferred_sources: list[str]
    interim_risk: RiskLevel
    interim_actions: list[str]
    applied_rule_ids: list[str]
    retrieval_plan: RetrievalPlan
    web_queries: list[str]


class Evidence(StrictModel):
    id: str
    claim_id: str
    source_type: str
    publisher: str
    title: str
    url: str
    published_at: str | None
    retrieved_at: str
    excerpt: str
    relevance: float = Field(ge=0, le=1)
    authority: float = Field(ge=0, le=1)
    recency: float = Field(ge=0, le=1)
    stance: Stance
    verification_status: Literal["VERIFIED", "REVIEWED", "UNVERIFIED"]


class ClaimAssessment(StrictModel):
    claim_id: str
    verdict: VerdictLabel
    supporting_evidence: list[str]
    refuting_evidence: list[str]
    contradiction_level: Literal["NONE", "LOW", "MEDIUM", "HIGH"]
    reason: str


class RecommendedAction(StrictModel):
    code: str
    title: str
    detail: str


class VerificationDecision(StrictModel):
    claims: list[ClaimAssessment]
    overall_verdict: VerdictLabel
    risk_level: RiskLevel
    evidence_sufficiency: float = Field(ge=0, le=1)
    requires_human_review: bool
    headline: str
    what_checked: list[str]
    why: list[str]
    recommended_actions: list[RecommendedAction]
    uncertainty: str


class AssessmentDimensions(StrictModel):
    factual_status: VerdictLabel | Literal["NOT_APPLICABLE"]
    source_authenticity: Literal[
        "VERIFIED", "UNVERIFIED", "SUSPICIOUS", "NOT_APPLICABLE"
    ]
    sender_identity: Literal[
        "VERIFIED",
        "UNVERIFIED",
        "IMPERSONATION_LIKELY",
        "IMPERSONATION_CONFIRMED",
        "NOT_APPLICABLE",
    ]
    channel_status: Literal[
        "VERIFIED", "UNVERIFIED", "SUSPICIOUS", "MALICIOUS", "NOT_APPLICABLE"
    ]
    scam_risk: RiskLevel
    content_authenticity: Literal[
        "ORIGINAL", "ALTERED", "SYNTHETIC", "UNVERIFIED", "NOT_APPLICABLE"
    ]


class PipelineStage(StrictModel):
    key: str
    label: str
    status: Literal["COMPLETED", "SKIPPED", "FALLBACK"]
    detail: str
    duration_ms: int


class SourceView(StrictModel):
    publisher: str
    title: str
    url: str
    published_at: str | None


class InputSummary(StrictModel):
    input_type: InputType
    content_type: str
    label: str
    media_type: str | None
    dimensions: str | None
    extraction_status: str
    excerpt: str
    source_url: str | None
    sender_context: SenderContext
    character_count: int
    urls_detected: int
    pii_types_redacted: list[str]


class VerificationResponse(StrictModel):
    request_id: str
    trace_id: str
    status: Literal["COMPLETED"]
    mode: Literal["LIVE"]
    mode_notice: str
    input_summary: InputSummary
    verdict: VerdictLabel
    risk_level: RiskLevel
    dimensions: AssessmentDimensions
    headline: str
    evidence_sufficiency: float
    evidence_sufficiency_label: str
    what_checked: list[str]
    why: list[str]
    evidence: list[Evidence]
    recommended_actions: list[RecommendedAction]
    sources: list[SourceView]
    uncertainty: str
    requires_human_review: bool
    community_status: Literal["NOT_REQUIRED", "ELIGIBLE_WITH_CONSENT"]
    privacy_notice: str
    rulebook: RulebookTrace
    pipeline: list[PipelineStage]
    disclaimer: str
