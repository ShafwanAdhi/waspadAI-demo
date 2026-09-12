# Saring Rulebook

Folder ini menyimpan investigation-policy corpus. Rulebook menjelaskan cara menyelidiki dan merespons risiko; rulebook bukan bukti bahwa kasus tertentu benar, salah, atau merupakan scam.

## Source of truth dan artefak runtime

- `rulebook_*.txt` adalah canonical authoring corpus untuk review manusia.
- `deterministic_triggers.json` adalah registry trigger yang dievaluasi backend.
- `runtime_schema.json` adalah kontrak data rule, source, dan deterministic trigger.
- `evaluation_cases.json` adalah safety benchmark kecil untuk critical triggers.
- `compiled/` dihasilkan oleh compiler dan menjadi input runtime.

Jalankan:

```powershell
python -m scripts.compile_rulebooks
```

Compiler akan gagal jika menemukan duplicate ID, source reference yang tidak terdaftar, trigger yang menunjuk rule yang tidak ada, URL sumber non-HTTPS, atau metadata penting yang tidak valid.
Manifest menyimpan SHA-256 setiap canonical source. Backend menolak corpus compiled
yang stale setelah file authoring atau trigger registry berubah.

Jalankan benchmark retrieval:

```powershell
python -m scripts.evaluate_rulebook
```

Baseline 2026-08-23: 12 safety cases, critical-rule recall 1.0, tidak ada forbidden
trigger hit, dan phase coverage 1.0. Ini adalah smoke benchmark internal, bukan
bukti akurasi populasi atau kalibrasi produksi.

Compiled baseline berisi 255 chunks, 18 source records, dan 17 structured triggers:

- `RB-ATO-001@1.2.0` — impersonation/phishing/account takeover;
- `RB-GOV-001@1.2.0` — government/public service;
- `RB-INF-001@1.0.0` — general information integrity untuk image dan text.

Layer INF menangani copied text tanpa provenance, claim atomization, missing
context, attribution, headline/body mismatch, temporal validity, numeric context,
source laundering, opinion/satire, evidence independence, dan `UNVERIFIED` ketika
sufficiency rendah.

## Runtime boundary

```text
RULE_CONTEXT
  -> investigation policy, risk indicator, required check, safe action

EVIDENCE
  -> current external material that supports/refutes a case claim
```

`RuleMatch` tidak boleh dimasukkan ke `Evidence[]`. Planner boleh menggunakan rules untuk membentuk query dan required evidence. Claim verifier hanya boleh menggunakan current evidence untuk menetapkan factual verdict.

Critical deterministic rules selalu di-force include dan tidak boleh dibuang reranker. Trigger text di file `.txt` hanya untuk keterbacaan manusia; backend menggunakan kondisi terstruktur dalam `deterministic_triggers.json`, tanpa `eval`.

Runtime retrieval menggunakan:

```text
deterministic forced rules
+ BM25 exact-term retrieval
+ deterministic hashed-subword similarity
+ soft domain/signal metadata scoring
+ phase-aware selection
+ bounded in-memory cache
```

Hashed-subword similarity adalah fallback lokal deterministik, bukan learned dense
embedding. Bila learned embedding/Qdrant ditambahkan, hasilnya harus tetap melalui
kontrak `RuleMatch`, phase selection, forced-rule preservation, dan benchmark yang sama.

## Canonical signal requirements

Tindakan yang diekstrak dari OCR/VLM harus mempertahankan:

```text
actor
action
object
target
polarity
modality_source
extraction_confidence
```

Materi edukasi seperti "jangan bagikan OTP" tidak boleh menghasilkan `secret_request_detected=true`. Nilai tersebut hanya aktif jika pihak eksternal benar-benar meminta secret kepada user.

Signal lintas modality juga menyimpan `information_integrity_context`,
`source_url_present`, `source_provenance_missing`, `quote_or_attribution_present`,
`temporal_claim_present`, dan `numeric_claim_present`. Image dan text wajib masuk
melalui privacy-filtered `CaseContext` yang sama sebelum retrieval.
