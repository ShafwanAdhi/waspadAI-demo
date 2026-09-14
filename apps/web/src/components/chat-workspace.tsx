"use client";

import {
  ArrowUp,
  CircleNotch,
  ListBullets,
  Paperclip,
  TextAlignLeft,
  WarningCircle,
  X,
} from "@phosphor-icons/react/dist/ssr";
import Image from "next/image";
import { ChangeEvent, DragEvent, FormEvent, useEffect, useRef, useState } from "react";
import { VerificationResult } from "@/components/verification-result";
import {
  VerificationApiError,
  type OutputMode,
  type VerificationResponse,
  verifyImage,
  verifyText,
} from "@/lib/verification-api";

interface VerificationExample {
  question: string;
  image: string;
  imageAlt: string;
  imageName: string;
  imagePosition?: string;
}

interface AttachedImage {
  name: string;
  src: string;
  alt: string;
  file: File | null;
}

interface RequestError {
  message: string;
  retryAfterSeconds: number | null;
}

interface QuickExample {
  label: string;
  text: string;
}

type DisplayMode = "STRUCTURED" | "NARRATIVE";

const MAX_IMAGE_BYTES = 8 * 1024 * 1024;
const MIN_IMAGE_WIDTH = 64;
const MIN_IMAGE_HEIGHT = 64;
const MAX_IMAGE_WIDTH = 6000;
const MAX_IMAGE_HEIGHT = 6000;
const MAX_IMAGE_PIXELS = 30_000_000;
const MAX_TEXT_LENGTH = 25_000;
const MAX_IMAGE_QUESTION_LENGTH = 500;
const REQUEST_TIMEOUT_MS = 105_000;
const OUTPUT_MODE_STORAGE_KEY = "waspadai.outputMode";
const ACCEPTED_IMAGE_TYPES = new Set(["image/png", "image/jpeg", "image/webp"]);
const checkingMessages = [
  {
    title: "Membaca informasi...",
    detail: "Kami sedang memahami isi pesan dan bagian yang perlu diperiksa.",
  },
  {
    title: "Mencari pembanding...",
    detail: "Kami menelusuri petunjuk dan sumber yang relevan untuk membantu menilai informasi ini.",
  },
  {
    title: "Menimbang risiko...",
    detail: "Kami memisahkan bagian yang tampak aman, meragukan, atau perlu diwaspadai.",
  },
  {
    title: "Menyusun hasil...",
    detail: "Sebentar lagi hasil pemeriksaan ditampilkan dengan alasan dan langkah yang disarankan.",
  },
];

const quickExamples: QuickExample[] = [
  {
    label: "SpaceX Berhasil Me...",
    text: "SpaceX Berhasil Menangkap Booster Starship di Bogor untuk Pertama Kalinya. SpaceX mencatat pencapaian baru pada 13 Oktober 2024 setelah booster Super Heavy kembali ke Bumi dan berhasil ditangkap menggunakan lengan mekanis menara peluncuran di Bogor, Jawa Barat. Keberhasilan tersebut menjadi bagian dari penerbangan uji kelima sistem Starship.",
  },
  {
    label: "Astronaut NASA Ke...",
    text: "Astronaut NASA Suni Williams dan Butch Wilmore Akhirnya Kembali Menggunakan Boeing Starliner. Setelah menghabiskan sekitar sembilan bulan di International Space Station, astronaut NASA Suni Williams dan Butch Wilmore akhirnya kembali ke Bumi pada 18 Maret 2025 menggunakan Boeing Starliner, wahana yang sebelumnya membawa mereka menuju ISS.",
  },
  {
    label: "Indonesia Melarang...",
    text: "Indonesia Melarang iPhone 16 karena Masalah Overheating dan Keselamatan Baterai. Pemerintah Indonesia menghentikan penjualan resmi iPhone 16 pada Oktober 2024 setelah ditemukan kekhawatiran terkait baterai yang terlalu panas dan risiko keselamatan perangkat. Pemerintah meminta Apple menyelesaikan masalah tersebut sebelum perangkat dapat kembali dipasarkan.",
  },
  {
    label: "Pembukaan Olimpiade...",
    text: "Pembukaan Olimpiade Paris 2024 digelar dengan parade di Sungai Seine. Upacara pembukaan Paris 2024 berlangsung pada 26 Juli 2024, dengan delegasi atlet berparade menggunakan kapal di Sungai Seine.",
  },
];

