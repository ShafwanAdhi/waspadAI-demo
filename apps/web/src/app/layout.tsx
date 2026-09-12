import type { Metadata } from "next";
import { JetBrains_Mono, Outfit } from "next/font/google";
import "./globals.css";

const outfit = Outfit({
  subsets: ["latin"],
  variable: "--font-outfit",
  display: "swap",
});

const jetBrainsMono = JetBrains_Mono({
  subsets: ["latin"],
  variable: "--font-mono",
  display: "swap",
});

export const metadata: Metadata = {
  title: {
    default: "WaspadAI — Periksa sebelum bertindak",
    template: "%s | WaspadAI",
  },
  description:
    "WaspadAI membantu kamu memeriksa informasi mencurigakan, memahami risikonya, dan menentukan langkah berikutnya.",
  icons: {
    icon: "/images/waspadai-logo.png",
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="id" data-scroll-behavior="smooth">
      <body className={`${outfit.variable} ${jetBrainsMono.variable}`}>
        {children}
      </body>
    </html>
  );
}
