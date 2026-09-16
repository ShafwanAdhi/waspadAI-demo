# Kontrak API Android WaspadAI

Status dokumen: kontrak integrasi MVP untuk aplikasi Android/Kotlin yang memakai
API AI WaspadAI pada repository ini.

Keputusan integrasi saat ini: aplikasi Android boleh memanggil endpoint publik
WaspadAI secara langsung setelah pengguna login di aplikasi. Login Supabase
dipakai oleh aplikasi Android untuk mengontrol akses fitur, tetapi token
Supabase tidak divalidasi oleh API WaspadAI pada mode demo ini.

## 1. Batas sistem

Mode MVP yang dipakai sekarang:

```text
Android Kotlin -> Public WaspadAI API -> pipeline fact-check
        |
        +-- Supabase login diperiksa di aplikasi Android
```

Pada mode ini, Android memakai endpoint publik WaspadAI:

```text
GET  https://waspadai.shafwan.digital/api/health
POST https://waspadai.shafwan.digital/api/v1/verify/text
POST https://waspadai.shafwan.digital/api/v1/verify/image
```

Android tidak boleh memanggil endpoint internal WaspadAI:

```text
POST https://waspadai.shafwan.digital/api/internal/v1/verify/text
POST https://waspadai.shafwan.digital/api/internal/v1/verify/image
```

Endpoint internal membutuhkan `X-Waspadai-API-Key`. Secret itu hanya boleh
disimpan di server, bukan di aplikasi Android, karena APK dapat dibongkar.

Mode lanjutan yang dapat dipakai nanti:

```text
Android -> FastAPI aplikasi -> FastAPI WaspadAI -> pipeline fact-check
             |                    |
             |                    +-- stateless; tanpa akun dan history
             +-- Supabase Auth, history, Storage, komunitas, dan voting
```

Mode lanjutan diperlukan jika history, Storage, komunitas, voting, ownership,
dan moderasi ingin dikelola secara server-side. Pada mode itu Android memanggil
FastAPI aplikasi, sedangkan FastAPI aplikasi memanggil endpoint internal
WaspadAI menggunakan `X-Waspadai-API-Key`.

## 2. Base URL dan autentikasi

Base URL AI WaspadAI yang dipakai Android pada mode MVP:

```text
https://waspadai.shafwan.digital
```

Endpoint verifikasi yang dipakai Android:

```text
POST /api/v1/verify/text
POST /api/v1/verify/image
```

Sebelum memanggil endpoint tersebut, aplikasi Android harus memastikan pengguna
sudah login melalui Supabase. API WaspadAI mode demo tidak menerima dan tidak
memvalidasi header `Authorization`.

Jika nanti memakai FastAPI aplikasi terpisah, barulah setiap request Android
wajib mengirim access token sesi Supabase:

```http
Authorization: Bearer <supabase_access_token>
Accept: application/json
```

Pada mode lanjutan tersebut, FastAPI aplikasi harus:

1. mengambil Bearer token dari header `Authorization`;
2. memvalidasi token melalui `supabase.auth.get_user(access_token)` pada MVP;
3. menolak token tidak valid atau kedaluwarsa dengan HTTP `401`;
4. mengambil `sub` token sebagai `user_id` terpercaya;
5. menggunakan `user_id` tersebut untuk semua operasi history, Storage, vote,
   dan kepemilikan kasus.

Android tidak mengirim refresh token ke API aplikasi. Jika menerima `401` dari
FastAPI aplikasi, Android meminta Supabase SDK memperbarui session lalu
mengulang request paling banyak satu kali.

Untuk request pemeriksaan, Android sebaiknya mengirim UUID yang tetap sama saat
mengulang aksi yang sama:

```http
Idempotency-Key: <uuid-v4>
```

Pada mode MVP direct-to-WaspadAI, header ini belum diproses oleh WaspadAI dan
bersifat opsional. Pada mode lanjutan, header ini mencegah retry jaringan
menjalankan pipeline AI dua kali; backend aplikasi dapat menyimpan pasangan
`user_id + Idempotency-Key` secara singkat, misalnya 10 menit.

## 3. Karakteristik pemeriksaan

- Pemeriksaan bersifat synchronous: satu request menghasilkan satu respons.
- Timeout client yang disarankan adalah 120 detik.
- Chat bukan percakapan multi-turn; setiap pesan adalah pemeriksaan baru.
- Naratif menjadi tampilan utama.
- Bukti, sumber, tindakan, dan detail tetap dikirim sebagai data terstruktur
  untuk bagian UI yang dapat dibuka.
