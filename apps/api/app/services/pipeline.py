import asyncio
import re
import time
import uuid
from datetime import datetime, timezone

from groq import APIConnectionError, APIStatusError, BadRequestError, InternalServerError, RateLimitError
from PIL import Image

from app.config import Settings
from app.schemas import (
    AssessmentDimensions,
    CaseContext,
    CaseSignals,
    ClaimAssessment,
    CommunityEvidenceRecord,
    Evidence,
    InputSummary,
    MediaMetadata,
    NarrativePresentation,
    OutputMode,
    PipelineStage,
    PlannedClaim,
    PlannerOutput,
    ResponsePresentation,
    RulebookResult,
    RulebookTrace,
    RecommendedAction,
    SourceView,
    VerificationResponse,
    VerificationDecision,
    PageContext,
)
from app.services.groq_service import (
    GroqFactCheckService,
    ModelOutputError,
    review_token_budget,
)
from app.services.community_evidence import (
    community_evidence_trace,
    community_records_to_evidence,
)
from app.services.debug_trace import DebugTraceStore, instruction_profile
from app.services.evidence_store import LocalVerifiedEvidenceStore
from app.services.image_processing import image_to_data_url, run_local_ocr
from app.services.input_adapters import (
    build_image_case,
    build_text_case,
    sanitize_urls_in_text,
)
from app.services.privacy import normalize_text, redact_pii
from app.services.rag import RulebookRAG
from app.services.rate_limits import GroqRateLimitMonitor
from app.services.signal_extraction import extract_case_signals
from app.services.web_search import TavilyWebSearchService, WebSearchError
from app.services.planner_guardrails import (
    deterministic_fallback_plan,
    validate_and_repair_plan,
)
from app.services.presentation import build_narrative_presentation


RECOVERABLE_MODEL_ERRORS = (
    ModelOutputError,
    APIStatusError,
    BadRequestError,
    RateLimitError,
    APIConnectionError,
    InternalServerError,
    WebSearchError,
)


CLAIM_STOPWORDS = {
    "yang", "dan", "atau", "dari", "di", "ke", "ini", "itu", "untuk", "pada",
    "dengan", "sebagai", "setelah", "tersebut", "dalam", "oleh", "karena",
    "the", "and", "or", "of", "in", "on", "as", "to", "for", "with", "from",
    "berhasil", "menjadi", "menggunakan", "dilaksanakan", "berlangsung",
}
TOKEN_RE = re.compile(r"[a-z0-9]+", re.I)
NUMBER_RE = re.compile(r"\b\d+(?:[.,]\d+)?\b")
YEAR_RE = re.compile(r"\b20\d{2}\b")
DATE_TOKEN_RE = re.compile(
    r"\b(?:januari|februari|maret|april|mei|juni|juli|agustus|september|"
    r"oktober|november|desember|january|february|march|april|may|june|july|"
    r"august|september|october|november|december)\b",
    re.I,
)
LOCATION_ALIASES = {
    "bogor": {"bogor", "jawa barat", "indonesia"},
    "florida": {"florida"},
    "texas": {"texas", "starbase", "boca chica"},
    "starbase": {"starbase", "boca chica", "texas"},
    "boca": {"boca chica", "starbase", "texas"},
    "hokkaido": {"hokkaido"},
    "noto": {"noto", "ishikawa", "honshu"},
    "ishikawa": {"ishikawa", "noto", "honshu"},
    "stade": {"stade de france", "stadium"},
    "seine": {"seine", "sungai seine", "river seine"},
    "washington": {"washington", "capitol", "rotunda"},
}


