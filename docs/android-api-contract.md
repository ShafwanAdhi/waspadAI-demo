# Kontrak API Android WaspadAI

Status dokumen: **MUTLAK v1.0** untuk integrasi Android/Kotlin melalui Product
API milik aplikasi mobile menuju service AI WaspadAI.

Dokumen ini adalah sumber kontrak utama untuk tim Android dan backend aplikasi
mobile. Jika implementasi belum memiliki endpoint tertentu, statusnya ditandai
sebagai `TARGET`; kontrak tetap menjadi arah implementasi yang harus diikuti.

## 1. Keputusan Arsitektur Final

Android tidak memanggil WaspadAI secara langsung.

Jalur yang berlaku:

```text
Android Kotlinko
  -> FastAPI aplikasi mobile / Product Backend
  -> Database Product, Supabase Auth, Storage, Community
  -> Internal API WaspadAI
  -> Pipeline fact-check WaspadAI
```

Tanggung jawab tiap sistem:

| Sistem | Tanggung jawab |
| --- | --- |
| Android | Mengirim input pengguna, Supabase access token, dan menampilkan hasil. |
| Product Backend | Validasi login, history, screenshot storage, community, vote, moderasi, dan pemilihan community evidence. |
| WaspadAI | Menjalankan pipeline fact-check dan mengembalikan hasil AI. |
| Database Product | Menjadi sumber state history, community, consent, vote, dan moderasi. |

Aturan yang tidak boleh dilanggar:

- Android hanya memanggil Product Backend.
- Android tidak pernah menyimpan atau mengirim `X-Waspadai-API-Key`.
- WaspadAI tidak menerima Supabase access token.
- WaspadAI tidak mengakses Supabase Database, Supabase Storage, atau database
  aplikasi mobile.
- WaspadAI tidak menyimpan history pengguna.
- Community evidence dikirim ke WaspadAI hanya sebagai payload sanitized dari
  Product Backend.

Endpoint publik WaspadAI tetap ada untuk website demo dan pengujian manual:

```text
GET  https://waspadai.shafwan.digital/api/health
POST https://waspadai.shafwan.digital/api/v1/verify/text
POST https://waspadai.shafwan.digital/api/v1/verify/image
```

Endpoint internal WaspadAI hanya boleh dipanggil server:

```text
POST https://waspadai.shafwan.digital/api/internal/v1/verify/text
POST https://waspadai.shafwan.digital/api/internal/v1/verify/image
```

## 2. Base URL Android

Android memakai base URL Product Backend aplikasi mobile:

```text
https://<api-aplikasi-mobile>
```

Android tidak memakai base URL `https://waspadai.shafwan.digital` untuk mode
production aplikasi mobile. Domain WaspadAI hanya dipakai oleh Product Backend.

## 3. Autentikasi Android

Semua endpoint Product API yang dipakai Android wajib menerima:

```http
Authorization: Bearer <supabase_access_token>
Accept: application/json
```

Product Backend wajib:

1. mengambil bearer token dari header `Authorization`;
2. memvalidasi token dengan `supabase.auth.get_user(access_token)` pada MVP;
3. menolak token invalid atau expired dengan HTTP `401`;
4. mengambil `sub` sebagai `user_id` terpercaya;
5. memakai `user_id` untuk history, Storage, community, vote, dan ownership.

Android tidak mengirim refresh token ke Product Backend. Jika menerima `401`,
Android meminta Supabase SDK refresh session lalu retry request yang sama paling
banyak satu kali.

Untuk request pemeriksaan, Android wajib mengirim:

```http
Idempotency-Key: <uuid-v4>
```

Product Backend memakai kombinasi `user_id + Idempotency-Key` untuk mencegah
pipeline AI berjalan dua kali akibat retry jaringan.

## 4. Karakteristik Pemeriksaan

- Pemeriksaan bersifat synchronous.
- Satu request menghasilkan satu respons.
- Chatbot MVP bukan percakapan multi-turn; setiap pesan adalah pemeriksaan baru.
- Timeout Android untuk pemeriksaan AI: 150 detik.
- Deadline Product Backend ketika memanggil WaspadAI: 120 detik.
- Android tidak mengirim `output_mode`.
- Product Backend selalu meminta `output_mode=BOTH` ke WaspadAI.
- Naratif adalah tampilan utama.
- Bukti, sumber, tindakan, dimensi, dan detail lain ditampilkan bertingkat.

