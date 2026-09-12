# Evaluasi Investigation Planner 20B

Dokumen ini mencatat benchmark stage-level untuk `openai/gpt-oss-20b` sebagai
Investigation Planner. Benchmark tidak memanggil model 120B dan tidak mengubah
pipeline produksi.

## Tujuan

Evaluasi mengukur apakah planner dapat:

- mengklasifikasikan jenis input;
- mempertahankan klaim material tanpa membuat klaim baru;
- membawa domain yang diwajibkan oleh signal extractor;
- memilih critical check dari konteks rulebook;
- menyusun retrieval plan yang sesuai;
- membuat query yang mencakup entitas dan pokok klaim;
- mengenali kasus yang perlu dieskalasi;
- selalu menghasilkan output yang memenuhi `PlannerOutput` schema.

## Dataset

Dataset berada di `evaluation/planner_cases.json` dan berisi delapan kasus
sintetis berbahasa Indonesia. Kasus mencakup impersonation bank, permintaan OTP,
APK yang mengatasnamakan BPJS, klaim statistik tanpa sumber, berita lama yang
beredar kembali, opini, satire, dugaan deepfake pejabat, dan pesan bantuan
pemerintah dengan banyak klaim serta risiko finansial.

Label kasus adalah hipotesis engineering dan harus ditinjau manusia sebelum
digunakan sebagai release gate produksi.

## Cara menjalankan

Pastikan `GROQ_API_KEY` tersedia, kemudian jalankan:

```powershell
python -m scripts.evaluate_planner
```

Runner memberi jeda 62 detik antar-request secara default karena Free Plan untuk
GPT-OSS memiliki batas TPM rendah. Untuk smoke test satu kasus:

```powershell
python -m scripts.evaluate_planner --case-limit 1 --delay-seconds 0
```

Hasil lengkap ditulis ke `evaluation/planner_results.json`.

## Definisi metrik

| Metrik | Definisi |
|---|---|
| Schema validity | Persentase kasus yang menghasilkan `PlannerOutput` valid |
| Classification accuracy | Kesesuaian classification dengan label yang diterima |
| Claim recall | Klaim material berlabel yang ditemukan planner |
| Claim precision proxy | Klaim keluaran yang cocok dengan konsep berlabel |
| Required-domain recall | Domain wajib yang dipertahankan planner |
| Critical-check recall | Pemeriksaan penting berlabel yang muncul |
| Retrieval-plan accuracy | Kesesuaian web search, domain RAG, dan fact-check RAG |
| Query usefulness proxy | Coverage konsep penting di dalam query pencarian |
| Escalation recall | Kasus wajib eskalasi yang diberi complexity `HIGH` |
| Escalation false-positive rate | Kasus sederhana yang tidak perlu tetapi diberi `HIGH` |

Claim precision dan query usefulness disebut *proxy* karena menggunakan
pencocokan konsep deterministik. Keduanya belum menggantikan penilaian semantik
oleh reviewer manusia atau pengukuran keberhasilan live evidence retrieval.

## Hasil baseline

Baseline live dijalankan pada 10 September 2026 terhadap
`openai/gpt-oss-20b`. Delapan kasus dikirim berurutan dengan jeda 62 detik dan
tanpa memanggil model 120B.

| Metrik | Hasil |
|---|---:|
| Schema validity | 75.00% (6/8 kasus) |
| Classification accuracy | 50.00% (4/8 kasus) |
| Claim recall | 40.91% (9/22 unit klaim) |
| Claim precision proxy | 90.00% (9/10 klaim keluaran valid) |
| Required-domain recall | 58.82% (10/17 domain wajib) |
| Critical-check recall | 50.00% (9/18 pemeriksaan) |
| Retrieval-plan accuracy | 50.00% (12/24 keputusan) |
| Query usefulness proxy | 37.50% (3/8 konsep query) |
| Escalation recall | 20.00% (1/5 kasus wajib eskalasi) |
| Escalation false-positive rate | 0.00% (0/3 kasus non-eskalasi) |

Skor keseluruhan memasukkan schema error sebagai kegagalan downstream. Untuk
membedakan kualitas isi dari reliability kontrak, pada enam kasus yang selesai:

- claim recall = 75.00% (9/12);
- required-domain recall = 90.91% (10/11);
- critical-check recall = 81.82% (9/11);
- retrieval-plan accuracy = 66.67% (12/18);
- query concept coverage = 75.00% (3/4).

## Temuan per kasus

- Pesan OTP bank berhasil diberi complexity `HIGH`, tetapi pada baseline
  diklasifikasikan sebagai `FACTUAL_CLAIM` dan seluruh tiga klaim material
  diganti menjadi klaim baru bahwa pesan tersebut aman. Pada smoke run terpisah,
  input yang sama justru menjadi `SCAM_MESSAGE` dengan seluruh klaim terambil.
  Ini menunjukkan instability yang perlu diuji berulang.
- Pesan BPJS yang meminta instal APK mengambil klaim, domain, dan critical check
  dengan baik, tetapi diklasifikasikan sebagai `FACTUAL_CLAIM/MEDIUM`; kebijakan
  benchmark mengharuskannya menjadi kasus berisiko yang dieskalasi.