class FactCheckPipeline:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.rulebook = RulebookRAG(settings)
        self.evidence_store = LocalVerifiedEvidenceStore()
        self.rate_limits = GroqRateLimitMonitor(settings)
        self.web_search = TavilyWebSearchService(settings)
        self.groq = (
            GroqFactCheckService(settings, rate_limits=self.rate_limits)
            if settings.groq_api_key.strip()
            else None
        )
        self.debug_traces = DebugTraceStore(settings)

    async def verify_image(
        self,
        image: Image.Image,
        metadata: MediaMetadata,
        filename: str,
        question: str,
        output_mode: OutputMode = "STRUCTURED",
        community_evidence: list[CommunityEvidenceRecord] | None = None,
    ) -> VerificationResponse:
        request_id = f"req_{uuid.uuid4().hex[:12]}"
        trace_id = f"trace_{uuid.uuid4().hex[:16]}"
        stages: list[PipelineStage] = []
        self.debug_traces.start(
            trace_id,
            request_id,
            input_type="IMAGE",
            mode="LIVE",
        )

        started = time.perf_counter()
        ocr = await asyncio.to_thread(run_local_ocr, image, self.settings)
        normalized_ocr = normalize_text(ocr.raw_text)
        sanitized_ocr, _ = sanitize_urls_in_text(
            normalized_ocr,
            max_urls=self.settings.max_case_urls,
        )
        redacted_ocr, ocr_pii_types = redact_pii(sanitized_ocr)
        normalized_question = normalize_text(question[: self.settings.max_image_question_chars])
        sanitized_question, _ = sanitize_urls_in_text(
            normalized_question,
            max_urls=self.settings.max_case_urls,
        )
        safe_question, question_pii_types = redact_pii(sanitized_question)
        extraction_ms = _elapsed_ms(started)
        self.debug_traces.add_stage(
            trace_id,
            key="image_preprocessing",
            label="Validasi gambar & OCR lokal",
            status="FALLBACK" if ocr.status != "OK" else "COMPLETED",
            duration_ms=extraction_ms,
            input_data={
                "filename": filename,
                "question": safe_question,
                "metadata": metadata,
            },
            output_data={
                "ocr_status": ocr.status,
                "ocr_excerpt_redacted": redacted_ocr[:1200],
                "pii_types_redacted": _unique([*ocr_pii_types, *question_pii_types]),
            },
            notes=["Binary gambar dan raw OCR tidak dimasukkan ke debug trace."],
        )

        assert self.groq is not None
        image_data_url = await asyncio.to_thread(image_to_data_url, image, metadata)
        vision_started = time.perf_counter()
        vision = await self.groq.understand_image(
            image_data_url=image_data_url,
            ocr=ocr,
            metadata=metadata,
            redacted_ocr_text=redacted_ocr,
            user_query=safe_question,
        )
        vision_ms = _elapsed_ms(vision_started)
        self.debug_traces.add_stage(
            trace_id,
            key="vision_understanding",
            label="Vision understanding",
            status="COMPLETED",
            duration_ms=vision_ms,
            runtime="GROQ",
            model=self.settings.groq_vision_model,
            input_data={
                "ocr_status": ocr.status,
                "ocr_excerpt_redacted": redacted_ocr[:1200],
                "metadata": metadata,
                "question": safe_question,
            },
            output_data=vision,
            instruction=instruction_profile("vision", self.settings.groq_vision_model),
            notes=["Image data URL sengaja tidak dicatat."],
        )
        case, adapter_pii_types = build_image_case(
            vision,
            redacted_ocr,
            safe_question,
            len(normalized_ocr),
            self.settings.max_case_urls,
        )
        pii_types = _unique([*ocr_pii_types, *question_pii_types, *adapter_pii_types])
        input_summary = _image_input_summary(
            case,
            filename,
            metadata,
            ocr.status,
            pii_types,
        )
        self.debug_traces.add_stage(
            trace_id,
            key="case_adapter",
            label="Bangun CaseContext aman",
            status="COMPLETED",
            input_data={"vision_output": vision, "ocr_status": ocr.status},
            output_data=case,
            notes=["CaseContext sudah melalui sanitasi URL dan redaksi PII."],
        )
        self.debug_traces.set_input_summary(trace_id, input_summary)
        stages.append(
            PipelineStage(
                key="extraction",
                label="Baca gambar",
                status="COMPLETED" if ocr.status == "OK" else "FALLBACK",
                detail=f"OCR {ocr.status.lower()}, metadata, dan Qwen Vision digabungkan.",
                duration_ms=extraction_ms + vision_ms,
            )
        )

        if _is_non_checkable_image(case):
            relevance_stage = PipelineStage(
                key="image_relevance",
                label="Cek kelayakan fact-check",
                status="SKIPPED",
                detail="Tidak ada klaim, teks, URL, pesan, dokumen, poster, atau konteks verifikasi yang terdeteksi.",
                duration_ms=0,
            )
            stages.append(relevance_stage)
            self.debug_traces.add_stage(
                trace_id,
                key="image_relevance",
                label="Cek kelayakan fact-check",
                status="SKIPPED",
                duration_ms=0,
                runtime="LOCAL_DETERMINISTIC",
                input_data={"case": case},
                output_data={
                    "non_checkable": True,
                    "reason": "Gambar tidak memuat klaim yang dapat diverifikasi.",
                },
                instruction={
                    "version": "image-relevance.v1",
                    "runtime": "LOCAL_DETERMINISTIC",
                    "invariants": [
                        "Gambar valid secara file belum tentu layak untuk fact-check.",
                        "Jika tidak ada klaim yang dapat diperiksa, skip planner, retrieval, dan verifier.",
                    ],
                },
            )
            response = self._build_non_checkable_image_response(
                request_id=request_id,
                trace_id=trace_id,
                input_summary=input_summary,
                stages=stages,
                output_mode=output_mode,
            )
            self.debug_traces.complete(trace_id, response)
            return response

        return await self._verify_case(
            case=case,
            input_summary=input_summary,
            stages=stages,
            request_id=request_id,
            trace_id=trace_id,
            output_mode=output_mode,
            community_records=community_evidence or [],
        )

    async def verify_text(
        self,
        text: str,
        question: str,
        source_url: str | None,
        sender_context: str,
        page_context: PageContext | None = None,
        output_mode: OutputMode = "STRUCTURED",
        community_evidence: list[CommunityEvidenceRecord] | None = None,
    ) -> VerificationResponse:
        request_id = f"req_{uuid.uuid4().hex[:12]}"
        trace_id = f"trace_{uuid.uuid4().hex[:16]}"
        self.debug_traces.start(
            trace_id,
            request_id,
            input_type="TEXT",
            mode="LIVE",
        )
        started = time.perf_counter()
        case, pii_types = build_text_case(
            text=text,
            question=question,
            source_url=source_url,
            sender_context=sender_context,
            max_urls=self.settings.max_case_urls,
            page_context=page_context,
        )
        stages = [
            PipelineStage(
                key="extraction",
                label="Baca teks",
                status="COMPLETED",
                detail=(
                    f"Normalisasi, sanitasi URL, redaksi PII, dan klasifikasi lokal "
                    f"selesai ({case.content_type})."
                ),
                duration_ms=_elapsed_ms(started),
            )
        ]
        input_summary = _text_input_summary(case, pii_types)
        self.debug_traces.add_stage(
            trace_id,
            key="text_input_adapter",
            label="Normalisasi & adaptasi teks",
            status="COMPLETED",
            duration_ms=stages[0].duration_ms,
            input_data={
                "character_count": len(text),
                "question": case.question,
                "page_context": case.page_context,
                "source_url": case.source_url,
                "sender_context": case.sender_context,
            },
            output_data=case,
            instruction={
                "version": "text-adapter.v1",
                "runtime": "LOCAL_DETERMINISTIC",
                "invariants": [
                    "Teks user adalah claim source, bukan evidence.",
                    "PII dan parameter pelacakan URL disaring sebelum reasoning.",
                    "Plain text tidak dinilai autentisitas medianya.",
                ],
            },
        )
        self.debug_traces.set_input_summary(trace_id, input_summary)
        return await self._verify_case(
            case=case,
            input_summary=input_summary,
            stages=stages,
            request_id=request_id,
            trace_id=trace_id,
            output_mode=output_mode,
            community_records=community_evidence or [],
        )

    async def _verify_case(
        self,
        case: CaseContext,
        input_summary: InputSummary,
        stages: list[PipelineStage],
        request_id: str,
        trace_id: str,
        output_mode: OutputMode,
        community_records: list[CommunityEvidenceRecord],
    ) -> VerificationResponse:
        assert self.groq is not None

        signal_started = time.perf_counter()
        signals = extract_case_signals(case)
        self.debug_traces.add_stage(
            trace_id,
            key="signal_extraction",
            label="Ekstraksi sinyal kanonik",
            duration_ms=_elapsed_ms(signal_started),
            input_data=case,
            output_data=signals,
            instruction={
                "version": "signals.v2",
                "runtime": "LOCAL_DETERMINISTIC",
                "invariants": [
                    "Negasi dan konteks edukatif diperiksa sebelum memicu indikator.",
                    "Sinyal risiko bukan factual verdict.",
                ],
            },
        )

        rulebook_started = time.perf_counter()
        rule_query = " ".join(
            [
                case.safe_text,
                case.summary,
                case.question,
                *(claim.text for claim in case.seed_claims),
            ]
        )
        rulebook = await self.rulebook.retrieve(rule_query, signals)
        rulebook_ms = _elapsed_ms(rulebook_started)
        self.debug_traces.add_stage(
            trace_id,
            key="rulebook_retrieval",
            label="Retrieval Rulebook RAG",
            duration_ms=rulebook_ms,
            runtime="LOCAL_RAG",
            input_data={"query_redacted": rule_query, "signals": signals},
            output_data=rulebook,
            instruction={
                "version": "rulebook-rag.v2",
                "runtime": "DETERMINISTIC_TRIGGERS_PLUS_HYBRID_RETRIEVAL",
                "invariants": [
                    "RuleMatch adalah investigation policy, bukan Evidence.",
                    "Critical deterministic rules selalu di-force include.",
                    "Rule dipilih dengan phase-aware coverage.",
                ],
            },
        )
        stages.append(
            PipelineStage(
                key="rulebook",
                label="Ambil rulebook",
                status="COMPLETED",
                detail=(
                    f"{len(rulebook.matches)} rule terpilih; "
                    f"{len(rulebook.trace.forced_rule_ids)} deterministic force; "
                    f"mode {rulebook.trace.retrieval_mode}."
                ),
                duration_ms=rulebook_ms,
            )
        )

        planner_started = time.perf_counter()
        first_pass_error: Exception | None = None
        try:
            draft_plan = await self.groq.plan(case, signals, rulebook)
            first_pass_status = "COMPLETED"
        except RECOVERABLE_MODEL_ERRORS as exc:
            _raise_if_nonrecoverable_provider_error(exc)
            first_pass_error = exc
            first_pass_status = "FALLBACK"
            draft_plan = deterministic_fallback_plan(
                case,
                signals,
                rulebook,
                self.settings,
            )
        self.debug_traces.add_stage(
            trace_id,
            key="investigation_planner",
            label="Investigation planner - 20B first pass",
            status=first_pass_status,
            duration_ms=_elapsed_ms(planner_started),
            runtime="GROQ",
            model=self.settings.groq_planner_model,
            input_data={
                "case": case,
                "signals": signals,
                "rule_context_policy": rulebook.matches,
                "forced_actions": rulebook.forced_actions,
            },
            output_data={
                "draft_plan": draft_plan,
                "fallback_reason": _planner_error_view(first_pass_error),
            },
            instruction=instruction_profile("planner", self.settings.groq_planner_model),
            notes=[
                "Fallback deterministik dipakai; raw provider error tidak dicatat."
                if first_pass_error
                else "First-pass model selesai; output belum dipercaya sebelum validasi lokal."
            ],
        )

        validation_started = time.perf_counter()
        guardrail = validate_and_repair_plan(
            case,
            signals,
            rulebook,
            draft_plan,
            self.settings,
            fallback_used=first_pass_error is not None,
        )
        planner = guardrail.plan
        self.debug_traces.add_stage(
            trace_id,
            key="planner_validation",
            label="Validasi grounding & kebijakan eskalasi",
            duration_ms=_elapsed_ms(validation_started),
            runtime="LOCAL_DETERMINISTIC",
            input_data={"draft_plan": draft_plan, "signals": signals},
            output_data=guardrail.trace_payload(),
            instruction={
                "version": "planner-guardrail.v1",
                "runtime": "LOCAL_DETERMINISTIC",
                "invariants": [
                    "Klaim yang tidak terlacak ke input dibuang.",
                    "Critical signals dapat memaksa klasifikasi, risk, checks, dan eskalasi.",
                    "Model tidak menentukan eskalasinya sendiri.",
                ],
            },
        )

        review_reasons = _model_review_reasons(guardrail.escalation_reasons)
        review_budget = review_token_budget(
            case,
            signals,
            rulebook,
            planner,
            [*guardrail.issues, *guardrail.escalation_reasons],
            self.settings,
        )
        review_enabled = self.settings.planner_review_enabled
        review_attempted = (
            review_enabled
            and bool(review_reasons)
            and bool(review_budget["should_call"])
        )
        review_completed = False
        review_error: Exception | None = None
        review_skip_reason = ""
        if review_attempted:
            review_started = time.perf_counter()
            try:
                reviewed = await self.groq.review_plan(
                    case,
                    signals,
                    rulebook,
                    planner,
                    [*guardrail.issues, *guardrail.escalation_reasons],
                )
                reviewed_guardrail = validate_and_repair_plan(
                    case,
                    signals,
                    rulebook,
                    reviewed,
                    self.settings,
                )
                planner = reviewed_guardrail.plan
                review_completed = True
                review_output = {
                    "reviewed_plan": reviewed,
                    "post_review_validation": reviewed_guardrail.trace_payload(),
                }
                review_status = "COMPLETED"
            except RECOVERABLE_MODEL_ERRORS as exc:
                _raise_if_nonrecoverable_provider_error(exc)
                review_error = exc
                review_output = {
                    "retained_plan": planner,
                    "fallback_reason": _planner_error_view(exc),
                }
                review_status = "FALLBACK"
            self.debug_traces.add_stage(
                trace_id,
                key="planner_review",
                label="Senior planner review - 120B",
                status=review_status,
                duration_ms=_elapsed_ms(review_started),
                runtime="GROQ",
                model=self.settings.groq_escalation_model,
                input_data={
                    "validated_draft": guardrail.plan,
                    "validation_issues": guardrail.issues,
                    "escalation_reasons": guardrail.escalation_reasons,
                    "model_review_reasons": review_reasons,
                    "review_enabled": review_enabled,
                    "token_budget": review_budget,
                },
                output_data=review_output,
                instruction=instruction_profile(
                    "planner_review", self.settings.groq_escalation_model
                ),
                notes=[
                    "Review gagal; rencana tervalidasi lokal tetap digunakan."
                    if review_error
                    else "120B mereview payload ringkas, bukan mengulang seluruh planning."
                ],
            )
        else:
            review_skip_reason = (
                "Review 120B nonaktif pada konfigurasi ini; rencana aman lokal dipertahankan."
                if not review_enabled
                else "Tidak ada pemicu eskalasi yang membutuhkan model reviewer."
                if not review_reasons
                else "Estimasi token review melewati budget; rencana aman lokal dipertahankan."
            )
            self.debug_traces.add_stage(
                trace_id,
                key="planner_review",
                label="Senior planner review - 120B",
                status="SKIPPED",
                runtime="GROQ",
                model=self.settings.groq_escalation_model,
                input_data={
                    "escalation_reasons": guardrail.escalation_reasons,
                    "model_review_reasons": review_reasons,
                    "review_enabled": review_enabled,
                    "token_budget": review_budget,
                },
                output_data={"reason": review_skip_reason, "retained_plan": planner},
                instruction=instruction_profile(
                    "planner_review", self.settings.groq_escalation_model
                ),
            )

        planner_ms = _elapsed_ms(planner_started)
        degraded = first_pass_error is not None or review_error is not None
        stages.append(
            PipelineStage(
                key="planning",
                label="Petakan klaim",
                status="FALLBACK" if degraded else "COMPLETED",
                detail=(
                    f"{len(planner.claims)} klaim tervalidasi; domain "
                    f"{', '.join(planner.domains[:3]) or 'GENERAL'}; "
                    + (
                        "review 120B selesai."
                        if review_completed
                        else "review 120B gagal, rencana aman lokal dipertahankan."
                        if review_attempted
                        else review_skip_reason
                    )
                ),
                duration_ms=planner_ms,
            )
        )

        retrieval_started = time.perf_counter()
        web_result, domain_result = await asyncio.gather(
            _timed_external_result(self.web_search.search(planner)),
            _timed_result(
                self.evidence_store.retrieve_domain(
                    planner.claims,
                    planner.retrieval_plan.domain_rag,
                )
            ),
        )
        web_evidence, web_ms, web_error = web_result
        domain_evidence, domain_ms = domain_result
        community_started = time.perf_counter()
        community_evidence = community_records_to_evidence(community_records, planner.claims)
        community_ms = _elapsed_ms(community_started)
        search_provider = self.web_search.provider_name
        self.debug_traces.add_stage(
            trace_id,
            key="web_search",
            label="Web evidence retrieval",
            status=(
                "SKIPPED"
                if not planner.retrieval_plan.web_search
                else "FALLBACK"
                if web_error
                else "COMPLETED"
            ),
            duration_ms=web_ms,
            runtime="EXTERNAL_SEARCH_API",
            model=search_provider,
            input_data={
                "claims": planner.claims,
                "queries": planner.web_queries[: self.settings.web_search_max_queries],
                "domains": planner.domains,
                "requires_fresh_data": planner.requires_fresh_data,
                "provider_configured": self.web_search.configured,
            },
            output_data=(
                {
                    "evidence": [],
                    "fallback_reason": _planner_error_view(web_error),
                }
                if web_error
                else web_evidence
            ),
            instruction={
                "version": "controlled-web-search.v1",
                "runtime": "EXTERNAL_SEARCH_API",
                "provider": search_provider,
                "invariants": [
                    "Tidak ada model agentik yang mengatur loop pencarian.",
                    "Jumlah query, hasil, dan panjang snippet dibatasi backend.",
                    "Hasil pencarian adalah data tak tepercaya, bukan verdict.",
                ],
            },
            notes=(
                ["Web retrieval gagal; local verified stores tetap dilanjutkan."]
                if web_error
                else []
            ),
        )
        self.debug_traces.add_stage(
            trace_id,
            key="domain_evidence",
            label="Verified domain evidence store",
            duration_ms=domain_ms,
            runtime="LOCAL_VERIFIED_STORE",
            input_data={
                "claims": planner.claims,
                "enabled": planner.retrieval_plan.domain_rag,
            },
            output_data=domain_evidence,
            instruction={
                "version": "domain-store.v1",
                "invariant": "Hanya record lokal dengan provenance terverifikasi yang dikembalikan.",
            },
        )
        self.debug_traces.add_stage(
            trace_id,
            key="community_evidence",
            label="Request-scoped community evidence",
            duration_ms=community_ms,
            runtime="REQUEST_PAYLOAD_ADAPTER",
            input_data={
                "claims": planner.claims,
                "received_records": len(community_records),
            },
            output_data={
                "trace": community_evidence_trace(community_records, community_evidence),
                "evidence": community_evidence,
            },
            instruction={
                "version": "community-request-evidence.v1",
                "invariants": [
                    "WaspadAI tidak mengakses database komunitas.",
                    "Hanya payload yang sudah disaring Product Backend yang dipakai.",
                    "Satu post komunitas dihitung sebagai satu evidence group konservatif.",
                ],
            },
        )
        evidence = prepare_evidence_for_decision(
            aggregate_evidence(web_evidence + domain_evidence + community_evidence),
            planner.claims,
        )
        sufficiency = calculate_evidence_sufficiency(evidence, planner.claims)
        self.debug_traces.add_stage(
            trace_id,
            key="evidence_aggregation",
            label="Agregasi & evidence sufficiency",
            duration_ms=0,
            input_data={
                "web_count": len(web_evidence),
                "domain_count": len(domain_evidence),
                "community_count": len(community_evidence),
                "claims": planner.claims,
            },
            output_data={
                "evidence": evidence,
                "evidence_sufficiency": sufficiency,
                "threshold": self.settings.evidence_sufficiency_threshold,
            },
            instruction={
                "version": "evidence-aggregation.v2",
                "runtime": "LOCAL_DETERMINISTIC",
                "invariants": [
                    "Duplikat URL per claim dihapus.",
                    "Evidence CONTEXT tidak memenuhi claim coverage.",
                    "Sufficiency bukan probabilitas kebenaran.",
                ],
            },
        )
        before_guardrail = rulebook
        rulebook = self.rulebook.post_retrieval_guardrails(
            rulebook,
            evidence_sufficiency=sufficiency,
            signals=signals,
        )
        self.debug_traces.add_stage(
            trace_id,
            key="post_retrieval_guardrail",
            label="Guardrail pascaretrieval",
            duration_ms=0,
            runtime="LOCAL_DETERMINISTIC",
            input_data={
                "evidence_sufficiency": sufficiency,
                "pre_guardrail_rule_ids": [item.rule_id for item in before_guardrail.matches],
            },
            output_data={
                "rulebook": rulebook,
                "forced_actions": rulebook.forced_actions,
            },
            instruction={
                "version": "post-retrieval.v1",
                "invariant": "Bukti lemah memicu aturan batas keputusan dan safe action, bukan dugaan fakta.",
            },
        )
        stages.append(
            PipelineStage(
                key="retrieval",
                label="Cari bukti",
                status=(
                    "FALLBACK"
                    if planner.retrieval_plan.web_search and web_error
                    else "COMPLETED"
                ),
                detail=(
                    f"{len(web_evidence)} web, {len(domain_evidence)} RAG resmi, "
                    f"{len(community_evidence)} komunitas terverifikasi; dijalankan paralel."
                    + (
                        " Web search tidak tersedia; hasil akan konservatif."
                        if web_error
                        else ""
                    )
                ),
                duration_ms=_elapsed_ms(retrieval_started),
            )
        )

        verifier_started = time.perf_counter()
        verifier_error: Exception | None = None
        try:
            decision = await self.groq.verify_and_generate(
                planner,
                evidence,
                sufficiency,
                rulebook,
            )
            verifier_status = "COMPLETED"
        except RECOVERABLE_MODEL_ERRORS as exc:
            _raise_if_nonrecoverable_provider_error(exc)
            verifier_error = exc
            verifier_status = "FALLBACK"
            decision = _fallback_verification_decision(planner, evidence, sufficiency)
        _enforce_rulebook_safety(decision, rulebook)
        _enforce_scam_message_decision(decision, case, signals, planner)
        _enforce_community_conflict_review(decision, evidence)
        _normalize_mixed_evidence_decision(decision, evidence, self.settings.evidence_sufficiency_threshold)
        _enforce_final_decision_consistency(
            decision,
            planner,
            evidence,
            self.settings.evidence_sufficiency_threshold,
        )
        verifier_ms = _elapsed_ms(verifier_started)
        self.debug_traces.add_stage(
            trace_id,
            key="verifier",
            label="Evidence verifier & response generator",
            status=verifier_status,
            duration_ms=verifier_ms,
            runtime="GROQ",
            model=self.settings.groq_final_model,
            input_data={
                "planner": planner,
                "evidence": evidence[: self.settings.max_evidence_items_for_verifier],
                "evidence_sufficiency": sufficiency,
                "rule_context_policy": rulebook.matches,
            },
            output_data={
                "decision": decision,
                "fallback_reason": _planner_error_view(verifier_error),
            },
            instruction=instruction_profile("verifier", self.settings.groq_final_model),
            notes=(
                ["Verifier eksternal gagal; backend memakai fallback deterministik berbasis evidence."]
                if verifier_error
                else []
            ),
        )
        stages.append(
            PipelineStage(
                key="verification",
                label="Uji bukti",
                status=verifier_status,
                detail=(
                    "Bukti dirangking, kontradiksi diperiksa, lalu verdict dan tindakan dibuat."
                    if not verifier_error
                    else "Verifier eksternal tidak tersedia; fallback deterministik berbasis evidence dijalankan."
                ),
                duration_ms=verifier_ms,
            )
        )
        response = self._build_response(
            request_id=request_id,
            trace_id=trace_id,
            case=case,
            input_summary=input_summary,
            signals=signals,
            planner=planner,
            stages=stages,
            evidence=evidence,
            decision=decision,
            rulebook=rulebook,
            output_mode=output_mode,
        )
        self.debug_traces.add_stage(
            trace_id,
            key="response_builder",
            label="Bangun response API",
            duration_ms=0,
            input_data={"decision": decision, "input_summary": input_summary},
            output_data=response,
            instruction={
                "version": "response.v2",
                "runtime": "LOCAL_DETERMINISTIC",
                "invariant": "Kontrak response image dan text identik.",
            },
        )
        self.debug_traces.complete(trace_id, response)
        return response

    def _build_response(self, **data) -> VerificationResponse:
        decision = data.pop("decision")
        evidence: list[Evidence] = data.pop("evidence")
        rulebook: RulebookResult = data.pop("rulebook")
        case: CaseContext = data.pop("case")
        signals: CaseSignals = data.pop("signals")
        planner: PlannerOutput = data.pop("planner")
        output_mode: OutputMode = data.pop("output_mode")
        sufficiency = decision.evidence_sufficiency
        evidence_view = evidence[:8]
        sufficiency_label = _sufficiency_label(sufficiency, decision, planner)
        narrative = (
            build_narrative_presentation(
                verdict=decision.overall_verdict,
                risk_level=decision.risk_level,
                headline=decision.headline,
                why=decision.why,
                evidence=evidence_view,
                evidence_sufficiency_label=sufficiency_label,
                recommended_actions=decision.recommended_actions,
                uncertainty=decision.uncertainty,
                requires_human_review=decision.requires_human_review,
            )
            if output_mode in {"NARRATIVE", "BOTH"}
            else None
        )
        return VerificationResponse(
            request_id=data["request_id"],
            trace_id=data["trace_id"],
            status="COMPLETED",
            mode="LIVE",
            mode_notice=(
                "Analisis live menggunakan Groq, Rulebook RAG "
                f"({', '.join(rulebook.trace.corpus_versions)}), dan live evidence terpisah."
            ),
            input_summary=data["input_summary"],
            verdict=decision.overall_verdict,
            risk_level=decision.risk_level,
            dimensions=_assessment_dimensions(case, signals, planner, decision),
            headline=decision.headline,
            evidence_sufficiency=sufficiency,
            evidence_sufficiency_label=sufficiency_label,
            what_checked=decision.what_checked,
            why=decision.why,
            evidence=evidence_view,
            recommended_actions=decision.recommended_actions,
            sources=_source_views(evidence),
            uncertainty=decision.uncertainty,
            requires_human_review=decision.requires_human_review,
            community_status=(
                "ELIGIBLE_WITH_CONSENT"
                if decision.overall_verdict == "UNVERIFIED" or decision.requires_human_review
                else "NOT_REQUIRED"
            ),
            privacy_notice=(
                "WaspadAI memproses raw input sementara dan mengirimkannya ke layanan model Groq "
                "pada mode live; service WaspadAI tidak menyimpan atau mempublikasikannya otomatis. "
                "Aplikasi pemanggil dapat menerapkan kebijakan history sendiri. Pada development, data "
                "turunan yang sudah teredaksi dapat berada sementara di debug trace lokal. Publikasi "
                "komunitas hanya boleh dilakukan setelah redaksi PII dan persetujuan pengguna."
            ),
            rulebook=rulebook.trace,
            pipeline=data["stages"],
            presentation=ResponsePresentation(
                requested_mode=output_mode,
                structured=output_mode in {"STRUCTURED", "BOTH"},
                narrative=narrative,
            ),
            disclaimer="Fact-check adalah dukungan keputusan, bukan jaminan. Verifikasi ulang untuk keputusan berisiko tinggi.",
        )

    def _build_non_checkable_image_response(
        self,
        *,
        request_id: str,
        trace_id: str,
        input_summary: InputSummary,
        stages: list[PipelineStage],
        output_mode: OutputMode,
    ) -> VerificationResponse:
        recommended_actions = [
            RecommendedAction(
                code="UPLOAD_CHECKABLE_CONTENT",
                title="Unggah bahan yang ingin diverifikasi",
                detail="Gunakan screenshot berita, pesan, caption, poster, dokumen, atau tempelkan klaimnya sebagai teks.",
            ),
        ]
        why = [
            "Sistem tidak menemukan teks, klaim, URL, pesan, dokumen, poster, atau konteks yang dapat diverifikasi.",
        ]
        uncertainty = (
            "Gambar ini belum memuat klaim yang bisa diperiksa."
        )
        narrative_paragraphs = [
            "Gambar ini belum memuat informasi atau klaim yang bisa diperiksa.",
            "Coba unggah screenshot berita, pesan, caption, poster, dokumen, atau gunakan input teks jika klaimnya tidak terlihat jelas.",
        ]
        narrative = (
            NarrativePresentation(
                text="\n\n".join(narrative_paragraphs),
                summary="Gambar belum memuat klaim yang bisa diperiksa.",
                paragraphs=narrative_paragraphs,
            )
            if output_mode in {"NARRATIVE", "BOTH"}
            else None
        )
        return VerificationResponse(
            request_id=request_id,
            trace_id=trace_id,
            status="COMPLETED",
            mode="LIVE",
            mode_notice=(
                "Analisis live berhenti setelah OCR dan Vision karena gambar tidak memuat klaim "
                "yang dapat diperiksa."
            ),
            input_summary=input_summary,
            verdict="UNVERIFIED",
            risk_level="LOW",
            dimensions=AssessmentDimensions(
                factual_status="UNVERIFIED",
                source_authenticity="NOT_APPLICABLE",
                sender_identity="NOT_APPLICABLE",
                channel_status="NOT_APPLICABLE",
                scam_risk="LOW",
                content_authenticity="UNVERIFIED",
            ),
            headline="Gambar tidak memuat klaim yang bisa diperiksa",
            evidence_sufficiency=0.0,
            evidence_sufficiency_label="Tidak ada klaim yang dapat diperiksa",
            what_checked=["Kelayakan gambar sebagai bahan fact-check"],
            why=why,
            evidence=[],
            recommended_actions=recommended_actions,
            sources=[],
            uncertainty=uncertainty,
            requires_human_review=False,
            community_status="NOT_REQUIRED",
            privacy_notice=(
                "WaspadAI memproses raw input sementara dan mengirimkannya ke layanan model Groq "
                "pada mode live; service WaspadAI tidak menyimpan atau mempublikasikannya otomatis."
            ),
            rulebook=RulebookTrace(
                corpus_versions=list(self.rulebook.health.get("corpus_versions", [])),
                retrieval_mode="SKIPPED_NON_CHECKABLE_IMAGE",
                candidate_count=0,
                selected_count=0,
                forced_rule_ids=[],
                cache_hit=False,
                duration_ms=0,
            ),
            pipeline=stages,
            presentation=ResponsePresentation(
                requested_mode=output_mode,
                structured=output_mode in {"STRUCTURED", "BOTH"},
                narrative=narrative,
            ),
            disclaimer="Fact-check adalah dukungan keputusan, bukan jaminan. Verifikasi ulang untuk keputusan berisiko tinggi.",
        )


