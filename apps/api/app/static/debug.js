const traceList = document.querySelector("#traceList");
const traceEmpty = document.querySelector("#traceEmpty");
const detailEmpty = document.querySelector("#detailEmpty");
const traceDetail = document.querySelector("#traceDetail");
const searchInput = document.querySelector("#traceSearch");
const inputFilter = document.querySelector("#inputFilter");
const statusFilter = document.querySelector("#statusFilter");
const refreshButton = document.querySelector("#refreshButton");
const debugStatus = document.querySelector("#debugStatus");
const toast = document.querySelector("#toast");

let traces = [];
let selectedTraceId = new URLSearchParams(window.location.search).get("trace_id");
let selectedTrace = null;
let rateLimitSnapshot = null;
let toastTimer = null;

init();

async function init() {
  searchInput.addEventListener("input", renderTraceList);
  inputFilter.addEventListener("change", renderTraceList);
  statusFilter.addEventListener("change", renderTraceList);
  refreshButton.addEventListener("click", () => loadTraces(true));
  traceList.addEventListener("click", (event) => {
    const button = event.target.closest("[data-trace-id]");
    if (button) selectTrace(button.dataset.traceId);
  });
  document.querySelector("#stageTimeline").addEventListener("click", handleTimelineClick);
  await loadTraces(false);
  window.setInterval(() => loadTraces(false), 5000);
  window.setInterval(updateRateLimitCountdowns, 1000);
}

async function loadTraces(showSpinner) {
  if (showSpinner) refreshButton.classList.add("is-loading");
  try {
    const response = await fetch("/api/v1/debug/traces", { headers: { Accept: "application/json" } });
    if (!response.ok) throw new Error("Debug trace tidak tersedia.");
    const payload = await response.json();
    traces = payload.items || [];
    const retention = payload.retention || {};
    document.querySelector("#retentionNote").textContent = `${payload.count || 0}/${retention.max_records || 0} trace di memori · tidak persisten · raw input tidak disimpan`;
    setConnection("online", "Terhubung · refresh 5 dtk");
    renderTraceList();
    if (!selectedTraceId && traces.length) selectedTraceId = traces[0].trace_id;
    if (selectedTraceId) {
      const summary = traces.find((item) => item.trace_id === selectedTraceId);
      if (!selectedTrace || summary?.status === "RUNNING") await selectTrace(selectedTraceId, false);
    }
    await loadRateLimits();
  } catch (error) {
    setConnection("error", error.message || "Tidak terhubung");
    if (!traces.length) {
      traceEmpty.hidden = false;
      traceEmpty.querySelector("strong").textContent = "Log tidak tersedia";
    }
  } finally {
    refreshButton.classList.remove("is-loading");
  }
}

async function loadRateLimits() {
  try {
    const response = await fetch("/api/v1/debug/groq-rate-limits", { headers: { Accept: "application/json" } });
    if (!response.ok) throw new Error("Rate limit tidak tersedia.");
    rateLimitSnapshot = await response.json();
    renderRateLimits();
  } catch (error) {
    document.querySelector("#rateLimitStatus").textContent = "Tidak tersedia";
    document.querySelector("#rateLimitList").innerHTML = `<p class="rate-unobserved">${escapeHTML(error.message)}</p>`;
  }
}

function renderRateLimits() {
  const models = rateLimitSnapshot?.models || [];
  const observed = rateLimitSnapshot?.observed_model_count || 0;
  document.querySelector("#rateLimitStatus").textContent = `Referensi ${rateLimitSnapshot?.reference_plan || "—"} · ${observed}/${models.length} aktual`;
  document.querySelector("#rateLimitNotice").textContent = rateLimitSnapshot?.scope_notice || "";
  document.querySelector("#rateLimitList").innerHTML = models.map((item) => {
    const limits = item.reference_limits || {};
    const token = item.tokens || {};
    const request = item.requests || {};
    return `<div class="rate-limit-row">
      <div class="rate-model"><strong>${escapeHTML(item.model)}</strong><span>${escapeHTML((item.roles || []).join(" · "))}${item.observed ? ` · HTTP ${escapeHTML(item.status_code)}` : " · belum dipanggil"}</span></div>
      ${quotaValue("RPM", limits.rpm, null, "rpm")}
      ${quotaValue("RPD", limits.rpd, request, "rpd")}
      ${quotaValue("TPM", limits.tpm, token, "tpm")}
      ${quotaValue("TPD", limits.tpd, null, "tpd")}
      <div class="rate-reset">
        ${item.observed ? `<span><time data-reset-at="${escapeHTML(token.reset_at || "")}" data-reset-dimension="tpm">${formatCountdown(token.reset_at)}</time><small>reset TPM</small></span>
        <span><time data-reset-at="${escapeHTML(request.reset_at || "")}" data-reset-dimension="rpd">${formatCountdown(request.reset_at)}</time><small>reset RPD</small></span>` : '<span class="rate-unobserved">Menunggu respons live</span>'}
        ${item.retry_after_seconds != null ? `<span><time>${formatSeconds(item.retry_after_seconds)}</time><small>retry-after (429)</small></span>` : ""}
      </div>
    </div>`;
  }).join("");
}

