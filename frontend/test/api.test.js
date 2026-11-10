import assert from "node:assert/strict";
import { afterEach, test } from "node:test";

import {
  adaptBackendVoiceResponse,
  adaptCustomers,
  adaptLedger,
  adaptSummary,
  formatBackendError,
  isUndoSuccessful,
  ledgerEntryClass,
  postConfirm,
  postUndo,
  postText,
  postVoice,
  sortCustomersByBalance,
} from "../api.js";
import { makePlayableAudio } from "../voice.js";

const originalFetch = globalThis.fetch;

afterEach(() => {
  globalThis.fetch = originalFetch;
});

function jsonResponse(data, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "content-type": "application/json" },
  });
}

test("adapts a voice envelope with nested transaction result", async () => {
  globalThis.fetch = async () => jsonResponse({
    transcript: "రాము దగ్గర ఐదు వందల రూపాయలు అప్పు ఇచ్చాను",
    result: {
      status: "confirmation_required",
      pending_id: 18,
      customer: { customer_id: 4, customer_name: "రాము" },
      transaction: {
        transaction_type: "credit",
        amount: 500,
        description: "కిరాణా సరుకులు",
        items: [{ name: "బియ్యం", quantity: 2, unit: "kg" }],
      },
    },
    spoken_reply: "నిర్ధారించండి",
    audio: { content_type: "audio/wav", data: "UklGRg==" },
    timings_ms: { total: 25 },
  });

  const result = await postVoice(new Blob(["audio"], { type: "audio/webm;codecs=opus" }));

  assert.equal(result.state, "transaction_confirmation");
  assert.equal(result.pendingId, "18");
  assert.equal(result.customerName, "రాము");
  assert.equal(result.amount, 500);
  assert.equal(result.items, "బియ్యం 2 kg");
  assert.equal(result.description, "కిరాణా సరుకులు");
  assert.equal(result.transcript, "రాము దగ్గర ఐదు వందల రూపాయలు అప్పు ఇచ్చాను");
  assert.deepEqual(result.replyAudio, {
    kind: "base64",
    value: "UklGRg==",
    contentType: "audio/wav",
  });
});

test("uploads voice with audio_file and keeps its MIME type and filename", async () => {
  let requestOptions;
  globalThis.fetch = async (_url, options) => {
    requestOptions = options;
    return jsonResponse({ result: { status: "unclear" }, transcript: "" });
  };
  const audio = new Blob(["audio"], { type: "audio/ogg" });

  await postVoice(audio, { pendingId: "12", language: "te-IN" });

  const form = requestOptions.body;
  assert.equal(form.get("audio_file").type, "audio/ogg");
  assert.equal(form.get("audio_file").name, "voice.ogg");
  assert.equal(form.get("pending_id"), "12");
  assert.equal(form.get("language"), "te-IN");
  assert.equal(form.has("audio"), false);
});

test("maps text confirmation_required and nested fields", async () => {
  globalThis.fetch = async (_url, options) => {
    assert.deepEqual(JSON.parse(options.body), { text: "రాము దగ్గర 500 అప్పు" });
    return jsonResponse({
      status: "confirmation_required",
      pending_id: 27,
      customer: { customer_id: 4, customer_name: "రాము" },
      transaction: { transaction_type: "credit", amount: 500, items: [] },
    });
  };

  const result = await postText("రాము దగ్గర 500 అప్పు");
  assert.equal(result.state, "transaction_confirmation");
  assert.equal(result.pendingId, "27");
  assert.equal(result.customerName, "రాము");
  assert.equal(result.amount, 500);
});

test("maps customer_creation_confirmation and its original pending ID", () => {
  const result = adaptBackendVoiceResponse({
    status: "customer_creation_confirmation",
    customer_name: "రాము",
    pending_id: 31,
    transaction: {
      transaction_type: "credit",
      amount: 500,
      description: "సరుకులు",
      items: [],
    },
  });

  assert.equal(result.state, "customer_creation_confirmation");
  assert.equal(result.pendingId, "31");
  assert.equal(result.customerName, "రాము");
  assert.equal(result.amount, 500);
});

test("keeps the new transaction pending ID after customer creation", async () => {
  globalThis.fetch = async (url) => {
    assert.equal(url, "/api/confirm/31");
    return jsonResponse({
      status: "confirmation_required",
      pending_id: 32,
      customer: { customer_id: 4, customer_name: "రాము" },
      transaction: { transaction_type: "credit", amount: 500, items: [] },
    });
  };

  const result = await postConfirm("31");
  assert.equal(result.state, "transaction_confirmation");
  assert.equal(result.pendingId, "32");
  assert.equal(result.customerName, "రాము");
});