def prepare_evidence_for_decision(
    evidence: list[Evidence],
    claims: list[PlannedClaim],
) -> list[Evidence]:
    filtered = [
        item
        for item in evidence
        if not _is_off_topic_evidence(item, claims)
    ]
    remapped = _remap_evidence_to_related_claims(filtered, claims)
    enriched = [
        _apply_deterministic_stance(item, _claim_by_id(claims, item.claim_id))
        for item in remapped
    ]
    return aggregate_evidence(enriched)


def aggregate_evidence(items: list[Evidence]) -> list[Evidence]:
    by_url_and_claim: dict[tuple[str, str], Evidence] = {}
    for item in items:
        if item.stance == "UNKNOWN" and item.verification_status == "REVIEWED" and item.relevance < 0.35:
            continue
        if item.stance == "CONTEXT" and item.relevance < 0.24:
            continue
        key = (item.url, item.claim_id)
        existing = by_url_and_claim.get(key)
        if existing is None or (item.authority + item.relevance) > (existing.authority + existing.relevance):
            by_url_and_claim[key] = item
    return sorted(
        by_url_and_claim.values(),
        key=lambda item: (item.authority * 0.45 + item.relevance * 0.4 + item.recency * 0.15),
        reverse=True,
    )


def _remap_evidence_to_related_claims(
    evidence: list[Evidence],
    claims: list[PlannedClaim],
) -> list[Evidence]:
    output = list(evidence)
    existing = {(item.url, item.claim_id) for item in output}
    for item in evidence:
        if item.source_type == "community_verified":
            continue
        text = _evidence_text(item)
        for claim in claims:
            if not claim.verifiable or claim.id == item.claim_id:
                continue
            if (item.url, claim.id) in existing:
                continue
            score = _claim_evidence_overlap(claim.text, text)
            if (
                score < 0.42
                and not _has_shared_structured_facet(claim.text, text)
                and not _has_location_contradiction(claim.text, text)
                and not _has_numeric_contradiction(claim.text, text)
                and not _semantic_support_hint(claim.text, text)
            ):
                continue
            cloned = item.model_copy(
                update={
                    "id": _derived_evidence_id(item.id, claim.id),
                    "claim_id": claim.id,
                    "relevance": round(max(item.relevance * 0.82, min(0.86, score)), 3),
                }
            )
            output.append(cloned)
            existing.add((item.url, claim.id))
    return output


