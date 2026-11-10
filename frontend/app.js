// app.js — Main controller for Kirana Voice Khata.
//
// Manages the UI state machine, wires DOM events to API/voice modules,
// and renders dynamic content. Imports from i18n.js, api.js, voice.js.

import { t, formatDateTe, formatDateShortTe, formatRupees } from "./i18n.js";
import {
  getTodaySummary,
  getCustomers,
  getLedger,
  postVoice,
  postText,
  postConfirm,
  postCancel,
  postUndo,
  isUndoSuccessful,
  ledgerEntryClass,
  sortCustomersByBalance,
  checkServer,
} from "./api.js";
import { VoiceRecorder, makePlayableAudio } from "./voice.js";

// ---- App state -----------------------------------------------------------

const App = {
  state: "idle", // idle | recording | processing | customer_creation_confirmation | transaction_confirmation | success | error
  recorder: null,
  lastAudioObjectUrl: null,
  lastAudioRevoke: false,
  isSubmitting: false, // guards against duplicate voice/text submissions
  isConfirming: false, // guards confirm/cancel
  customers: [],
  customersLoaded: false,
  view: "main", // main | ledger
  ledgerCustomerId: null,
  ledgerCustomerName: "",
  serverOnline: null,
};

// ---- DOM refs (populated on DOMContentLoaded) ---------------------------

let el = {};

function cacheDom() {
  el = {
    // Header
    dateLabel: document.getElementById("date-label"),
    statusDot: document.getElementById("status-dot"),
    statusText: document.getElementById("status-text"),

    // Summary
    creditToday: document.getElementById("credit-today"),
    paymentsToday: document.getElementById("payments-today"),
    transactionCount: document.getElementById("transaction-count"),
    summaryError: document.getElementById("summary-error"),

    // Voice
    micButton: document.getElementById("mic-button"),
    micLabel: document.getElementById("mic-label"),
    micLabelEn: document.getElementById("mic-label-en"),
    micIcon: document.getElementById("mic-icon"),
    recordTimer: document.getElementById("record-timer"),
    transcriptBox: document.getElementById("transcript-box"),
    transcriptText: document.getElementById("transcript-text"),
    voiceHint: document.getElementById("voice-hint"),

    // Confirmation card
    confirmCard: document.getElementById("confirm-card"),
    confirmTitle: document.getElementById("confirm-title"),
    confirmTitleEn: document.getElementById("confirm-title-en"),
    confirmBody: document.getElementById("confirm-body"),
    btnConfirm: document.getElementById("btn-confirm"),
    btnCancel: document.getElementById("btn-cancel"),
    confirmSpinner: document.getElementById("confirm-spinner"),

    // Success / error toast
    toast: document.getElementById("toast"),
    toastTitle: document.getElementById("toast-title"),
    toastEn: document.getElementById("toast-en"),
    toastIcon: document.getElementById("toast-icon"),

    // Customers
    customerList: document.getElementById("customer-list"),
    customerSearch: document.getElementById("customer-search"),
    customersError: document.getElementById("customers-error"),
    customersCount: document.getElementById("customers-count"),

    // Ledger view
    ledgerView: document.getElementById("ledger-view"),
    mainView: document.getElementById("main-view"),
    ledgerName: document.getElementById("ledger-name"),
    ledgerBalance: document.getElementById("ledger-balance"),
    ledgerBalanceLabel: document.getElementById("ledger-balance-label"),
    ledgerList: document.getElementById("ledger-list"),
    ledgerError: document.getElementById("ledger-error"),
    btnBack: document.getElementById("btn-back"),

    // Manual text input
    textInput: document.getElementById("text-input"),
    btnSendText: document.getElementById("btn-send-text"),
    sendSpinner: document.getElementById("send-spinner"),

    // Undo
    btnUndo: document.getElementById("btn-undo"),
    undoHint: document.getElementById("undo-hint"),

    // Modal (undo confirm)
    modal: document.getElementById("modal"),
    modalTitle: document.getElementById("modal-title"),
    modalTitleEn: document.getElementById("modal-title-en"),
    modalYes: document.getElementById("modal-yes"),
    modalNo: document.getElementById("modal-no"),
    modalSpinner: document.getElementById("modal-spinner"),
  };
}

