# WaspadAI API

Base URL production:

```text
https://waspadai.shafwan.digital
```

WaspadAI memiliki tiga kelompok endpoint:

- `/api/v1/*` dipakai frontend publik WaspadAI.
- `/api/internal/v1/*` dipakai integrasi server-to-server dan wajib memakai `X-Waspadai-API-Key`.
- `/api/extension/v1/*` dipakai Chrome extension dan memakai anonymous installation Bearer token.

Health check umum:

```bash
curl https://waspadai.shafwan.digital/api/health
```

## Endpoint

| Method | Path | Auth | Fungsi |
| --- | --- | --- | --- |
| `GET` | `/api/health` | Tidak | Health backend utama |
| `GET` | `/api/extension/v1/health` | Tidak | Health gateway extension tanpa detail sensitif |
| `POST` | `/api/internal/v1/verify/text` | `X-Waspadai-API-Key` | Verifikasi teks dari service lain |
| `POST` | `/api/internal/v1/verify/image` | `X-Waspadai-API-Key` | Verifikasi gambar dari service lain |
| `POST` | `/api/extension/v1/installations` | Tidak, rate limited per IP | Membuat anonymous installation token |
| `POST` | `/api/extension/v1/installations/refresh` | Bearer installation token | Merotasi token instalasi |
| `POST` | `/api/extension/v1/verify/text` | Bearer installation token | Verifikasi selected text/manual text |
| `POST` | `/api/extension/v1/verify/image` | Bearer installation token | Verifikasi gambar dari extension |

## Environment variables

```env
WASPADAI_API_KEYS=key_project_pertama,key_project_kedua
EXTENSION_INSTALLATION_STORE_PATH=runtime/extension_installations.json
EXTENSION_TOKEN_LIFETIME_DAYS=90
EXTENSION_TOKEN_OVERLAP_SECONDS=300
EXTENSION_REGISTRATION_IP_LIMIT_PER_HOUR=20
EXTENSION_TEXT_INSTALLATION_LIMIT_PER_MINUTE=10
EXTENSION_IMAGE_INSTALLATION_LIMIT_PER_MINUTE=4
EXTENSION_IP_VERIFY_LIMIT_PER_MINUTE=30
EXTENSION_CONCURRENT_REQUESTS_PER_INSTALLATION=2
EXTENSION_ALLOWED_ORIGINS=chrome-extension://extension_id_dev,chrome-extension://extension_id_prod
```

Jangan menaruh internal API key atau token instalasi di repository, log publik,
frontend browser, atau variabel `NEXT_PUBLIC_*`.

## Batas input

| Input | Aturan |
| --- | --- |
| Panjang teks | Minimal 10 karakter, maksimal 25.000 karakter |
| Ukuran gambar | Maksimal 8 MB |
| Dimensi gambar | Minimal 64x64 piksel, maksimal 6000x6000 piksel, dan maksimal 30.000.000 piksel total |
| Format gambar | `JPEG`, `PNG`, atau `WEBP` |
| Pertanyaan teks | Opsional, maksimal 500 karakter |
| Pertanyaan gambar | Opsional, maksimal 500 karakter |
| `page_context.title` | Opsional, maksimal 300 karakter |
| `page_context.before` | Opsional, maksimal 500 karakter |
| `page_context.after` | Opsional, maksimal 500 karakter |
| Teks hanya URL | URL publik diterima sebagai `URL_ONLY`; query string/fragment dibuang; URL privat seperti localhost/IP internal ditolak |

Jika `page_context` dikirim, minimal satu dari `title`, `before`, atau `after`
harus berisi nilai. `text` tetap menjadi klaim utama; `page_context` hanya
dipakai sebagai konteks pendukung selected text.

## Internal API

Header wajib:

```http
X-Waspadai-API-Key: key_project_pertama
```

Verifikasi teks:

```bash
curl -X POST "https://waspadai.shafwan.digital/api/internal/v1/verify/text" \
  -H "Content-Type: application/json" \
  -H "X-Waspadai-API-Key: key_project_pertama" \
  -d '{
    "text": "Selamat, Anda mendapat bantuan Rp5 juta. Klik link berikut untuk klaim hadiah.",
    "question": "Apakah isi teks ini benar dan aman ditindaklanjuti?",
    "sender_context": "UNKNOWN_NUMBER",
    "page_context": {
      "title": "Contoh halaman",
      "before": "Konteks sebelum teks pilihan.",
      "after": "Konteks setelah teks pilihan."
    }
  }'
```

Verifikasi gambar:

```bash
curl -X POST "https://waspadai.shafwan.digital/api/internal/v1/verify/image" \
  -H "X-Waspadai-API-Key: key_project_pertama" \
  -F "image=@contoh.png" \
  -F "question=Tolong cek apakah pesan pada gambar ini penipuan atau bukan"
```