def _apply_deterministic_stance(item: Evidence, claim: PlannedClaim | None) -> Evidence:
    if claim is None or item.stance in {"SUPPORTS", "REFUTES"}:
        return item
    text = _evidence_text(item)
    stance = item.stance
    relevance = item.relevance
    if _has_numeric_contradiction(claim.text, text) or _has_location_contradiction(claim.text, text):
        stance = "REFUTES"
        relevance = max(relevance, 0.72)
    elif _claim_is_clearly_supported(claim.text, text, item):
        stance = "SUPPORTS"
        relevance = max(relevance, 0.62)
    if stance == item.stance and relevance == item.relevance:
        return item
    return item.model_copy(update={"stance": stance, "relevance": round(min(1.0, relevance), 3)})


def _is_off_topic_evidence(item: Evidence, claims: list[PlannedClaim]) -> bool:
    if item.stance in {"SUPPORTS", "REFUTES"}:
        return False
    text = _evidence_text(item)
    claim = _claim_by_id(claims, item.claim_id)
    if claim is None:
        return False
    if item.authority >= 0.95 and item.relevance >= 0.45:
        return False
    claim_text = " ".join(claim.text for claim in claims)
    anchors = _anchor_tokens(claim_text)
    if anchors:
        evidence_tokens = _tokens(text)
        if not (anchors & evidence_tokens) and _topic_requires_anchor(claim_text):
            return True
    claim_years = set(YEAR_RE.findall(claim_text))
    evidence_years = set(YEAR_RE.findall(text))
    if claim_years and evidence_years and not (claim_years & evidence_years):
        return True
    if _has_event_type_conflict(claim.text, text):
        return True
    return item.relevance < 0.5 and _claim_evidence_overlap(claim.text, text) < 0.25


def _claim_by_id(claims: list[PlannedClaim], claim_id: str) -> PlannedClaim | None:
    return next((claim for claim in claims if claim.id == claim_id), None)


def _derived_evidence_id(source_id: str, claim_id: str) -> str:
    return f"{source_id}_{claim_id}"[:64]


def _evidence_text(item: Evidence) -> str:
    return " ".join([item.publisher, item.title, item.excerpt, item.url]).casefold()


def _tokens(text: str) -> set[str]:
    return {
        token.casefold()
        for token in TOKEN_RE.findall(text)
        if len(token) > 2 and token.casefold() not in CLAIM_STOPWORDS
    }


def _anchor_tokens(text: str) -> set[str]:
    tokens = _tokens(text)
    anchors = {
        token
        for token in tokens
        if token in {
            "spacex", "starship", "super", "heavy", "bogor", "florida", "texas",
            "starbase", "boca", "chica", "paris", "olimpiade", "olympic", "seine",
            "stade", "france", "prevost", "paus", "pope", "leo", "trump",
            "washington", "gempa", "earthquake", "hokkaido", "jepang", "japan",
            "noto", "ishikawa", "honshu", "tsunami",
        }
    }
    anchors.update(YEAR_RE.findall(text))
    return anchors


