import type { ReactNode } from "react";
import type {
  Evidence,
  VerificationResponse,
} from "@/lib/verification-api";

const verdictLabels: Record<VerificationResponse["verdict"], string> = {
  SUPPORTED: "Didukung bukti",
  REFUTED: "Terbantahkan",
  MISLEADING: "Menyesatkan",
  PARTLY_TRUE: "Sebagian benar",
  OUTDATED: "Sudah tidak berlaku",
  UNVERIFIED: "Belum terverifikasi",
  SATIRE: "Satire",
  OPINION: "Opini",
};

const riskLabels: Record<VerificationResponse["risk_level"], string> = {
  CRITICAL: "Sangat tinggi",
  HIGH: "Tinggi",
  MEDIUM: "Sedang",
  LOW: "Rendah",
  UNKNOWN: "Belum diketahui",
};

const stanceLabels: Record<Evidence["stance"], string> = {
  SUPPORTS: "Mendukung",
  REFUTES: "Membantah",
  CONTEXT: "Memberi konteks",
  UNKNOWN: "Belum jelas",
};

const verificationLabels: Record<Evidence["verification_status"], string> = {
  VERIFIED: "Terverifikasi",
  REVIEWED: "Telah ditinjau",
  UNVERIFIED: "Belum terverifikasi",
};

function formatDate(value: string | null): string | null {
  if (!value) return null;
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return new Intl.DateTimeFormat("id-ID", {
    day: "numeric",
    month: "long",
    year: "numeric",
  }).format(parsed);
}

function canonicalUrl(value: string): string {
  try {
    const url = new URL(value);
    url.hash = "";
    return url.toString().replace(/\/$/, "").toLowerCase();
  } catch {
    return value.trim().replace(/\/$/, "").toLowerCase();
  }
}

function ResultSection({
  eyebrow,
  title,
  children,
}: {
  eyebrow: string;
  title: string;
  children: ReactNode;
}) {
  return (
    <section className="report-section">
      <header className="report-section__head">
        <span>{eyebrow}</span>
        <h3>{title}</h3>
      </header>
      {children}
    </section>
  );
}

