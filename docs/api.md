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