## 5. Product API Untuk Android

### 5.1 Pemeriksaan Teks

```http
POST /api/v1/verifications/text
Authorization: Bearer <supabase_access_token>
Idempotency-Key: <uuid-v4>
Content-Type: application/json
```

Status implementasi: endpoint text vertical slice sudah tersedia pada Product
Backend, tetapi remote call ke WaspadAI mengikuti kesiapan repository aplikasi
mobile.

Request:

```json
{
  "text": "Pesan mengaku dari bank dan meminta OTP agar akun tidak diblokir.",
  "question": "Apakah pesan ini aman?",
  "source_url": null,
  "sender_context": "UNKNOWN_NUMBER",
  "page_context": {
    "title": "Chat dari nomor tidak dikenal",
    "before": null,
    "after": null
  }
}
```

Aturan field:

| Field | Wajib | Aturan |
| --- | --- | --- |
| `text` | Ya | 10 sampai 25.000 karakter setelah trim. |
| `question` | Tidak | Maksimal 500 karakter; backend memakai pertanyaan default jika kosong. |
| `source_url` | Tidak | URL publik HTTP(S), maksimal 2.048 karakter. |
| `sender_context` | Tidak | Default `UNKNOWN`. |
| `page_context` | Tidak | Object opsional; minimal satu field berisi nilai jika dikirim. |

Nilai `sender_context`:

```text
NOT_APPLICABLE
UNKNOWN_NUMBER
KNOWN_CONTACT
FORWARDED
SOCIAL_MEDIA
UNKNOWN
```

Aturan `page_context`:

| Field | Aturan |
| --- | --- |
| `title` | Maksimal 300 karakter. |
| `before` | Maksimal 500 karakter. |
| `after` | Maksimal 500 karakter. |

Teks yang hanya berisi satu URL publik tetap valid. URL `localhost`, loopback,
private IP, file URL, dan URL internal harus ditolak oleh Product Backend.

### 5.2 Pemeriksaan Screenshot

```http
POST /api/v1/verifications/image
Authorization: Bearer <supabase_access_token>
Idempotency-Key: <uuid-v4>
Content-Type: multipart/form-data
```

Status implementasi: `TARGET`; belum boleh dianggap tersedia sampai Product
Backend mengekspor endpoint, OpenAPI, test, dan deployment.

Multipart fields:

| Field | Wajib | Aturan |
| --- | --- | --- |
| `image` | Ya | File biner JPG, PNG, atau WEBP. |
| `question` | Tidak | Maksimal 500 karakter. |

Batas gambar:

| Batas | Nilai |
| --- | --- |
| Ukuran file | Maksimal 8 MB. |
| Dimensi minimal | 64 x 64 piksel. |
| Dimensi maksimal | 6.000 x 6.000 piksel. |
| Jumlah piksel | Maksimal 30.000.000 piksel. |
| Format | JPEG/JPG, PNG, WEBP. |

Alur Android untuk screenshot:

1. ambil screenshot melalui capture/overlay Android;
2. tampilkan preview dan crop;
3. kirim hasil crop sebagai multipart binary;
4. jangan kirim gambar sebagai Base64 JSON;
5. pertahankan loading sampai respons diterima atau timeout.

## 6. Response Product API

Product Backend boleh membungkus hasil WaspadAI dengan metadata history,
community, dan execution mode.

Wrapper final yang diterima Android:

```json
{
  "request_id": "8f20b3a3-7d90-4b0a-a5ee-59b7b0a4e8b8",
  "status": "COMPLETED",
  "execution_mode": "REMOTE",
  "history": {
    "saved": true,
    "case_id": "56f50192-7dd1-4bec-9a52-d838174c9d23",
    "save_reason": "UNVERIFIED",
    "community_eligible": true,
    "community_state": "PRIVATE"
  },
  "result": {
    "request_id": "req_8f20b3a37d90",
    "trace_id": "trace_01kotlinexample",
    "status": "COMPLETED",
    "mode": "LIVE",
    "mode_notice": "Pemeriksaan dilakukan oleh pipeline WaspadAI.",
    "input_summary": {
      "input_type": "TEXT",
      "content_type": "UNKNOWN_SENDER_MESSAGE",
      "label": "Teks",
      "media_type": null,
      "dimensions": null,
      "extraction_status": "parsed",
      "excerpt": "Pesan mengaku dari bank dan meminta OTP agar akun tidak diblokir.",
      "source_url": null,
      "sender_context": "UNKNOWN_NUMBER",
      "character_count": 68,
      "urls_detected": 0,
      "pii_types_redacted": []
    },
    "verdict": "UNVERIFIED",
    "risk_level": "MEDIUM",
    "headline": "Bukti belum cukup untuk memastikan klaim",
    "evidence_sufficiency": 0.42,
    "evidence_sufficiency_label": "Bukti belum cukup untuk memastikan klaim",
    "requires_human_review": true,
    "community_status": "ELIGIBLE_WITH_CONSENT",
    "official_referral": {
      "status": "URGENT",
      "mode": "RECOVERY",
      "reason_codes": ["USER_ALREADY_ACTED:PAYMENT_SENT"],
      "summary": "Pengguna sudah melakukan tindakan sensitif; arahkan ke kanal pemulihan resmi.",
      "routes": [
        {
          "route_type": "FINANCIAL_PROVIDER",
          "priority": "PRIMARY",
          "reason": "Laporkan transaksi ke bank atau penyedia jasa pembayaran resmi."
        },
        {
          "route_type": "FINANCIAL_SCAM_REPORTING",
          "priority": "SECONDARY",
          "reason": "Gunakan jalur pelaporan penipuan finansial resmi setelah bukti disiapkan."
        }
      ]
    },
    "privacy_notice": "Data ditangani sesuai kebijakan privasi WaspadAI.",
    "what_checked": [
      "Klaim utama pada pesan",
      "Kecocokan dengan sumber yang ditemukan"
    ],
    "why": [
      "Bukti yang ditemukan belum mencakup seluruh klaim material."
    ],
    "evidence": [],
    "sources": [],
    "recommended_actions": [
      {
        "code": "RETURN_UNVERIFIED",
        "title": "Tunggu bukti yang lebih kuat",
        "detail": "Jangan jadikan informasi ini satu-satunya dasar keputusan."
      }
    ],
    "uncertainty": "Masih diperlukan sumber primer atau sumber tepercaya lain.",
    "dimensions": {
      "factual_status": "UNVERIFIED",
      "source_authenticity": "UNVERIFIED",
      "sender_identity": "UNVERIFIED",
      "channel_status": "UNVERIFIED",
      "scam_risk": "MEDIUM",
      "content_authenticity": "NOT_APPLICABLE"
    },
    "rulebook": {
      "corpus_versions": [],
      "retrieval_mode": "LIVE",
      "candidate_count": 0,
      "selected_count": 0,
      "forced_rule_ids": [],
      "cache_hit": false,
      "duration_ms": 0
    },
    "pipeline": [],
    "presentation": {
      "requested_mode": "BOTH",
      "structured": true,
      "narrative": {
        "text": "Hasil pemeriksaan: bukti yang tersedia belum cukup untuk memastikan klaim. Periksa kembali sumber resmi sebelum menindaklanjutinya.",
        "summary": "Bukti belum cukup untuk memastikan klaim",
        "paragraphs": [
          "Hasil pemeriksaan: bukti yang tersedia belum cukup untuk memastikan klaim.",
          "Periksa kembali sumber resmi sebelum menindaklanjutinya."
        ]
      }
    },
    "disclaimer": "Fact-check adalah dukungan keputusan, bukan jaminan."
  }
}
```

### 6.1 Official Referral dari WaspadAI

`result.official_referral` wajib dianggap sebagai field respons sukses WaspadAI.
Field ini tidak mengganti `verdict`, `risk_level`, `requires_human_review`, atau
`community_status`; ia hanya memberi sinyal terstruktur agar Product Backend atau
Android dapat menampilkan rujukan kanal resmi.

