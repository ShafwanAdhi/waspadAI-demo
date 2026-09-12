# Deployment WaspadAI ke VPS

## Topologi

```text
Internet -> HTTPS/domain -> Nginx -> Next.js :3000
                              |----> FastAPI :8001 (/api/*)
FastAPI -> Groq dan sumber bukti eksternal
```

Hanya Nginx yang dipublikasikan. FastAPI dan Next.js berada di jaringan internal Docker. Endpoint debug ditutup oleh Nginx dan juga otomatis nonaktif pada `APP_ENV=production`.

## Persiapan VPS

Pasang Docker Engine, Docker Compose plugin, Git, serta firewall. Buka hanya SSH, HTTP, dan HTTPS; jangan mengekspos port 3000 atau 8001 ke internet.

Clone repository lalu siapkan kredensial backend:

```bash
cp apps/api/.env.example apps/api/.env
nano apps/api/.env
```

Nilai minimum produksi:

```env
APP_ENV=production
GROQ_API_KEY=gsk_isi_kredensial_produksi
TAVILY_API_KEY=tvly-isi_kredensial_produksi
DEBUG_TRACE_ENABLED=false
```

File `.env` sudah diabaikan Git dan Docker build context. Jangan menaruh secret Groq/Tavily di `apps/web/.env*` atau variabel berawalan `NEXT_PUBLIC_`.

## Jalankan stack

Untuk uji pada port 8080:

```bash
docker compose up --build -d
docker compose ps
curl http://127.0.0.1:8080/api/health
```

Untuk memakai port 80:

```bash
HTTP_PORT=80 docker compose up --build -d
```

Gunakan DNS A/AAAA menuju VPS. Untuk produksi publik, pasang sertifikat TLS melalui reverse proxy host, Certbot, Caddy, atau load balancer penyedia; lalu paksa pengalihan HTTP ke HTTPS. Konfigurasi contoh repository sengaja hanya membuka HTTP agar tidak mengasumsikan nama domain atau lokasi sertifikat.

## Operasional

```bash
docker compose logs -f api
docker compose logs -f web
docker compose pull
docker compose up --build -d
```

Log container dibatasi langsung dari `compose.yaml` dengan driver `json-file`,
`max-size=10m`, dan `max-file=5` untuk setiap service. Pengaturan ini menjaga
disk VPS agar tidak penuh oleh log aplikasi, Nginx, atau proses build ulang.

Sebelum deploy perubahan, jalankan test backend, lint, typecheck, dan build frontend. Backup `apps/api/.env` di password manager atau secret manager, bukan di repository. Debug trace development hanya in-memory; untuk observability produksi gunakan log terstruktur yang tetap menerapkan redaksi PII.
