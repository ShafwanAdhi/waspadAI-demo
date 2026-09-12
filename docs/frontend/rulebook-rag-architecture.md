# Rulebook RAG Architecture

This document captures how WaspadAI should use Retrieval-Augmented Generation for scam and fact-check investigation. It summarizes the provided Rulebook RAG documentation as repository reference material.

## Core Separation

Rulebook RAG answers:

```text
How should this case be investigated?
```

Live evidence answers:

```text
What is true about this case now?
```

Those layers must stay separate. Rulebook matches can force risk posture, critical checks, and safe actions, but they must not force a factual verdict. A risky pattern is not the same as proof that the current claim is false.

## Active Baseline

The referenced implementation baseline describes a modular FastAPI monolith with:

- 255 semantic rule chunks;
- 18 authoritative source records;
- 17 structured deterministic triggers;
- BM25 lexical retrieval;
- deterministic hashed-subword similarity;
- soft metadata scoring;
- phase-aware rule selection;
- bounded cache with corpus hash and staleness checks.

Hashed-subword similarity is a reproducible local fallback, not learned dense embedding. Qdrant or learned embeddings are optional scale-out paths.

## Rulebook Domains

The current canonical layers are:

- `RB-INF-001@1.0.0`: general information integrity.
- `RB-ATO-001@1.2.0`: impersonation, phishing, malware, and account takeover.
- `RB-GOV-001@1.2.0`: government, public service, and aid.

Domain classification should be multi-label. Attack patterns such as `phishing`, `urgency`, `otp_request`, `malicious_apk`, `remote_access`, `money_mule`, or `identity_impersonation` are cross-domain tags, not business domains.

## Retrieval Pipeline

```text
CaseContext
-> domain and attack-pattern classification
-> deterministic critical triggers
-> metadata filtering
-> BM25 lexical candidates
-> hashed-subword or dense candidates
-> merge and deduplicate
-> rerank
-> phase-aware RuleMatch selection
```

Use deterministic triggers for safety-critical signals. Examples include OTP requests, APK installation through chat, PIN/password/CVV requests, remote-access requests, payment required for jobs, withdrawal fees requiring new deposits, and intimate threats.

## Chunk Strategy

Rules should be chunked by semantic unit, not arbitrary token windows. Prefer one logical rule per chunk:

```text
ATO-R004 - OTP request
ATO-R006 - APK installation through chat
GOV-R001 - program legitimacy is separate from channel legitimacy
GLOBAL-R003 - verify identity through an independently discovered official channel
```

Each rule should include metadata such as rule ID, domain, chunk type, severity, attack patterns, channels, country, language, version, source IDs, and freshness dependency.

## Chunk Types

Supported rule purposes include:

- `scope`
- `attack_pattern`
- `critical_indicator`
- `red_flag`
- `verification_question`
- `investigation_step`
- `search_template`
- `evidence_requirement`
- `decision_guidance`
- `safe_action`
- `do_not_do`
- `escalation_rule`
- `source_registry`

Selection should cover detection, investigation, decision, and response phases so the planner receives a balanced context.

## Rule-Grounded Search

Search queries should be generated from rule templates plus extracted entities, not improvised freely. For example, an entity extractor may find `agency=BPJS`, `channel=WhatsApp`, and `artifact=APK`, then generate:

```text
"BPJS Kesehatan" penipuan WhatsApp
"BPJS Kesehatan" APK
site:bpjs-kesehatan.go.id WhatsApp APK
site:bpjs-kesehatan.go.id OTP
```

This keeps retrieval aligned with required checks and preferred sources.

## Evidence Boundary

Rule matches should produce `RuleMatch[]`. Current material should produce `Evidence[]`. Do not mix these contracts.

The verifier may use rules to understand risk indicators, required checks, safe actions, and escalation conditions. It must use current evidence to decide factual claim status. Tier 4 evidence, such as anonymous posts or unsupported testimony, should not be decisive by itself.

## Evaluation Targets

Evaluate the system per stage:

- domain routing: top-k recall and multi-label F1;
- attack-pattern extraction: precision, recall, and F1;
- rule retrieval: Recall@K, Precision@K, MRR or nDCG, critical-rule recall;
- investigation planning: required-check coverage and source-selection quality;
- evidence retrieval: source authority distribution and evidence precision;
- verification: verdict accuracy, unsupported definitive verdict rate, and `UNVERIFIED` calibration;
- safety: safe-action accuracy and PII leakage rate.

Small smoke benchmarks prove wiring only. Do not present them as production accuracy.

## Implementation Invariants

- LLM output is not ground truth.
- Rulebook RAG is investigation policy, not a truth database.
- Live/current evidence decides factual status.
- Scam risk, factual truth, and content authenticity are separate.
- Absence of evidence is not proof of safety or falsity.
- Unverified community data cannot be decisive.
- Retrieved webpages are untrusted content.
- Every verdict should be traceable to evidence.
- Escalation models are used for complexity, not as the default path.
- Independent retrieval should run in parallel where possible.