WaspadAI tidak mengirim URL, nomor telepon, hotline, rekening, OTP, atau PII di
field ini. Product Backend/mobile harus memetakan `route_type` ke direktori kanal
resmi yang dikelola aplikasi, misalnya daftar bank, penyedia akun, platform, atau
jalur pelaporan finansial yang sudah diverifikasi.

Nilai status:

| Status | Kapan dipakai |
| --- | --- |
| `NOT_REQUIRED` | Tidak ada referral resmi khusus. |
| `RECOMMENDED` | Ada sinyal scam/impersonation berisiko tinggi, tetapi user belum terdeteksi melakukan tindakan sensitif. |
| `URGENT` | User sudah transfer, memasukkan kredensial, membagikan OTP, memasang APK, memberi remote access, atau kehilangan akses akun. |

Nilai mode:

| Mode | Arti |
| --- | --- |
| `PREVENTION` | Bantu user memverifikasi kanal resmi sebelum bertindak. |
| `RECOVERY` | Bantu user melakukan pemulihan setelah tindakan sensitif terjadi. |
| `null` | Hanya untuk `status=NOT_REQUIRED`. |

Route type yang dapat dikirim WaspadAI:

| Route type | Tanggung jawab Product Backend/mobile |
| --- | --- |
| `OFFICIAL_INSTITUTION` | Map ke institusi resmi terkait konteks pemerintah/layanan publik. |
| `ACCOUNT_PROVIDER` | Map ke kanal pemulihan akun layanan yang relevan. |
| `FINANCIAL_PROVIDER` | Map ke bank/PJP/dompet digital resmi. |
| `FINANCIAL_SCAM_REPORTING` | Map ke jalur pelaporan penipuan finansial resmi. |
| `PLATFORM_REPORTING` | Map ke fitur pelaporan platform tempat pesan/konten muncul. |
| `DEVICE_RECOVERY` | Map ke alur pemulihan perangkat, pencabutan izin, atau edukasi uninstall aman. |

Aturan tampilan Android:

- tampilkan `result.presentation.narrative.text` sebagai jawaban utama;
- tampilkan `result.headline` sebagai ringkasan pendek;
- tampilkan `result.evidence`, `result.sources`, `result.recommended_actions`,
  `result.uncertainty`, dan `result.dimensions` secara bertingkat;
- jangan menjadikan `risk_level` sebagai elemen utama kecuali nilainya
  `HIGH` atau `CRITICAL`;
- jangan menampilkan `pipeline` kepada pengguna umum kecuali mode debug aktif.

ID pada wrapper Product Backend boleh UUID. ID internal WaspadAI menggunakan
format runtime WaspadAI, misalnya `req_<12hex>` dan `trace_<id>`.

## 7. Policy History

History adalah milik Product Backend, bukan WaspadAI.

Mode policy yang valid:

| Policy | Arti |
| --- | --- |
| `REVIEW_REQUIRED` | Simpan hanya kasus `UNVERIFIED` atau `requires_human_review=true`. Ini policy default MVP. |
| `ALL` | Simpan semua hasil pemeriksaan. Ini hanya boleh aktif jika UI, retensi, dan privacy policy sudah siap. |

Rumus final:

```text
saved = HISTORY_POLICY == "ALL"
     OR verdict == "UNVERIFIED"
     OR requires_human_review == true
```

Jika `HISTORY_POLICY=REVIEW_REQUIRED`, maka history hanya berisi kasus
`UNVERIFIED` atau `requires_human_review=true`.

Endpoint history Product Backend:

```http
GET    /api/v1/history?limit=20&cursor=<opaque_cursor>
GET    /api/v1/history/{case_id}
DELETE /api/v1/history/{case_id}
```

`GET` list/detail sudah tersedia sesuai implementasi Product Backend. `DELETE`
adalah target jika belum diekspor oleh repository aplikasi mobile.

Daftar history mengembalikan ringkasan:

```json
{
  "items": [
    {
      "case_id": "56f50192-7dd1-4bec-9a52-d838174c9d23",
      "input_type": "IMAGE",
      "headline": "Bukti belum cukup untuk memastikan klaim",
      "verdict": "UNVERIFIED",
      "requires_human_review": true,
      "community_state": "PRIVATE",
      "created_at": "2026-09-14T12:00:00Z"
    }
  ],
  "next_cursor": null
}
```

