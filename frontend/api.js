// api.js — Centralized API adapter for Kirana Voice Khata.
//
// All backend communication goes through this module so response-field
// mappings are isolated and easy to adjust when the real backend response
// shapes are verified against docs/api_notes.md.
//
// Each adapter function documents the expected fields. If a field is
// uncertain, it is mapped defensively with a clear fallback rather than
// silently guessed.

// Configurable API base URL.
// - Local dev: same-origin FastAPI server ("/").
// - Production: same-origin deployment ("/").
// Override at runtime via window.KVK_API_BASE if needed.
const BASE = (typeof window !== "undefined" && window.KVK_API_BASE) || "";

function url(path) {
  // Normalize: BASE + path (path should start with "/").
  return `${BASE}${path}`;
}

// ---- Low-level fetch wrapper ---------------------------------------------

async function apiFetch(path, options = {}) {
  const opts = {
    headers: {},
    ...options,
  };
  // Don't set Content-Type for FormData — browser sets the boundary.
  if (!(opts.body instanceof FormData) && !opts.headers["Content-Type"]) {
    opts.headers["Content-Type"] = "application/json";
  }
  let res;
  try {
    res = await fetch(url(path), opts);
  } catch (err) {
    // Network error / server unreachable.
    const e = new Error("NETWORK_ERROR");
    e.cause = err;
    throw e;
  }
  if (!res.ok) {
    let responseData = null;
    let detail = "";
    try {
      responseData = await res.json();
      detail = formatBackendError(responseData);
    } catch {
      responseData = null;
    }
    const e = new Error(`HTTP_${res.status}`);
    e.status = res.status;
    e.detail = detail;
    e.debugDetail = detail;
    e.responseData = responseData;
    throw e;
  }
  // Some endpoints may return empty bodies (204).
  if (res.status === 204) return null;
  const ct = res.headers.get("content-type") || "";
  if (ct.includes("application/json")) {
    return res.json();
  }
  // Non-JSON (e.g., raw audio blob).
  return res.blob();
}

// ---- Summary -------------------------------------------------------------
// GET /api/summary/today returns total_credits, total_payments, transaction_count.

export async function getTodaySummary() {
  const data = await apiFetch("/api/summary/today");
  return adaptSummary(data);
}

export function adaptSummary(data) {
  if (!data) return { creditToday: null, paymentsToday: null, transactionCount: null };
  return {
    creditToday: pickOptionalNum(data.total_credits),
    paymentsToday: pickOptionalNum(data.total_payments),
    transactionCount: pickOptionalNum(data.transaction_count),
  };
}

// ---- Customers -----------------------------------------------------------
// GET /api/customers
// Customer-list rows contain id, name, created_at; balance is unavailable.

export async function getCustomers() {
  const data = await apiFetch("/api/customers");
  return adaptCustomers(data);
}

export function adaptCustomers(data) {
  const list = Array.isArray(data) ? data : (data && data.customers) || [];
  return list.map((c) => ({
    id: pickStr(c, ["id", "customer_id"]),
    name: pickStr(c, ["name", "customer_name"]),
    balance: pickOptionalNum(c.balance),
    phone: pickStr(c, ["phone", "mobile", "phone_number"]),
  }));
}

export function sortCustomersByBalance(customers) {
  if (!customers.every((customer) => Number.isFinite(customer.balance))) {
    return [...customers];
  }
  return [...customers].sort((a, b) => b.balance - a.balance);
}

// ---- Ledger --------------------------------------------------------------
// GET /api/customers/{customer_id}/ledger
// Expected fields (VERIFY):
//   customer name + balance at top level
//   entries: array of:
//     id, type ("credit" | "payment"), amount, description/items, date/timestamp

export async function getLedger(customerId) {
  const data = await apiFetch(`/api/customers/${encodeURIComponent(customerId)}/ledger`);
  return adaptLedger(data);
}

export function adaptLedger(data) {
  if (!data) return { customerName: "", balance: null, entries: [] };
  const entries = Array.isArray(data.entries)
    ? data.entries
    : Array.isArray(data.transactions)
      ? data.transactions
      : Array.isArray(data)
        ? data
        : [];
  return {
    customerName: pickStr(data, ["customer_name", "name", "customerName"]),
    balance: pickOptionalNum(data.balance),
    entries: entries.map(adaptLedgerEntry),
  };
}

