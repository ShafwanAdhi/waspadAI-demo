# WaspadAI API

Base URL production:

```text
https://waspadai.shafwan.digital
```

WaspadAI menyediakan dua kelompok endpoint:

- `/api/v1/*` dipakai oleh frontend publik WaspadAI.
- `/api/internal/v1/*` dipakai project lain secara server-to-server dan wajib
  mengirim API key internal.

Health check tetap terbuka agar mudah dipakai monitoring:

```bash
curl https://waspadai.shafwan.digital/api/health
```

## Konfigurasi API key internal

Tambahkan satu atau beberapa key di `apps/api/.env`:

```env
WASPADAI_API_KEYS=key_project_pertama,key_project_kedua
```

Gunakan key panjang yang acak. Jangan menaruh key ini di frontend browser,
repository, GitHub Actions log, atau variabel `NEXT_PUBLIC_*`.

Header yang wajib dikirim:

```http
X-Waspadai-API-Key: key_project_pertama
```

API key ini dimaksudkan untuk integrasi server-to-server. Jika project lain
berupa website, panggil WaspadAI dari backend project tersebut, bukan langsung
dari browser.

## Endpoint

| Method | Path | Auth | Fungsi |
| --- | --- | --- | --- |
| `GET` | `/api/health` | Tidak | Cek status service, RAG, OCR, dan web search |
| `POST` | `/api/internal/v1/verify/text` | Ya | Verifikasi teks, berita, pesan, atau tautan |
| `POST` | `/api/internal/v1/verify/image` | Ya | Verifikasi gambar/screenshot pesan atau klaim |

## Batas input

| Input | Aturan |
| --- | --- |
| Panjang teks | Minimal 10 karakter, maksimal 25.000 karakter |
| Ukuran gambar | Maksimal 8 MB |
| Dimensi gambar | Minimal 64x64 piksel, maksimal 6000x6000 piksel, dan maksimal 30.000.000 piksel total |
| Format gambar | `JPEG`, `PNG`, atau `WEBP` |
| Pertanyaan teks | Opsional, maksimal 500 karakter |
| Pertanyaan gambar | Opsional, maksimal 500 karakter |
| Teks hanya URL | URL publik diterima sebagai `URL_ONLY`; query string/fragment dibuang; URL privat seperti localhost/IP internal ditolak |

## Verifikasi teks

```bash
curl -X POST "https://waspadai.shafwan.digital/api/internal/v1/verify/text" \
  -H "Content-Type: application/json" \
  -H "X-Waspadai-API-Key: key_project_pertama" \
  -d '{
    "text": "Selamat, Anda mendapat bantuan Rp5 juta. Klik link berikut untuk klaim hadiah.",
    "question": "Apakah isi teks ini benar dan aman ditindaklanjuti?",
    "sender_context": "UNKNOWN_NUMBER"
  }'
```

Field request:

| Field | Tipe | Wajib | Keterangan |
| --- | --- | --- | --- |
| `text` | string | Ya | Teks yang ingin diperiksa |
| `question` | string | Tidak | Pertanyaan pemeriksaan; default dipakai jika kosong |
| `source_url` | string/null | Tidak | URL sumber awal jika ada |
| `sender_context` | string | Tidak | `UNKNOWN`, `UNKNOWN_NUMBER`, `KNOWN_CONTACT`, `FORWARDED`, atau `SOCIAL_MEDIA` |

## Verifikasi gambar

```bash
curl -X POST "https://waspadai.shafwan.digital/api/internal/v1/verify/image" \
  -H "X-Waspadai-API-Key: key_project_pertama" \
  -F "image=@contoh.png" \
  -F "question=Tolong cek apakah pesan pada gambar ini penipuan atau bukan"
```

Field multipart:

| Field | Tipe | Wajib | Keterangan |
| --- | --- | --- | --- |
| `image` | file | Ya | Gambar `PNG`, `JPEG`, atau `WEBP`, maksimal sesuai konfigurasi backend |
| `question` | string | Tidak | Pertanyaan pemeriksaan, maksimal 500 karakter |