Detail history boleh mengembalikan signed URL sementara untuk screenshot privat.
Bucket Supabase Storage tidak boleh public.

## 8. Community Publication

Community publication dikelola Product Backend. WaspadAI tidak mengakses endpoint
ini dan tidak menulis ke database community.

Kasus baru selalu privat. Tidak ada publikasi otomatis.

### 8.1 Membuat Preview Redaksi

```http
POST /api/v1/history/{case_id}/community-preview
```

Response:

```json
{
  "preview_id": "preview_01example",
  "expires_at": "2026-09-14T12:15:00Z",
  "redacted_text": "Hubungi [PHONE_REDACTED] untuk informasi lebih lanjut.",
  "redacted_image_url": "https://signed-storage-url.example",
  "redactions": ["PHONE"],
  "confirmation_required": true
}
```

Android wajib menampilkan preview final yang sudah diredaksi sebelum meminta
konfirmasi publikasi.

### 8.2 Mengonfirmasi Publikasi

```http
POST /api/v1/history/{case_id}/community
Content-Type: application/json
```

Request final:

```json
{
  "preview_id": "preview_01example",
  "publication_consent": true,
  "rag_reuse_consent": true
}
```

Makna consent:

| Field | Makna |
| --- | --- |
| `publication_consent` | Pengguna setuju konten sanitized tampil di komunitas. |
| `rag_reuse_consent` | Pengguna setuju konten sanitized dipakai ulang sebagai kandidat evidence AI setelah dimoderasi. |

Kedua consent harus eksplisit dan terpisah. Publikasi komunitas tidak otomatis
menjadi izin reuse oleh AI.

Jika `publication_consent=false`, backend menolak request publikasi. Jika
`publication_consent=true` tetapi `rag_reuse_consent=false`, post boleh tampil
di community setelah validasi product, tetapi tidak pernah boleh dikirim ke
WaspadAI sebagai community evidence.

### 8.3 Menarik Kasus

```http
DELETE /api/v1/history/{case_id}/community
```

Pemilik dapat menarik kasus selama belum berstatus `VERIFIED_EVIDENCE`.

## 9. Community Feed Dan Voting

Endpoint Product Backend:

```http
GET    /api/v1/community?limit=20&cursor=<opaque_cursor>
GET    /api/v1/community/{case_id}
PUT    /api/v1/community/{case_id}/vote
DELETE /api/v1/community/{case_id}/vote
```

Vote request:

```json
{
  "vote": "DIDUKUNG"
}
```

Nilai vote valid:

```text
DIDUKUNG
DIBANTAH
```

Aturan vote:

- satu pengguna maksimal punya satu vote aktif per kasus;
- `PUT` membuat atau mengganti vote;
- `DELETE` membatalkan vote;
- pemilik kasus tidak boleh vote pada kasus sendiri;
- identitas voter tidak ditampilkan;
- vote adalah opini komunitas, bukan verdict faktual;
- jumlah vote tidak boleh otomatis membuat kasus menjadi evidence terverifikasi.

Hanya moderator/admin yang boleh menetapkan `VERIFIED_EVIDENCE`.

## 10. Error Envelope

Product Backend tidak boleh meneruskan exception mentah WaspadAI ke Android.

Format error:

```json
{
  "error": {
    "code": "INVALID_ACCESS_TOKEN",
    "message": "Sesi tidak valid atau sudah berakhir.",
    "request_id": "req_01error",
    "retryable": false,
    "retry_after_seconds": null
  }
}
```

Mapping status:

| HTTP | Contoh code | Tindakan Android |
| --- | --- | --- |
| `400` | `INVALID_REQUEST` | Tampilkan kesalahan input. |
| `401` | `INVALID_ACCESS_TOKEN` | Refresh session lalu retry satu kali. |
| `403` | `OWNER_CANNOT_VOTE`, `CASE_LOCKED` | Tampilkan alasan; jangan retry. |
| `404` | `CASE_NOT_FOUND` | Kembali ke daftar sebelumnya. |
| `409` | `PREVIEW_EXPIRED`, `CASE_ALREADY_VERIFIED` | Refresh data atau buat preview baru. |
| `413` | `PAYLOAD_TOO_LARGE` | Minta pengguna crop/kompres gambar. |
| `415` | `UNSUPPORTED_MEDIA_TYPE` | Gunakan JPG, PNG, atau WEBP. |
| `422` | `VALIDATION_ERROR` | Tampilkan pesan validasi field. |
| `429` | `RATE_LIMITED` | Tunggu `retry_after_seconds`. |
| `502` | `FACT_CHECK_UPSTREAM_FAILURE` | Tawarkan coba lagi. |
| `503` | `SERVICE_UNAVAILABLE` | Tawarkan coba lagi nanti. |

