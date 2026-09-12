"use client";

import { useGSAP } from "@gsap/react";
import {
  ArrowDown,
  ArrowUpRight,
  EnvelopeSimple,
  GithubLogo,
  LinkedinLogo,
} from "@phosphor-icons/react/dist/ssr";
import gsap from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";
import Image from "next/image";
import Link from "next/link";
import type { KeyboardEvent } from "react";
import { useRef, useState } from "react";

gsap.registerPlugin(useGSAP, ScrollTrigger);

const flowDetails = [
  {
    id: "input",
    title: "Input Pengguna",
    copy: "Pengguna memasukkan bahan yang ingin diperiksa, bisa berupa gambar atau teks. Contohnya screenshot chat, poster bantuan, berita, atau pesan dari nomor tidak dikenal.",
  },
  {
    id: "type",
    title: "Jenis Input",
    copy: "Sistem menentukan apakah input yang diterima berupa gambar atau teks. Ini menentukan cara awal sistem membaca isi kasus.",
  },
  {
    id: "image",
    title: "Baca Isi Gambar",
    copy: "Jika input berupa gambar, sistem membaca teks dan elemen visual yang terlihat. Tahap ini membantu menangkap isi screenshot, poster, logo, atau tampilan aplikasi.",
  },
  {
    id: "clean",
    title: "Bersihkan & Rapikan Teks",
    copy: "Jika input berupa teks, sistem merapikan isi pesan agar lebih mudah dipahami. Bagian ini juga menyaring data sensitif yang tidak perlu digunakan dalam proses pemeriksaan.",
  },
  {
    id: "signals",
    title: "Deteksi Sinyal Penting",
    copy: "Sistem mencari tanda-tanda penting dari kasus, seperti permintaan OTP, tautan mencurigakan, klaim hadiah, desakan waktu, atau nama instansi. Sinyal ini membantu menentukan jenis risiko yang perlu diperiksa.",
  },
  {
    id: "rulebook",
    title: "Ambil Rulebook Relevan",
    copy: "Sistem mengambil aturan pemeriksaan yang sesuai dengan sinyal dan isi kasus. Rulebook membantu sistem tahu pola apa yang harus diwaspadai dan langkah verifikasi apa yang perlu dilakukan.",
  },
  {
    id: "plan",
    title: "Buat Rencana Pemeriksaan",
    copy: "Sistem menentukan klaim mana yang perlu dicek dan bukti apa yang harus dicari. Tahap ini membuat proses verifikasi lebih terarah.",
  },
  {
    id: "validate",
    title: "Validasi Rencana",
    copy: "Rencana pemeriksaan dicek ulang agar tetap sesuai dengan input pengguna. Jika ada klaim yang terlalu lemah, tidak relevan, atau berisiko, sistem memperbaikinya sebelum mencari bukti.",
  },
  {
    id: "search",
    title: "Pencarian Bukti",
    copy: "Sistem mencari bukti dari beberapa sumber yang relevan. Tujuannya adalah menemukan informasi pendukung atau pembantah terhadap klaim yang sedang diperiksa.",
  },
  {
    id: "web",
    title: "Sumber Web",
    copy: "Sistem mencari informasi dari sumber online, terutama untuk klaim yang membutuhkan data terbaru. Ini berguna untuk berita, kebijakan, pengumuman resmi, atau isu yang sedang berlangsung.",
  },
  {
    id: "local",
    title: "Database Bukti Lokal",
    copy: "Sistem mengecek kumpulan bukti dan pola kasus yang sudah tersimpan sebelumnya. Ini membantu mengenali pola penipuan atau klaim berulang tanpa selalu bergantung pada pencarian web.",
  },
  {
    id: "combine",
    title: "Gabungkan Bukti",
    copy: "Semua bukti yang ditemukan dikumpulkan dan dirapikan. Sistem mengelompokkan bukti berdasarkan klaim agar lebih mudah dinilai.",
  },
  {
    id: "enough",
    title: "Cek Kecukupan Bukti",
    copy: "Sistem menilai apakah bukti yang tersedia sudah cukup kuat untuk membuat kesimpulan. Jika bukti belum cukup, sistem tidak memaksakan hasil menjadi benar atau salah.",
  },
  {
    id: "result",
    title: "Hasil Akhir untuk Pengguna",
    copy: "Pengguna menerima hasil pemeriksaan dalam bentuk yang mudah dibaca. Isinya dapat mencakup status klaim, alasan utama, bukti penting, tingkat risiko, dan saran tindakan aman.",
  },
] as const;