- Pada mode MVP, Android sebaiknya mengirim `output_mode=BOTH` agar mendapatkan
  hasil naratif dan data terstruktur dalam satu request.
- Pada mode lanjutan, backend aplikasi dapat selalu meminta `output_mode=BOTH`
  kepada WaspadAI sehingga Android tidak perlu mengelola mode output.

## 4. Pemeriksaan teks

```http
POST /api/v1/verify/text
Content-Type: application/json
```

Request:

```json
{
  "text": "Pesan mengaku dari bank dan meminta OTP agar akun tidak diblokir.",
  "question": "Apakah pesan ini aman?",
  "source_url": null,
  "sender_context": "UNKNOWN_NUMBER",
  "output_mode": "BOTH"
}
```

Field:

| Field | Wajib | Aturan |
| --- | --- | --- |
| `text` | Ya | 10-25.000 karakter setelah trim |
| `question` | Tidak | Maksimal 500 karakter; backend memakai pertanyaan default jika kosong |
| `source_url` | Tidak | URL publik maksimal 2.048 karakter |
| `sender_context` | Tidak | Default `UNKNOWN` |
| `output_mode` | Tidak | Gunakan `BOTH` agar response berisi naratif dan data terstruktur |

Nilai `sender_context`:

```text
NOT_APPLICABLE
UNKNOWN_NUMBER
KNOWN_CONTACT
FORWARDED
SOCIAL_MEDIA
UNKNOWN
```

Teks yang hanya berisi satu URL publik tetap valid. URL localhost, loopback,
private IP, dan URL internal harus ditolak.

## 5. Pemeriksaan screenshot

```http
POST /api/v1/verify/image
Content-Type: multipart/form-data
```

Multipart fields:

| Field | Wajib | Aturan |
| --- | --- | --- |
| `image` | Ya | File biner JPG, PNG, atau WEBP |
| `question` | Tidak | Maksimal 500 karakter |
| `output_mode` | Tidak | Gunakan `BOTH` agar response berisi naratif dan data terstruktur |

Batas gambar:

| Batas | Nilai |
| --- | --- |
| Ukuran file | Maksimal 8 MB |
| Dimensi minimal | 64 x 64 piksel |
| Dimensi maksimal | 6.000 x 6.000 piksel |
| Jumlah piksel | Maksimal 30.000.000 piksel |
| Format | JPEG/JPG, PNG, WEBP |

Android harus menggunakan alur berikut:

1. mengambil screenshot melalui flow capture/overlay Android;
2. menampilkan preview dan crop;
3. mengirim hasil crop sebagai file multipart, bukan Base64 dalam JSON;
4. mempertahankan layar loading sampai respons diterima atau timeout.

WEBP atau JPEG terkompresi disarankan untuk mengurangi waktu upload. Kompresi
tidak boleh membuat teks pada screenshot sulit dibaca.

## 6. Respons pemeriksaan

Pada mode MVP direct-to-WaspadAI, response dikembalikan langsung oleh API
WaspadAI. Tidak ada wrapper `result` dan tidak ada metadata `history` dari API
ini.

Contoh bentuk response yang perlu dibaca Android:

```json
{
  "request_id": "req_01kotlinexample",
  "status": "COMPLETED",
  "mode": "LIVE",
  "verdict": "UNVERIFIED",
  "risk_level": "MEDIUM",
  "headline": "Bukti belum cukup untuk memastikan klaim",
  "evidence_sufficiency": 0.42,
  "evidence_sufficiency_label": "Bukti belum cukup untuk memastikan klaim",
  "requires_human_review": true,
  "community_status": "ELIGIBLE_WITH_CONSENT",
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
    },
  },
  "disclaimer": "Fact-check adalah dukungan keputusan, bukan jaminan."
}
```

Android harus memakai `presentation.narrative.text` sebagai jawaban utama.
Bagian `evidence`, `sources`, `recommended_actions`, `uncertainty`, dan
`dimensions` ditampilkan secara bertingkat ketika pengguna membuka detail.

Jika nanti memakai FastAPI aplikasi terpisah, backend aplikasi boleh membungkus
hasil WaspadAI dengan metadata history:

```json
{
  "request_id": "req_01kotlinexample",
  "status": "COMPLETED",
  "history": {
    "saved": true,
    "case_id": "case_01example",
    "save_reason": "UNVERIFIED",
    "community_eligible": true,
    "community_state": "PRIVATE"
  },
  "result": {
    "verdict": "UNVERIFIED",
    "headline": "Bukti belum cukup untuk memastikan klaim"
  }
}
```

Aturan penyimpanan:

```text
saved = verdict == UNVERIFIED OR requires_human_review == true
```

Jika hasil sudah cukup tegas dan tidak memerlukan review:

```json
{
  "history": {
    "saved": false,
    "case_id": null,
    "save_reason": "NOT_REQUIRED",
    "community_eligible": false,
    "community_state": "NOT_AVAILABLE"
  }
}
```

Aturan penyimpanan ini hanya berlaku jika ada FastAPI aplikasi yang mengelola
history. API WaspadAI pada mode MVP direct tidak menyimpan history pengguna.

## 7. History pada mode lanjutan

Bagian ini belum disediakan oleh API WaspadAI mode demo. History dikelola oleh
FastAPI aplikasi jika nanti arsitektur lanjutan dipakai.

History hanya berisi kasus `UNVERIFIED` atau `requires_human_review=true`.

```http
GET /api/v1/history?limit=20&cursor=<opaque_cursor>
GET /api/v1/history/{case_id}
DELETE /api/v1/history/{case_id}
```

Daftar history mengembalikan ringkasan, bukan seluruh evidence:

```json
{
  "items": [
    {
      "case_id": "case_01example",
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

`GET /history/{case_id}` mengembalikan hasil lengkap dan signed URL sementara
untuk screenshot privat. Bucket Supabase Storage tidak boleh public.

Pengguna dapat menghapus history selama kasus belum menjadi
`VERIFIED_EVIDENCE`. Jika kasus sedang terlihat di komunitas, penghapusan juga
menarik kasus dari komunitas dan menghapus file turunan yang dipublikasikan.

## 8. Preview dan publikasi komunitas pada mode lanjutan

Bagian ini belum disediakan oleh API WaspadAI mode demo. Preview, redaksi final,
publikasi komunitas, dan consent dikelola oleh FastAPI aplikasi jika nanti
arsitektur lanjutan dipakai.

Kasus baru selalu privat. Tidak ada publikasi otomatis.

### Membuat preview redaksi

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

Preview dibuat dari screenshot yang sebelumnya sudah di-preview/crop oleh
pengguna. Backend melakukan redaksi PII lagi dan Android wajib menampilkan hasil
akhir tersebut sebelum meminta konfirmasi.

### Mengonfirmasi publikasi

```http
POST /api/v1/history/{case_id}/community
Content-Type: application/json
```

```json
{
  "preview_id": "preview_01example",
  "consent": true
}
```

`consent` harus bernilai `true`. Preview yang kedaluwarsa harus dibuat ulang.
Komunitas hanya melihat image hasil redaksi, klaim, hasil awal AI, dan agregat
vote. `user_id`, email, nomor telepon, serta path screenshot asli tidak pernah
dikirim ke client komunitas.

### Menarik kasus

```http
DELETE /api/v1/history/{case_id}/community
```

Pemilik dapat menarik kasus selama belum berstatus `VERIFIED_EVIDENCE`.

## 9. Community feed dan voting pada mode lanjutan

Bagian ini belum disediakan oleh API WaspadAI mode demo. Feed komunitas dan vote
dikelola oleh FastAPI aplikasi jika nanti arsitektur lanjutan dipakai.

```http
GET    /api/v1/community?limit=20&cursor=<opaque_cursor>
GET    /api/v1/community/{case_id}
PUT    /api/v1/community/{case_id}/vote
DELETE /api/v1/community/{case_id}/vote
```

Memberikan atau mengubah vote:

```json
{
  "vote": "DIDUKUNG"
}
```

Nilai vote yang valid hanya:

```text
DIDUKUNG
DIBANTAH
```

Response agregat:

```json
{
  "case_id": "case_01example",
  "user_vote": "DIDUKUNG",
  "counts": {
    "DIDUKUNG": 18,
    "DIBANTAH": 7
  }
}
```

Aturan vote:

- satu pengguna memiliki maksimal satu vote aktif per kasus;
- `PUT` membuat vote atau mengganti vote lama;
- `DELETE` membatalkan vote pengguna;
- pemilik kasus tidak boleh memberikan vote pada kasusnya sendiri;
- identitas voter tidak ditampilkan;
- vote adalah sinyal komunitas, bukan verdict faktual;
- jumlah vote tidak boleh otomatis menjadikan kasus evidence terverifikasi.

Hanya moderator/admin yang dapat menetapkan `VERIFIED_EVIDENCE` setelah menilai
sumber dan bukti. Endpoint moderasi tidak termasuk kontrak Android.

## 10. Error envelope

Pada mode MVP direct-to-WaspadAI, error mengikuti response FastAPI WaspadAI.
Contoh error validasi:

```json
{
  "detail": [
    {
      "type": "string_too_short",
      "loc": ["body", "text"],
      "msg": "String should have at least 10 characters"
    }
  ]
}
```

Jika nanti memakai FastAPI aplikasi terpisah, backend aplikasi sebaiknya
menyeragamkan error menjadi bentuk berikut:

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

Status dan tindakan Android:

| HTTP | Contoh code | Tindakan client |
| --- | --- | --- |
| `400` | `INVALID_REQUEST` | Tampilkan kesalahan input |
| `401` | `INVALID_ACCESS_TOKEN` | Hanya untuk mode backend aplikasi; refresh session lalu retry satu kali |
| `403` | `OWNER_CANNOT_VOTE`, `CASE_LOCKED` | Tampilkan alasan; jangan retry |
| `404` | `CASE_NOT_FOUND` | Kembali ke daftar sebelumnya |
| `409` | `PREVIEW_EXPIRED`, `CASE_ALREADY_VERIFIED` | Refresh data atau buat preview baru |
| `413` | `PAYLOAD_TOO_LARGE` | Minta pengguna mengompres/crop gambar |
| `415` | `UNSUPPORTED_MEDIA_TYPE` | Gunakan JPG, PNG, atau WEBP |
| `422` | `VALIDATION_ERROR` | Tampilkan pesan validasi field |
| `429` | `RATE_LIMITED` | Tunggu `retry_after_seconds` |
| `502` | `FACT_CHECK_UPSTREAM_FAILURE` | Tawarkan coba lagi |
| `503` | `SERVICE_UNAVAILABLE` | Tawarkan coba lagi nanti |

Android tidak boleh menampilkan stack trace atau exception internal kepada
pengguna. Pada mode direct, tampilkan pesan ramah berdasarkan HTTP status dan
simpan detail teknis hanya untuk log/debug.

## 11. Kontrak internal backend aplikasi ke WaspadAI

Bagian ini untuk tim backend, bukan tim Android.

```http
POST /api/internal/v1/verify/text
POST /api/internal/v1/verify/image
X-Waspadai-API-Key: <service_secret>
```

Backend aplikasi harus selalu meminta `output_mode=BOTH`, memakai timeout 120
detik, dan meneruskan file sebagai multipart tanpa Base64. Secret disimpan pada
environment backend dan WaspadAI.

Karena kedua FastAPI berada pada VPS yang sama tetapi berbeda repository,
hubungkan container melalui private Docker network. Endpoint internal WaspadAI
tidak perlu dipublikasikan sebagai rute internet khusus.

WaspadAI tidak memvalidasi Supabase token dan tidak menyimpan history. FastAPI
aplikasi adalah pemilik autentikasi, `user_id`, Supabase Database, Storage,
community state, vote, dan moderasi.

## 12. Checklist implementasi Kotlin

- Pastikan session Supabase aktif sebelum pengguna boleh memakai fitur cek AI.
- Untuk mode MVP direct, jangan kirim Bearer token ke WaspadAI.
- Jangan pernah mengirim `user_id` atau service key WaspadAI dari Android.
- Gunakan request JSON untuk teks dan multipart untuk screenshot.
- Kirim `output_mode=BOTH` pada request teks dan screenshot.
- Tampilkan preview/crop sebelum upload screenshot.
- Gunakan timeout 120 detik dan satu loading state.
- Refresh token dan retry paling banyak sekali ketika menerima `401` dari
  backend aplikasi; pada mode direct WaspadAI, `401` tidak menjadi alur normal.
- `Idempotency-Key` opsional pada mode direct; wajib dipertimbangkan jika nanti
  memakai backend aplikasi.
- Tampilkan naratif terlebih dahulu, lalu detail bertingkat.
- Pada mode direct, baca naratif dari `presentation.narrative.text`.
- Fitur history, community, signed URL screenshot, dan vote membutuhkan backend
  aplikasi terpisah; jangan menganggap field tersebut tersedia dari API
  WaspadAI direct.