Android tidak boleh menampilkan stack trace, exception name, atau detail teknis
mentah kepada pengguna umum.

## 11. Internal Product Backend -> WaspadAI

Bagian ini untuk backend aplikasi mobile, bukan Android.

```http
POST /api/internal/v1/verify/text
POST /api/internal/v1/verify/image
X-Waspadai-API-Key: <service_secret>
```

Aturan internal:

- simpan `X-Waspadai-API-Key` hanya di environment server;
- gunakan private Docker network jika kedua service berada di VPS yang sama;
- timeout call ke WaspadAI: 120 detik;
- selalu kirim `output_mode=BOTH`;
- teruskan `page_context` dari Product API jika ada;
- image dikirim sebagai multipart binary, bukan Base64;
- WaspadAI tidak menerima Supabase token dan tidak menyimpan history.

### 11.1 Request Internal Teks

Status: implemented di WaspadAI. Field `community_evidence` hanya diterima di
endpoint internal dan ditolak oleh endpoint publik.

```http
POST /api/internal/v1/verify/text
X-Waspadai-API-Key: <service_secret>
Content-Type: application/json
```

```json
{
  "text": "Pesan mengaku dari bank dan meminta OTP agar akun tidak diblokir.",
  "question": "Apakah pesan ini aman?",
  "source_url": null,
  "sender_context": "UNKNOWN_NUMBER",
  "page_context": {
    "title": "Chat dari nomor tidak dikenal",
    "before": null,
    "after": null
  },
  "output_mode": "BOTH",
  "community_evidence": []
}
```

### 11.2 Request Internal Image

Status: implemented di WaspadAI. Field `community_evidence_json` hanya diterima
di endpoint internal image multipart dan ditolak oleh endpoint publik.

```text
image=<file biner>
question=<teks pertanyaan>
output_mode=BOTH
community_evidence_json=<JSON array dari Community Evidence DTO>
```

`community_evidence_json` memakai schema yang sama dengan
`community_evidence`.

## 12. Community Evidence DTO

Community evidence tidak dibuat oleh Android. Product Backend mengambil data
dari Database Product, memvalidasi eligibility, lalu mengirim DTO sanitized ke
WaspadAI.

Jumlah maksimum final:

| Batas | Nilai |
| --- | --- |
| Record per request | Maksimal 5. |
| Source per record | Maksimal 3. |
| `redacted_text` per record | Maksimal 4.000 karakter saat dikirim ke WaspadAI. |
| Total serialized `community_evidence` | Maksimal 30 KB. |
| Overflow behavior | Potong berdasarkan ranking relevansi; jangan kirim payload melebihi limit. |

DTO final:

```json
{
  "schema_version": "1.0",
  "record_type": "COMMUNITY_VERIFIED_EVIDENCE",
  "community_post_id": "9bf23d78-5a46-4e37-a7ce-4ed22b0aac5d",
  "case_id": "56f50192-7dd1-4bec-9a52-d838174c9d23",
  "revision": 3,
  "content_hash": "7b0cf4b662bec1b2f6abdb3c1d86a45c397312594070bf74b5409b5c37e3d721",
  "status": "VERIFIED_EVIDENCE",
  "title": "Klaim bantuan tunai melalui tautan tidak resmi",
  "verified_claim": "Tautan pada pesan bantuan tunai tersebut bukan kanal resmi program pemerintah.",
  "stance": "REFUTES",
  "evidence_summary": "Moderator memverifikasi sumber resmi yang menyatakan program bantuan hanya diumumkan melalui kanal pemerintah, bukan melalui tautan pada pesan tersebut.",
  "redacted_text": "Pesan menawarkan bantuan tunai melalui tautan tidak resmi.",
  "published_at": "2026-09-15T10:00:00Z",
  "verified_at": "2026-09-15T12:30:00Z",
  "sources": [
    {
      "url": "https://example.go.id/klarifikasi-bantuan",
      "title": "Klarifikasi program bantuan",
      "publisher": "Instansi resmi",
      "published_at": "2026-09-15T09:00:00Z"
    }
  ]
}
```