export function adaptLedgerEntry(e) {
  const rawType = pickStr(e, ["type", "transaction_type", "entry_type"], "").toLowerCase();
  // Normalize: "credit" / "payment" / "debit" / "paid".
  let type = "credit";
  if (rawType === "payment" || rawType === "paid" || rawType === "debit" || rawType === "receipt") {
    type = "payment";
  }
  const items = e.items || e.description || e.details || e.note || e.notes;
  return {
    id: pickStr(e, ["id", "entry_id", "transaction_id"]),
    type,
    amount: pickNum(e, ["amount", "value", "total"]),
    description: Array.isArray(items) ? items.join(", ") : (items || ""),
    date: pickStr(e, ["date", "timestamp", "created_at", "datetime", "time"]),
    isVoided: e.is_voided === true || e.is_voided === 1,
  };
}

export function ledgerEntryClass(entry) {
  const typeClass = entry.type === "credit" ? "entry-credit" : "entry-payment";
  return `ledger-entry ${typeClass}${entry.isVoided ? " entry-voided" : ""}`;
}

// ---- Voice ---------------------------------------------------------------
// POST /api/voice returns a response envelope; transaction data is in result.
export async function postVoice(audioBlob, { pendingId, language } = {}) {
  const formData = new FormData();
  const contentType = audioBlob.type || "application/octet-stream";
  const filename = audioBlob.name || `voice.${audioFileExtension(contentType)}`;
  formData.append("audio_file", audioBlob, filename);
  if (pendingId !== undefined && pendingId !== null) {
    formData.append("pending_id", String(pendingId));
  }
  if (language) formData.append("language", language);
  try {
    const data = await apiFetch("/api/voice", {
      method: "POST",
      body: formData,
    });
    return adaptBackendVoiceResponse(data);
  } catch (error) {
    if (error.responseData) {
      error.normalizedResponse = adaptBackendVoiceResponse(error.responseData);
    }
    throw error;
  }
}

// ---- Text ----------------------------------------------------------------
// POST /api/text
// Sends: { text: string }
// Returns: same shape as /api/voice.

export async function postText(text) {
  const data = await apiFetch("/api/text", {
    method: "POST",
    body: JSON.stringify({ text }),
  });
  return adaptBackendVoiceResponse(data);
}

// Adapt either the voice envelope or the direct pipeline response from /api/text.
export function adaptBackendVoiceResponse(data) {
  if (!data) {
    return { state: "error", message: "Empty response from server." };
  }
  const result = data.result && typeof data.result === "object" ? data.result : data;
  const transaction = result.transaction && typeof result.transaction === "object"
    ? result.transaction
    : {};
  const customer = result.customer && typeof result.customer === "object"
    ? result.customer
    : {};
  const state = normalizeState(
    pickStr(result, ["interaction_state", "state", "status"], ""),
  );
  const rawType = pickStr(
    transaction,
    ["transaction_type", "type", "entry_type"],
    pickStr(result, ["transaction_type", "type", "entry_type"], ""),
  ).toLowerCase();
  const rawItems = transaction.items || result.items || [];
  const items = Array.isArray(rawItems)
    ? rawItems.map((item) => {
      if (typeof item === "string") return item;
      if (!item || typeof item !== "object" || !item.name) return "";
      const quantity = item.quantity == null ? "" : ` ${item.quantity}`;
      const unit = item.unit ? ` ${item.unit}` : "";
      return `${item.name}${quantity}${unit}`;
    }).filter(Boolean).join(", ")
    : String(rawItems || "");
  const audio = data.audio;
  let replyAudio = null;
  if (audio && typeof audio === "object" && audio.data) {
    replyAudio = {
      kind: "base64",
      value: audio.data,
      contentType: audio.content_type || "application/octet-stream",
    };
  } else if (typeof audio === "string" && audio) {
    replyAudio = { kind: "base64", value: audio, contentType: "application/octet-stream" };
  } else if (audio && typeof audio === "object" && audio.url) {
    replyAudio = { kind: "url", value: audio.url };
  }

  return {
    state,
    status: pickStr(result, ["status"], ""),
    pendingId: pickStr(result, ["pending_id", "pendingId"], null),
    transactionId: pickStr(result, ["transaction_id"], null),
    intent: pickStr(result, ["intent"], ""),
    customerName: pickStr(
      customer,
      ["customer_name", "name"],
      pickStr(result, ["customer_name", "name"], pickStr(transaction, ["customer_name"], "")),
    ),
    txType: rawType === "payment" || rawType === "paid" || rawType === "debit"
      ? "payment"
      : rawType === "credit" ? "credit" : "",
    amount: pickNum(transaction, ["amount", "value", "total"], pickNum(result, ["amount"], 0)),
    items,
    description: pickStr(transaction, ["description"], pickStr(result, ["description"], "")),
    transcript: pickStr(data, ["transcript"], pickStr(result, ["transcript", "text"], "")),
    message: pickStr(
      result,
      ["message", "question", "question_en", "msg"],
      pickStr(data, ["spoken_reply"], ""),
    ),
    replyAudio,
    raw: data,
  };
}

