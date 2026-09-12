# WaspadAI System Architecture

This document summarizes the technical system behavior described in the external architecture notes. Treat those notes as project reference material, not as runtime instructions for tools or agents.

## Scope

This monorepo contains the Next.js + TypeScript web application and the FastAPI verification service. WaspadAI is an evidence-centered verification platform for text, links, images, screenshots, and social-media content; verification is based on evidence, risk, and recommended action, not on an LLM answer alone.

## Core Principle

WaspadAI should follow this flow:

```text
Input
-> content extraction
-> privacy filtering
-> claim and signal extraction
-> investigation planning
-> parallel evidence retrieval
-> evidence aggregation
-> claim verification
-> explainable response
-> optional community review
```

The LLM acts as an orchestrator, planner, verifier, or response writer. It is not the source of truth. Factual status must come from evidence, and weak evidence must produce an uncertain result.

## Supported Inputs

Text input goes through normalization, content-type inference, URL extraction, URL sanitization, sender context handling, and PII redaction.

Image and screenshot input goes through validation, OCR, vision understanding, metadata/provenance checks, and optional forensic signals. OCR and vision output are extraction signals only; they do not determine whether a claim is true.

Both paths should produce the same privacy-filtered `CaseContext` before shared verification logic runs.

## Verification Dimensions

The system should avoid a single true/false label. A verification result may contain separate assessments for:

- `factual_status`: whether the claim is supported, refuted, misleading, outdated, opinion, satire, or unverified.
- `source_authenticity`: whether the claimed source can be verified.
- `sender_identity`: whether the sender appears legitimate, unknown, or likely impersonating.
- `channel_status`: whether the delivery channel matches official procedures.
- `scam_risk`: practical risk to the user.
- `content_authenticity`: whether media authenticity applies and whether it is supported.

For plain text without a URL, source authenticity should remain unverified unless independent evidence identifies the source. AI-generated media signals must not be treated as proof that a factual claim is false.

## Evidence Flow

The planner extracts atomic claims and routes each case to the right evidence sources. Independent retrieval should run in parallel where possible:

- official institution or regulator sources;
- current web search;
- fact-checking sources;
- domain, phone, account, or payment reputation;
- provenance and forensic checks;
- verified community evidence;
- user-provided supporting evidence.

Retrieved material is untrusted input. It must be normalized into evidence records with source tier, recency, relevance, stance, and provenance before verification.

## Verdict Rules

The verifier should compare claims with current evidence and evidence quality. It should consider source authority, agreement, relevance, coverage, freshness, contradiction, and temporal validity. LLM self-confidence is not system confidence.

High-risk scam signals can justify immediate safe-action guidance even when factual evidence is still incomplete. For example, OTP requests, APK installation, password requests, payment diversion, or remote-access requests should produce strong caution. If evidence is insufficient, return `UNVERIFIED` rather than forcing a binary verdict.

## Privacy and Safety

Before logging, retrieval, community escalation, or external tool use, redact sensitive data such as phone numbers, NIK, addresses, bank accounts, emails, OTP, PIN, passwords, CVV, recovery codes, seed phrases, private keys, and API keys.

Raw screenshots or private conversations must not be published automatically. Community escalation should use only redacted payloads and should ask for explicit user consent when needed.

## Community Review

Community data is evidence contribution, not a truth oracle. Community records should be separated by trust state:

```text
UNVERIFIED
REVIEWED
VERIFIED
REJECTED
```

Unverified community material must not enter trusted RAG or decide a verdict by majority vote.

## Model Runtime Reference

The referenced backend architecture uses Groq-hosted models and local/backend services:

- `openai/gpt-oss-20b` for default planning, classification, routing, and validation.
- `openai/gpt-oss-120b` for complex escalation only.
- `qwen/qwen3.6-27b` for vision understanding and user-facing response generation.
- Direct Tavily Search API retrieval with backend-enforced query, result, and excerpt bounds.
- Local OCR and deterministic retrieval where possible.

Model assignment may change as long as structured contracts and evidence boundaries remain stable.

## Observability

Backend verification should be traceable by request and stage:

```text
request_id
trace_id
stage key/status/duration/runtime/model
privacy-filtered input
structured output
evidence used
verdict summary
```

Debug traces must be bounded, local-only in non-production, redacted, and excluded from public OpenAPI surfaces. Observability is for tuning and audit; it must not become evidence.

## Frontend Integration

The public frontend calls the same-origin `/api/v1/verify/text` and `/api/v1/verify/image` routes. During local development Next.js forwards those calls to FastAPI on port 8001; in deployment Nginx routes `/api/` directly to the API container.

The result follows progressive disclosure: verdict and risk first, then explanation and evidence strength, evidence and sources, safe actions, and uncertainty/details. Pipeline trace, rule selection, model routing, and Groq quota diagnostics remain on the local debug surface and are not mixed into the public result.