Field wajib:

| Field | Aturan |
| --- | --- |
| `schema_version` | Wajib `1.0`. |
| `record_type` | Wajib `COMMUNITY_VERIFIED_EVIDENCE`. |
| `community_post_id`, `case_id` | UUID. |
| `revision` | Integer positif; harus revisi terbaru. |
| `content_hash` | SHA-256 lowercase 64 karakter untuk konten sanitized. |
| `status` | Wajib `VERIFIED_EVIDENCE`. |
| `title` | 1 sampai 200 karakter. |
| `verified_claim` | Klaim faktual yang diverifikasi moderator, 1 sampai 500 karakter. |
| `stance` | Salah satu `SUPPORTS`, `REFUTES`, atau `CONTEXT`. |
| `evidence_summary` | Ringkasan alasan moderasi yang sanitized, 1 sampai 800 karakter. |
| `redacted_text` | Konten sanitized, 1 sampai 4.000 karakter saat dikirim ke WaspadAI. |
| `published_at`, `verified_at` | RFC 3339 UTC. |
| `sources` | 1 sampai 3 sumber publik yang direview moderator. |

Field `sources[]`:

| Field | Aturan |
| --- | --- |
| `url` | URL HTTP(S) publik, maksimal 2.048 karakter. |
| `title` | Wajib, 1 sampai 200 karakter. |
| `publisher` | Opsional, maksimal 160 karakter. |
| `published_at` | Opsional, RFC 3339 UTC jika diketahui. |

Makna `stance`:

| Nilai | Arti |
| --- | --- |
| `SUPPORTS` | Evidence community mendukung klaim yang sedang diperiksa. |
| `REFUTES` | Evidence community membantah klaim yang sedang diperiksa. |
| `CONTEXT` | Evidence community memberi konteks relevan, tetapi tidak cukup untuk mendukung atau membantah langsung. |

Jika Product Backend tidak dapat menentukan `stance`, record tidak boleh
dikirim sebagai evidence decisive. Gunakan `CONTEXT` hanya jika moderator memang
menetapkannya sebagai konteks relevan.

## 13. Eligibility Community Evidence

Product Backend hanya boleh mengirim record yang lulus semua gate berikut dalam
satu snapshot database yang konsisten:

1. `community_posts.status = 'VERIFIED_EVIDENCE'`;
2. `community_posts.withdrawn_at IS NULL`;
3. `community_posts.verified_at IS NOT NULL`;
4. parent `verification_cases.community_state = 'VERIFIED_EVIDENCE'`;
5. `verification_cases.deleted_at IS NULL`;
6. `verification_cases.retention_expires_at > now()`;
7. `verification_contribution_id` tidak `null`;
8. contribution berstatus `VERIFIED`;
9. `contributions.verified_at IS NOT NULL`;
10. `contributions.retracted_at IS NULL`;
11. keputusan moderasi efektif terbaru memiliki `action = 'VERIFY'`;
12. keputusan moderasi efektif terbaru memiliki `new_status = 'VERIFIED'`;
13. keputusan moderasi efektif terbaru memiliki `allow_rag = true`;
14. keputusan tersebut berlaku untuk revision/content yang sedang diproyeksikan;
15. consent aktif `COMMUNITY_PUBLICATION` tersedia;
16. consent aktif `RAG_REUSE` tersedia;
17. kedua consent dimiliki owner post dan mengarah ke case/contribution/preview
    yang menghasilkan post;
18. `content_hash` consent cocok dengan `community_posts.content_hash`;
19. consent belum dicabut dan belum expired;
20. `revision` adalah revisi terbaru;
21. `content_hash` cocok dengan konten sanitized yang dikirim;
22. minimal satu source yang dikirim tercantum dalam evidence moderasi efektif;
23. payload tidak mengandung PII, signed URL privat, path Storage, atau data raw.