type FlowStepId = (typeof flowDetails)[number]["id"];

export function AboutExperience() {
  const root = useRef<HTMLDivElement>(null);
  const guideRef = useRef<HTMLDivElement>(null);
  const [activeFlowStep, setActiveFlowStep] = useState<FlowStepId>("input");

  function selectFlowStep(stepId: FlowStepId) {
    setActiveFlowStep(stepId);

    window.requestAnimationFrame(() => {
      const flow = root.current?.querySelector<HTMLElement>(".about-v2-flow");
      const node = root.current?.querySelector<SVGGElement>(`[data-flow-node="${stepId}"]`);

      if (!flow || !node) return;

      const flowRect = flow.getBoundingClientRect();
      const nodeRect = node.getBoundingClientRect();
      const target =
        flow.scrollLeft + nodeRect.left - flowRect.left - flowRect.width / 2 + nodeRect.width / 2;

      flow.scrollTo({ left: Math.max(0, target), behavior: "smooth" });
    });
  }

  function selectFlowNode(stepId: FlowStepId) {
    selectFlowStep(stepId);

    window.requestAnimationFrame(() => {
      guideRef.current
        ?.querySelector<HTMLElement>(`[data-flow-detail="${stepId}"]`)
        ?.scrollIntoView({ behavior: "smooth", block: "center" });
    });
  }

  function handleFlowNodeKey(event: KeyboardEvent<SVGGElement>, stepId: FlowStepId) {
    if (event.key !== "Enter" && event.key !== " ") return;

    event.preventDefault();
    selectFlowNode(stepId);
  }

  useGSAP(
    () => {
      if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;

      const rootElement = root.current;
      if (!rootElement) return;

      gsap
        .timeline({
          defaults: { ease: "power3.out" },
        })
        .from("[data-about-hero='eyebrow']", {
          y: 12,
          autoAlpha: 0,
          duration: 0.5,
        })
        .from(
          "[data-about-hero='title']",
          {
            y: 22,
            autoAlpha: 0,
            duration: 0.72,
          },
          "-=0.22",
        )
        .from(
          "[data-about-hero='lead']",
          {
            y: 18,
            autoAlpha: 0,
            duration: 0.62,
          },
          "-=0.34",
        )
        .from(
          ".about-v2-hero__article p",
          {
            y: 14,
            autoAlpha: 0,
            duration: 0.5,
            stagger: 0.08,
          },
          "-=0.18",
        )
        .from(
          ".about-v2-hero__text-link",
          {
            y: 12,
            autoAlpha: 0,
            duration: 0.44,
          },
          "-=0.14",
        );

      gsap.utils
        .toArray<HTMLElement>(
          "[data-about-reveal], .about-v2-flow, .about-v2-flow-guide, .about-v2-developer__links",
        )
        .forEach((element) => {
        gsap.from(element, {
          y: 26,
          autoAlpha: 0,
          duration: 0.62,
          ease: "power3.out",
          scrollTrigger: {
            trigger: element,
            start: "top 84%",
            once: true,
          },
        });
      });
    },
    { scope: root },
  );

  return (
    <div ref={root} className="about-v2">
      <section className="about-v2-hero" aria-labelledby="about-title">
        <div className="about-v2-hero__copy">
          <div className="about-v2-hero__intro">
            <span className="eyebrow" data-about-hero="eyebrow">Tentang WaspadAI</span>
            <h1 id="about-title" data-about-hero="title">Apa itu WaspadAI?</h1>
            <p data-about-hero="lead">
              WaspadAI membantu kamu memperlambat keputusan saat menerima informasi yang terasa
              meragukan.
            </p>
          </div>

          <div className="about-v2-hero__reader">
            <div className="about-v2-hero__article">
              <p>
                WaspadAI adalah pendamping verifikasi untuk pesan, tautan, dan gambar. Sistem ini
                menyusun informasi yang kamu kirim menjadi bagian yang lebih mudah dibaca:
                kesimpulan sementara, risiko, alasan, bukti yang perlu diperiksa, dan tindakan yang
                bisa dilakukan.
              </p>
              <p>
                Saat menerima klaim dari media sosial, percakapan pribadi, tautan berita, atau
                gambar, bagian tersulit sering kali bukan mencari jawaban cepat. Bagian tersulit
                adalah memisahkan fakta, asumsi, sumber, dan konsekuensi jika informasi itu langsung
                dipercaya.
              </p>
              <p>
                Karena itu, WaspadAI tidak dirancang untuk memaksa jawaban benar atau salah. Jika
                bukti belum cukup, hasil tetap menampilkan ketidakpastian agar kamu punya alasan
                yang jelas untuk memeriksa sumber resmi terlebih dahulu.
              </p>
            </div>
          </div>

          <a className="about-v2-hero__text-link" href="#cara-kerja">
            Lihat cara kerja <ArrowDown size={17} aria-hidden="true" />
          </a>
        </div>
      </section>

      <section className="about-v2-process" id="cara-kerja" aria-labelledby="process-title">
        <header data-about-reveal>
          <h2 id="process-title">Bagaimana cara kerjanya?</h2>
          <p>
            Setiap informasi diperiksa melalui beberapa tahap. Jika buktinya belum cukup, WaspadAI
            tidak memaksakan jawaban.
          </p>
        </header>

        <figure
          className="about-v2-flow"
          tabIndex={0}
          aria-label="Alur Proses Pemeriksaan"
        >
          <svg
            viewBox="0 0 1700 460"
            preserveAspectRatio="xMidYMid meet"
            role="img"
            aria-labelledby="flow-title flow-desc"
          >
            <title id="flow-title">Alur Proses Pemeriksaan</title>
            <desc id="flow-desc">
              Diagram dimulai dari Input Pengguna, bercabang berdasarkan jenis input gambar atau
              teks, lalu berlanjut menuju pencarian bukti dan hasil akhir untuk pengguna.
            </desc>
            <defs>
              <marker
                id="about-flow-arrow"
                viewBox="0 0 10 10"
                refX="9"
                refY="5"
                markerWidth="4.5"
                markerHeight="4.5"
                orient="auto-start-reverse"
              >
                <path d="M0,0 L10,5 L0,10 z" />
              </marker>
            </defs>

            <g className="about-v2-flow__lines">
              <line className="about-v2-flow__line" x1="180" y1="110" x2="315" y2="110" />
              <line className="about-v2-flow__line" x1="420" y1="90" x2="620" y2="60" />
              <line className="about-v2-flow__line" x1="420" y1="130" x2="620" y2="170" />
              <line className="about-v2-flow__line" x1="780" y1="60" x2="920" y2="95" />
              <line className="about-v2-flow__line" x1="780" y1="170" x2="920" y2="125" />
              <line className="about-v2-flow__line" x1="1080" y1="110" x2="1220" y2="110" />
              <line className="about-v2-flow__line" x1="1380" y1="110" x2="1520" y2="110" />
              <line className="about-v2-flow__line" x1="1600" y1="137" x2="1600" y2="302" />
              <line className="about-v2-flow__line" x1="1520" y1="330" x2="1380" y2="330" />
              <line className="about-v2-flow__line" x1="1220" y1="330" x2="1080" y2="280" />
              <line className="about-v2-flow__line" x1="1220" y1="330" x2="1080" y2="390" />
              <line className="about-v2-flow__line" x1="920" y1="280" x2="780" y2="315" />
              <line className="about-v2-flow__line" x1="920" y1="390" x2="780" y2="345" />
              <line className="about-v2-flow__line" x1="620" y1="330" x2="480" y2="330" />
              <line className="about-v2-flow__line" x1="320" y1="330" x2="180" y2="330" />
            </g>

            <text className="about-v2-flow__label" x="510" y="55" textAnchor="middle">
              Gambar
            </text>
            <text className="about-v2-flow__label" x="510" y="180" textAnchor="middle">
              Teks
            </text>

            <g
              className={`about-v2-flow__node about-v2-flow__node--start ${
                activeFlowStep === "input" ? "about-v2-flow__node--active" : ""
              }`}
              data-flow-node="input"
              tabIndex={0}
              role="button"
              aria-label="Input Pengguna"
              aria-pressed={activeFlowStep === "input"}
              onClick={() => selectFlowNode("input")}
              onKeyDown={(event) => handleFlowNodeKey(event, "input")}
            >
              <rect x="20" y="82" width="160" height="55" rx="6" />
              <text x="100" y="115" textAnchor="middle">Input Pengguna</text>
            </g>

            <g
              className={`about-v2-flow__node about-v2-flow__node--decision ${
                activeFlowStep === "type" ? "about-v2-flow__node--active" : ""
              }`}
              data-flow-node="type"
              tabIndex={0}
              role="button"
              aria-label="Jenis Input"
              aria-pressed={activeFlowStep === "type"}
              onClick={() => selectFlowNode("type")}
              onKeyDown={(event) => handleFlowNodeKey(event, "type")}
            >
              <polygon points="400,65 485,110 400,155 315,110" />
              <text x="400" y="106" textAnchor="middle">Jenis</text>
              <text x="400" y="121" textAnchor="middle">Input</text>
            </g>

            <g
              className={`about-v2-flow__node ${
                activeFlowStep === "image" ? "about-v2-flow__node--active" : ""
              }`}
              data-flow-node="image"
              tabIndex={0}
              role="button"
              aria-label="Baca Isi Gambar"
              aria-pressed={activeFlowStep === "image"}
              onClick={() => selectFlowNode("image")}
              onKeyDown={(event) => handleFlowNodeKey(event, "image")}
            >
              <rect x="620" y="32" width="160" height="55" rx="6" />
              <text x="700" y="64" textAnchor="middle">Baca Isi Gambar</text>
            </g>

            <g
              className={`about-v2-flow__node ${
                activeFlowStep === "clean" ? "about-v2-flow__node--active" : ""
              }`}
              data-flow-node="clean"
              tabIndex={0}
              role="button"
              aria-label="Bersihkan dan Rapikan Teks"
              aria-pressed={activeFlowStep === "clean"}
              onClick={() => selectFlowNode("clean")}
              onKeyDown={(event) => handleFlowNodeKey(event, "clean")}
            >
              <rect x="620" y="142" width="160" height="55" rx="6" />
              <text x="700" y="164" textAnchor="middle">Bersihkan &amp;</text>
              <text x="700" y="180" textAnchor="middle">Rapikan Teks</text>
            </g>

            <g
              className={`about-v2-flow__node ${
                activeFlowStep === "signals" ? "about-v2-flow__node--active" : ""
              }`}
              data-flow-node="signals"
              tabIndex={0}
              role="button"
              aria-label="Deteksi Sinyal Penting"
              aria-pressed={activeFlowStep === "signals"}
              onClick={() => selectFlowNode("signals")}
              onKeyDown={(event) => handleFlowNodeKey(event, "signals")}
            >
              <rect x="920" y="82" width="160" height="55" rx="6" />
              <text x="1000" y="106" textAnchor="middle">Deteksi Sinyal</text>
              <text x="1000" y="122" textAnchor="middle">Penting</text>
            </g>

            <g
              className={`about-v2-flow__node ${
                activeFlowStep === "rulebook" ? "about-v2-flow__node--active" : ""
              }`}
              data-flow-node="rulebook"
              tabIndex={0}
              role="button"
              aria-label="Ambil Rulebook Relevan"
              aria-pressed={activeFlowStep === "rulebook"}
              onClick={() => selectFlowNode("rulebook")}
              onKeyDown={(event) => handleFlowNodeKey(event, "rulebook")}
            >
              <rect x="1220" y="82" width="160" height="55" rx="6" />
              <text x="1300" y="106" textAnchor="middle">Ambil Rulebook</text>
              <text x="1300" y="122" textAnchor="middle">Relevan</text>
            </g>

            <g
              className={`about-v2-flow__node ${
                activeFlowStep === "plan" ? "about-v2-flow__node--active" : ""
              }`}
              data-flow-node="plan"
              tabIndex={0}
              role="button"
              aria-label="Buat Rencana Pemeriksaan"
              aria-pressed={activeFlowStep === "plan"}
              onClick={() => selectFlowNode("plan")}
              onKeyDown={(event) => handleFlowNodeKey(event, "plan")}
            >
              <rect x="1520" y="82" width="160" height="55" rx="6" />
              <text x="1600" y="106" textAnchor="middle">Buat Rencana</text>
              <text x="1600" y="122" textAnchor="middle">Pemeriksaan</text>
            </g>

            <g
              className={`about-v2-flow__node ${
                activeFlowStep === "validate" ? "about-v2-flow__node--active" : ""
              }`}
              data-flow-node="validate"
              tabIndex={0}
              role="button"
              aria-label="Validasi Rencana"
              aria-pressed={activeFlowStep === "validate"}
              onClick={() => selectFlowNode("validate")}
              onKeyDown={(event) => handleFlowNodeKey(event, "validate")}
            >
              <rect x="1520" y="302" width="160" height="55" rx="6" />
              <text x="1600" y="326" textAnchor="middle">Validasi</text>
              <text x="1600" y="342" textAnchor="middle">Rencana</text>
            </g>

            <g
              className={`about-v2-flow__node ${
                activeFlowStep === "search" ? "about-v2-flow__node--active" : ""
              }`}
              data-flow-node="search"
              tabIndex={0}
              role="button"
              aria-label="Pencarian Bukti"
              aria-pressed={activeFlowStep === "search"}
              onClick={() => selectFlowNode("search")}
              onKeyDown={(event) => handleFlowNodeKey(event, "search")}
            >
              <rect x="1220" y="302" width="160" height="55" rx="6" />
              <text x="1300" y="335" textAnchor="middle">Pencarian Bukti</text>
            </g>

            <g
              className={`about-v2-flow__node about-v2-flow__node--source ${
                activeFlowStep === "web" ? "about-v2-flow__node--active" : ""
              }`}
              data-flow-node="web"
              tabIndex={0}
              role="button"
              aria-label="Sumber Web"
              aria-pressed={activeFlowStep === "web"}
              onClick={() => selectFlowNode("web")}
              onKeyDown={(event) => handleFlowNodeKey(event, "web")}
            >
              <rect x="920" y="252" width="160" height="55" rx="6" />
              <text x="1000" y="285" textAnchor="middle">Sumber Web</text>
            </g>

            <g
              className={`about-v2-flow__node about-v2-flow__node--source ${
                activeFlowStep === "local" ? "about-v2-flow__node--active" : ""
              }`}
              data-flow-node="local"
              tabIndex={0}
              role="button"
              aria-label="Database Bukti Lokal"
              aria-pressed={activeFlowStep === "local"}
              onClick={() => selectFlowNode("local")}
              onKeyDown={(event) => handleFlowNodeKey(event, "local")}
            >
              <rect x="920" y="362" width="160" height="55" rx="6" />
              <text x="1000" y="386" textAnchor="middle">Database Bukti</text>
              <text x="1000" y="402" textAnchor="middle">Lokal</text>
            </g>

            <g
              className={`about-v2-flow__node ${
                activeFlowStep === "combine" ? "about-v2-flow__node--active" : ""
              }`}
              data-flow-node="combine"
              tabIndex={0}
              role="button"
              aria-label="Gabungkan Bukti"
              aria-pressed={activeFlowStep === "combine"}
              onClick={() => selectFlowNode("combine")}
              onKeyDown={(event) => handleFlowNodeKey(event, "combine")}
            >
              <rect x="620" y="302" width="160" height="55" rx="6" />
              <text x="700" y="335" textAnchor="middle">Gabungkan Bukti</text>
            </g>

            <g
              className={`about-v2-flow__node ${
                activeFlowStep === "enough" ? "about-v2-flow__node--active" : ""
              }`}
              data-flow-node="enough"
              tabIndex={0}
              role="button"
              aria-label="Cek Kecukupan Bukti"
              aria-pressed={activeFlowStep === "enough"}
              onClick={() => selectFlowNode("enough")}
              onKeyDown={(event) => handleFlowNodeKey(event, "enough")}
            >
              <rect x="320" y="302" width="160" height="55" rx="6" />
              <text x="400" y="326" textAnchor="middle">Cek Kecukupan</text>
              <text x="400" y="342" textAnchor="middle">Bukti</text>
            </g>

            <g
              className={`about-v2-flow__node about-v2-flow__node--end ${
                activeFlowStep === "result" ? "about-v2-flow__node--active" : ""
              }`}
              data-flow-node="result"
              tabIndex={0}
              role="button"
              aria-label="Hasil Akhir untuk Pengguna"
              aria-pressed={activeFlowStep === "result"}
              onClick={() => selectFlowNode("result")}
              onKeyDown={(event) => handleFlowNodeKey(event, "result")}
            >
              <rect x="20" y="302" width="160" height="55" rx="6" />
              <text x="100" y="326" textAnchor="middle">Hasil Akhir</text>
              <text x="100" y="342" textAnchor="middle">untuk Pengguna</text>
            </g>
          </svg>
        </figure>

        <div
          ref={guideRef}
          className="about-v2-flow-guide"
          aria-label="Keterangan alur pemeriksaan"
        >
          {flowDetails.map((step, index) => (
            <button
              className={`about-v2-flow-guide__item ${
                activeFlowStep === step.id ? "about-v2-flow-guide__item--active" : ""
              }`}
              type="button"
              key={step.id}
              data-flow-detail={step.id}
              onClick={() => selectFlowStep(step.id)}
              aria-pressed={activeFlowStep === step.id}
            >
              <span className="about-v2-flow-guide__index">
                {String(index + 1).padStart(2, "0")}
              </span>
              <span className="about-v2-flow-guide__body">
                <strong>{step.title}</strong>
                <span>{step.copy}</span>
              </span>
            </button>
          ))}
        </div>
      </section>

      <section className="about-v2-developer" aria-labelledby="developer-title">
        <div className="about-v2-developer__photo" data-about-reveal>
          <Image
            src="/images/shafwan-adhi-dwi-nugraha.jpg"
            alt="Shafwan Adhi Dwi Nugraha"
            width={360}
            height={360}
            sizes="(max-width: 720px) calc(100vw - 32px), 360px"
          />
        </div>

        <div className="about-v2-developer__copy" data-about-reveal>
          <h2 id="developer-title">Tentang Pengembang</h2>
          <p className="about-v2-developer__name">Shafwan Adhi Dwi Nugraha</p>
          <p className="about-v2-developer__role">
            Mahasiswa Teknik Informatika, Universitas Negeri Malang
          </p>
          <p>
            Mengembangkan WaspadAI untuk membantu orang menghadapi informasi digital dengan lebih
            hati-hati.
          </p>

          <nav className="about-v2-developer__links" aria-label="Kontak pengembang">
            <a href="https://github.com/ShafwanAdhi" target="_blank" rel="noreferrer">
              <GithubLogo size={20} weight="fill" aria-hidden="true" /> GitHub
              <ArrowUpRight size={15} aria-hidden="true" />
            </a>
            <a
              href="https://www.linkedin.com/in/shafwan-adhi-dwi-nugraha-b90943321/"
              target="_blank"
              rel="noreferrer"
            >
              <LinkedinLogo size={20} weight="fill" aria-hidden="true" /> LinkedIn
              <ArrowUpRight size={15} aria-hidden="true" />
            </a>
            <a href="mailto:shafwan.adhi.dwi@gmail.com">
              <EnvelopeSimple size={20} weight="fill" aria-hidden="true" /> Email
            </a>
          </nav>

          <Link className="button button--dark" href="/chat">
            Mulai periksa <ArrowUpRight size={19} aria-hidden="true" />
          </Link>
        </div>
      </section>
    </div>
  );
}