export function VerificationResult({ result }: { result: VerificationResponse }) {
  const isHighRisk = result.risk_level === "HIGH" || result.risk_level === "CRITICAL";
  const isLikelyScam = (
    (result.dimensions.scam_risk === "HIGH" || result.dimensions.scam_risk === "CRITICAL")
    && (
      result.dimensions.channel_status === "MALICIOUS"
      || result.dimensions.sender_identity === "IMPERSONATION_LIKELY"
      || result.dimensions.sender_identity === "IMPERSONATION_CONFIRMED"
    )
  );
  const evidenceLabelParts = result.evidence_sufficiency_label
    .replaceAll("â€”", " - ")
    .replaceAll("—", " - ")
    .split(" - ");
  const uniqueEvidence = result.evidence.filter((item, index, items) => {
    const signature = `${canonicalUrl(item.url)}|${item.title.trim().toLowerCase()}|${item.stance}`;
    return items.findIndex((candidate) => (
      `${canonicalUrl(candidate.url)}|${candidate.title.trim().toLowerCase()}|${candidate.stance}`
    ) === signature) === index;
  });
  const evidenceUrls = new Set(uniqueEvidence.map((item) => canonicalUrl(item.url)));
  const additionalSources = result.sources.filter((source, index, items) => {
    const url = canonicalUrl(source.url);
    return !evidenceUrls.has(url) && items.findIndex(
      (candidate) => canonicalUrl(candidate.url) === url,
    ) === index;
  });
  const score = Math.round(Math.max(0, Math.min(1, result.evidence_sufficiency)) * 100);

  return (
    <article
      className={`verification-report verification-report--${result.risk_level.toLowerCase()}`}
      aria-labelledby="verification-headline"
    >
      <details className="input-summary">
        <summary>
          <span>Informasi yang diperiksa</span>
        </summary>
        <div className="input-summary__body">
          <strong>{result.input_summary.label}</strong>
          <p>{result.input_summary.excerpt}</p>
          <dl>
            <div>
              <dt>Jenis input</dt>
              <dd>{result.input_summary.input_type === "IMAGE" ? "Gambar" : "Teks"}</dd>
            </div>
            <div>
              <dt>Jenis konten</dt>
              <dd>{result.input_summary.content_type.replaceAll("_", " ")}</dd>
            </div>
            <div>
              <dt>Tautan terdeteksi</dt>
              <dd>{result.input_summary.urls_detected}</dd>
            </div>
            {result.input_summary.dimensions && (
              <div>
                <dt>Dimensi gambar</dt>
                <dd>{result.input_summary.dimensions}</dd>
              </div>
            )}
          </dl>
        </div>
      </details>

      <header className="report-verdict">
        <div>
          <span className="report-kicker">Hasil pemeriksaan</span>
          <strong>{isLikelyScam ? "Patut diduga penipuan" : verdictLabels[result.verdict]}</strong>
        </div>
        <span className={`report-risk report-risk--${result.risk_level.toLowerCase()}`}>
          Risiko {riskLabels[result.risk_level]}
        </span>
        <h2 id="verification-headline">{result.headline}</h2>
      </header>

      {isHighRisk && result.recommended_actions.length > 0 && (
        <aside className="safety-alert" aria-label="Peringatan keselamatan">
          <div>
            <strong>Berhenti sebelum bertindak</strong>
            <p>{result.recommended_actions[0].detail}</p>
          </div>
        </aside>
      )}

      <div className="report-two-column">
        <ResultSection eyebrow="Penjelasan" title="Mengapa hasilnya demikian">
          <ul className="report-list report-list--numbered">
            {result.why.map((item, index) => (
              <li key={item}>
                <span>{String(index + 1).padStart(2, "0")}</span>
                <p>{item}</p>
              </li>
            ))}
          </ul>
        </ResultSection>

        <ResultSection eyebrow="Cakupan" title="Apa yang diperiksa">
          <ul className="report-list report-list--checked">
            {result.what_checked.map((item) => (
              <li key={item}>
                <span>{item}</span>
              </li>
            ))}
          </ul>
        </ResultSection>
      </div>

      <ResultSection eyebrow="Dasar penilaian" title="Kekuatan bukti">
        <div className="evidence-strength">
          <div className="evidence-strength__copy">
            <strong>{evidenceLabelParts[0].trim()}</strong>
            <p>
              {evidenceLabelParts.length > 1
                ? evidenceLabelParts.slice(1).join(" - ").trim()
                : "Skor menunjukkan kecukupan bukti, bukan probabilitas kebenaran."}
            </p>
          </div>
          <strong className="evidence-strength__score">{score}/100</strong>
          <div
            className="evidence-strength__meter"
            role="meter"
            aria-label="Skor kecukupan bukti"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={score}
          >
            <span style={{ width: `${score}%` }} />
          </div>
        </div>
      </ResultSection>

      <ResultSection eyebrow="Referensi" title="Bukti dan sumber">
        {uniqueEvidence.length > 0 ? (
          <div className="evidence-list">
            {uniqueEvidence.map((item) => (
              <article className="evidence-item" key={item.id}>
                <div className="evidence-item__meta">
                  <span className={`stance stance--${item.stance.toLowerCase()}`}>
                    {stanceLabels[item.stance]}
                  </span>
                  <span>{verificationLabels[item.verification_status]}</span>
                </div>
                <h4>{item.title}</h4>
                <p className="evidence-item__publisher">
                  {item.publisher}
                  {formatDate(item.published_at) ? ` · ${formatDate(item.published_at)}` : ""}
                </p>
                <p className="evidence-item__excerpt">{item.excerpt}</p>
                <a href={item.url} target="_blank" rel="noreferrer">
                  Buka sumber
                </a>
              </article>
            ))}
          </div>
        ) : (
          <div className="empty-evidence">
            <p>Belum ada bukti yang cukup untuk ditampilkan.</p>
          </div>
        )}

        {additionalSources.length > 0 && (
          <details className="additional-sources">
            <summary>Sumber tambahan ({additionalSources.length})</summary>
            <ul>
              {additionalSources.map((source) => (
                <li key={source.url}>
                  <a href={source.url} target="_blank" rel="noreferrer">
                    <span>{source.publisher}</span>
                    <strong>{source.title}</strong>
                  </a>
                </li>
              ))}
            </ul>
          </details>
        )}
      </ResultSection>

      <ResultSection eyebrow="Langkah berikutnya" title="Yang sebaiknya dilakukan">
        <ol className="recommended-actions">
          {result.recommended_actions.map((action, index) => (
            <li key={`${action.code}-${index}`}>
              <span>{String(index + 1).padStart(2, "0")}</span>
              <div>
                <strong>{action.title}</strong>
                <p>{action.detail}</p>
              </div>
            </li>
          ))}
        </ol>
      </ResultSection>
    </article>
  );
}