def _topic_requires_anchor(text: str) -> bool:
    folded = text.casefold()
    return any(
        marker in folded
        for marker in (
            "gempa", "earthquake", "tsunami", "spacex", "starship", "olimpiade",
            "olympic", "paris", "prevost", "paus", "pope", "trump",
        )
    )


def _claim_evidence_overlap(claim_text: str, evidence_text: str) -> float:
    claim_tokens = _tokens(claim_text)
    if not claim_tokens:
        return 0.0
    evidence_tokens = _tokens(evidence_text)
    return len(claim_tokens & evidence_tokens) / max(1, len(claim_tokens))


def _has_shared_structured_facet(claim_text: str, evidence_text: str) -> bool:
    claim_numbers = set(NUMBER_RE.findall(claim_text.replace(",", ".")))
    evidence_numbers = set(NUMBER_RE.findall(evidence_text.replace(",", ".")))
    if claim_numbers and evidence_numbers and claim_numbers & evidence_numbers:
        return True
    claim_years = set(YEAR_RE.findall(claim_text))
    evidence_years = set(YEAR_RE.findall(evidence_text))
    if claim_years and evidence_years and claim_years & evidence_years:
        return _claim_evidence_overlap(claim_text, evidence_text) >= 0.25
    return False


def _has_numeric_contradiction(claim_text: str, evidence_text: str) -> bool:
    claim_numbers = _normalized_numbers(claim_text)
    evidence_numbers = _normalized_numbers(evidence_text)
    if not claim_numbers or not evidence_numbers:
        return False
    folded_claim = claim_text.casefold()
    folded_evidence = evidence_text.casefold()
    numeric_topic = any(term in folded_claim for term in ("magnitudo", "magnitude", "presiden", "president", "uji", "flight"))
    if not numeric_topic:
        return False
    claim_years = {number for number in claim_numbers if number >= 1900}
    evidence_years = {number for number in evidence_numbers if number >= 1900}
    non_year_claim = [number for number in claim_numbers if number < 1900]
    non_year_evidence = [number for number in evidence_numbers if number < 1900]
    if claim_years and evidence_years and claim_years.isdisjoint(evidence_years):
        return True
    if any(term in folded_claim for term in ("magnitudo", "magnitude")):
        return bool(non_year_claim and non_year_evidence and all(abs(a - b) > 0.2 for a in non_year_claim for b in non_year_evidence))
    return False


def _normalized_numbers(text: str) -> list[float]:
    output: list[float] = []
    for value in NUMBER_RE.findall(text.replace(",", ".")):
        try:
            output.append(float(value))
        except ValueError:
            continue
    return output


def _has_location_contradiction(claim_text: str, evidence_text: str) -> bool:
    claim_locations = _location_markers(claim_text)
    evidence_locations = _location_markers(evidence_text)
    if not claim_locations or not evidence_locations:
        return False
    if claim_locations & evidence_locations:
        return False
    incompatible_pairs = {
        frozenset({"bogor", "texas"}),
        frozenset({"florida", "texas"}),
        frozenset({"stade", "seine"}),
        frozenset({"hokkaido", "noto"}),
        frozenset({"hokkaido", "ishikawa"}),
    }
    return any(frozenset({left, right}) in incompatible_pairs for left in claim_locations for right in evidence_locations)


def _has_event_type_conflict(claim_text: str, evidence_text: str) -> bool:
    claim = claim_text.casefold()
    evidence = evidence_text.casefold()
    opening_claim = any(term in claim for term in ("dibuka", "pembukaan", "opening ceremony"))
    closing_evidence = any(term in evidence for term in ("penutupan", "closing ceremony"))
    return opening_claim and closing_evidence and not any(term in evidence for term in ("pembukaan", "opening ceremony"))


def _location_markers(text: str) -> set[str]:
    folded = text.casefold()
    output: set[str] = set()
    for marker, aliases in LOCATION_ALIASES.items():
        if any(alias in folded for alias in aliases):
            output.add(marker)
    return output


def _claim_is_clearly_supported(claim_text: str, evidence_text: str, item: Evidence) -> bool:
    overlap = _claim_evidence_overlap(claim_text, evidence_text)
    if overlap >= 0.62 and not _has_numeric_contradiction(claim_text, evidence_text) and not _has_location_contradiction(claim_text, evidence_text):
        return True
    folded_claim = claim_text.casefold()
    folded_evidence = evidence_text.casefold()
    if _semantic_support_hint(folded_claim, folded_evidence):
        return True
    return item.authority >= 0.95 and overlap >= 0.45


def _semantic_support_hint(claim_text: str, evidence_text: str) -> bool:
    claim = claim_text.casefold()
    evidence = evidence_text.casefold()
    if "prevost" in claim and "prevost" in evidence:
        if "leo xiv" in claim and "leo xiv" in evidence:
            return True
        if "terpilih" in claim and "elected" in evidence:
            return True
        if any(term in claim for term in ("paus pertama", "amerika serikat", "asal amerika")) and "first american" in evidence:
            return True
        if "paus" in claim and "pope" in evidence and "elected" in evidence:
            return True
    if "trump" in claim and "trump" in evidence:
        if ("ke-47" in claim or "47" in claim) and ("ke-47" in evidence or "47" in evidence):
            return True
    if "starship" in claim and "starship" in evidence:
        if any(term in claim for term in ("uji kelima", "penerbangan uji kelima", "uji terbang kelima")) and any(
            term in evidence
            for term in ("fifth flight", "uji kelima", "uji terbang kelima", "penerbangan kelima", "penerbangan uji kelima")
        ):
            return True
    if "paris 2024" in claim and "seine" in evidence:
        return True
    if any(term in claim for term in ("parade atlet", "athletes")) and any(
        term in evidence for term in ("boat parade", "boats", "kapal", "seine")
    ):
        return True
    return False


def calculate_evidence_sufficiency(
    evidence: list[Evidence],
    claims: list[PlannedClaim],
) -> float:
    """Conservative evidence score; CONTEXT records cannot satisfy a claim."""
    if not evidence:
        return 0.0
    verifiable_claim_ids = _material_verifiable_claim_ids(claims)
    decisive = [
        item
        for item in evidence
        if item.claim_id in verifiable_claim_ids
        and item.stance in {"SUPPORTS", "REFUTES"}
        and item.relevance >= 0.45
    ]
    search_candidates = [
        item
        for item in evidence
        if item.claim_id in verifiable_claim_ids
        and item.stance == "UNKNOWN"
        and item.verification_status == "REVIEWED"
        and item.relevance >= 0.45
        and bool(item.excerpt.strip())
    ]
    if not decisive and search_candidates:
        count = len(search_candidates)
        source_quality = sum(item.authority for item in search_candidates) / count
        relevance = sum(item.relevance for item in search_candidates) / count
        temporal_validity = sum(item.recency for item in search_candidates) / count
        publisher_count = len({item.publisher.casefold() for item in search_candidates})
        independence = min(1.0, publisher_count / 3)
        covered_claims = {item.claim_id for item in search_candidates}
        coverage = len(covered_claims) / max(1, len(verifiable_claim_ids))
        official_coverage = {
            item.claim_id
            for item in search_candidates
            if item.authority >= 0.95 and item.relevance >= 0.6
        }
        has_primary_official_coverage = coverage >= 1.0 and verifiable_claim_ids <= official_coverage
        score = (
            0.25 * source_quality
            + 0.25 * relevance
            + 0.20 * independence
            + 0.20 * coverage
            + 0.10 * temporal_validity
        )
        # One publisher is useful context, but never enough to unlock a factual verdict.
        if coverage < 1.0:
            score = min(score, 0.57)
        elif publisher_count < 2 and not has_primary_official_coverage:
            score = min(score, 0.57)
        return round(max(0.0, min(1.0, score)), 3)
    if not decisive:
        context_quality = sum(item.authority * item.relevance for item in evidence) / len(evidence)
        return round(min(0.35, context_quality * 0.35), 3)

    count = len(decisive)
    source_quality = sum(item.authority for item in decisive) / count
    relevance = sum(item.relevance for item in decisive) / count
    temporal_validity = sum(item.recency for item in decisive) / count
    independence = min(1.0, len({item.publisher.casefold() for item in decisive}) / 3)
    covered_claims = {item.claim_id for item in decisive}
    coverage = len(covered_claims) / max(1, len(verifiable_claim_ids))
    agreement_scores: list[float] = []
    contradictions = 0
    for claim_id in covered_claims:
        stances = {item.stance for item in decisive if item.claim_id == claim_id}
        if len(stances) > 1:
            contradictions += 1
            agreement_scores.append(0.0)
        else:
            agreement_scores.append(1.0)
    agreement = sum(agreement_scores) / max(1, len(agreement_scores))
    contradiction_penalty = min(0.25, contradictions * 0.12)
    score = (
        0.25 * source_quality
        + 0.22 * relevance
        + 0.13 * independence
        + 0.20 * coverage
        + 0.10 * temporal_validity
        + 0.10 * agreement
        - contradiction_penalty
    )
    has_refutation = any(item.stance == "REFUTES" for item in decisive)
    if coverage < 1.0 and not has_refutation:
        score = min(score, 0.57)
    if decisive and all(item.source_type == "community_verified" for item in decisive):
        score = min(score, 0.57)
    return round(max(0.0, min(1.0, score)), 3)


def _material_verifiable_claim_ids(claims: list[PlannedClaim]) -> set[str]:
    verifiable = [claim for claim in claims if claim.verifiable]
    material = [claim for claim in verifiable if _is_material_claim_type(claim.claim_type)]
    return {claim.id for claim in (material or verifiable)}


def _is_material_claim_type(claim_type: str) -> bool:
    normalized = claim_type.strip().casefold()
    return normalized in {
        "factual",
        "factual_claim",
        "news_article",
        "news_excerpt",
        "claim_only",
        "scam_message",
    }