function quotaValue(label, referenceLimit, observedDimension, key) {
  const limit = observedDimension?.limit ?? referenceLimit;
  const remaining = observedDimension?.remaining;
  const limitAttribute = limit == null ? "" : String(limit);
  if (limit == null) {
    return `<div class="quota-value" data-label="${label}"><b>—</b><small>tidak dipublikasikan Groq</small></div>`;
  }
  if (observedDimension?.window_state === "RESET_ELAPSED_AWAITING_OBSERVATION") {
    return `<div class="quota-value is-awaiting" data-label="${label}" data-rate-value="${key}" data-rate-limit="${limitAttribute}"><b>${quotaNumber(limit)}</b><small>jatah ${label} · sisa menunggu snapshot</small></div>`;
  }
  if (remaining != null) {
    const percent = limit > 0 ? Math.max(0, Math.min(100, remaining / limit * 100)) : 0;
    return `<div class="quota-value is-live" data-label="${label}" data-rate-value="${key}" data-rate-limit="${limitAttribute}"><b>${quotaNumber(remaining)} / ${quotaNumber(limit)}</b><small>sisa / jatah · header aktual</small><span class="rate-meter"><i class="${percent < 15 ? "is-low" : ""}" style="width:${percent.toFixed(2)}%"></i></span></div>`;
  }
  return `<div class="quota-value" data-label="${label}" data-rate-value="${key}" data-rate-limit="${limitAttribute}"><b>${quotaNumber(limit)}</b><small>jatah ${label} · referensi ${escapeHTML(rateLimitSnapshot?.reference_plan || "plan")}</small></div>`;
}

function updateRateLimitCountdowns() {
  document.querySelectorAll("[data-reset-at]").forEach((node) => {
    if (!node.dataset.resetAt) {
      node.textContent = "—";
      return;
    }
    const seconds = secondsUntil(node.dataset.resetAt);
    node.textContent = formatSeconds(seconds);
    if (seconds === 0) markRateWindowElapsed(node);
  });
}

function markRateWindowElapsed(timerNode) {
  const dimension = timerNode.dataset.resetDimension;
  const valueNode = timerNode.closest(".rate-limit-row")?.querySelector(`[data-rate-value="${dimension}"]`);
  if (!valueNode || valueNode.classList.contains("is-awaiting")) return;
  const limit = Number(valueNode.dataset.rateLimit);
  valueNode.className = "quota-value is-awaiting";
  valueNode.innerHTML = `<b>${quotaNumber(limit)}</b><small>jatah ${dimension.toUpperCase()} · sisa menunggu snapshot</small>`;
}

function quotaNumber(value) {
  return Number(value).toLocaleString("id-ID");
}

function formatCountdown(resetAt) {
  if (!resetAt) return "—";
  return formatSeconds(secondsUntil(resetAt));
}

function secondsUntil(resetAt) {
  return Math.max(0, Math.ceil((new Date(resetAt).getTime() - Date.now()) / 1000));
}

function formatSeconds(totalSeconds) {
  const seconds = Math.max(0, Math.ceil(Number(totalSeconds) || 0));
  const days = Math.floor(seconds / 86400);
  const hours = Math.floor(seconds % 86400 / 3600);
  const minutes = Math.floor(seconds % 3600 / 60);
  const rest = seconds % 60;
  if (days) return `${days}h ${hours}j ${minutes}m ${rest}d`;
  if (hours) return `${hours}j ${minutes}m ${rest}d`;
  if (minutes) return `${minutes}m ${rest}d`;
  return `${rest} detik`;
}