// ---- Bootstrap -----------------------------------------------------------

document.addEventListener("DOMContentLoaded", init);

async function init() {
  cacheDom();
  el.dateLabel.textContent = formatDateTe(new Date());

  // Wire events
  el.micButton.addEventListener("click", onMicClick);
  el.btnConfirm.addEventListener("click", () => onConfirm(false));
  el.btnCancel.addEventListener("click", onCancel);
  el.btnSendText.addEventListener("click", onSendText);
  el.textInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") onSendText();
  });
  el.btnUndo.addEventListener("click", onUndoClick);
  el.btnBack.addEventListener("click", showMainView);
  el.customerSearch.addEventListener("input", onCustomerSearch);
  el.modalYes.addEventListener("click", onUndoConfirm);
  el.modalNo.addEventListener("click", hideModal);
  updateUndoAvailability();

  // Keyboard: Space toggles recording when idle/recording and not focused in input.
  document.addEventListener("keydown", (e) => {
    if (e.code === "Space" && !isTypingTarget(e.target)) {
      e.preventDefault();
      onMicClick();
    }
  });

  // Initialize recorder
  if (VoiceRecorder.isSupported()) {
    App.recorder = new VoiceRecorder();
    App.recorder.onDurationUpdate = (secs) => {
      el.recordTimer.textContent = formatDuration(secs);
    };
    App.recorder.onStop = (blob) => {
      // Upload the recorded audio.
      uploadVoice(blob);
    };
    App.recorder.onError = (err) => {
      showError(t.recordError, t.recordErrorEn);
      setState("idle");
    };
  } else {
    // Disable mic button, show unsupported note.
    el.micButton.disabled = true;
    el.micLabel.textContent = t.micUnsupported;
    el.micLabelEn.textContent = t.micUnsupportedEn;
    el.micButton.classList.add("mic-unsupported");
  }

  // Register service worker for PWA.
  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("/service-worker.js", { scope: "/" }).catch(() => {
      // SW registration failure is non-fatal.
    });
  }

  // Online/offline indicator events.
  window.addEventListener("online", () => updateOnlineStatus());
  window.addEventListener("offline", () => updateOnlineStatus());

  // Initial data load.
  updateOnlineStatus();
  await refreshAll();
}

function isTypingTarget(target) {
  if (!target) return false;
  const tag = target.tagName;
  return tag === "INPUT" || tag === "TEXTAREA" || target.isContentEditable;
}