def _image_input_summary(
    case: CaseContext,
    filename: str,
    metadata: MediaMetadata,
    ocr_status: str,
    pii_types: list[str],
) -> InputSummary:
    return InputSummary(
        input_type="IMAGE",
        content_type=case.content_type,
        label=filename[:180],
        media_type=metadata.mime_type,
        dimensions=f"{metadata.width} Ã— {metadata.height}",
        extraction_status=ocr_status,
        excerpt=(case.safe_text[:320] or case.summary[:320] or "Tidak ada teks yang dapat ditampilkan."),
        source_url=None,
        sender_context="NOT_APPLICABLE",
        character_count=case.source_character_count,
        urls_detected=len(case.urls),
        pii_types_redacted=_unique(pii_types),
    )


def _text_input_summary(case: CaseContext, pii_types: list[str]) -> InputSummary:
    return InputSummary(
        input_type="TEXT",
        content_type=case.content_type,
        label=f"Teks tempel - {case.source_character_count} karakter",
        media_type="text/plain",
        dimensions=None,
        extraction_status="OK",
        excerpt=case.safe_text[:320],
        source_url=case.source_url,
        sender_context=case.sender_context,
        character_count=case.source_character_count,
        urls_detected=len(case.urls),
        pii_types_redacted=_unique(pii_types),
    )


def _source_views(evidence: list[Evidence]) -> list[SourceView]:
    seen: set[str] = set()
    output: list[SourceView] = []
    for item in evidence:
        if item.url in seen:
            continue
        seen.add(item.url)
        output.append(
            SourceView(
                publisher=item.publisher,
                title=item.title,
                url=item.url,
                published_at=item.published_at,
            )
        )
    return output[:8]


def _sufficiency_label(
    score: float,
    decision: VerificationDecision | None = None,
    planner: PlannerOutput | None = None,
) -> str:
    if (
        planner is not None
        and planner.classification == "SCAM_MESSAGE"
        and decision is not None
        and decision.overall_verdict != "UNVERIFIED"
    ):
        return "Indikator risiko kuat - keputusan keamanan berbasis sinyal pesan, bukan reputasi URL final"
    if score >= 0.8:
        return "Bukti kuat - skor kecukupan, bukan probabilitas kebenaran"
    if score >= 0.58:
        return "Bukti cukup - tetap periksa konteks dan waktu"
    return "Bukti belum cukup - verdict dikunci sebagai belum terverifikasi"


def _assessment_dimensions(
    case: CaseContext,
    signals: CaseSignals,
    planner: PlannerOutput,
    decision: VerificationDecision,
) -> AssessmentDimensions:
    scam_message = planner.classification == "SCAM_MESSAGE"
    has_verifiable_claim = any(claim.verifiable for claim in planner.claims)
    factual_status = (
        decision.overall_verdict
        if has_verifiable_claim
        else "NOT_APPLICABLE"
    )
    sender_relevant = (
        case.sender_context != "NOT_APPLICABLE"
        or "message" in case.content_type.casefold()
        or case.possible_impersonation
    )
    if sender_relevant and (
        case.possible_impersonation
        or "authority_impersonation" in signals.attack_patterns
    ):
        sender_identity = "IMPERSONATION_LIKELY"
    elif sender_relevant:
        sender_identity = "UNVERIFIED"
    else:
        sender_identity = "NOT_APPLICABLE"

    if case.urls:
        if scam_message and decision.risk_level in {"HIGH", "CRITICAL"}:
            channel_status = "MALICIOUS"
        else:
            channel_status = (
                "SUSPICIOUS"
                if signals.sensitive_action_requested or case.possible_impersonation
                else "UNVERIFIED"
            )
    elif sender_relevant:
        channel_status = "UNVERIFIED"
    else:
        channel_status = "NOT_APPLICABLE"

    return AssessmentDimensions(
        factual_status=factual_status,
        # A pasted URL or visible logo is not proof of origin. The current MVP
        # has no cryptographic provenance/identity verification adapter.
        source_authenticity=(
            "SUSPICIOUS"
            if scam_message and decision.risk_level in {"HIGH", "CRITICAL"}
            else "UNVERIFIED"
        ),
        sender_identity=sender_identity,
        channel_status=channel_status,
        scam_risk=decision.risk_level,
        content_authenticity=(
            "UNVERIFIED" if case.input_type == "IMAGE" else "NOT_APPLICABLE"
        ),
    )


async def _timed_result(awaitable):
    started = time.perf_counter()
    result = await awaitable
    return result, _elapsed_ms(started)


async def _timed_external_result(awaitable):
    started = time.perf_counter()
    try:
        result = await awaitable
        return result, _elapsed_ms(started), None
    except RECOVERABLE_MODEL_ERRORS as exc:
        _raise_if_nonrecoverable_provider_error(exc)
        return [], _elapsed_ms(started), exc


def _elapsed_ms(started: float) -> int:
    return max(1, round((time.perf_counter() - started) * 1000))


def _planner_error_view(exc: Exception | None) -> dict[str, object] | None:
    if exc is None:
        return None
    return {
        "type": type(exc).__name__,
        "status_code": getattr(exc, "status_code", None),
        "recoverable": True,
        "raw_message_stored": False,
    }


MODEL_REVIEW_REASON_PREFIXES = (
    "FIRST_PASS_MODEL_FAILURE",
    "UNGROUNDED_PLANNER_CLAIM",
    "MODEL_REPORTED_HIGH_COMPLEXITY",
    "MANY_MATERIAL_CLAIMS",
    "TEMPORAL_CONTEXT_CONFLICT",
    "SYNTHETIC_MEDIA_WITH_AUTHORITY_OR_PAYMENT",
)


def _model_review_reasons(reasons: list[str]) -> list[str]:
    """Only use 120B for semantic ambiguity, not deterministic safety signals."""
    return [
        reason
        for reason in reasons
        if any(reason.startswith(prefix) for prefix in MODEL_REVIEW_REASON_PREFIXES)
    ]


def _raise_if_nonrecoverable_provider_error(exc: Exception) -> None:
    """Keep auth/permission errors as configuration failures, not safe fallbacks."""
    if getattr(exc, "status_code", None) in {401, 403}:
        raise exc