- Klaim statistik tanpa sumber dipetakan dengan baik: classification, klaim,
  critical check, retrieval plan, dan query sesuai label.
- Berita lama berhasil dipecah menjadi dua klaim dan memiliki temporal checks,
  tetapi tidak dieskalasi, tidak mengaktifkan fact-check RAG, dan query memakai
  tahun 2023 alih-alih konteks tanggal saat evaluasi (2026).
- Opini dan satire dikenali sebagai `OPINION/SIMPLE` dan `SATIRE/SIMPLE`.
  Planner tetap memilih web/fact-check retrieval pada satire meskipun label
  benchmark menilai label eksplisitnya cukup untuk tidak melakukan retrieval.
- Kasus deepfake pejabat dan pesan bantuan multi-klaim gagal memenuhi JSON
  schema. `failed_generation` berhenti setelah daftar klaim dan tidak memuat
  field perencanaan lain. Pola ini mengindikasikan output budget atau beban
  schema/prompt perlu diperiksa.
- Pada kasus deepfake, failed generation juga menambahkan pernyataan yang tidak
  diberikan input, seperti program didanai anggaran pemerintah dan program bukan
  scam. Karena output invalid, pipeline memang menolaknya, tetapi perilaku ini
  menunjukkan perlunya validator grounding klaim.

## Kesimpulan baseline

Dalam konfigurasi saat ini, 20B belum layak menjadi satu-satunya sumber keputusan
planner. Model cukup menjanjikan untuk first pass pada kasus sederhana dan
menengah, tetapi reliability schema, grounding klaim, dan terutama escalation
recall belum memenuhi kebutuhan sistem berisiko tinggi.

Implikasi arsitektur yang disarankan:

1. pertahankan 20B sebagai first-pass planner;
2. validasi klaim terhadap teks input dan `seed_claims`;
3. tentukan eskalasi dari deterministic risk signals, bukan label complexity
   model saja;
4. jika output schema gagal, jangan kehilangan hasil aman yang sudah tersedia
   dari signals dan rulebook;
5. kirim hanya rencana ringkas dan konflik terdeteksi kepada 120B sebagai
   reviewer;
6. pecah schema atau pindahkan daftar klaim ke bagian akhir apabila pengujian
   lanjutan memastikan completion budget menjadi penyebab truncation.

Baseline ini belum menjadi release gate. Dataset masih kecil, seluruh kasus
sintetis, pencocokan klaim bersifat bilingual lexical proxy, dan setiap kasus baru
dijalankan satu kali. Langkah berikutnya adalah menambah kasus nyata yang sudah
dianonimkan, menjalankan beberapa repetisi per kasus, dan melakukan human review
terhadap claim grounding serta kualitas query.

## Perubahan arsitektur setelah baseline

Baseline di atas mengukur planner sebelum guardrail baru. Implementasi berikut
kemudian ditambahkan:

- model mengeluarkan `PlannerDraftOutput` yang lebih kecil; field deterministik
  seperti freshness minimum, URL presence, financial/impersonation flags,
  interim risk floor, dan safe actions diisi backend;
- input planner memakai excerpt kasus maksimum 6.000 karakter, signal non-kosong,
  serta maksimum enam rule dengan isi maksimum 240 karakter;
- backend memvalidasi claim grounding, membuang klaim unsupported, dan
  memulihkan material source claims;
- escalation policy memakai critical signals dan validation failure, tidak hanya
  `complexity` model;
- 120B menjadi reviewer dengan excerpt maksimum 3.200 karakter dan maksimum lima
  rule ringkas;
- kegagalan 20B menghasilkan deterministic fallback plan; kegagalan reviewer
  mempertahankan plan tervalidasi tersebut.

Smoke test live setelah perubahan pada `multi_claim_government_aid`—kasus yang
sebelumnya gagal `PlannerOutput` schema—berhasil memenuhi schema baru dengan:

```text
classification = SCAM_MESSAGE
model complexity = MEDIUM
claim recall proxy = 100%
required-domain recall = 100%
retrieval-plan accuracy = 100%
```

Nilai `MEDIUM` tidak lagi melewatkan eskalasi karena backend mendeteksi secret,
pembayaran ke rekening pribadi, impersonation, dan banyak klaim. Hasil smoke
tersimpan di `evaluation/planner_post_change_smoke.json`. Angka ini hanya satu
kasus dan bukan pengganti pengulangan full benchmark.

Uji live end-to-end pada kasus yang sama kemudian berhasil menyelesaikan compact
120B review, mempertahankan empat klaim tervalidasi, mengambil tujuh evidence,
dan menghasilkan verdict konservatif `UNVERIFIED`. Selama pengujian ditemukan
dua limit eksternal tambahan dan keduanya diperbaiki: Compound web search kini
terisolasi sebagai branch fallback, sedangkan Qwen verifier menggunakan maksimum
900 output token agar berada di bawah OTPM 1.000 yang diberlakukan pada organisasi
saat pengujian. Jika verifier tetap gagal, backend mengembalikan deterministic
`UNVERIFIED` response dan tidak menghentikan seluruh request.