function formatDuration(secs) {
  const m = Math.floor(secs / 60);
  const s = secs % 60;
  return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

// ---- State machine -------------------------------------------------------

function setState(newState) {
  App.state = newState;
  document.body.dataset.state = newState;

  // Mic button labels.
  switch (newState) {
    case "recording":
      el.micLabel.textContent = t.listening;
      el.micLabelEn.textContent = t.listeningEn;
      el.micButton.classList.add("recording");
      el.recordTimer.classList.add("show");
      el.voiceHint.textContent = t.tapToStop;
      break;
    case "processing":
      el.micLabel.textContent = t.processing;
      el.micLabelEn.textContent = t.processingEn;
      el.micButton.classList.remove("recording");
      el.micButton.classList.add("processing");
      el.micButton.disabled = true;
      el.recordTimer.classList.remove("show");
      el.voiceHint.textContent = "";
      break;
    case "idle":
      el.micLabel.textContent = t.speak;
      el.micLabelEn.textContent = t.speakEn;
      el.micButton.classList.remove("recording", "processing");
      el.micButton.disabled = false;
      el.recordTimer.classList.remove("show");
      el.recordTimer.textContent = "00:00";
      el.voiceHint.textContent = t.tapToSpeak;
      break;
    default:
      // For confirmation/success/error states, mic returns to idle appearance.
      el.micButton.classList.remove("recording", "processing");
      el.micButton.disabled = false;
      el.recordTimer.classList.remove("show");
      el.voiceHint.textContent = t.tapToSpeak;
      el.micLabel.textContent = t.speak;
      el.micLabelEn.textContent = t.speakEn;
      break;
  }
}

// ---- Online/offline ------------------------------------------------------

function updateOnlineStatus() {
  const online = navigator.onLine;
  if (online) {
    el.statusDot.classList.remove("offline");
    el.statusDot.classList.add("online");
    el.statusText.textContent = t.online;
  } else {
    el.statusDot.classList.remove("online");
    el.statusDot.classList.add("offline");
    el.statusText.textContent = t.offline;
  }
  App.serverOnline = online ? App.serverOnline : false;
}

// ---- Voice recording -----------------------------------------------------

async function onMicClick() {
  if (App.state === "recording") {
    // Stop recording → triggers upload via onStop callback.
    App.recorder.stop();
    setState("processing");
    return;
  }
  if (App.state === "processing" || App.isSubmitting) return;
  if (!App.recorder) {
    showError(t.micUnsupported, t.micUnsupportedEn);
    return;
  }
  // Hide any previous confirmation/toast.
  hideConfirmCard();
  hideToast();
  hideTranscript();

  try {
    await App.recorder.start();
    setState("recording");
  } catch (err) {
    handleMicError(err);
  }
}

function handleMicError(err) {
  const msg = err && err.message;
  if (msg === "PERMISSION_DENIED") {
    showError(t.micDenied, t.micDeniedEn);
  } else if (msg === "UNSUPPORTED") {
    showError(t.micUnsupported, t.micUnsupportedEn);
  } else {
    showError(t.recordError, t.recordErrorEn);
  }
  setState("idle");
}

async function uploadVoice(blob) {
  if (App.isSubmitting) return;
  App.isSubmitting = true;
  setState("processing");
  try {
    const result = await postVoice(blob);
    handleVoiceOrTextResult(result);
  } catch (err) {
    if (err.normalizedResponse?.transcript) {
      showTranscript(err.normalizedResponse.transcript);
    }
    handleApiError(err);
  } finally {
    App.isSubmitting = false;
  }
}

// ---- Manual text input ---------------------------------------------------

async function onSendText() {
  const text = (el.textInput.value || "").trim();
  if (!text) {
    showError(t.emptyText, t.emptyTextEn);
    return;
  }
  if (App.isSubmitting) return;
  App.isSubmitting = true;
  el.btnSendText.disabled = true;
  el.sendSpinner.classList.add("show");
  hideConfirmCard();
  hideToast();
  hideTranscript();
  setState("processing");
  try {
    const result = await postText(text);
    handleVoiceOrTextResult(result);
    el.textInput.value = "";
  } catch (err) {
    handleApiError(err);
  } finally {
    App.isSubmitting = false;
    el.btnSendText.disabled = false;
    el.sendSpinner.classList.remove("show");
  }
}

// ---- Shared result handler (voice & text) --------------------------------

function handleVoiceOrTextResult(result) {
  // Play reply audio if present.
  if (result.replyAudio) {
    playReplyAudio(result.replyAudio);
  }

  // Show transcript if present.
  if (result.transcript) {
    showTranscript(result.transcript);
  }

  switch (result.state) {
    case "transaction_confirmation":
      showTransactionCard(result);
      setState("transaction_confirmation");
      break;
    case "customer_creation_confirmation":
      showCustomerCreationCard(result);
      setState("customer_creation_confirmation");
      break;
    case "success":
      showSuccess(result.message || t.transactionSaved, t.transactionSavedEn);
      refreshAll();
      break;
    case "error":
      showError(
        result.message || t.couldNotHear,
        result.message ? "" : t.couldNotHearEn,
      );
      setState("error");
      setTimeout(() => setState("idle"), 3000);
      break;
    default:
      showError(result.message || t.couldNotHear, t.couldNotHearEn);
      setState("error");
      setTimeout(() => setState("idle"), 3000);
  }
}

// ---- Audio playback ------------------------------------------------------

let currentAudioEl = null;

function playReplyAudio(replyAudio) {
  // Clean up previous audio.
  if (App.lastAudioObjectUrl && App.lastAudioRevoke) {
    URL.revokeObjectURL(App.lastAudioObjectUrl);
    App.lastAudioObjectUrl = null;
    App.lastAudioRevoke = false;
  }
  if (currentAudioEl) {
    currentAudioEl.pause();
    currentAudioEl = null;
  }

  const playable = makePlayableAudio(replyAudio);
  if (!playable) return;
  App.lastAudioObjectUrl = playable.url;
  App.lastAudioRevoke = playable.revoke;

  const audio = new Audio(playable.url);
  currentAudioEl = audio;
  audio.play().catch(() => {
    // Autoplay may be blocked until user interaction; ignore silently.
    // The user will have tapped a button, so this is rare.
  });
}

// ---- Transaction confirmation card --------------------------------------

function showTransactionCard(result) {
  el.confirmCard.classList.add("show");
  el.confirmTitle.textContent = t.confirmTransaction;
  el.confirmTitleEn.textContent = t.confirmTransactionEn;
  el.confirmSpinner.classList.remove("show");
  el.btnConfirm.disabled = false;
  el.btnCancel.disabled = false;

  const typeLabel = result.txType === "payment" ? t.payment : t.credit;
  const typeLabelEn = result.txType === "payment" ? t.paymentEn : t.creditEn;
  const typeClass = result.txType === "payment" ? "type-payment" : "type-credit";

  el.confirmBody.innerHTML = `
    <div class="confirm-row">
      <span class="confirm-label">${t.customer}</span>
      <span class="confirm-value">${escapeHtml(result.customerName || "-")}</span>
    </div>
    <div class="confirm-row">
      <span class="confirm-label">${t.type}</span>
      <span class="confirm-value ${typeClass}">${escapeHtml(typeLabel)} <small>(${escapeHtml(typeLabelEn)})</small></span>
    </div>
    <div class="confirm-row">
      <span class="confirm-label">${t.amount}</span>
      <span class="confirm-value amount-big">${formatRupees(result.amount)}</span>
    </div>
    ${result.items ? `
    <div class="confirm-row">
      <span class="confirm-label">${t.items}</span>
      <span class="confirm-value">${escapeHtml(result.items)}</span>
    </div>` : ""}
    ${result.description ? `
    <div class="confirm-row">
      <span class="confirm-label">${t.description}</span>
      <span class="confirm-value">${escapeHtml(result.description)}</span>
    </div>` : ""}
    ${result.transcript ? `
    <div class="confirm-row transcript-row">
      <span class="confirm-label">${t.transcriptLabel}</span>
      <span class="confirm-value transcript-value">${escapeHtml(result.transcript)}</span>
    </div>` : ""}
  `;

  // Store pending id for confirm/cancel.
  el.btnConfirm.dataset.pendingId = result.pendingId || "";
  el.btnCancel.dataset.pendingId = result.pendingId || "";
  delete el.btnConfirm.dataset.isCustomerCreation;
  delete el.btnCancel.dataset.isCustomerCreation;
}

function showCustomerCreationCard(result) {
  el.confirmCard.classList.add("show");
  el.confirmTitle.textContent = "";
  el.confirmTitleEn.textContent = "";
  el.confirmSpinner.classList.remove("show");
  el.btnConfirm.disabled = false;
  el.btnCancel.disabled = false;

  const name = result.customerName || "";
  el.confirmBody.innerHTML = `
    <div class="customer-create-msg">
      <p class="te-large">"${escapeHtml(name)}" ${t.customerMissingPrefix}</p>
      <p class="en-sub">${escapeHtml(name)} ${t.customerMissingPrefixEn}</p>
      <p class="te-large ask">${t.createCustomerAsk}</p>
      <p class="en-sub">${t.createCustomerAskEn}</p>
    </div>
  `;

  // For customer creation, "confirm" creates the customer.
  el.btnConfirm.dataset.pendingId = result.pendingId || "";
  el.btnConfirm.dataset.isCustomerCreation = "true";
  el.btnCancel.dataset.pendingId = result.pendingId || "";
  el.btnCancel.dataset.isCustomerCreation = "true";
}

function hideConfirmCard() {
  el.confirmCard.classList.remove("show");
  el.btnConfirm.dataset.pendingId = "";
  el.btnCancel.dataset.pendingId = "";
  delete el.btnConfirm.dataset.isCustomerCreation;
  delete el.btnCancel.dataset.isCustomerCreation;
}

// ---- Confirm / Cancel ----------------------------------------------------

async function onConfirm(isCustomerCreation) {
  const pendingId = el.btnConfirm.dataset.pendingId;
  if (!pendingId || App.isConfirming) return;
  App.isConfirming = true;
  el.btnConfirm.disabled = true;
  el.btnCancel.disabled = true;
  el.confirmSpinner.classList.add("show");

  try {
    const result = await postConfirm(pendingId);
    // Reset the customer-creation flag.
    delete el.btnConfirm.dataset.isCustomerCreation;

    // Play any new reply audio.
    if (result.replyAudio) playReplyAudio(result.replyAudio);

    if (result.state === "transaction_confirmation") {
      // After customer creation, backend returns a NEW pending transaction.
      // Show a fresh transaction confirmation card.
      showTransactionCard(result);
      setState("transaction_confirmation");
    } else if (result.state === "success") {
      hideConfirmCard();
      showSuccess(result.message || t.transactionSaved, t.transactionSavedEn);
      refreshAll();
    } else if (result.state === "error") {
      showError(result.message || t.confirmError, t.confirmErrorEn);
    } else {
      showError(result.message || t.confirmError, t.confirmErrorEn);
      setState("error");
    }
  } catch (err) {
    handleApiError(err, t.confirmError, t.confirmErrorEn);
  } finally {
    App.isConfirming = false;
    el.confirmSpinner.classList.remove("show");
    el.btnConfirm.disabled = false;
    el.btnCancel.disabled = false;
  }
}

async function onCancel() {
  const pendingId = el.btnCancel.dataset.pendingId;
  if (!pendingId || App.isConfirming) return;
  App.isConfirming = true;
  el.btnConfirm.disabled = true;
  el.btnCancel.disabled = true;
  el.confirmSpinner.classList.add("show");

  try {
    const result = await postCancel(pendingId);
    if (result && result.state === "success") {
      hideConfirmCard();
      showSuccess(result.message || t.canceled, t.canceledEn);
      setState("idle");
    } else {
      showError(result.message || t.cancelError, t.cancelErrorEn);
      setState("error");
    }
  } catch (err) {
    handleApiError(err, t.cancelError, t.cancelErrorEn);
  } finally {
    App.isConfirming = false;
    el.confirmSpinner.classList.remove("show");
    el.btnConfirm.disabled = false;
    el.btnCancel.disabled = false;
  }
}

// ---- Undo ----------------------------------------------------------------

function onUndoClick() {
  if (!App.ledgerCustomerId) {
    showError(t.selectCustomerForUndo, t.selectCustomerForUndoEn);
    return;
  }
  el.modal.classList.add("show");
  el.modalTitle.textContent = `${App.ledgerCustomerName}: ${t.undoAsk}`;
  el.modalTitleEn.textContent = `${t.undoAskEn} (${App.ledgerCustomerName})`;
  el.modalYes.disabled = false;
  el.modalNo.disabled = false;
  el.modalSpinner.classList.remove("show");
}

function hideModal() {
  el.modal.classList.remove("show");
}

async function onUndoConfirm() {
  const customerId = App.ledgerCustomerId;
  if (!customerId) {
    hideModal();
    showError(t.selectCustomerForUndo, t.selectCustomerForUndoEn);
    return;
  }
  el.modalYes.disabled = true;
  el.modalNo.disabled = true;
  el.modalSpinner.classList.add("show");
  try {
    const result = await postUndo(customerId);
    hideModal();
    if (!isUndoSuccessful(result)) {
      showError(t.undoError, t.undoErrorEn);
      return;
    }
    showSuccess(t.undoSuccess, t.undoSuccessEn);
    await Promise.all([loadSummary(), loadCustomers(), refreshSelectedLedger(customerId)]);
  } catch (err) {
    hideModal();
    if (err.status === 409 && /no non-voided transactions/i.test(err.debugDetail || "")) {
      showError(t.nothingToUndo, t.nothingToUndoEn);
    } else {
      handleApiError(err, t.undoError, t.undoErrorEn);
    }
  } finally {
    el.modalSpinner.classList.remove("show");
    el.modalYes.disabled = false;
    el.modalNo.disabled = false;
  }
}

// ---- Today's summary -----------------------------------------------------

async function loadSummary() {
  try {
    const s = await getTodaySummary();
    el.creditToday.textContent = s.creditToday === null ? t.unavailable : formatRupees(s.creditToday);
    el.paymentsToday.textContent = s.paymentsToday === null ? t.unavailable : formatRupees(s.paymentsToday);
    el.transactionCount.textContent = s.transactionCount === null ? t.unavailable : String(s.transactionCount);
    el.summaryError.classList.remove("show");
    App.serverOnline = true;
    updateOnlineStatus();
  } catch (err) {
    el.summaryError.classList.add("show");
    App.serverOnline = false;
    updateOnlineStatus();
  }
}

// ---- Customers -----------------------------------------------------------

async function loadCustomers() {
  try {
    const list = await getCustomers();
    App.customers = list;
    App.customersLoaded = true;
    renderCustomers(list);
    el.customersError.classList.remove("show");
  } catch (err) {
    el.customersError.classList.add("show");
  }
}

function renderCustomers(list) {
  // The backend's ID-ascending order is retained when list balances are unavailable.
  const sorted = sortCustomersByBalance(list);

  el.customersCount.textContent = sorted.length;

  if (sorted.length === 0) {
    el.customerList.innerHTML = `<p class="empty-state">${t.noCustomers}<br><small>${t.noCustomersEn}</small></p>`;
    return;
  }

  el.customerList.innerHTML = sorted
    .map((c) => {
      const bal = c.balance;
      const balClass = bal === null ? "balance-unavailable"
        : bal > 0 ? "has-dues" : bal < 0 ? "has-credit" : "zero-dues";
      const balText = bal === null ? t.unavailable : bal === 0 ? t.noDues : formatRupees(bal);
      return `
        <button class="customer-card" data-customer-id="${escapeHtml(c.id)}" type="button">
          <span class="customer-name">${escapeHtml(c.name)}</span>
          <span class="customer-balance ${balClass}">${escapeHtml(balText)}</span>
        </button>
      `;
    })
    .join("");

  // Wire clicks.
  el.customerList.querySelectorAll(".customer-card").forEach((card) => {
    card.addEventListener("click", () => {
      const id = card.dataset.customerId;
      openLedger(id, card.querySelector(".customer-name").textContent);
    });
  });
}

function onCustomerSearch() {
  const q = (el.customerSearch.value || "").trim().toLowerCase();
  if (!q) {
    renderCustomers(App.customers);
    return;
  }
  const filtered = App.customers.filter((c) =>
    (c.name || "").toLowerCase().includes(q),
  );
  if (filtered.length === 0) {
    el.customerList.innerHTML = `<p class="empty-state">${t.noMatch}<br><small>${t.noMatchEn}</small></p>`;
  } else {
    renderCustomers(filtered);
  }
}

// ---- Ledger --------------------------------------------------------------

async function openLedger(customerId, fallbackName) {
  App.view = "ledger";
  App.ledgerCustomerId = String(customerId);
  App.ledgerCustomerName = fallbackName || "";
  updateUndoAvailability();
  el.mainView.classList.remove("show");
  el.ledgerView.classList.add("show");
  el.ledgerName.textContent = fallbackName || "";
  el.ledgerBalance.textContent = t.loading;
  el.ledgerList.innerHTML = `<p class="empty-state">${t.loading}<br><small>${t.loadingEn}</small></p>`;
  el.ledgerError.classList.remove("show");
  // Scroll ledger to top.
  el.ledgerView.scrollTop = 0;

  try {
    const ledger = await getLedger(customerId);
    renderLedger(ledger, fallbackName);
  } catch (err) {
    el.ledgerList.innerHTML = "";
    el.ledgerError.classList.add("show");
  }
}

function updateUndoAvailability() {
  if (!el.btnUndo) return;
  const selected = Boolean(App.ledgerCustomerId);
  el.btnUndo.disabled = !selected;
  if (el.undoHint) {
    el.undoHint.textContent = selected
      ? `${t.undoSelectedCustomer}: ${App.ledgerCustomerName}`
      : `${t.selectCustomerForUndo} · ${t.selectCustomerForUndoEn}`;
  }
}

async function refreshSelectedLedger(customerId) {
  try {
    const ledger = await getLedger(customerId);
    if (App.view === "ledger" && App.ledgerCustomerId === String(customerId)) {
      renderLedger(ledger, App.ledgerCustomerName);
    }
  } catch {
    if (App.view === "ledger" && App.ledgerCustomerId === String(customerId)) {
      el.ledgerError.classList.add("show");
    } else {
      showError(t.undoRefreshError, t.undoRefreshErrorEn);
    }
  }
}

function renderLedger(ledger, fallbackName) {
  const name = ledger.customerName || fallbackName || "";
  el.ledgerName.textContent = name;
  const bal = ledger.balance;
  const balClass = bal === null ? "balance-unavailable"
    : bal > 0 ? "has-dues" : bal < 0 ? "has-credit" : "zero-dues";
  el.ledgerBalance.textContent = bal === null ? t.unavailable : bal === 0 ? t.noDues : formatRupees(bal);
  el.ledgerBalance.className = `ledger-balance-value ${balClass}`;

  const entries = ledger.entries || [];
  if (entries.length === 0) {
    el.ledgerList.innerHTML = `<p class="empty-state">${t.noTransactions}<br><small>${t.noTransactionsEn}</small></p>`;
    return;
  }

  el.ledgerList.innerHTML = entries
    .map((e) => {
      const isCredit = e.type === "credit";
      const typeLabel = isCredit ? t.credit : t.payment;
      const typeEn = isCredit ? t.creditEn : t.paymentEn;
      const sign = isCredit ? "+" : "-";
      const entryClass = ledgerEntryClass(e);
      const dateStr = formatDateShortTe(e.date);
      return `
        <div class="${entryClass}"${e.isVoided ? ' aria-label="' + escapeHtml(t.voided) + '"' : ""}>
          <div class="entry-top">
            <span class="entry-type">${escapeHtml(typeLabel)} <small>${escapeHtml(typeEn)}</small>${e.isVoided ? ` <span class="entry-voided-label">${escapeHtml(t.voided)} · ${escapeHtml(t.voidedEn)}</span>` : ""}</span>
            <span class="entry-amount">${sign}${formatRupees(e.amount).replace("-", "")}</span>
          </div>
          ${e.description ? `<div class="entry-desc">${escapeHtml(e.description)}</div>` : ""}
          ${dateStr ? `<div class="entry-date">${escapeHtml(dateStr)}</div>` : ""}
        </div>
      `;
    })
    .join("");
}

function showMainView() {
  App.view = "main";
  el.ledgerView.classList.remove("show");
  el.mainView.classList.add("show");
  // Refresh data when returning to main.
  refreshAll();
}

// ---- Toast (success / error) ---------------------------------------------

function showSuccess(te, en) {
  el.toast.classList.add("show", "toast-success");
  el.toast.classList.remove("toast-error");
  el.toastIcon.textContent = "✓";
  el.toastTitle.textContent = te || t.success;
  el.toastEn.textContent = en || t.successEn;
  setState("success");
  setTimeout(() => {
    el.toast.classList.remove("show");
    setState("idle");
  }, 3000);
}

function showError(te, en) {
  el.toast.classList.add("show", "toast-error");
  el.toast.classList.remove("toast-success");
  el.toastIcon.textContent = "!";
  el.toastTitle.textContent = te;
  el.toastEn.textContent = en || "";
  setState("error");
  setTimeout(() => {
    el.toast.classList.remove("show");
    if (App.state === "error") setState("idle");
  }, 4000);
}

function hideToast() {
  el.toast.classList.remove("show");
}

function showTranscript(text) {
  el.transcriptBox.classList.add("show");
  el.transcriptText.textContent = text;
}

function hideTranscript() {
  el.transcriptBox.classList.remove("show");
  el.transcriptText.textContent = "";
}

// ---- Error handling ------------------------------------------------------

function handleApiError(err, fallbackTe, fallbackEn) {
  const msg = err && err.message;
  if (msg === "NETWORK_ERROR") {
    showError(t.networkError, t.networkErrorEn);
  } else {
    showError(fallbackTe || t.serverError, fallbackEn || t.serverErrorEn);
  }
  // Structured backend detail stays on the error object for debugging; never render it raw.
  if (err?.debugDetail) console.debug("Backend request detail:", err.debugDetail);
  setState("idle");
}

// ---- Refresh all data ----------------------------------------------------

async function refreshAll() {
  await Promise.allSettled([loadSummary(), loadCustomers()]);
}

// ---- Utility -------------------------------------------------------------

function escapeHtml(str) {
  if (str === null || str === undefined) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}