Jika satu gate tidak dapat dipastikan, default-nya adalah exclude.

`PUBLISHED_UNVERIFIED` boleh tampil di feed Product, tetapi tidak boleh dikirim
ke WaspadAI sebagai factual evidence. Vote, jumlah vote, dan verdict AI lama
tidak boleh dipakai sebagai evidence.

## 14. Data Yang Dilarang Dikirim Ke WaspadAI

Product Backend tidak boleh mengirim:

- row database mentah atau hasil `SELECT *`;
- `owner_id`, `user_id`, email, nomor telepon, identitas moderator, atau
  identitas voter;
- consent ID, isi audit consent, atau metadata internal consent;
- vote, jumlah vote, atau rasio vote;
- screenshot asli, path Storage privat, bucket, object path, atau signed URL
  privat;
- hasil/verdict AI lama sebagai evidence;
- post `PRIVATE`, `PUBLISHED_UNVERIFIED`, atau `WITHDRAWN`;
- contribution yang belum diverifikasi atau sudah diretract;
- moderation reason mentah, audit log, outbox payload mentah, dan credential
  database.

## 15. Status Implementasi WaspadAI

Saat dokumen ini dibuat:

- endpoint WaspadAI text dan image sudah ada;
- endpoint internal WaspadAI memakai `X-Waspadai-API-Key`;
- `output_mode=BOTH` sudah didukung;
- `official_referral` tersedia pada semua response sukses WaspadAI dan tidak
  berisi URL/nomor/hotline; aplikasi pemanggil wajib melakukan mapping sendiri;
- `community_evidence` dan `community_evidence_json` sudah didukung pada
  endpoint internal;
- WaspadAI tidak mengakses database komunitas, Supabase, Storage, vote, atau
  history; semua community evidence harus dikirim sebagai DTO sanitized dari
  Product Backend;
- community evidence dipakai sebagai request-scoped evidence, bukan corpus RAG
  permanen.

Penambahan community evidence tidak boleh menambah call Groq baru. Payload
community digabungkan ke evidence yang sudah dipakai oleh verifier pada call AI
yang sama.

## 16. Checklist Kotlin

- Login Supabase harus aktif sebelum fitur AI bisa dipakai.
- Kirim Bearer token hanya ke Product Backend.
- Jangan panggil WaspadAI langsung dari Android.
- Jangan menyimpan service key atau `X-Waspadai-API-Key` di Android.
- Gunakan JSON untuk teks dan multipart untuk screenshot.
- Jangan mengirim `output_mode`.
- Jangan menyusun `community_evidence` di Android.
- Tampilkan preview/crop sebelum upload screenshot.
- Timeout pemeriksaan AI: 150 detik.
- Retry `401` paling banyak satu kali setelah refresh session.
- Kirim `Idempotency-Key` untuk setiap pemeriksaan.
- Tampilkan naratif lebih dulu, lalu detail bertingkat.
- Ambil jawaban utama dari `result.presentation.narrative.text`.
- Gunakan `result.official_referral` untuk menampilkan CTA kanal resmi bila
  statusnya `RECOMMENDED` atau `URGENT`.

## 17. Checklist Product Backend

- Validasi Supabase token dan ambil `sub` sebagai `user_id`.
- Kelola history, Storage, community, vote, consent, dan moderation di Product
  Backend.
- Simpan `X-Waspadai-API-Key` hanya di environment server.
- Panggil WaspadAI melalui endpoint internal.
- Selalu minta `output_mode=BOTH`.
- Teruskan `page_context` jika dikirim Android.
- Kirim image sebagai multipart binary.
- Kirim `community_evidence=[]` jika tidak ada record eligible.
- Terapkan semua eligibility gate sebelum mengirim community evidence.
- Kirim hanya DTO sanitized Bagian 12.
- Jangan gunakan vote atau hasil AI lama sebagai evidence.
- Kirim community evidence hanya ke endpoint internal WaspadAI; endpoint publik
  tidak menerima field tersebut.
- Jangan teruskan URL referral dari WaspadAI karena WaspadAI tidak mengirim URL
  tersebut; lakukan mapping route resmi di Product Backend/mobile.
