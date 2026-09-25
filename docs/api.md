# WaspadAI API

Base URL production:

```text
https://waspadai.shafwan.digital
```

WaspadAI memiliki dua kelompok endpoint:

- `/api/v1/*` dipakai frontend publik WaspadAI.
- `/api/internal/v1/*` dipakai integrasi server-to-server dan wajib memakai `X-Waspadai-API-Key`.

Kontrak untuk aplikasi Android berada di
[`android-api-contract.md`](android-api-contract.md). Untuk MVP saat ini,
Android/Kotlin memanggil Product Backend aplikasi, bukan WaspadAI langsung.
Product Backend memvalidasi login Supabase, mengelola database/history/community,
lalu memanggil endpoint internal WaspadAI secara server-to-server.

Health check umum:

```bash
curl https://waspadai.shafwan.digital/api/health
```

## Endpoint

| Method | Path | Auth | Fungsi |
| --- | --- | --- | --- |
| `GET` | `/api/health` | Tidak | Health backend utama |
| `POST` | `/api/v1/verify/text` | Tidak | Verifikasi teks untuk website demo anonim |
| `POST` | `/api/v1/verify/image` | Tidak | Verifikasi gambar untuk website demo anonim |
| `POST` | `/api/internal/v1/verify/text` | `X-Waspadai-API-Key` | Verifikasi teks dari service lain |
| `POST` | `/api/internal/v1/verify/image` | `X-Waspadai-API-Key` | Verifikasi gambar dari service lain |

## Mode output

Endpoint verifikasi mendukung tiga nilai `output_mode`:

| Mode | Kegunaan |
| --- | --- |
| `STRUCTURED` | Default. Mengembalikan hasil poin-poin seperti verdict, alasan, bukti, sumber, dan tindakan. |
| `NARRATIVE` | Menambahkan `presentation.narrative` berisi penjelasan berbentuk teks natural seperti jawaban chatbot. |
| `BOTH` | Mengembalikan structured fields dan naratif sekaligus, cocok untuk frontend yang punya toggle tampilan tanpa request ulang. |

Mode naratif tidak menambah panggilan Groq. Teks naratif disusun secara lokal
dari hasil verifikasi kanonik yang sudah ada, sehingga verdict, risiko, bukti,
uncertainty, dan rekomendasi tetap sama dengan mode structured.

Mode naratif tidak mengulang daftar bukti, nama sumber, atau link sumber.
Client tetap menerima `evidence` dan `sources` pada response yang sama, lalu
menampilkannya sebagai detail bertingkat bila dibutuhkan.

Untuk menjaga hasil tetap ramah dibaca, mode naratif tidak selalu menampilkan
tingkat risiko. Risiko `LOW` dan `MEDIUM` tidak otomatis disebutkan di teks
naratif, sedangkan `HIGH` dan `CRITICAL` selalu muncul sebagai peringatan
eksplisit. Jika verdict `UNVERIFIED`, naratif wajib memakai bahasa belum final
dan tidak boleh terdengar seperti klaim sudah terbukti salah atau benar.

Pada JSON request teks, kirim `output_mode` di body. Pada multipart request
gambar, kirim `output_mode` sebagai form field.

## Environment variables

```env
WASPADAI_API_KEYS=key_project_pertama,key_project_kedua
```

Jangan menaruh internal API key di repository, log publik, aplikasi Android,
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

Pada endpoint image publik dan internal, gambar yang valid secara file tetapi
tidak memuat klaim, teks, URL, pesan, dokumen, poster, atau konteks yang bisa
diverifikasi tetap mengembalikan `200 COMPLETED`. Responsnya memakai
`verdict=UNVERIFIED`, `risk_level=LOW`, `requires_human_review=false`,
`evidence=[]`, `sources=[]`, `why=[]`, `recommended_actions=[]`,
`uncertainty=""`, `official_referral.status=NOT_REQUIRED`, dan headline
`Gambar tidak memuat klaim yang bisa diperiksa`.
Ini bukan error input; UI sebaiknya hanya menampilkan headline dan
`presentation.narrative.paragraphs`. Untuk kondisi ini, jangan tampilkan section
analisis normal seperti "Mengapa berisiko", "Tindakan yang disarankan",
"Status Risiko", atau "Ketidakpastian".

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
    "output_mode": "BOTH",
    "community_evidence": [],
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
  -F "question=Tolong cek apakah pesan pada gambar ini penipuan atau bukan" \
  -F "output_mode=BOTH" \
  -F "community_evidence_json=[]"