test("decodes backend base64 WAV using the returned MIME type", async () => {
  const playable = makePlayableAudio({
    kind: "base64",
    value: "UklGRg==",
    contentType: "audio/wav",
  });
  try {
    const blob = await (await fetch(playable.url)).blob();
    assert.equal(blob.type, "audio/wav");
    assert.deepEqual(
      [...new Uint8Array(await blob.arrayBuffer())],
      [...Buffer.from("UklGRg==", "base64")],
    );
  } finally {
    URL.revokeObjectURL(playable.url);
  }
});

test("does not map unknown backend states to success", () => {
  const result = adaptBackendVoiceResponse({ status: "future_transaction_state" });
  assert.equal(result.state, "error");
});

test("preserves voice transcript and response details on backend errors", async () => {
  globalThis.fetch = async () => jsonResponse({
    transcript: "రాము",
    result: { status: "pipeline_failed", message: "Transaction processing failed." },
  }, 502);

  await assert.rejects(postVoice(new Blob(["audio"], { type: "audio/wav" })), (error) => {
    assert.equal(error.status, 502);
    assert.equal(error.detail, "Transaction processing failed.");
    assert.equal(error.responseData.transcript, "రాము");
    assert.equal(error.normalizedResponse.transcript, "రాము");
    assert.equal(error.normalizedResponse.state, "error");
    return true;
  });
});

test("undo sends the selected customer_id and accepts only a confirmed void", async () => {
  let requestBody;
  globalThis.fetch = async (_url, options) => {
    requestBody = JSON.parse(options.body);
    return jsonResponse({
      status: "voided",
      transaction_id: 9,
      balance: 0,
      transaction: { id: 9, is_voided: true },
    });
  };

  const result = await postUndo("42");

  assert.deepEqual(requestBody, { customer_id: 42 });
  assert.equal(isUndoSuccessful(result), true);
  assert.equal(isUndoSuccessful({ status: "error", transactionId: "9" }), false);
  assert.equal(isUndoSuccessful({ status: "voided" }), false);
});

test("undo without a selected customer rejects without calling the API", async () => {
  let calls = 0;
  globalThis.fetch = async () => {
    calls += 1;
    return jsonResponse({ status: "voided", transaction_id: 9 });
  };

  await assert.rejects(postUndo(null), { message: "CUSTOMER_REQUIRED" });
  assert.equal(calls, 0);
});

test("customer-list balances remain unavailable when the API omits them", () => {
  const customers = adaptCustomers({
    customers: [
      { id: 4, name: "Ramu", created_at: "2026-11-10" },
      { id: 8, name: "Sita", created_at: "2026-11-10" },
    ],
  });

  assert.deepEqual(customers.map((customer) => customer.balance), [null, null]);
  assert.deepEqual(sortCustomersByBalance(customers).map((customer) => customer.id), ["4", "8"]);
});

test("actual customer balances sort highest first", () => {
  const customers = adaptCustomers({
    customers: [
      { id: 1, name: "A", balance: 25 },
      { id: 2, name: "B", balance: 120 },
      { id: 3, name: "C", balance: 70 },
    ],
  });

  assert.deepEqual(sortCustomersByBalance(customers).map((customer) => customer.balance), [120, 70, 25]);
});

test("voided ledger entries are marked distinct and excluded from backend balance", () => {
  const ledger = adaptLedger({
    customer_id: 4,
    balance: 200,
    transactions: [
      { id: 1, transaction_type: "credit", amount: 500, is_voided: 0 },
      { id: 2, transaction_type: "credit", amount: 900, is_voided: 1 },
      { id: 3, transaction_type: "payment", amount: 300, is_voided: 0 },
    ],
  });

  assert.equal(ledger.balance, 200);
  assert.equal(ledger.entries[1].isVoided, true);
  assert.equal(ledgerEntryClass(ledger.entries[0]), "ledger-entry entry-credit");
  assert.equal(
    ledgerEntryClass(ledger.entries[1]),
    "ledger-entry entry-credit entry-voided",
  );
});

test("today summary maps actual API values and leaves unsupported dues unavailable", () => {
  const summary = adaptSummary({
    total_credits: 700,
    total_payments: 250,
    transaction_count: 4,
    total_dues: 9999,
  });

  assert.deepEqual(summary, {
    creditToday: 700,
    paymentsToday: 250,
    transactionCount: 4,
  });
  assert.equal(adaptSummary({}).creditToday, null);
});

test("backend string, object, and list errors are extracted safely", () => {
  assert.equal(formatBackendError({ detail: "Not found" }), "Not found");
  assert.equal(
    formatBackendError({ detail: { message: "Customer does not exist", code: "missing" } }),
    "Customer does not exist",
  );
  assert.equal(
    formatBackendError({ detail: [{ loc: ["body", "customer_id"], msg: "Field required" }] }),
    "Field required",
  );
});