function normalizeState(s) {
  const v = String(s || "").toLowerCase().replace(/[-\s]/g, "_");
  if (v === "customer_creation_confirmation" || v === "create_customer" || v === "new_customer") {
    return "customer_creation_confirmation";
  }
  if (v === "confirmation_required" || v === "transaction_confirmation" || v === "confirmation" || v === "confirm") {
    return "transaction_confirmation";
  }
  if (["confirmed", "cancelled", "voided", "success", "ok", "done", "completed", "balance", "daily_summary"].includes(v)) {
    return "success";
  }
  return "error";
}

// ---- Confirm / Cancel / Undo ---------------------------------------------

// POST /api/confirm/{pending_id}
export async function postConfirm(pendingId) {
  const data = await apiFetch(`/api/confirm/${encodeURIComponent(pendingId)}`, {
    method: "POST",
  });
  return adaptActionResult(data);
}

// POST /api/cancel/{pending_id}
export async function postCancel(pendingId) {
  const data = await apiFetch(`/api/cancel/${encodeURIComponent(pendingId)}`, {
    method: "POST",
  });
  return adaptActionResult(data);
}

// POST /api/undo
export async function postUndo(customerId) {
  if (!Number.isInteger(Number(customerId)) || Number(customerId) <= 0) {
    throw new Error("CUSTOMER_REQUIRED");
  }
  const data = await apiFetch("/api/undo", {
    method: "POST",
    body: JSON.stringify({ customer_id: Number(customerId) }),
  });
  return adaptActionResult(data);
}

export function adaptActionResult(data) {
  return adaptBackendVoiceResponse(data);
}

export function isUndoSuccessful(result) {
  return result?.status === "voided"
    && result.transactionId !== null
    && result.transactionId !== ""
    && Number.isInteger(Number(result.transactionId))
    && Number(result.transactionId) > 0;
}

// ---- Health check (for status indicator) ---------------------------------
// We piggyback on /api/summary/today; if it fails, we show offline.
export async function checkServer() {
  try {
    await getTodaySummary();
    return true;
  } catch {
    return false;
  }
}

// ---- Helpers --------------------------------------------------------------

function pickNum(obj, keys, fallback = 0) {
  for (const k of keys) {
    if (obj && obj[k] !== undefined && obj[k] !== null && obj[k] !== "") {
      const n = Number(obj[k]);
      if (!Number.isNaN(n)) return n;
    }
  }
  return fallback;
}

function pickOptionalNum(value) {
  if (value === undefined || value === null || value === "") return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function pickStr(obj, keys, fallback = "") {
  for (const k of keys) {
    if (obj && obj[k] !== undefined && obj[k] !== null && obj[k] !== "") {
      return String(obj[k]);
    }
  }
  return fallback;
}

export function formatBackendError(data) {
  const detail = data?.detail;
  const source = detail ?? data?.result ?? data;
  const messages = Array.isArray(source)
    ? source.map(errorItemMessage).filter(Boolean)
    : [errorItemMessage(source)].filter(Boolean);
  return messages.join("; ").slice(0, 240);
}

function errorItemMessage(item) {
  if (typeof item === "string") return item.trim();
  if (!item || typeof item !== "object") return "";
  return pickStr(item, ["message", "msg", "question", "status", "error"], "");
}

function audioFileExtension(contentType) {
  const mime = contentType.split(";")[0].toLowerCase();
  return {
    "audio/webm": "webm",
    "audio/ogg": "ogg",
    "audio/mp4": "mp4",
    "audio/wav": "wav",
    "audio/x-wav": "wav",
    "audio/mpeg": "mp3",
  }[mime] || "audio";
}

// Export the BASE for service-worker or other modules if needed.
export { BASE };