function renderTraceList() {
  const query = searchInput.value.trim().toLowerCase();
  const input = inputFilter.value;
  const status = statusFilter.value;
  const filtered = traces.filter((trace) => {
    const haystack = [trace.trace_id, trace.request_id, trace.label, trace.summary?.verdict, trace.summary?.headline].join(" ").toLowerCase();
    return (!query || haystack.includes(query))
      && (input === "ALL" || trace.input_type === input)
      && (status === "ALL" || trace.status === status);
  });
  traceEmpty.hidden = filtered.length > 0;
  traceList.innerHTML = filtered.map((trace) => {
    const statusClass = String(trace.status || "running").toLowerCase();
    return `<button class="trace-item ${trace.trace_id === selectedTraceId ? "is-active" : ""}" type="button" data-trace-id="${escapeHTML(trace.trace_id)}" aria-pressed="${trace.trace_id === selectedTraceId}">
      <span class="trace-item-top"><span class="modality">${escapeHTML(trace.input_type)} · ${escapeHTML(trace.mode)}</span><time class="trace-time">${formatTime(trace.started_at)}</time></span>
      <strong>${escapeHTML(trace.label || trace.trace_id)}</strong>
      <p>${escapeHTML(trace.summary?.headline || "Pipeline sedang diproses")}</p>
      <span class="trace-item-foot"><span>${escapeHTML(shortId(trace.trace_id))}</span><span class="mini-status ${statusClass}">${escapeHTML(statusLabel(trace.status))}</span></span>
    </button>`;
  }).join("");
}

async function selectTrace(traceId, updateUrl = true) {
  selectedTraceId = traceId;
  renderTraceList();
  try {
    const response = await fetch(`/api/v1/debug/traces/${encodeURIComponent(traceId)}`);
    if (!response.ok) throw new Error("Trace sudah tidak tersedia di memori.");
    selectedTrace = await response.json();
    if (updateUrl) window.history.replaceState({}, "", `/debug?trace_id=${encodeURIComponent(traceId)}`);
    renderTraceDetail(selectedTrace);
  } catch (error) {
    showToast(error.message);
  }
}

function renderTraceDetail(trace) {
  detailEmpty.hidden = true;
  traceDetail.hidden = false;
  document.querySelector("#traceKicker").textContent = `${trace.input_type} · ${trace.mode} · ${formatDate(trace.started_at)}`;
  document.querySelector("#traceTitle").textContent = trace.label || trace.trace_id;
  document.querySelector("#traceHeadline").textContent = trace.summary?.headline || trace.error?.message || "Pipeline masih berjalan.";
  const statusNode = document.querySelector("#traceStatus");
  statusNode.className = `status-pill ${String(trace.status).toLowerCase()}`;
  statusNode.textContent = statusLabel(trace.status);
  document.querySelector("#traceMeta").innerHTML = [
    ["Trace", trace.trace_id],
    ["Request", trace.request_id],
    ["Durasi", formatDuration(trace.duration_ms)],
    ["Verdict", trace.summary?.verdict || "—"],
    ["Risk", trace.summary?.risk_level || "—"],
  ].map(([term, value]) => `<div><dt>${escapeHTML(term)}</dt><dd>${escapeHTML(value)}</dd></div>`).join("");
  const privacy = trace.privacy || {};
  document.querySelector("#privacyBanner").textContent = `Privacy boundary: raw input ${privacy.raw_input_stored ? "tersimpan" : "tidak disimpan"}; binary gambar ${privacy.image_binary_stored ? "tersimpan" : "tidak disimpan"}; kredensial ${privacy.credentials_stored ? "tersimpan" : "tidak disimpan"}. Retensi: ${privacy.persistence || "memori sementara"}.`;
  const stages = trace.stages || [];
  document.querySelector("#stageCount").textContent = `${stages.length} tahap tercatat`;
  document.querySelector("#stageTimeline").innerHTML = stages.map((stage, index) => renderStage(stage, index)).join("");
}