## Response

Response internal menggunakan schema yang sama dengan frontend: verdict,
risk level, dimensi pemeriksaan, bukti, kecukupan bukti, rekomendasi tindakan,
source, rulebook trace, dan pipeline stage.

Field response yang paling penting untuk integrasi:

| Field | Keterangan |
| --- | --- |
| `request_id` | ID request untuk debugging dan pelacakan |
| `verdict` | Kesimpulan utama: `SUPPORTED`, `REFUTED`, `MISLEADING`, `PARTLY_TRUE`, `OUTDATED`, `UNVERIFIED`, `SATIRE`, atau `OPINION` |
| `risk_level` | Risiko tindakan: `LOW`, `MEDIUM`, `HIGH`, `CRITICAL`, atau `UNKNOWN` |
| `headline` | Ringkasan singkat hasil pemeriksaan |
| `what_checked` | Klaim utama yang diperiksa |
| `why` | Alasan penting di balik keputusan |
| `evidence_sufficiency_label` | Keterangan kecukupan bukti |
| `evidence` | Bukti yang dipakai untuk menilai klaim |
| `sources` | Daftar sumber yang bisa ditampilkan ke pengguna |
| `recommended_actions` | Saran tindakan untuk pengguna |
| `requires_human_review` | `true` jika bukti belum cukup atau kasus perlu dicek manual |

Contoh pola penggunaan di backend JavaScript/TypeScript:

```ts
const response = await fetch("https://waspadai.shafwan.digital/api/internal/v1/verify/text", {
  method: "POST",
  headers: {
    "Content-Type": "application/json",
    "X-Waspadai-API-Key": process.env.WASPADAI_API_KEY!,
  },
  body: JSON.stringify({
    text: "Isi pesan yang ingin dicek",
    sender_context: "UNKNOWN_NUMBER",
  }),
});

if (!response.ok) {
  throw new Error(`WaspadAI API failed: ${response.status}`);
}

const result = await response.json();
```

## Error umum

| Status | Arti |
| --- | --- |
| `401` | API key tidak dikirim atau tidak valid |
| `413` | Teks/gambar terlalu besar |
| `415` | File bukan gambar yang didukung |
| `422` | Input tidak valid |
| `429` | Rate limit provider AI sedang tercapai |
| `502` | Pipeline gagal pada layanan eksternal |
| `503` | Konfigurasi backend belum lengkap |

Jika API key tidak dikirim atau salah, endpoint internal mengembalikan `401`.
Jika `WASPADAI_API_KEYS` belum dikonfigurasi, endpoint internal mengembalikan
`503`.

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
  "evidence": [
    {
      "publisher": "Olympics",
      "title": "Paris 2024 opening ceremony information",
      "url": "https://olympics.com/example",
      "stance": "SUPPORTS",
      "verification_status": "VERIFIED"
    }
  ],
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
  "evidence": [
    {
      "publisher": "FIFA",
      "title": "ASEAN Cup information",
      "url": "https://www.fifa.com/example",
      "stance": "REFUTES",
      "verification_status": "VERIFIED"
    }
  ],
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
  "evidence": [
    {
      "publisher": "OJK",
      "title": "Peringatan penipuan permintaan OTP",
      "url": "https://ojk.go.id/example",
      "stance": "CONTEXT",
      "verification_status": "VERIFIED"
    }
  ],
  "sources": [{"publisher": "OJK", "title": "Peringatan penipuan permintaan OTP", "url": "https://ojk.go.id/example"}],
  "recommended_actions": [{"title": "Jangan kirim OTP", "detail": "Putus komunikasi dan hubungi kanal resmi lembaga terkait."}],
  "requires_human_review": false
}
```

requires_human_review true:

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

Respons error:

```json
{
  "detail": "Header X-Waspadai-API-Key wajib diisi."
}
```
