import json
from datetime import datetime
from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


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
OutputMode = Literal["STRUCTURED", "NARRATIVE", "BOTH"]
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


class PageContext(StrictModel):
    title: str | None = Field(default=None, max_length=300)
    before: str | None = Field(default=None, max_length=500)
    after: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def has_context_value(self) -> "PageContext":
        values = (self.title, self.before, self.after)
        if not any(value and value.strip() for value in values):
            raise ValueError("page_context harus memiliki minimal satu field berisi nilai.")
        return self


class TextVerificationRequest(StrictModel):
    text: str = Field(min_length=10, max_length=25_000)
    question: str = Field(
        default="Apakah isi teks ini benar dan aman ditindaklanjuti?",
        max_length=500,
    )
    source_url: str | None = Field(default=None, max_length=2048)
    sender_context: SenderContext = "UNKNOWN"
    page_context: PageContext | None = None
    output_mode: OutputMode = "STRUCTURED"


class CommunityEvidenceSource(StrictModel):
    title: str = Field(min_length=1, max_length=200)
    url: str = Field(min_length=1, max_length=2048)
    publisher: str | None = Field(default=None, max_length=160)
    published_at: str | None = None

    @field_validator("url")
    @classmethod
    def must_be_public_http_url(cls, value: str) -> str:
        parsed = urlparse(value.strip())
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("source url harus HTTP(S) publik.")
        host = parsed.hostname or ""
        if host in {"localhost", "127.0.0.1", "::1"} or host.startswith("10.") or host.startswith("192.168."):
            raise ValueError("source url tidak boleh menunjuk alamat lokal/private.")
        if host.startswith("172."):
            parts = host.split(".")
            if len(parts) > 1 and parts[1].isdigit() and 16 <= int(parts[1]) <= 31:
                raise ValueError("source url tidak boleh menunjuk alamat lokal/private.")
        return value.strip()

    @field_validator("published_at")
    @classmethod
    def validate_optional_rfc3339(cls, value: str | None) -> str | None:
        if value is None:
            return value
        _parse_rfc3339(value)
        return value


class CommunityEvidenceRecord(StrictModel):
    schema_version: Literal["1.0"]
    record_type: Literal["COMMUNITY_VERIFIED_EVIDENCE"]
    community_post_id: str
    case_id: str
    revision: int = Field(ge=1)
    content_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    status: Literal["VERIFIED_EVIDENCE"]
    title: str = Field(min_length=1, max_length=200)
    verified_claim: str = Field(min_length=1, max_length=500)
    stance: Literal["SUPPORTS", "REFUTES", "CONTEXT"]
    evidence_summary: str = Field(min_length=1, max_length=800)
    redacted_text: str | None = Field(default=None, max_length=4000)
    published_at: str
    verified_at: str
    sources: list[CommunityEvidenceSource] = Field(min_length=1, max_length=3)

    @field_validator("community_post_id", "case_id")
    @classmethod
    def validate_uuid_string(cls, value: str) -> str:
        import uuid

        try:
            uuid.UUID(value)
        except ValueError as exc:
            raise ValueError("harus UUID valid.") from exc
        return value

    @field_validator("published_at", "verified_at")
    @classmethod
    def validate_required_rfc3339(cls, value: str) -> str:
        _parse_rfc3339(value)
        return value


class InternalTextVerificationRequest(TextVerificationRequest):
    community_evidence: list[CommunityEvidenceRecord] = Field(default_factory=list, max_length=5)

    @model_validator(mode="after")
    def community_payload_size_limit(self) -> "InternalTextVerificationRequest":
        payload = json.dumps(
            [record.model_dump(mode="json") for record in self.community_evidence],
            ensure_ascii=False,
        ).encode("utf-8")
        if len(payload) > 30 * 1024:
            raise ValueError("community_evidence maksimal 30KB.")
        return self


def _parse_rfc3339(value: str) -> datetime:
    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError("timestamp harus RFC3339.") from exc
    if parsed.tzinfo is None:
        raise ValueError("timestamp harus memiliki timezone.")
    return parsed


class CaseContext(StrictModel):
    """Privacy-filtered, modality-neutral input consumed by the shared pipeline."""

    input_type: InputType
    content_type: str
    safe_text: str
    question: str
    page_context: PageContext | None = None
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


class NarrativePresentation(StrictModel):
    text: str
    summary: str
    paragraphs: list[str]


class ResponsePresentation(StrictModel):
    requested_mode: OutputMode
    structured: bool
    narrative: NarrativePresentation | None


class OfficialReferralRoute(StrictModel):
    route_type: Literal[
        "OFFICIAL_INSTITUTION",
        "ACCOUNT_PROVIDER",
        "FINANCIAL_PROVIDER",
        "FINANCIAL_SCAM_REPORTING",
        "PLATFORM_REPORTING",
        "DEVICE_RECOVERY",
    ]
    priority: Literal["PRIMARY", "SECONDARY"]
    reason: str = Field(min_length=1, max_length=240)


class OfficialReferralAdvice(StrictModel):
    status: Literal["NOT_REQUIRED", "RECOMMENDED", "URGENT"]
    mode: Literal["PREVENTION", "RECOVERY"] | None
    reason_codes: list[str]
    summary: str | None = Field(default=None, max_length=300)
    routes: list[OfficialReferralRoute]


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
    official_referral: OfficialReferralAdvice
    privacy_notice: str
    rulebook: RulebookTrace
    pipeline: list[PipelineStage]
    presentation: ResponsePresentation
    disclaimer: str