function renderStage(stage, index) {
  const status = String(stage.status || "COMPLETED").toLowerCase();
  const initialView = stage.output != null ? "output" : stage.input != null ? "input" : "instruction";
  const payload = viewPayload(stage, initialView);
  const shouldOpen = index === 0 || stage.status === "FAILED";
  return `<details class="stage" data-sequence="${String(stage.sequence || index + 1).padStart(2, "0")}" ${shouldOpen ? "open" : ""}>
    <summary>
      <span><span class="stage-title-row"><strong>${escapeHTML(stage.label)}</strong><span class="stage-key">${escapeHTML(stage.key)}</span></span><span class="stage-runtime">${escapeHTML(stage.runtime || "LOCAL")}${stage.model ? ` · ${escapeHTML(stage.model)}` : ""}</span></span>
      <span class="stage-state"><i class="state-dot ${status}"></i>${escapeHTML(statusLabel(stage.status))} · ${formatDuration(stage.duration_ms)}</span>
    </summary>
    <div class="stage-body" data-stage-index="${index}" data-current-view="${initialView}">
      <nav class="stage-tabs" aria-label="Detail tahap ${escapeHTML(stage.label)}">
        ${tabButton("output", "Output", initialView, stage.output != null)}
        ${tabButton("input", "Input aman", initialView, stage.input != null)}
        ${tabButton("instruction", "Instruksi", initialView, stage.instruction != null)}
        ${tabButton("notes", "Catatan", initialView, (stage.notes || []).length > 0)}
      </nav>
      <div class="payload-pane"><button class="copy-button" type="button" data-copy-payload>Salin JSON</button><pre>${escapeHTML(formatJson(payload))}</pre></div>
    </div>
  </details>`;
}

function tabButton(view, label, activeView, enabled) {
  if (!enabled) return "";
  return `<button class="stage-tab ${view === activeView ? "is-active" : ""}" type="button" data-stage-view="${view}">${label}</button>`;
}

function handleTimelineClick(event) {
  const body = event.target.closest(".stage-body");
  if (!body) return;
  const stage = selectedTrace?.stages?.[Number(body.dataset.stageIndex)];
  if (!stage) return;
  const tab = event.target.closest("[data-stage-view]");
  if (tab) {
    body.dataset.currentView = tab.dataset.stageView;
    body.querySelectorAll(".stage-tab").forEach((node) => node.classList.toggle("is-active", node === tab));
    body.querySelector("pre").textContent = formatJson(viewPayload(stage, tab.dataset.stageView));
  }
  if (event.target.closest("[data-copy-payload]")) {
    navigator.clipboard.writeText(formatJson(viewPayload(stage, body.dataset.currentView)))
      .then(() => showToast("Payload disalin."))
      .catch(() => showToast("Browser menolak akses clipboard."));
  }
}

function viewPayload(stage, view) {
  if (view === "notes") return stage.notes || [];
  return stage[view];
}

function setConnection(kind, message) {
  debugStatus.className = `connection-status is-${kind}`;
  debugStatus.innerHTML = `<i></i>${escapeHTML(message)}`;
}

function showToast(message) {
  window.clearTimeout(toastTimer);
  toast.textContent = message;
  toast.hidden = false;
  toastTimer = window.setTimeout(() => { toast.hidden = true; }, 2200);
}

function formatJson(value) {
  if (value == null) return "Tidak ada payload untuk tahap ini.";
  return JSON.stringify(value, null, 2);
}

function formatDuration(value) {
  if (value == null) return "berjalan";
  return `${Number(value).toLocaleString("id-ID")} ms`;
}

function formatTime(value) {
  if (!value) return "—";
  return new Intl.DateTimeFormat("id-ID", { hour: "2-digit", minute: "2-digit", second: "2-digit" }).format(new Date(value));
}

function formatDate(value) {
  if (!value) return "—";
  return new Intl.DateTimeFormat("id-ID", { dateStyle: "medium", timeStyle: "medium" }).format(new Date(value));
}

function shortId(value) {
  return String(value || "").replace("trace_", "").slice(0, 9);
}

function statusLabel(value) {
  return ({ COMPLETED: "Selesai", FAILED: "Gagal", RUNNING: "Berjalan", SKIPPED: "Dilewati", FALLBACK: "Fallback" })[value] || String(value || "—");
}

function escapeHTML(value) {
  return String(value ?? "").replace(/[&<>'"]/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" })[char]);
}