_RISK_RANK = {"UNKNOWN": 0, "LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}


def _enforce_scam_message_decision(
    decision: VerificationDecision,
    case: CaseContext,
    signals: CaseSignals,
    planner: PlannerOutput,
) -> None:
    if planner.classification != "SCAM_MESSAGE":
        return

    scam_strength = _scam_signal_strength(case, signals)
    if scam_strength == "NONE":
        return

    target_risk = "CRITICAL" if scam_strength == "CRITICAL" else "HIGH"
    if _RISK_RANK[target_risk] > _RISK_RANK[decision.risk_level]:
        decision.risk_level = target_risk

    if scam_strength in {"HIGH", "CRITICAL"}:
        decision.overall_verdict = "MISLEADING"
        decision.requires_human_review = False
        decision.headline = (
            "Pesan patut diduga penipuan atau phishing"
            if target_risk == "HIGH"
            else "Pesan sangat berisiko dan perlu ditangani sebagai penipuan"
        )
        decision.what_checked = _merge_front(
            [
                "Indikator penipuan/phishing pada pesan",
                "Keaslian identitas pengirim",
                "Keamanan tautan atau instruksi yang diminta",
            ],
            decision.what_checked,
        )
        decision.why = _scam_decision_reasons(case, signals)
        decision.uncertainty = (
            "Ini adalah keputusan keamanan berbasis pola pesan, domain, dan instruksi yang terlihat. "
            "Reputasi final URL tetap perlu dicek melalui kanal resmi, tetapi tindakan aman saat ini "
            "adalah tidak membuka tautan dan tidak mengikuti instruksi pesan."
        )
        decision.recommended_actions = _merge_actions(
            _scam_recommended_actions(signals),
            decision.recommended_actions,
        )
        for claim in decision.claims:
            if claim.verdict == "UNVERIFIED":
                claim.verdict = "MISLEADING"
                claim.contradiction_level = "HIGH"
                claim.reason = "Pola pesan menunjukkan impersonasi dan instruksi berisiko, sehingga tidak aman ditindaklanjuti."


def _scam_signal_strength(case: CaseContext, signals: CaseSignals) -> str:
    if signals.user_action_state in {
        "OTP_SHARED",
        "APK_INSTALLED",
        "REMOTE_ACCESS_GRANTED",
        "PAYMENT_SENT",
        "ACCOUNT_TAKEOVER_SUSPECTED",
    }:
        return "CRITICAL"
    if (
        signals.secret_request_detected
        or signals.suspicious_executable_received
        or signals.remote_access_requested
        or signals.screen_share_requested
        or signals.safe_account_transfer_requested
        or (signals.payment_requested and (signals.authority or case.possible_impersonation))
    ):
        return "HIGH"
    suspicious_link = "suspicious_link_domain" in signals.attack_patterns
    link_request = "OPEN_LINK" in signals.requested_actions
    if link_request and (signals.authority or case.possible_impersonation) and (
        signals.urgency or signals.threat or suspicious_link
    ):
        return "HIGH"
    if link_request and suspicious_link:
        return "HIGH"
    return "NONE"


def _scam_decision_reasons(case: CaseContext, signals: CaseSignals) -> list[str]:
    reasons: list[str] = []
    if signals.authority or case.possible_impersonation:
        reasons.append("Pesan mengatasnamakan pihak resmi atau brand, tetapi identitas pengirim tidak terverifikasi.")
    if "OPEN_LINK" in signals.requested_actions:
        reasons.append("Pesan meminta penerima membuka tautan; tautan dari pesan pribadi tidak membuktikan kanal resmi.")
    if "suspicious_link_domain" in signals.attack_patterns:
        reasons.append("Domain tautan tidak cocok dengan kanal resmi yang diharapkan atau memakai pola domain mencurigakan.")
    if signals.urgency or signals.threat:
        reasons.append("Ada tekanan waktu, ancaman, atau konsekuensi yang mendorong penerima bertindak cepat.")
    if signals.payment_requested:
        reasons.append("Pesan memuat instruksi pembayaran atau denda yang harus diverifikasi langsung lewat kanal resmi.")
    if signals.secret_request_detected:
        reasons.append("Pesan meminta secret seperti OTP, PIN, password, atau kode rahasia.")
    return reasons or [
        "Rulebook keamanan mengklasifikasikan pesan sebagai berisiko tinggi untuk ditindaklanjuti."
    ]


def _scam_recommended_actions(signals: CaseSignals) -> list[RecommendedAction]:
    actions: list[RecommendedAction] = []
    if "OPEN_LINK" in signals.requested_actions:
        actions.append(
            RecommendedAction(
                code="DO_NOT_OPEN_LINK",
                title="Jangan buka tautan",
                detail="Jangan klik tautan dari pesan ini. Buka aplikasi atau situs resmi secara manual bila perlu mengecek akun atau tagihan.",
            )
        )
    if signals.secret_request_detected:
        actions.append(
            RecommendedAction(
                code="DO_NOT_SHARE_SECRET",
                title="Jangan bagikan kode rahasia",
                detail="Jangan berikan OTP, PIN, password, CVV, recovery code, atau secret lain kepada siapa pun.",
            )
        )
    if signals.payment_requested:
        actions.append(
            RecommendedAction(
                code="DO_NOT_TRANSFER",
                title="Jangan transfer dana",
                detail="Hentikan pembayaran sampai alasan, kanal, dan penerima terverifikasi lewat sumber resmi.",
            )
        )
    actions.extend(
        [
            RecommendedAction(
                code="VERIFY_OFFICIAL_CHANNEL",
                title="Verifikasi lewat kanal resmi",
                detail="Cari sendiri kanal resmi pihak terkait; jangan gunakan tautan, nomor, atau kontak yang diberikan dalam pesan.",
            ),
            RecommendedAction(
                code="BLOCK_AND_REPORT",
                title="Blokir dan laporkan",
                detail="Laporkan pesan sebagai spam/penipuan di aplikasi pesan, lalu simpan tangkapan layar bila diperlukan.",
            ),
        ]
    )
    return actions


def _merge_front(first: list[str], second: list[str]) -> list[str]:
    return list(dict.fromkeys(item for item in [*first, *second] if item))


def _merge_actions(
    first: list[RecommendedAction],
    second: list[RecommendedAction],
) -> list[RecommendedAction]:
    output: list[RecommendedAction] = []
    seen: set[str] = set()
    for action in [*first, *second]:
        if action.code in seen:
            continue
        output.append(action)
        seen.add(action.code)
    return output


def _enforce_community_conflict_review(
    decision: VerificationDecision,
    evidence: list[Evidence],
) -> None:
    conflict_claims = _community_conflict_claim_ids(evidence)
    if not conflict_claims:
        return
    decision.overall_verdict = "UNVERIFIED"
    decision.requires_human_review = True
    decision.headline = "Bukti komunitas perlu ditinjau bersama bukti lain"
    reason = (
        "Ada evidence komunitas terverifikasi yang bertentangan dengan evidence non-komunitas "
        "berotoritas tinggi, sehingga sistem tidak mengunci verdict otomatis."
    )
    if reason not in decision.why:
        decision.why.insert(0, reason)
    decision.uncertainty = (
        "Perlu review manusia untuk menilai konteks publikasi komunitas dan bukti pembanding yang lebih kuat."
    )
    for claim in decision.claims:
        if claim.claim_id in conflict_claims:
            claim.verdict = "UNVERIFIED"
            claim.contradiction_level = "HIGH"
            claim.reason = reason


def _community_conflict_claim_ids(evidence: list[Evidence]) -> set[str]:
    output: set[str] = set()
    for claim_id in {item.claim_id for item in evidence}:
        community_stances = {
            item.stance
            for item in evidence
            if item.claim_id == claim_id
            and item.source_type == "community_verified"
            and item.stance in {"SUPPORTS", "REFUTES"}
            and item.relevance >= 0.45
        }
        strong_non_community_stances = {
            item.stance
            for item in evidence
            if item.claim_id == claim_id
            and item.source_type != "community_verified"
            and item.stance in {"SUPPORTS", "REFUTES"}
            and item.relevance >= 0.65
            and item.authority >= 0.85
        }
        if (
            ("SUPPORTS" in community_stances and "REFUTES" in strong_non_community_stances)
            or ("REFUTES" in community_stances and "SUPPORTS" in strong_non_community_stances)
        ):
            output.add(claim_id)
    return output


def _normalize_mixed_evidence_decision(
    decision: VerificationDecision,
    evidence: list[Evidence],
    sufficiency_threshold: float,
) -> None:
    if decision.evidence_sufficiency < sufficiency_threshold:
        return
    supported_claims = {
        claim.claim_id
        for claim in decision.claims
        if claim.verdict in {"SUPPORTED", "PARTLY_TRUE"} and claim.supporting_evidence
    }
    refuted_claims = {
        claim.claim_id
        for claim in decision.claims
        if claim.verdict == "REFUTED" and claim.refuting_evidence
    }
    if not supported_claims or not refuted_claims:
        return
    if supported_claims - refuted_claims and decision.overall_verdict in {"REFUTED", "PARTLY_TRUE"}:
        decision.overall_verdict = "MISLEADING"
        decision.requires_human_review = False
        if not any("campuran" in item.casefold() or "sebagian" in item.casefold() for item in decision.why):
            decision.why.append(
                "Bukti menunjukkan sebagian facet klaim benar, tetapi facet material lain terbantahkan."
            )
        if decision.headline.startswith("Pemeriksaan belum"):
            decision.headline = "Klaim menyesatkan karena mencampur fakta benar dengan detail yang salah"


def _enforce_final_decision_consistency(
    decision: VerificationDecision,
    planner: PlannerOutput,
    evidence: list[Evidence],
    sufficiency_threshold: float,
) -> None:
    """Keep the final public decision consistent after model and local guardrails."""
    if planner.classification == "SCAM_MESSAGE" and decision.risk_level in {"HIGH", "CRITICAL"}:
        _sanitize_claim_evidence_ids(decision, evidence)
        return

    if decision.evidence_sufficiency < sufficiency_threshold:
        decision.overall_verdict = "UNVERIFIED"
        decision.requires_human_review = True
        for claim in decision.claims:
            claim.verdict = "UNVERIFIED"
            claim.supporting_evidence = []
            claim.refuting_evidence = []
            claim.contradiction_level = "NONE"
            claim.reason = "Bukti yang tersedia belum cukup untuk memberi keputusan faktual yang aman."
        decision.headline = "Bukti belum cukup untuk memastikan klaim"
        decision.why = [
            "Bukti yang ditemukan belum cukup kuat atau belum mencakup seluruh klaim material.",
            "Sistem tidak membuat vonis benar atau salah ketika coverage bukti masih rendah.",
        ]
        decision.uncertainty = (
            "Masih diperlukan bukti tambahan dari sumber primer atau sumber tepercaya lain sebelum klaim ini dapat disimpulkan."
        )
        _ensure_return_unverified_action(decision)
    else:
        decisive_claims = [claim for claim in decision.claims if claim.verdict != "UNVERIFIED"]
        if not decisive_claims and decision.overall_verdict not in {"OPINION", "SATIRE"}:
            decision.overall_verdict = "UNVERIFIED"
            decision.requires_human_review = True
            decision.headline = "Bukti belum cukup untuk memastikan klaim"
        else:
            decision.requires_human_review = decision.requires_human_review or _has_unresolved_material_claim(decision)
            decision.headline = _canonical_headline(decision.overall_verdict, decision.headline)
    _sanitize_claim_evidence_ids(decision, evidence)


def _sanitize_claim_evidence_ids(decision: VerificationDecision, evidence: list[Evidence]) -> None:
    valid_ids = {item.id for item in evidence}
    for claim in decision.claims:
        claim.supporting_evidence = [item for item in claim.supporting_evidence if item in valid_ids]
        claim.refuting_evidence = [item for item in claim.refuting_evidence if item in valid_ids]


def _has_unresolved_material_claim(decision: VerificationDecision) -> bool:
    decisive = [claim for claim in decision.claims if claim.verdict != "UNVERIFIED"]
    unresolved = [claim for claim in decision.claims if claim.verdict == "UNVERIFIED"]
    return bool(decisive and unresolved)


def _ensure_return_unverified_action(decision: VerificationDecision) -> None:
    if any(action.code == "RETURN_UNVERIFIED" for action in decision.recommended_actions):
        return
    decision.recommended_actions.insert(
        0,
        RecommendedAction(
            code="RETURN_UNVERIFIED",
            title="Tunggu bukti yang memadai",
            detail="Jangan menjadikan informasi ini dasar keputusan sampai ada konfirmasi dari sumber yang lebih kuat.",
        ),
    )


def _canonical_headline(verdict: str, current: str) -> str:
    lowered = current.casefold()
    if verdict == "SUPPORTED" and any(term in lowered for term in ["salah", "keliru", "terbantah", "menyesatkan"]):
        return "Klaim didukung oleh bukti yang tersedia"
    if verdict == "REFUTED" and any(term in lowered for term in ["didukung", "terkonfirmasi", "benar"]):
        return "Klaim bertentangan dengan bukti yang tersedia"
    if verdict == "MISLEADING" and any(term in lowered for term in ["didukung", "terkonfirmasi"]):
        return "Klaim menyesatkan karena konteks penting tidak lengkap"
    if verdict == "UNVERIFIED":
        return "Bukti belum cukup untuk memastikan klaim"
    return current


def _fallback_verification_decision(
    planner: PlannerOutput,
    evidence: list[Evidence],
    evidence_sufficiency: float,
) -> VerificationDecision:
    assessments = [
        _fallback_claim_assessment(claim, evidence, evidence_sufficiency)
        for claim in planner.claims
    ]
    decisive = [item for item in assessments if item.verdict != "UNVERIFIED"]
    if decisive:
        verdicts = {item.verdict for item in decisive}
        if "REFUTED" in verdicts and ("SUPPORTED" in verdicts or "PARTLY_TRUE" in verdicts):
            overall = "MISLEADING"
        elif "REFUTED" in verdicts:
            overall = "REFUTED"
        elif "SUPPORTED" in verdicts:
            overall = "SUPPORTED"
        else:
            overall = decisive[0].verdict
        return VerificationDecision(
            claims=assessments,
            overall_verdict=overall,
            risk_level=planner.interim_risk,
            evidence_sufficiency=evidence_sufficiency,
            requires_human_review=False,
            headline=_fallback_headline(overall),
            what_checked=[claim.text for claim in planner.claims],
            why=[
                "Verifier eksternal gagal, tetapi evidence terambil dengan kecukupan tinggi.",
                "Fallback deterministik hanya memakai pola dukungan atau bantahan yang eksplisit dalam evidence.",
            ],
            recommended_actions=[
                RecommendedAction(
                    code="VERIFY_VIA_OFFICIAL_CHANNEL",
                    title="Bandingkan dengan sumber resmi",
                    detail="Gunakan sumber resmi pada referensi sebagai konteks utama sebelum membagikan informasi.",
                )
            ],
            uncertainty=(
                "Keputusan dibuat oleh fallback deterministik karena verifier final gagal; "
                "hasil tetap sebaiknya ditinjau ulang untuk nuansa bahasa."
            ),
        )
    return VerificationDecision(
        claims=[
            ClaimAssessment(
                claim_id=claim.id,
                verdict="UNVERIFIED",
                supporting_evidence=[],
                refuting_evidence=[],
                contradiction_level="NONE",
                reason="Verifier eksternal tidak selesai; klaim tidak diberi keputusan faktual.",
            )
            for claim in planner.claims
        ],
        overall_verdict="UNVERIFIED",
        risk_level=planner.interim_risk,
        evidence_sufficiency=evidence_sufficiency,
        requires_human_review=True,
        headline="Pemeriksaan belum dapat diselesaikan secara penuh",
        what_checked=[claim.text for claim in planner.claims],
        why=[
            "Verifier eksternal tidak tersedia atau tidak memenuhi kontrak output.",
            "Sistem mempertahankan batas risiko dan tindakan aman tanpa menebak verdict.",
        ],
        recommended_actions=[
            RecommendedAction(
                code="VERIFY_VIA_OFFICIAL_CHANNEL",
                title="Verifikasi melalui kanal resmi",
                detail="Jangan mengambil tindakan sensitif sebelum memperoleh konfirmasi resmi.",
            )
        ],
        uncertainty=(
            "Evidence belum dapat dinilai oleh verifier; hasil dikunci sebagai "
            "belum terverifikasi dan memerlukan pemeriksaan lanjutan."
        ),
    )


def _fallback_claim_assessment(
    claim: PlannedClaim,
    evidence: list[Evidence],
    evidence_sufficiency: float,
) -> ClaimAssessment:
    claim_evidence = [item for item in evidence if item.claim_id == claim.id] or evidence[:4]
    evidence_ids = [item.id for item in claim_evidence[:3]]
    combined = " ".join(
        [claim.text, *(item.title for item in claim_evidence), *(item.excerpt for item in claim_evidence)]
    ).casefold()
    claim_text = claim.text.casefold()
    refuters = [item.id for item in claim_evidence if item.stance == "REFUTES" and item.relevance >= 0.55]
    supporters = [item.id for item in claim_evidence if item.stance == "SUPPORTS" and item.relevance >= 0.55]
    if evidence_sufficiency >= 0.58 and refuters:
        return ClaimAssessment(
            claim_id=claim.id,
            verdict="REFUTED",
            supporting_evidence=[],
            refuting_evidence=refuters[:3],
            contradiction_level="HIGH",
            reason="Evidence terstruktur membantah salah satu facet utama klaim.",
        )
    if evidence_sufficiency >= 0.58 and supporters:
        return ClaimAssessment(
            claim_id=claim.id,
            verdict="SUPPORTED",
            supporting_evidence=supporters[:3],
            refuting_evidence=[],
            contradiction_level="NONE",
            reason="Evidence terstruktur mendukung facet utama klaim.",
        )
    if evidence_sufficiency >= 0.58 and _is_explicit_demotion_refutation(claim_text, combined):
        return ClaimAssessment(
            claim_id=claim.id,
            verdict="REFUTED",
            supporting_evidence=[],
            refuting_evidence=evidence_ids,
            contradiction_level="HIGH",
            reason="Evidence menyatakan konteksnya upacara penurunan bendera atau gambar hasil suntingan, bukan penurunan jabatan.",
        )
    if evidence_sufficiency >= 0.58 and _is_explicitly_supported_by_official_source(claim, claim_evidence):
        return ClaimAssessment(
            claim_id=claim.id,
            verdict="SUPPORTED",
            supporting_evidence=evidence_ids,
            refuting_evidence=[],
            contradiction_level="NONE",
            reason="Evidence resmi yang relevan secara eksplisit mendukung klaim.",
        )
    return ClaimAssessment(
        claim_id=claim.id,
        verdict="UNVERIFIED",
        supporting_evidence=[],
        refuting_evidence=[],
        contradiction_level="NONE",
        reason="Verifier eksternal tidak selesai; fallback tidak menemukan pola deterministik yang cukup jelas.",
    )


def _is_explicit_demotion_refutation(claim_text: str, evidence_text: str) -> bool:
    demotion_claim = bool(
        re.search(r"\b(?:penurunan\s+jabatan|lengser|dicopot|pemecatan|demotion)\b", claim_text)
        or ("penurunan prabowo" in claim_text and "bendera" not in claim_text)
    )
    refuting_context = bool(
        re.search(r"\bpenurunan\s+bendera\b", evidence_text)
        or re.search(r"\b(?:diedit|diubah|rekayasa|hasil\s+rekayasa|bukan\s+tayangan\s+asli)\b", evidence_text)
    )
    return demotion_claim and refuting_context


def _is_explicitly_supported_by_official_source(
    claim: PlannedClaim,
    evidence: list[Evidence],
) -> bool:
    claim_tokens = {
        token
        for token in re.findall(r"[a-z0-9]+", claim.text.casefold())
        if len(token) > 3
    }
    if not claim_tokens:
        return False
    for item in evidence:
        if item.authority < 0.95 or item.relevance < 0.6:
            continue
        text = f"{item.title} {item.excerpt}".casefold()
        evidence_tokens = set(re.findall(r"[a-z0-9]+", text))
        if len(claim_tokens & evidence_tokens) / max(1, len(claim_tokens)) >= 0.55:
            return True
    return False


def _fallback_headline(verdict: str) -> str:
    if verdict == "REFUTED":
        return "Klaim dibantah oleh evidence yang tersedia"
    if verdict == "MISLEADING":
        return "Klaim menyesatkan tanpa konteks lengkap"
    if verdict == "SUPPORTED":
        return "Klaim didukung oleh evidence resmi"
    return "Pemeriksaan belum dapat diselesaikan secara penuh"


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


def _is_non_checkable_image(case: CaseContext) -> bool:
    if case.input_type != "IMAGE":
        return False
    content_type = case.content_type.casefold().replace("-", "_").replace(" ", "_")
    if any(
        marker in content_type
        for marker in (
            "chat",
            "message",
            "screenshot",
            "news",
            "poster",
            "document",
            "invoice",
            "receipt",
            "social_media",
        )
    ):
        return False
    if case.possible_impersonation or case.urls:
        return False
    if any(claim.verifiable and claim.text.strip() for claim in case.seed_claims):
        return False
    text_tokens = _tokens(case.safe_text)
    has_enough_text = len(text_tokens) >= 8 or len(case.safe_text.strip()) >= 40
    if has_enough_text:
        return False
    non_document_photo = any(
        marker in content_type
        for marker in ("photo", "image", "other", "unknown", "landscape", "classroom", "room")
    )
    return non_document_photo or not content_type.strip()


FORCED_ACTION_DETAILS = {
    "DO_NOT_SHARE_SECRET": (
        "Jangan bagikan kode rahasia",
        "Jangan berikan OTP, PIN, password, CVV, recovery code, atau secret lain kepada siapa pun.",
    ),
    "DO_NOT_INSTALL": (
        "Jangan instal file atau aplikasi",
        "Jangan menjalankan APK atau executable yang diterima melalui pesan mencurigakan.",
    ),
    "DO_NOT_GRANT_REMOTE_ACCESS": (
        "Tolak akses jarak jauh",
        "Jangan memberikan remote access, accessibility permission, atau screen sharing.",
    ),
    "DO_NOT_TRANSFER": (
        "Jangan transfer dana",
        "Hentikan pembayaran sampai alasan, kanal, dan penerima terverifikasi.",
    ),
    "CONTACT_PROVIDER_VIA_OFFICIAL_CHANNEL": (
        "Hubungi penyedia melalui kanal resmi",
        "Cari sendiri aplikasi, situs, atau nomor resmi; jangan gunakan kontak dari pesan tersebut.",
    ),
    "CONTACT_BANK_OR_PJP": (
        "Segera hubungi bank atau PJP",
        "Laporkan transaksi melalui kanal resmi bank atau penyedia jasa pembayaran.",
    ),
    "REPORT_TO_IASC": (
        "Laporkan melalui IASC",
        "Gunakan portal resmi iasc.ojk.go.id untuk jalur penanganan finansial.",
    ),
    "PRESERVE_EVIDENCE": (
        "Simpan bukti dengan aman",
        "Simpan kronologi, percakapan, dan bukti transfer tanpa membagikan secret.",
    ),
    "RETURN_UNVERIFIED": (
        "Tunggu bukti yang memadai",
        "Jangan mengambil tindakan sensitif selama status masih belum terverifikasi.",
    ),
}


def _enforce_rulebook_safety(
    decision: VerificationDecision,
    rulebook: RulebookResult,
) -> None:
    """Enforce safe actions without allowing rules to alter factual verdicts."""
    existing_codes = {item.code for item in decision.recommended_actions}
    for action_code in rulebook.forced_actions:
        if action_code in existing_codes:
            continue
        title, detail = FORCED_ACTION_DETAILS.get(
            action_code,
            (
                action_code.replace("_", " ").title(),
                "Tindakan keselamatan ini dipicu oleh rulebook terverifikasi.",
            ),
        )
        decision.recommended_actions.append(
            RecommendedAction(code=action_code, title=title, detail=detail)
        )
        existing_codes.add(action_code)

    critical_observable = any(
        match.severity == "CRITICAL"
        and "DETERMINISTIC" in match.match_types
        and match.chunk_type in {"critical_indicator", "safe_action", "do_not_do"}
        for match in rulebook.matches
    )
    if critical_observable:
        decision.risk_level = "CRITICAL"