const newsExamples: VerificationExample[] = [
  {
    question: 'Apakah informasi tentang berita bahwa "Indonesia menjadi tuan rumah FIFA ASEAN Cup 2026" ini benar?',
    image: "/images/examples/fifa-asean-cup-2026.jpeg",
    imageAlt: "Unggahan berita Indonesia menjadi tuan rumah FIFA ASEAN Cup 2026",
    imageName: "fifa-asean-cup-2026.jpeg",
  },
  {
    question: "Apakah berita tentang penurunan presiden ini benar?",
    image: "/images/examples/berita-penurunan-presiden.jpeg",
    imageAlt: "Cuplikan siaran dengan kabar upacara penurunan Presiden Prabowo Subianto",
    imageName: "berita-penurunan-presiden.jpeg",
  },
  {
    question: "Apakah informasi tentang kamar Seskab Teddy ini benar?",
    image: "/images/examples/kamar-seskab-teddy.jpeg",
    imageAlt: "Unggahan tentang kamar dan ruang kerja Seskab Teddy",
    imageName: "kamar-seskab-teddy.jpeg",
    imagePosition: "center 56%",
  },
];

const privateMessageExamples: VerificationExample[] = [
  {
    question: "Apakah URL dari nomor yang mengaku sebagai WhatsApp ini aman untuk ditindaklanjuti?",
    image: "/images/examples/pesan-whatsapp-palsu.jpeg",
    imageAlt: "Pesan yang mengaku sebagai peringatan resmi WhatsApp dan memuat tautan",
    imageName: "pesan-whatsapp-palsu.jpeg",
    imagePosition: "center 62%",
  },
  {
    question: "Apakah URL promo dari nomor yang mengaku sebagai Wingstop ini aman?",
    image: "/images/examples/promo-wingstop-sms.jpeg",
    imageAlt: "Pesan promo yang mengatasnamakan Wingstop dan memuat tautan",
    imageName: "promo-wingstop-sms.jpeg",
  },
  {
    question: "Apakah ada potensi penipuan dari pesan kejaksaan ini?",
    image: "/images/examples/pesan-kejaksaan-palsu.jpeg",
    imageAlt: "Pesan yang mengatasnamakan kejaksaan dan meminta pembayaran melalui tautan",
    imageName: "pesan-kejaksaan-palsu.jpeg",
    imagePosition: "center 42%",
  },
];

const exampleSections = [
  {
    title: "Contoh berita",
    description: "Pilih satu berita untuk mencoba pemeriksaan.",
    items: newsExamples,
  },
  {
    title: "Contoh pesan pribadi",
    description: "Pilih satu pesan untuk mencoba pemeriksaan.",
    items: privateMessageExamples,
  },
];

function readableError(error: unknown): RequestError {
  if (error instanceof VerificationApiError) {
    return { message: error.message, retryAfterSeconds: error.retryAfterSeconds };
  }
  if (error instanceof DOMException && error.name === "AbortError") {
    return {
      message: "Pemeriksaan memerlukan waktu terlalu lama. Coba lagi beberapa saat lagi.",
      retryAfterSeconds: null,
    };
  }
  if (error instanceof TypeError) {
    return {
      message: "Layanan pemeriksaan tidak dapat dihubungi. Pastikan backend sedang berjalan.",
      retryAfterSeconds: null,
    };
  }
  return {
    message: "Terjadi kendala saat memeriksa informasi. Coba lagi.",
    retryAfterSeconds: null,
  };
}

function imageDimensions(file: File): Promise<{ width: number; height: number }> {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file);
    const image = new window.Image();
    image.onload = () => {
      URL.revokeObjectURL(url);
      resolve({ width: image.naturalWidth, height: image.naturalHeight });
    };
    image.onerror = () => {
      URL.revokeObjectURL(url);
      reject(new Error("Gambar tidak dapat dibaca."));
    };
    image.src = url;
  });
}

