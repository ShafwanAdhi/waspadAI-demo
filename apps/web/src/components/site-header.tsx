"use client";

import { List, X } from "@phosphor-icons/react/dist/ssr";
import Image from "next/image";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";

const navigation = [
  { href: "/", label: "Beranda" },
  { href: "/chat", label: "Periksa" },
  { href: "/about", label: "Tentang" },
];

export function SiteHeader({ tone = "light" }: { tone?: "light" | "dark" }) {
  const pathname = usePathname();
  const [open, setOpen] = useState(false);

  return (
    <header className={`site-header site-header--${tone}`}>
      <div className="header-shell">
        <Link className="brand" href="/" aria-label="WaspadAI beranda">
          <Image
            className="brand-logo"
            src="/images/waspadai-logo.png"
            alt="WaspadAI"
            width={136}
            height={60}
            priority
          />
          <span className="brand-copy" aria-hidden="true">
            <strong>WaspadAI</strong>
            <span>(Demo Version)</span>
          </span>
        </Link>

        <nav className={`main-nav ${open ? "main-nav--open" : ""}`} aria-label="Navigasi utama">
          {navigation.map((item) => (
            <Link
              key={item.href}
              className={pathname === item.href ? "nav-link nav-link--active" : "nav-link"}
              href={item.href}
              onClick={() => setOpen(false)}
            >
              {item.label}
            </Link>
          ))}
        </nav>

        <button
          className="menu-button"
          type="button"
          aria-label={open ? "Tutup menu" : "Buka menu"}
          aria-expanded={open}
          onClick={() => setOpen((value) => !value)}
        >
          {open ? <X size={22} /> : <List size={22} />}
        </button>
      </div>
    </header>
  );
}
