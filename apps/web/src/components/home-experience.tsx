"use client";

import { useGSAP } from "@gsap/react";
import { ArrowDown, ArrowUpRight } from "@phosphor-icons/react/dist/ssr";
import gsap from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";
import Link from "next/link";
import { useRef } from "react";
import { SiteFooter } from "./site-footer";
import { SiteHeader } from "./site-header";

gsap.registerPlugin(ScrollTrigger, useGSAP);

const resultParts = [
  ["Kesimpulan", "Apa status informasinya"],
  ["Risiko", "Seberapa hati-hati kamu perlu bersikap"],
  ["Alasan", "Temuan yang memengaruhi penilaian"],
  ["Bukti", "Dasar yang mendukung kesimpulan"],
  ["Tindakan", "Apa yang sebaiknya dilakukan sekarang"],
];

export function HomeExperience() {
  const root = useRef<HTMLElement>(null);

  useGSAP(
    () => {
      if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;

      gsap
        .timeline({ defaults: { ease: "power3.out" } })
        .from(".hero-image", { scale: 1.1, duration: 1.5 })
        .from(".hero-kicker", { autoAlpha: 0, y: 16, duration: 0.55 }, 0.2)
        .from(".hero-title > span", { autoAlpha: 0, y: 54, stagger: 0.1, duration: 0.8 }, 0.28)
        .from(".hero-copy", { autoAlpha: 0, y: 24, duration: 0.65 }, 0.52)
        .from(".hero-actions", { autoAlpha: 0, y: 20, duration: 0.6 }, 0.64);

      gsap
        .timeline({
          scrollTrigger: {
            trigger: ".result-anatomy",
            start: "top 76%",
          },
        })
        .from(".result-anatomy__heading > *", {
          y: 24,
          opacity: 0,
          stagger: 0.08,
          duration: 0.6,
          ease: "power3.out",
        })
        .from(
          ".result-part",
          {
            x: 34,
            opacity: 0,
            stagger: 0.07,
            duration: 0.55,
            ease: "power3.out",
          },
          0.12,
        );
    },
    { scope: root },
  );

  return (
    <main ref={root} className="home-v2 overflow-guard">
      <section className="hero" aria-labelledby="home-title">
        <SiteHeader tone="dark" />
        <div className="hero-image" aria-hidden="true" />
        <div className="hero-shade" aria-hidden="true" />

        <div className="hero-content">
          <span className="hero-kicker">Teman verifikasi untuk keputusan digital</span>
          <h1 className="hero-title" id="home-title">
            <span>Ragu dengan informasi</span>
            <span>yang kamu terima?</span>
          </h1>
          <p className="hero-copy">
            Kirim pesan, tautan, atau gambar. WaspadAI membantu memeriksa bukti, menjelaskan risiko,
            dan menunjukkan langkah yang lebih aman.
          </p>
          <div className="hero-actions">
            <Link className="button button--primary" href="/chat">
              Mulai periksa <ArrowUpRight size={19} />
            </Link>
            <Link className="button button--ghost" href="#hasil">
              Lihat cara kerjanya <ArrowDown size={18} />
            </Link>
          </div>
        </div>

      </section>

      <section className="result-anatomy" id="hasil">
        <div className="result-anatomy__heading">
          <span>Isi hasil verifikasi</span>
          <h2>Satu hasil. Lima hal yang perlu kamu tahu.</h2>
          <p>
            Temuan disusun dari kesimpulan hingga tindakan, sehingga bagian terpenting dapat dibaca
            lebih dahulu.
          </p>
        </div>
        <div className="result-anatomy__rail">
          {resultParts.map(([title, copy], index) => (
            <article className="result-part" key={title}>
              <span>0{index + 1}</span>
              <h3>{title}</h3>
              <p>{copy}</p>
            </article>
          ))}
        </div>
      </section>

      <section className="evidence-feature">
        <div className="evidence-feature__image" role="img" aria-label="Dua orang memeriksa informasi pada ponsel di kafe" />
        <div className="evidence-feature__copy">
          <span>Bukti sebelum keyakinan</span>
          <h2>“Belum dapat diverifikasi” adalah jawaban yang penting.</h2>
          <p>
            WaspadAI tidak mengarang kepastian. Saat sumber lemah, bertentangan, atau belum tersedia,
            hasil akan menjaga keraguan itu tetap terlihat.
          </p>
          <Link href="/about">Pelajari cara kami bekerja <ArrowUpRight size={18} /></Link>
        </div>
      </section>

      <section className="home-final-cta">
        <div className="home-final-cta__image" aria-hidden="true" />
        <div className="home-final-cta__wash" aria-hidden="true" />
        <div className="home-final-cta__content">
          <span>Mulai dari informasi yang membuatmu ragu</span>
          <h2>Berhenti sejenak. Periksa sebelum bertindak.</h2>
          <Link className="button button--primary" href="/chat">
            Mulai periksa <ArrowUpRight size={19} />
          </Link>
        </div>
      </section>

      <SiteFooter />
    </main>
  );
}