export function ChatWorkspace() {
  const [input, setInput] = useState("");
  const [attachedImage, setAttachedImage] = useState<AttachedImage | null>(null);
  const [isChecking, setIsChecking] = useState(false);
  const [checkingStep, setCheckingStep] = useState(0);
  const [isDraggingImage, setIsDraggingImage] = useState(false);
  const [result, setResult] = useState<VerificationResponse | null>(null);
  const [displayMode, setDisplayMode] = useState<DisplayMode>(() => {
    if (typeof window === "undefined") return "STRUCTURED";
    const stored = window.localStorage.getItem(OUTPUT_MODE_STORAGE_KEY);
    return stored === "NARRATIVE" ? "NARRATIVE" : "STRUCTURED";
  });
  const [requestError, setRequestError] = useState<RequestError | null>(null);
  const [retryRemaining, setRetryRemaining] = useState(0);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const composerRef = useRef<HTMLFormElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const resultRef = useRef<HTMLDivElement>(null);
  const activeRequestRef = useRef<AbortController | null>(null);

  const inputLimit = attachedImage ? MAX_IMAGE_QUESTION_LENGTH : MAX_TEXT_LENGTH;
  const inputIsValid = attachedImage
    ? input.trim().length <= MAX_IMAGE_QUESTION_LENGTH
    : input.trim().length >= 10 && input.trim().length <= MAX_TEXT_LENGTH;
  const canSubmit = Boolean(attachedImage || input.trim()) && inputIsValid && retryRemaining === 0;

  useEffect(() => () => activeRequestRef.current?.abort(), []);

  useEffect(() => {
    if (retryRemaining <= 0) return;
    const timer = window.setInterval(
      () => setRetryRemaining((value) => Math.max(0, value - 1)),
      1000,
    );
    return () => window.clearInterval(timer);
  }, [retryRemaining]);

  useEffect(() => {
    if (!isChecking) return;
    const timer = window.setInterval(
      () => setCheckingStep((value) => Math.min(checkingMessages.length - 1, value + 1)),
      2600,
    );
    return () => window.clearInterval(timer);
  }, [isChecking]);

  useEffect(() => {
    if (!result) return;
    let timeout: number | undefined;
    const firstFrame = window.requestAnimationFrame(() => {
      window.requestAnimationFrame(() => {
        timeout = window.setTimeout(() => {
          const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
          const resultStart = resultRef.current?.querySelector(".input-summary");
          resultStart?.scrollIntoView({
            behavior: reduceMotion ? "auto" : "smooth",
            block: "start",
          });
        }, 80);
      });
    });
    return () => {
      window.cancelAnimationFrame(firstFrame);
      if (timeout) window.clearTimeout(timeout);
    };
  }, [result]);

  const attachImageFile = async (file: File) => {
    if (!ACCEPTED_IMAGE_TYPES.has(file.type)) {
      setRequestError({
        message: "Gunakan gambar PNG, JPG, JPEG, atau WebP.",
        retryAfterSeconds: null,
      });
      return false;
    }
    if (file.size > MAX_IMAGE_BYTES) {
      setRequestError({ message: "Ukuran gambar maksimal 8 MB.", retryAfterSeconds: null });
      return false;
    }

    try {
      const dimensions = await imageDimensions(file);
      if (dimensions.width < MIN_IMAGE_WIDTH || dimensions.height < MIN_IMAGE_HEIGHT) {
        setRequestError({
          message: `Dimensi gambar minimal ${MIN_IMAGE_WIDTH}x${MIN_IMAGE_HEIGHT} piksel.`,
          retryAfterSeconds: null,
        });
        return false;
      }
      if (dimensions.width > MAX_IMAGE_WIDTH || dimensions.height > MAX_IMAGE_HEIGHT) {
        setRequestError({
          message: `Dimensi gambar maksimal ${MAX_IMAGE_WIDTH}x${MAX_IMAGE_HEIGHT} piksel.`,
          retryAfterSeconds: null,
        });
        return false;
      }
      if (dimensions.width * dimensions.height > MAX_IMAGE_PIXELS) {
        setRequestError({
          message: "Jumlah piksel gambar maksimal 30 juta piksel.",
          retryAfterSeconds: null,
        });
        return false;
      }
    } catch {
      setRequestError({
        message: "Gambar tidak dapat dibaca. Gunakan file PNG, JPG, JPEG, atau WebP.",
        retryAfterSeconds: null,
      });
      return false;
    }

    const reader = new FileReader();
    reader.addEventListener("load", () => {
      if (typeof reader.result !== "string") return;
      setAttachedImage({
        name: file.name,
        src: reader.result,
        alt: `Pratinjau ${file.name}`,
        file,
      });
      setResult(null);
      setRequestError(null);
    });
    reader.readAsDataURL(file);
    return true;
  };

  const handleFile = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;
    const attached = await attachImageFile(file);
    if (!attached) event.target.value = "";
  };

  const draggedItemsContainImage = (event: DragEvent<HTMLFormElement>) => (
    Array.from(event.dataTransfer.items).some((item) => (
      item.kind === "file" && (!item.type || item.type.startsWith("image/"))
    ))
  );

  const handleComposerDragEnter = (event: DragEvent<HTMLFormElement>) => {
    if (!draggedItemsContainImage(event)) return;
    event.preventDefault();
    event.dataTransfer.dropEffect = "copy";
    setIsDraggingImage(true);
  };

  const handleComposerDragOver = (event: DragEvent<HTMLFormElement>) => {
    if (!draggedItemsContainImage(event)) return;
    event.preventDefault();
    event.dataTransfer.dropEffect = "copy";
    setIsDraggingImage(true);
  };

  const handleComposerDragLeave = (event: DragEvent<HTMLFormElement>) => {
    if (event.currentTarget.contains(event.relatedTarget as Node | null)) return;
    setIsDraggingImage(false);
  };

  const handleComposerDrop = async (event: DragEvent<HTMLFormElement>) => {
    event.preventDefault();
    setIsDraggingImage(false);
    const file = Array.from(event.dataTransfer.files).find((item) => item.type.startsWith("image/"));
    if (!file) {
      setRequestError({
        message: "Tarik file gambar PNG, JPG, JPEG, atau WebP ke kolom pemeriksaan.",
        retryAfterSeconds: null,
      });
      return;
    }
    const attached = await attachImageFile(file);
    if (attached && fileInputRef.current) fileInputRef.current.value = "";
  };

  const removeAttachedImage = () => {
    setAttachedImage(null);
    setResult(null);
    setRequestError(null);
    if (fileInputRef.current) fileInputRef.current.value = "";
  };

  const resolveImageFile = async (image: AttachedImage, signal: AbortSignal): Promise<File> => {
    if (image.file) return image.file;
    const response = await fetch(image.src, { signal });
    if (!response.ok) throw new Error("Gambar contoh tidak dapat dibaca.");
    const blob = await response.blob();
    return new File([blob], image.name, { type: blob.type || "image/jpeg" });
  };

  const submitVerification = async () => {
    if (!canSubmit || isChecking) return;

    activeRequestRef.current?.abort();
    const controller = new AbortController();
    activeRequestRef.current = controller;
    const timeout = window.setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);

    setIsChecking(true);
    setCheckingStep(0);
    setResult(null);
    setRequestError(null);

    try {
      const response = attachedImage
        ? await verifyImage(
            await resolveImageFile(attachedImage, controller.signal),
            input.trim(),
            controller.signal,
            requestedOutputMode,
          )
        : await verifyText(input.trim(), controller.signal, requestedOutputMode);
      setResult(response);
    } catch (error) {
      const readable = readableError(error);
      setRequestError(readable);
      setRetryRemaining(readable.retryAfterSeconds ?? 0);
    } finally {
      window.clearTimeout(timeout);
      if (activeRequestRef.current === controller) activeRequestRef.current = null;
      setIsChecking(false);
      setCheckingStep(0);
    }
  };

  const runCheck = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    void submitVerification();
  };

  const scrollToComposer = () => {
    window.requestAnimationFrame(() => {
      const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      composerRef.current?.scrollIntoView({
        behavior: reduceMotion ? "auto" : "smooth",
        block: "center",
      });
      textareaRef.current?.focus({ preventScroll: true });
    });
  };

  const applyExample = (item: VerificationExample) => {
    setInput(item.question);
    setAttachedImage({
      name: item.imageName,
      src: item.image,
      alt: item.imageAlt,
      file: null,
    });
    setResult(null);
    setRequestError(null);
    scrollToComposer();
  };

  const applyQuickExample = (example: QuickExample) => {
    setInput(example.text);
    setAttachedImage(null);
    setResult(null);
    setRequestError(null);
    if (fileInputRef.current) fileInputRef.current.value = "";
    scrollToComposer();
  };

  const changeDisplayMode = (mode: DisplayMode) => {
    setDisplayMode(mode);
    window.localStorage.setItem(OUTPUT_MODE_STORAGE_KEY, mode);
  };

  return (
    <section className="verify-lab" aria-labelledby="verify-title">
      <div className="verify-lab__intro">
        <h1 id="verify-title">Periksa informasi Anda di sini</h1>
        <p>Masukkan pesan, tautan berita, gambar, atau informasi lain yang ingin diperiksa.</p>
      </div>

      <div className="verify-console">
        <form
          ref={composerRef}
          className={`checker-form verify-composer${isDraggingImage ? " verify-composer--dragging" : ""}`}
          onSubmit={runCheck}
          onDragEnter={handleComposerDragEnter}
          onDragOver={handleComposerDragOver}
          onDragLeave={handleComposerDragLeave}
          onDrop={handleComposerDrop}
        >
          {attachedImage && (
            <div className="attached-image">
              <div className="attached-image__preview">
                <Image src={attachedImage.src} alt={attachedImage.alt} fill sizes="240px" unoptimized />
                <button type="button" aria-label="Hapus gambar" onClick={removeAttachedImage}>
                  <X size={16} weight="bold" />
                </button>
              </div>
              <span title={attachedImage.name}>{attachedImage.name}</span>
            </div>
          )}
          <textarea
            ref={textareaRef}
            value={input}
            maxLength={inputLimit}
            onChange={(event) => {
              setInput(event.target.value);
              setResult(null);
              setRequestError(null);
            }}
            placeholder={
              attachedImage
                ? "Tulis pertanyaan atau konteks singkat tentang gambar..."
                : "Tulis atau tempel informasi yang ingin diperiksa..."
            }
            aria-label="Informasi yang ingin diperiksa"
          />
          <input
            ref={fileInputRef}
            className="visually-hidden"
            type="file"
            accept="image/png,image/jpeg,image/webp"
            onChange={handleFile}
          />
          <div className="composer-actions">
            <button
              className="attach-button"
              type="button"
              aria-label="Lampirkan gambar"
              title="Lampirkan gambar"
              onClick={() => fileInputRef.current?.click()}
            >
              <Paperclip size={19} />
            </button>
            <span className="composer-context">
              {attachedImage ? `Pertanyaan gambar · maks. ${inputLimit} karakter` : "Teks atau tautan"}
            </span>
            <button className="submit-check" type="submit" disabled={isChecking || !canSubmit}>
              {isChecking ? <CircleNotch className="spin" size={19} /> : <ArrowUp size={19} />}
              {isChecking
                ? "Memeriksa"
                : retryRemaining > 0
                  ? `Tunggu ${retryRemaining} dtk`
                  : "Periksa"}
            </button>
          </div>
          <div className="quick-examples" aria-label="Contoh cepat">
            <span>Contoh cepat</span>
            <div className="quick-examples__list">
              {quickExamples.map((example) => (
                <button
                  type="button"
                  key={example.label}
                  title={example.text}
                  onClick={() => applyQuickExample(example)}
                >
                  {example.label}
                </button>
              ))}
            </div>
          </div>
        </form>

        {isChecking && (
          <div className="checking-state" role="status" aria-live="polite">
            <div>
              <strong>{checkingMessages[checkingStep].title}</strong>
              <p>{checkingMessages[checkingStep].detail}</p>
            </div>
          </div>
        )}

        {requestError && (
          <div className="request-error" role="alert">
            <WarningCircle size={23} weight="fill" />
            <div>
              <strong>Pemeriksaan belum selesai</strong>
              <p>{requestError.message}</p>
              {!isChecking && (
                <button type="button" onClick={() => void submitVerification()} disabled={retryRemaining > 0}>
                  {retryRemaining > 0 ? `Coba lagi dalam ${retryRemaining} detik` : "Coba lagi"}
                </button>
              )}
            </div>
          </div>
        )}

        <div ref={resultRef} className="verification-result-anchor">
          {result && (
            <>
              <div className="result-view-switch" aria-label="Mode tampilan hasil">
                <button
                  type="button"
                  aria-pressed={displayMode === "STRUCTURED"}
                  onClick={() => changeDisplayMode("STRUCTURED")}
                >
                  <ListBullets size={17} />
                  Poin-poin
                </button>
                <button
                  type="button"
                  aria-pressed={displayMode === "NARRATIVE"}
                  onClick={() => changeDisplayMode("NARRATIVE")}
                >
                  <TextAlignLeft size={17} />
                  Naratif
                </button>
              </div>
              <VerificationResult result={result} displayMode={displayMode} />
            </>
          )}
        </div>
      </div>

      {!result && !isChecking && exampleSections.map((section) => (
        <div className="news-starters" key={section.title}>
          <div className="news-starters__head">
            <h2>{section.title}</h2>
            <p>{section.description}</p>
          </div>
          <div className="news-grid">
            {section.items.map((item) => (
              <button
                className="news-card"
                type="button"
                key={item.question}
                aria-pressed={attachedImage?.src === item.image}
                onClick={() => applyExample(item)}
              >
                <span className="news-card__image">
                  <Image
                    src={item.image}
                    alt={item.imageAlt}
                    fill
                    sizes="(max-width: 600px) 33vw, (max-width: 920px) 33vw, 254px"
                    style={{ objectPosition: item.imagePosition ?? "center" }}
                  />
                </span>
                <span className="news-card__body"><strong>{item.question}</strong></span>
              </button>
            ))}
          </div>
        </div>
      ))}
    </section>
  );
}
    const requestedOutputMode: OutputMode = "BOTH";
