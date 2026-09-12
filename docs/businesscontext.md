# Business Context

## 1. Overview

Sistem ini merupakan **Digital Safety Companion** yang membantu masyarakat Indonesia, khususnya masyarakat perdesaan dan pengguna dengan literasi digital dasar, dalam menghadapi **online scam, hoaks, phishing, social engineering, impersonation, dan konten manipulatif berbasis AI**.

Platform dirancang tidak hanya sebagai alat deteksi, tetapi sebagai sistem perlindungan end-to-end melalui pendekatan:

**Learn → Practice → Verify → Protect → Recover**

Tujuan utama sistem adalah membantu pengguna menjawab pertanyaan sederhana:

> **“Apakah konten atau interaksi digital ini aman untuk dipercaya dan ditindaklanjuti?”**

---

## 2. Business Problem

Adopsi internet dan layanan digital di Indonesia terus meningkat, termasuk di wilayah perdesaan. Namun, peningkatan tersebut belum sepenuhnya diikuti oleh peningkatan kemampuan masyarakat dalam:

* mengenali scam dan social engineering;
* memverifikasi informasi;
* mengecek nomor, rekening, dan tautan;
* mengenali konten AI/deepfake;
* mengetahui tindakan yang tepat ketika menemukan atau menjadi korban scam.

Di sisi lain, modus penipuan berkembang dari phishing sederhana menjadi **multimodal scam** yang dapat menggabungkan:

`AI Video → WhatsApp → Social Engineering → Phishing Link → Transfer`

Solusi yang tersedia saat ini masih tersebar pada berbagai platform seperti IASC, CekRekening, AduanNomor, fact-checking tools, dan deepfake detector sehingga menghasilkan **fragmented user journey**.

---

## 3. Target Users

### Primary Users

* Masyarakat perdesaan yang aktif menggunakan internet.
* Pengguna dengan tingkat literasi digital dasar–menengah.
* Orang tua/lansia pengguna WhatsApp dan media sosial.
* Pelaku UMKM.
* Pengguna mobile banking dan e-wallet.

### Secondary Users

* Keluarga atau trusted contacts.
* Kader/perangkat desa.
* Komunitas literasi digital.
* Pemerintah daerah.
* Institusi keuangan.
* Organisasi anti-hoaks dan anti-scam.

---

## 4. Value Proposition

Sistem menyediakan **satu pintu perlindungan digital** sehingga pengguna tidak perlu mengetahui tool apa yang harus digunakan ketika menemukan sesuatu yang mencurigakan.

### Core Value Proposition

> **One Tap to Check, Understand, and Act Safely.**

Pengguna cukup mengirim atau memilih konten yang ingin diperiksa dan sistem akan menentukan pemeriksaan yang diperlukan.

---

## 5. Key Solution

### Learn

Micro-learning mengenai:

* modus scam terbaru;
* phishing;
* social engineering;
* deepfake;
* keamanan akun;
* perlindungan data pribadi.

### Practice

Simulasi interaktif seperti:

* chat scam;
* phishing link;
* impersonasi keluarga;
* OTP scam;
* bantuan pemerintah palsu.

Digunakan untuk meningkatkan **digital resilience** sebelum pengguna menghadapi ancaman nyata.

### Verify / TrueCheck

Pengguna dapat memeriksa:

* pesan hasil copy-paste, termasuk dari nomor tidak dikenal;
* berita atau kutipan yang ditempel;
* caption dan klaim media sosial;
* screenshot;
* foto;
* video;
* URL;
* nomor telepon;
* rekening.

Sistem menganalisis beberapa indikator untuk menghasilkan **Risk Assessment**.
Untuk mencegah kesimpulan yang rancu, hasil TrueCheck memisahkan status faktual,
autentisitas sumber, identitas pengirim, status kanal, risiko scam, dan autentisitas
konten. Teks tanpa URL asal tetap dapat diperiksa secara faktual, tetapi sumbernya
tidak dinyatakan autentik.

### Guard

Verifikasi dilakukan melalui mekanisme seperti:

* Share-to-Verify;
* screenshot;
* floating verification button;
* contextual warning.

Tujuannya adalah memberikan perlindungan pada **moment of decision**.

### Recovery / SOS

Jika pengguna telah menjadi korban, sistem memberikan:

* langkah mitigasi;
* rekomendasi pengamanan akun;
* panduan menghubungi bank;
* panduan pelaporan;
* integrasi/rujukan menuju IASC dan layanan resmi lainnya.

---

## 6. Core Technology

Sistem menggunakan **Unified Trust Engine** yang menggabungkan beberapa signal:

* NLP-based scam detection;
* social engineering pattern detection;
* phishing/URL analysis;
* phone number reputation;
* bank account reputation;
* fact checking;
* source credibility;
* deepfake/AI-content detection;
* media provenance;
* community reports.

Sistem tidak hanya menghasilkan:

> “AI detected: 80%”

tetapi menghasilkan assessment seperti:

> **HIGH RISK**
>
> Terdapat permintaan transfer mendadak, URL tidak resmi, pola impersonasi, dan rekening memiliki laporan sebelumnya.
>
> **Recommended Action:** Jangan melakukan transfer sebelum melakukan verifikasi melalui kanal resmi.

---

## 7. Competitive Landscape

Existing solutions mencakup:

* **IASC** → scam reporting dan financial recovery.
* **CekRekening** → pemeriksaan rekening.
* **AduanNomor** → pemeriksaan nomor.
* **CekFakta / TurnBackHoax / CekSumber** → fact checking.
* **Google / WhatsApp Scam Detection** → contextual scam protection.
* **Deepfake Detector / C2PA** → media authenticity.
* **Tular Nalar** → digital literacy.

### Market Gap

Solusi tersebut masih relatif terpisah.

Belum terdapat satu platform Indonesia yang mengintegrasikan:

**Education + Simulation + Verification + Scam Detection + AI Detection + Reporting + Recovery**

dalam satu user journey sederhana.

---

## 8. Key Differentiators

### Unified Verification

Satu interface untuk berbagai jenis ancaman digital.

### Context-Aware Protection

Pengguna dapat melakukan verifikasi ketika sedang melihat konten mencurigakan.

### Evidence Fusion

Keputusan tidak bergantung pada satu AI model tetapi beberapa signal sekaligus.

### Explainable Risk

Sistem menjelaskan alasan di balik risk score dan memberikan rekomendasi tindakan.

### Indonesian Context

Knowledge base dapat difokuskan pada modus lokal seperti:

* bansos palsu;
* undangan APK;
* pinjol;
* BPJS;
* kurir palsu;
* KUR;
* CPNS;
* impersonasi keluarga;
* impersonasi pejabat.

### Community Learning Loop

Kasus scam yang telah diverifikasi dapat dianonimkan dan diubah menjadi materi **Practice** baru.

---

## 9. Business Objectives

* Mengurangi kemungkinan pengguna menjadi korban scam.
* Mempercepat proses verifikasi informasi mencurigakan.
* Meningkatkan digital safety awareness.
* Meningkatkan kemampuan pengguna mengenali social engineering.
* Mendorong pelaporan scam yang lebih cepat.
* Membangun database pola scam lokal Indonesia.
* Menciptakan community-driven digital resilience.

---

## 10. Potential Business Model

### B2C

Model freemium:

**Free**

* Learn;
* Practice;
* basic verification.

**Premium**

* advanced AI verification;
* Family Guard;
* monitoring/reputation feature;
* enhanced protection.

### B2B / B2G

Potensi partnership dengan:

* bank;
* fintech;
* e-wallet;
* pemerintah desa;
* pemerintah daerah;
* institusi pendidikan;
* operator telekomunikasi;
* organisasi literasi digital.

Produk dapat dikembangkan sebagai **Digital Safety as a Service** untuk membantu institusi melindungi komunitas atau customer mereka.

---

## 11. Key Stakeholders

* End users.
* Keluarga / trusted contacts.
* Pemerintah desa.
* Komdigi.
* OJK / IASC.
* Bank dan fintech.
* Mafindo / fact-checking organizations.
* Telco providers.
* Educational institutions.

---

## 12. MVP Scope

MVP difokuskan pada fitur yang memiliki **high impact dan technical feasibility tinggi**:

* Learn.
* Practice scam simulation.
* Text/WhatsApp scam detection.
* Screenshot verification.
* URL phishing detection.
* Phone/rekening risk checking.
* Risk Score + explanation.
* Community report.
* Recovery guidance.

Baseline saat ini telah mengimplementasikan input text dan image pada shared
FastAPI pipeline. URL/phone/rekening reputation yang lengkap, publikasi community,
real-time interception, dan cryptographic provenance tetap berada di tahap lanjut.

Untuk tuning internal, MVP juga memiliki Pipeline Log lokal yang menunjukkan output
setiap tahap, model, durasi, dan snapshot kontrak instruksi. Fitur ini bukan halaman
end-user produksi: akses dibatasi ke localhost, otomatis nonaktif pada production,
dan hanya menyimpan data turunan teredaksi secara FIFO di memori. Raw text, binary
gambar, kredensial, dan chain-of-thought tidak menjadi bagian dari log.
Pipeline Log juga menunjukkan snapshot rate limit Groq per model dari response
headers terakhir, termasuk countdown reset, tanpa menghabiskan request tambahan.
Tabel operasional mencakup RPM, RPD, TPM, dan TPD; jatah plan dibedakan dari
remaining aktual agar operator tidak membaca referensi statis sebagai telemetry.

Fitur seperti **real-time WhatsApp call interception dan full real-time deepfake detection** tidak menjadi prioritas MVP karena memiliki kompleksitas teknis, privacy, dan platform restriction yang lebih tinggi.

---

## 13. Success Metrics

Beberapa KPI awal:

* Monthly Active Users.
* Number of verification requests.
* Scam detection engagement rate.
* Practice completion rate.
* Learning improvement score.
* Percentage of high-risk interactions avoided.
* Number of validated community reports.
* Average verification response time.
* Recovery assistance usage.
* User retention rate.

---

## 14. Long-Term Vision

Dalam jangka panjang, sistem diarahkan menjadi:

> **Digital Trust Infrastructure for Indonesian Communities**

yang tidak hanya membantu pengguna mengetahui apakah sesuatu merupakan scam, tetapi juga membangun kemampuan masyarakat untuk **recognize, verify, respond, dan recover** dari ancaman digital.

Target akhirnya adalah menciptakan ekosistem di mana:

**1 scam terdeteksi**

→ dilaporkan

→ diverifikasi

→ dipelajari sistem

→ menjadi peringatan komunitas

→ menjadi materi latihan

→ mencegah korban berikutnya.

Dengan demikian, semakin banyak ancaman yang ditemukan, semakin kuat **collective digital resilience** komunitas.
