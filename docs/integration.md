# Integrasi Frontend dan Backend WaspadAI

Status: implemented, 2026-09-11.

## Batas tanggung jawab

WaspadAI menggunakan modular monolith. `apps/api` menjalankan seluruh orkestrasi pemeriksaan dalam satu aplikasi FastAPI, sedangkan Groq dan sumber pencarian dipanggil sebagai layanan eksternal. `apps/web` hanya menangani input, status proses, error yang dapat ditindaklanjuti, dan presentasi hasil.

Frontend tidak menyimpan atau menerima API key Groq. Browser selalu mengirim permintaan ke path same-origin `/api/...`; Next.js meneruskannya ke FastAPI ketika development dan Nginx melakukannya ketika deployment.

## Alur input

### Teks

1. Pengguna menempel berita, pesan, caption, atau klaim.
2. Frontend mengirim JSON ke `POST /api/v1/verify/text`.
3. FastAPI memvalidasi dan menormalisasi teks, menyaring PII/URL, lalu meneruskannya ke pipeline bersama.

### Gambar

1. Pengguna memilih JPG, PNG, atau WebP hingga 8 MB dan dapat menambahkan pertanyaan/konteks.
2. Frontend mengirim multipart form ke `POST /api/v1/verify/image`.
3. FastAPI memvalidasi file, menjalankan ekstraksi gambar/OCR, menyaring PII, lalu meneruskannya ke pipeline yang sama dengan input teks.

Keduanya menghasilkan kontrak `VerificationResponse` yang sama. Perbedaan modality hanya terjadi sebelum `CaseContext`; rulebook, planner, evidence retrieval, sufficiency, guardrail, dan penyajian hasil tetap setara.

Frontend mengirim `output_mode=BOTH` untuk request dari website. Backend tetap
menjalankan satu pipeline verifikasi yang sama, lalu menambahkan presentasi
naratif secara lokal dari hasil kanonik; toggle poin-poin/naratif di browser
tidak memicu request baru dan tidak menambah panggilan Groq.

Integrasi aplikasi production dapat mengirim community evidence hanya melalui
endpoint internal `/api/internal/v1/*`. Website demo tidak mengirim field ini.
WaspadAI memperlakukan data community sebagai evidence sementara per-request:
tidak ada akses database, tidak ada storage permanen, dan tidak ada panggilan
Groq tambahan.

## Susunan hasil bertingkat

Urutan publik sengaja berbeda dari urutan internal pipeline:

1. **Ringkasan input** — konteks singkat tentang materi yang diperiksa.
2. **Putusan dan tingkat risiko** — jawaban utama yang dapat dipindai cepat.
3. **Peringatan keselamatan** — muncul menonjol untuk risiko tinggi/kritis.
4. **Apa yang diperiksa dan alasannya** — klaim utama serta penjelasan ringkas.
5. **Kecukupan bukti** — label kekuatan bukti; skor teknis tersedia sebagai detail, bukan probabilitas kebenaran.
6. **Bukti dan sumber** — sikap bukti, status verifikasi, penerbit, tanggal, kutipan, dan tautan.
7. **Tindakan yang disarankan** — seluruh langkah aman dari backend, tanpa dipotong.
8. **Ketidakpastian dan review manusia** — batas pemeriksaan yang masih tersisa.
9. **Dimensi relevan** — factual status, autentisitas sumber/pengirim/channel, scam risk, dan autentisitas konten; nilai `NOT_APPLICABLE` disembunyikan.
10. **Disclaimer, privasi, dan request ID** — konteks audit ringan di bagian akhir.

`rulebook`, `pipeline`, detail model, dan trace tidak ditampilkan di hasil publik. Semua itu tetap tersedia di `/debug` pada development agar tuning tidak membebani atau membingungkan pengguna. `community_status` juga belum ditampilkan sampai alur consent dan review komunitas benar-benar tersedia.

Evidence dengan `source_type=community_verified` boleh tampil di daftar bukti
sebagai konteks komunitas terverifikasi. Namun, jika hanya community evidence
yang tersedia, backend tetap konservatif dan tidak mengunci verdict final tanpa
dukungan bukti non-community yang memadai.

Mode naratif menampilkan paragraf ringkas dari `presentation.narrative`, tetapi
tetap mempertahankan sumber utama agar pengguna masih bisa memeriksa asal bukti.
Mode poin-poin memakai field structured utama seperti sebelumnya.

Di mode naratif, risiko rendah dan sedang tidak otomatis disebutkan agar hasil
tidak terasa berlebihan untuk kasus biasa. Risiko tinggi dan kritis tetap
ditampilkan sebagai peringatan jelas, sementara kasus `UNVERIFIED` harus memakai
bahasa "belum dapat dipastikan" dan bukan "terbantahkan".

Backend menjalankan final consistency gate sebelum response dikirim. Gate ini
memastikan low sufficiency pada kasus faktual non-scam menjadi `UNVERIFIED`,
headline dan alasan tetap non-final, evidence ID tidak mengarah ke bukti yang
tidak ada, dan status `requires_human_review` konsisten dengan coverage bukti.

## Kontrak API

Pydantic schema di backend adalah sumber kebenaran. Kontrak OpenAPI dan tipe TypeScript disinkronkan dengan:

```powershell
cd apps\api
python scripts\export_openapi.py

cd ..\web
npm run api:types
```

Hasilnya adalah `contracts/openapi.json` dan `apps/web/src/lib/api-schema.ts`. Perubahan response backend dianggap belum selesai sampai kedua artefak ini diperbarui dan pemeriksaan tipe frontend lolos.

## Penanganan kegagalan

Frontend membedakan validasi input, respons API, rate limit, timeout, dan kegagalan jaringan. Header `Retry-After` diterjemahkan menjadi hitung mundur dan tombol coba lagi; frontend tidak mengulang permintaan berbayar secara otomatis. Jika pipeline berhasil namun bukti tidak cukup, backend tetap mengembalikan hasil konservatif `UNVERIFIED`, bukan error transport.
