import Image from "next/image";
import Link from "next/link";

export function SiteFooter() {
  return (
    <footer className="site-footer">
      <div className="footer-shell">
        <div className="footer-brand">
          <Image
            className="footer-logo"
            src="/images/waspadai-logo.png"
            alt="WaspadAI"
            width={136}
            height={60}
          />
          <div>
            <strong>WaspadAI</strong>
            <p>Teman verifikasi untuk keputusan digital yang lebih aman.</p>
          </div>
        </div>

        <nav className="footer-group" aria-label="Navigasi footer">
          <span>Jelajahi</span>
          <Link href="/">Beranda</Link>
          <Link href="/chat">Periksa</Link>
          <Link href="/about">Tentang</Link>
        </nav>

        <div className="footer-group">
          <span>Prinsip</span>
          <p>Bukti sebelum keyakinan.</p>
          <p>Risiko dan fakta dipisahkan.</p>
          <p>Ketidakpastian tetap ditampilkan.</p>
        </div>
      </div>
      <div className="footer-meta">
        <span>© {new Date().getFullYear()} WaspadAI</span>
      </div>
    </footer>
  );
}
