import type { Metadata } from "next";
import { AboutExperience } from "@/components/about-experience";
import { SiteFooter } from "@/components/site-footer";
import { SiteHeader } from "@/components/site-header";

export const metadata: Metadata = {
  title: "Tentang",
  description:
    "Kenali WaspadAI, pahami alur pemeriksaannya, dan temui pengembang di balik proyek ini.",
};

export default function AboutPage() {
  return (
    <main className="inner-page about-page overflow-guard">
      <SiteHeader />
      <AboutExperience />
      <SiteFooter />
    </main>
  );
}
