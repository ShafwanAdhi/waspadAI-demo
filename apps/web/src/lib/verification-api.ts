import type { components } from "@/lib/api-schema";

export type VerificationResponse = components["schemas"]["VerificationResponse"];
export type Evidence = components["schemas"]["Evidence"];
export type AssessmentDimensions = components["schemas"]["AssessmentDimensions"];
export type OutputMode = "STRUCTURED" | "NARRATIVE" | "BOTH";

interface ApiErrorPayload {
  detail?: string | Array<{ msg?: string }>;
}

export class VerificationApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly retryAfterSeconds: number | null = null,
  ) {
    super(message);
    this.name = "VerificationApiError";
  }
}

function errorMessage(payload: ApiErrorPayload, fallback: string): string {
  if (typeof payload.detail === "string" && payload.detail.trim()) {
    return payload.detail;
  }
  if (Array.isArray(payload.detail)) {
    const messages = payload.detail
      .map((item) => item.msg?.trim())
      .filter((item): item is string => Boolean(item));
    if (messages.length) return messages.join(" ");
  }
  return fallback;
}

async function readResponse(response: Response): Promise<VerificationResponse> {
  let payload: VerificationResponse | ApiErrorPayload | null = null;
  try {
    payload = (await response.json()) as VerificationResponse | ApiErrorPayload;
  } catch {
    payload = null;
  }

  if (!response.ok) {
    const retryHeader = response.headers.get("retry-after");
    const retryAfter = retryHeader ? Number.parseInt(retryHeader, 10) : Number.NaN;
    throw new VerificationApiError(
      errorMessage(
        (payload ?? {}) as ApiErrorPayload,
        "Pemeriksaan belum dapat diselesaikan. Coba lagi.",
      ),
      response.status,
      Number.isFinite(retryAfter) ? Math.max(1, retryAfter) : null,
    );
  }

  return payload as VerificationResponse;
}

export async function verifyText(
  text: string,
  signal: AbortSignal,
  outputMode: OutputMode = "BOTH",
): Promise<VerificationResponse> {
  const response = await fetch("/api/v1/verify/text", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      text,
      question: "Apakah isi teks ini benar dan aman ditindaklanjuti?",
      sender_context: "UNKNOWN",
      output_mode: outputMode,
    }),
    cache: "no-store",
    signal,
  });
  return readResponse(response);
}

export async function verifyImage(
  image: File,
  question: string,
  signal: AbortSignal,
  outputMode: OutputMode = "BOTH",
): Promise<VerificationResponse> {
  const formData = new FormData();
  formData.append("image", image, image.name);
  formData.append(
    "question",
    question || "Apakah informasi dalam gambar ini benar dan aman ditindaklanjuti?",
  );
  formData.append("output_mode", outputMode);

  const response = await fetch("/api/v1/verify/image", {
    method: "POST",
    body: formData,
    cache: "no-store",
    signal,
  });
  return readResponse(response);
}