```

## Community evidence internal

`community_evidence` hanya diterima pada endpoint internal. WaspadAI tidak
mengakses database, Supabase, Storage, history, vote, atau moderation log milik
aplikasi lain. Product Backend harus memilih record community yang eligible,
membersihkan PII, lalu mengirim DTO final yang sudah sanitized.

Pada request teks, kirim field JSON `community_evidence`. Pada request gambar,
kirim field multipart `community_evidence_json` berisi JSON array yang sama.
Jika tidak ada record eligible, kirim array kosong.

Ringkasan batas:

| Field | Aturan |
| --- | --- |
| Record per request | Maksimal 5 |
| Source per record | 1 sampai 3 sumber publik |
| Total payload community | Maksimal 30 KB |
| `redacted_text` | Opsional, maksimal 4.000 karakter |
| `status` | Wajib `VERIFIED_EVIDENCE` |
| `stance` | `SUPPORTS`, `REFUTES`, atau `CONTEXT` |

Community evidence dipakai sebagai request-scoped evidence pada pipeline yang
sama. Ia tidak menambah panggilan Groq baru dan tidak disimpan sebagai corpus RAG
permanen. Agar tidak menggelembungkan keputusan, evidence yang seluruhnya hanya
berasal dari community tetap dibatasi di bawah threshold verdict final; community
baru dapat membantu keputusan decisive jika selaras dengan bukti non-community
yang relevan.

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
| `official_referral` | Instruksi terstruktur untuk Product Backend/mobile agar mengarahkan pengguna ke kanal resmi yang dipetakan di sisi aplikasi pemanggil |
| `presentation.requested_mode` | Mode output yang diminta client: `STRUCTURED`, `NARRATIVE`, atau `BOTH` |
| `presentation.narrative` | Teks naratif lokal; bernilai `null` jika mode `STRUCTURED` |

Catatan keputusan: `verdict`, `risk_level`, `evidence_sufficiency`, dan
`requires_human_review` adalah sumbu yang berbeda. Untuk kasus faktual non-scam,
bukti di bawah threshold membuat response menjadi `UNVERIFIED` dan
`requires_human_review=true`. Risiko `MEDIUM` tetap tersedia di JSON, tetapi mode
naratif hanya menampilkan peringatan eksplisit untuk `HIGH` dan `CRITICAL`.

`official_referral` juga merupakan sumbu terpisah. Field ini tidak mengubah
truth verdict, tidak mengganti `requires_human_review`, dan tidak berisi URL,
nomor telepon, hotline, OTP, nomor rekening, atau PII. WaspadAI hanya mengirim
`route_type`, `priority`, dan alasan singkat; Product Backend/mobile harus
memetakan route tersebut ke direktori kanal resmi yang sudah diverifikasi.

Nilai `official_referral.status`:

| Status | Arti |
| --- | --- |
| `NOT_REQUIRED` | Tidak ada referral resmi khusus yang perlu ditampilkan. |
| `RECOMMENDED` | Ada sinyal scam/impersonation berisiko tinggi sebelum user bertindak; tampilkan verifikasi kanal resmi sebagai pencegahan. |
| `URGENT` | User sudah melakukan tindakan sensitif seperti transfer, memasukkan kredensial, membagikan OTP, memasang APK, memberi remote access, atau kehilangan akun; arahkan ke alur recovery resmi. |

Nilai `official_referral.mode` adalah `PREVENTION`, `RECOVERY`, atau `null`
jika `status=NOT_REQUIRED`. Route yang mungkin dikirim: `OFFICIAL_INSTITUTION`,
`ACCOUNT_PROVIDER`, `FINANCIAL_PROVIDER`, `FINANCIAL_SCAM_REPORTING`,
`PLATFORM_REPORTING`, dan `DEVICE_RECOVERY`.

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
  "requires_human_review": false,
  "official_referral": {"status": "NOT_REQUIRED", "mode": null, "reason_codes": [], "summary": null, "routes": []}
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
  "requires_human_review": false,
  "official_referral": {"status": "NOT_REQUIRED", "mode": null, "reason_codes": [], "summary": null, "routes": []}
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
  "requires_human_review": true,
  "official_referral": {"status": "NOT_REQUIRED", "mode": null, "reason_codes": [], "summary": null, "routes": []}
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
  "requires_human_review": false,
  "official_referral": {
    "status": "RECOMMENDED",
    "mode": "PREVENTION",
    "reason_codes": ["POSSIBLE_IMPERSONATION", "SECRET_REQUEST"],
    "summary": "Ada sinyal penipuan atau impersonasi; verifikasi hanya melalui kanal resmi.",
    "routes": [
      {"route_type": "FINANCIAL_PROVIDER", "priority": "PRIMARY", "reason": "Verifikasi instruksi pembayaran atau akun melalui penyedia finansial resmi."},
      {"route_type": "PLATFORM_REPORTING", "priority": "SECONDARY", "reason": "Laporkan akun atau pesan mencurigakan melalui fitur pelaporan platform."}
    ]
  }
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
  "requires_human_review": true,
  "official_referral": {
    "status": "URGENT",
    "mode": "RECOVERY",
    "reason_codes": ["USER_ALREADY_ACTED:PAYMENT_SENT"],
    "summary": "Pengguna sudah melakukan tindakan sensitif; arahkan ke kanal pemulihan resmi.",
    "routes": [
      {"route_type": "FINANCIAL_PROVIDER", "priority": "PRIMARY", "reason": "Laporkan transaksi ke bank atau penyedia jasa pembayaran resmi."},
      {"route_type": "FINANCIAL_SCAM_REPORTING", "priority": "SECONDARY", "reason": "Gunakan jalur pelaporan penipuan finansial resmi setelah bukti disiapkan."}
    ]
  }
}
```

Respons error WaspadAI:

```json
{
  "detail": "API key internal tidak valid."
}
```

FastAPI aplikasi yang dikonsumsi Android memakai error envelope stabil yang
berbeda. Kontraknya dijelaskan di
[`android-api-contract.md`](android-api-contract.md#10-error-envelope).
