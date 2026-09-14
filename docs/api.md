# WaspadAI API

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
repository, atau variabel `NEXT_PUBLIC_*`.

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

## Verifikasi gambar

```bash
curl -X POST "https://waspadai.shafwan.digital/api/internal/v1/verify/image" \
  -H "X-Waspadai-API-Key: key_project_pertama" \
  -F "image=@contoh.png" \
  -F "question=Tolong cek apakah pesan pada gambar ini penipuan atau bukan"
```

## Response

Response internal menggunakan schema yang sama dengan frontend: verdict,
risk level, dimensi pemeriksaan, bukti, kecukupan bukti, rekomendasi tindakan,
source, rulebook trace, dan pipeline stage.

Jika API key tidak dikirim atau salah, endpoint internal mengembalikan `401`.
Jika `WASPADAI_API_KEYS` belum dikonfigurasi, endpoint internal mengembalikan
`503`.
