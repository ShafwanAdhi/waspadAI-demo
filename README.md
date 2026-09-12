# WaspadAI

WaspadAI adalah aplikasi pemeriksaan informasi berbasis bukti untuk teks dan gambar. Repository ini berbentuk **monorepo**: frontend Next.js menyajikan pengalaman pengguna, sedangkan backend FastAPI menjalankan pipeline rulebook, perencanaan pemeriksaan, pencarian bukti, dan verifikasi.

## Struktur repository

```text
apps/
  api/                  FastAPI, pipeline AI/RAG, rulebook, dan pengujian
  web/                  Next.js, tampilan publik, dan client kontrak API
contracts/
  openapi.json          Kontrak API yang dihasilkan dari FastAPI
docs/                   Konteks bisnis, arsitektur, integrasi, dan deployment
infrastructure/nginx/   Reverse proxy untuk deployment
compose.yaml            Stack produksi lokal/VPS
```

Hasil pemeriksaan memakai susunan bertingkat: ringkasan putusan dan risiko muncul terlebih dahulu, disusul alasan, kecukupan bukti, bukti dan sumber, tindakan yang disarankan, lalu detail ketidakpastian. Trace pipeline dan data tuning hanya tersedia pada halaman debug lokal, bukan pada hasil publik.

## Menjalankan secara lokal

Prasyarat: Python 3.11+, Node.js 22+, dan Tesseract opsional untuk OCR lokal.

Terminal pertama:

```powershell
cd apps\api
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
uvicorn app.main:app --reload --port 8001
```

Terminal kedua:

```powershell
cd apps\web
npm install
if (-not (Test-Path .env.local)) { Copy-Item .env.example .env.local }
npm run dev
```

Buka `http://127.0.0.1:3000`. Dokumentasi API tersedia di `http://127.0.0.1:8001/api/docs`; halaman trace lokal tersedia di `http://127.0.0.1:8001/debug` jika debug diaktifkan.

Kredensial Groq dan Tavily hanya disimpan di `apps/api/.env`. Jangan membuat variabel browser untuk API key atau memasukkan secret ke frontend.

## Pemeriksaan kualitas

```powershell
cd apps\api
python -m pytest -q

cd ..\web
npm run lint
npm run typecheck
npm run build
```

Jika skema respons FastAPI berubah, sinkronkan kontrak frontend:

```powershell
cd apps\api
python scripts\export_openapi.py

cd ..\web
npm run api:types
```

## Deployment

Stack container dapat dijalankan dari root repository:

```powershell
if (-not (Test-Path apps\api\.env)) { Copy-Item apps\api\.env.example apps\api\.env }
docker compose up --build -d
```

Secara default situs tersedia pada port `8080`, bukan `8000`. Lihat [panduan deployment](docs/deployment.md) dan [kontrak integrasi](docs/integration.md) sebelum memasang domain dan HTTPS.