## Chrome Extension API

Registration tidak meminta fingerprint, email, riwayat browsing, atau hardware
identifier. Server membuat `installation_id` dan token opaque; token yang
disimpan di server adalah hash.

Membuat instalasi:

```bash
curl -X POST "https://waspadai.shafwan.digital/api/extension/v1/installations" \
  -H "Content-Type: application/json" \
  -d '{"extension_version":"0.1.0"}'
```

Response `201 Created`:

```json
{
  "installation_id": "inst_01ab23cd45ef67ab89cd01ef",
  "installation_token": "opaque-server-issued-token",
  "token_type": "Bearer",
  "expires_at": "2026-12-31T00:00:00Z"
}
```

Refresh token:

```bash
curl -X POST "https://waspadai.shafwan.digital/api/extension/v1/installations/refresh" \
  -H "Authorization: Bearer INSTALLATION_TOKEN"
```

Token lama masih diterima selama overlap singkat sesuai
`EXTENSION_TOKEN_OVERLAP_SECONDS`, lalu tidak berlaku.

Verifikasi selected text:

```bash
curl -X POST "https://waspadai.shafwan.digital/api/extension/v1/verify/text" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer INSTALLATION_TOKEN" \
  -d '{
    "text": "Teks yang dipilih pengguna",
    "question": "Apakah informasi ini benar dan aman?",
    "source_url": "https://example.com/article",
    "sender_context": "UNKNOWN",
    "page_context": {
      "title": "Judul halaman",
      "before": "Konteks terbatas sebelum teks yang dipilih.",
      "after": "Konteks terbatas setelah teks yang dipilih."
    }
  }'
```

Verifikasi gambar:

```bash
curl -X POST "https://waspadai.shafwan.digital/api/extension/v1/verify/image" \
  -H "Authorization: Bearer INSTALLATION_TOKEN" \
  -F "image=@contoh.png" \
  -F "question=Tolong cek apakah pesan pada gambar ini penipuan atau bukan"
```

Response sukses extension tidak dibungkus `data` atau `result`; schema sama
dengan `VerificationResponse` production.

## Public error envelope extension

Semua error endpoint `/api/extension/v1/*` memakai envelope:

```json
{
  "error": {
    "code": "RATE_LIMITED",
    "message": "Batas verifikasi sementara tercapai.",
    "retry_after_seconds": 60,
    "request_id": "req_01ab23cd45ef"
  }
}
```

Kode error minimum:

| Code | Status |
| --- | --- |
| `INVALID_INSTALLATION_TOKEN` | `401` |
| `INSTALLATION_TOKEN_EXPIRED` | `401` |
| `INSTALLATION_BLOCKED` | `403` |
| `RATE_LIMITED` | `429` |
| `VALIDATION_ERROR` | `422` |
| `PAYLOAD_TOO_LARGE` | `413` |
| `UNSUPPORTED_MEDIA_TYPE` | `415` |
| `UPSTREAM_FAILURE` | `502` |
| `SERVICE_UNAVAILABLE` | `503` |

Response `429` juga mengirim header `Retry-After`.

## Field response penting

| Field | Keterangan |
| --- | --- |
| `request_id` | ID request untuk debugging dan pelacakan |
| `verdict` | `SUPPORTED`, `REFUTED`, `MISLEADING`, `PARTLY_TRUE`, `OUTDATED`, `UNVERIFIED`, `SATIRE`, atau `OPINION` |
| `risk_level` | `LOW`, `MEDIUM`, `HIGH`, `CRITICAL`, atau `UNKNOWN` |
| `headline` | Ringkasan singkat hasil pemeriksaan |
| `what_checked` | Klaim utama yang diperiksa |
| `why` | Alasan penting di balik keputusan |
| `evidence_sufficiency_label` | Keterangan kecukupan bukti |
| `evidence` | Bukti yang dipakai untuk menilai klaim |
| `sources` | Daftar sumber yang bisa ditampilkan ke pengguna |
| `recommended_actions` | Saran tindakan untuk pengguna |
| `requires_human_review` | `true` jika bukti belum cukup atau kasus perlu dicek manual |

## Contoh JSON response produksi

Contoh berikut dipadatkan untuk dokumentasi integrasi. Field penting yang perlu
dibaca client tetap sama dengan response production.

Klaim didukung:

```json
{
  "request_id": "req_supported_001",
  "status": "COMPLETED",
  "mode": "LIVE",
  "verdict": "SUPPORTED",
  "risk_level": "LOW",
  "headline": "Klaim utama didukung oleh sumber resmi.",
  "what_checked": ["Pembukaan Olimpiade Paris 2024 digelar dengan parade di Sungai Seine."],
  "why": ["Sumber resmi penyelenggara menjelaskan format parade di Sungai Seine."],
  "evidence_sufficiency": 0.86,
  "evidence_sufficiency_label": "Bukti cukup",
  "evidence": [{"publisher": "Olympics", "title": "Paris 2024 opening ceremony information", "url": "https://olympics.com/example", "stance": "SUPPORTS", "verification_status": "VERIFIED"}],
  "sources": [{"publisher": "Olympics", "title": "Paris 2024 opening ceremony information", "url": "https://olympics.com/example"}],
  "recommended_actions": [{"title": "Bagikan dengan konteks", "detail": "Sertakan sumber resmi saat meneruskan informasi."}],
  "requires_human_review": false
}
```

Klaim ditolak:

```json
{
  "request_id": "req_refuted_001",
  "status": "COMPLETED",
  "mode": "LIVE",
  "verdict": "REFUTED",
  "risk_level": "MEDIUM",
  "headline": "Klaim utama bertentangan dengan sumber yang lebih kuat.",
  "what_checked": ["Indonesia menjadi tuan rumah FIFA ASEAN Cup 2026."],
  "why": ["Tidak ditemukan turnamen resmi dengan nama tersebut pada sumber otoritatif."],
  "evidence_sufficiency": 0.78,
  "evidence_sufficiency_label": "Bukti cukup",
  "evidence": [{"publisher": "FIFA", "title": "ASEAN Cup information", "url": "https://www.fifa.com/example", "stance": "REFUTES", "verification_status": "VERIFIED"}],
  "sources": [{"publisher": "FIFA", "title": "ASEAN Cup information", "url": "https://www.fifa.com/example"}],
  "recommended_actions": [{"title": "Jangan teruskan klaim", "detail": "Tunggu konfirmasi dari sumber resmi sebelum membagikan."}],
  "requires_human_review": false
}
```

UNVERIFIED:

```json
{
  "request_id": "req_unverified_001",
  "status": "COMPLETED",
  "mode": "LIVE",
  "verdict": "UNVERIFIED",
  "risk_level": "UNKNOWN",
  "headline": "Bukti belum cukup untuk memastikan klaim.",
  "what_checked": ["Klaim viral tentang program baru yang belum menyebut sumber resmi."],
  "why": ["Sumber pembanding yang ditemukan belum cukup kuat atau belum langsung menjawab klaim."],
  "evidence_sufficiency": 0.34,
  "evidence_sufficiency_label": "Bukti belum cukup",
  "evidence": [],
  "sources": [],
  "recommended_actions": [{"title": "Tahan dulu", "detail": "Jangan jadikan informasi ini dasar keputusan penting."}],
  "requires_human_review": true
}
```

Risiko CRITICAL:

```json
{
  "request_id": "req_critical_001",
  "status": "COMPLETED",
  "mode": "LIVE",
  "verdict": "MISLEADING",
  "risk_level": "CRITICAL",
  "headline": "Pesan berisiko tinggi dan meminta tindakan sensitif.",
  "what_checked": ["Pesan mengaku dari bank dan meminta OTP agar akun tidak diblokir."],
  "why": ["Permintaan OTP dari pesan pribadi adalah indikator kuat upaya pengambilalihan akun."],
  "evidence_sufficiency": 0.72,
  "evidence_sufficiency_label": "Bukti risiko cukup",
  "evidence": [{"publisher": "OJK", "title": "Peringatan penipuan permintaan OTP", "url": "https://ojk.go.id/example", "stance": "CONTEXT", "verification_status": "VERIFIED"}],
  "sources": [{"publisher": "OJK", "title": "Peringatan penipuan permintaan OTP", "url": "https://ojk.go.id/example"}],
  "recommended_actions": [{"title": "Jangan kirim OTP", "detail": "Putus komunikasi dan hubungi kanal resmi lembaga terkait."}],
  "requires_human_review": false
}
```

Requires human review:

```json
{
  "request_id": "req_review_001",
  "status": "COMPLETED",
  "mode": "LIVE",
  "verdict": "UNVERIFIED",
  "risk_level": "MEDIUM",
  "headline": "Kasus perlu pemeriksaan manual.",
  "what_checked": ["Klaim lokal baru yang belum memiliki sumber pembanding memadai."],
  "why": ["Bukti yang tersedia belum cukup langsung dan ada konteks lokal yang perlu dikonfirmasi."],
  "evidence_sufficiency": 0.41,
  "evidence_sufficiency_label": "Perlu review manual",
  "evidence": [],
  "sources": [],
  "recommended_actions": [{"title": "Verifikasi ke pihak terkait", "detail": "Cari kanal resmi atau narasumber primer sebelum mengambil tindakan."}],
  "requires_human_review": true
}
```

Respons error extension:

```json
{
  "error": {
    "code": "INVALID_INSTALLATION_TOKEN",
    "message": "Header Authorization Bearer wajib diisi.",
    "request_id": "req_01ab23cd45ef"
  }
}
```
