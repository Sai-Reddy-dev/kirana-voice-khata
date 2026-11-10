// i18n.js — Bilingual Telugu/English strings for Kirana Voice Khata
// Keep all user-facing text here so nothing is hardcoded inline.

export const t = {
  appName: "కిరాణా వాయిస్ ఖాతా",
  appSubtitle: "Kirana Voice Khata",

  // Header / status
  online: "ఆన్‌లైన్",
  offline: "ఆఫ్‌లైన్",
  onlineEn: "Online",
  offlineEn: "Offline",

  // Today's summary
  creditToday: "ఈరోజు ఇచ్చిన అప్పు",
  creditTodayEn: "Credit given today",
  paymentsToday: "ఈరోజు వచ్చిన చెల్లింపులు",
  paymentsTodayEn: "Payments received today",
  transactionCount: "ఈరోజు లావాదేవీలు",
  transactionCountEn: "Today's transactions",
  unavailable: "అందుబాటులో లేదు · Not provided",
  todaySummaryError: "సారాంశం తీసుకోలేకపోయింది",
  todaySummaryErrorEn: "Could not load today's summary",

  // Voice area
  speak: "మాట్లాడండి",
  speakEn: "Speak",
  listening: "వింటున్నాను...",
  listeningEn: "Listening...",
  processing: "ప్రాసెస్ చేస్తున్నాను...",
  processingEn: "Processing...",
  tapToSpeak: "మాట్లాడటానికి ట్యాప్ చేయండి",
  tapToStop: "ఆపడానికి ట్యాప్ చేయండి",
  transcriptLabel: "మీరు చెప్పింది",

  // Permissions / unsupported
  micDenied: "మైక్రోఫోన్ అనుమతి లేదు. దయచేసి బ్రౌజర్ సెట్టింగ్‌లలో అనుమతించండి.",
  micDeniedEn: "Microphone permission denied. Please allow it in browser settings.",
  micUnsupported: "ఈ పరికరంలో రికార్డింగ్ సపోర్ట్ లేదు.",
  micUnsupportedEn: "Recording is not supported on this device.",
  recordError: "రికార్డింగ్‌లో సమస్య. మళ్లీ ప్రయత్నించండి.",
  recordErrorEn: "Recording problem. Please try again.",

  // Transaction confirmation
  confirmTransaction: "లావాదేవీ నిర్ధారించండి",
  confirmTransactionEn: "Confirm Transaction",
  customer: "కస్టమర్",
  customerEn: "Customer",
  type: "రకం",
  typeEn: "Type",
  amount: "మొత్తం",
  amountEn: "Amount",
  items: "వివరాలు",
  itemsEn: "Details",
  description: "వివరణ",
  descriptionEn: "Description",
  credit: "అప్పు",
  creditEn: "Credit",
  payment: "చెల్లింపు",
  paymentEn: "Payment",
  confirm: "అవును",
  confirmEn: "Confirm",
  cancel: "వద్దు",
  cancelEn: "Cancel",
  confirming: "నిర్ధారిస్తున్నాను...",
  canceling: "రద్దు చేస్తున్నాను...",
  confirmError: "నిర్ధారణలో సమస్య. మళ్లీ ప్రయత్నించండి.",
  confirmErrorEn: "Confirmation failed. Please try again.",
  cancelError: "రద్దులో సమస్య. మళ్లీ ప్రయత్నించండి.",
  cancelErrorEn: "Cancel failed. Please try again.",

  // Customer creation confirmation
  customerMissingPrefix: " అనే కస్టమర్ లేరు.",
  customerMissingPrefixEn: " customer does not exist.",
  createCustomerAsk: "కొత్త కస్టమర్‌గా సృష్టించాలా?",
  createCustomerAskEn: "Create as a new customer?",
  creatingCustomer: "కస్టమర్ సృష్టిస్తున్నాను...",
  createCustomerError: "కస్టమర్ సృష్టించడంలో సమస్య.",
  createCustomerErrorEn: "Problem creating customer.",

  // Success / error
  success: "విజయవంతమైంది!",
  successEn: "Success!",
  transactionSaved: "లావాదేవీ నమోదైంది.",
  transactionSavedEn: "Transaction recorded.",
  canceled: "రద్దు చేయబడింది.",
  canceledEn: "Canceled.",
  couldNotHear: "మీ మాటలు వినిపించలేదు. మళ్లీ ప్రయత్నించండి.",
  couldNotHearEn: "Could not hear you. Please try again.",
  serverError: "సర్వర్‌తో సమస్య. కొద్దిసేపట్లో మళ్లీ ప్రయత్నించండి.",
  serverErrorEn: "Server problem. Please try again shortly.",
  networkError: "నెట్‌వర్క్ లేదు. కనెక్షన్ తనిఖీ చేయండి.",
  networkErrorEn: "No network. Check your connection.",
  offlineMsg: "సర్వర్ అందుబాటులో లేదు. ఆఫ్‌లైన్‌లో ఉన్నారు.",
  offlineMsgEn: "Server unavailable. You are offline.",
  audioPlaybackError: "ఆడియో ప్లే చేయబోయింది.",
  audioPlaybackErrorEn: "Could not play audio.",

  // Customer list
  customers: "కస్టమర్‌లు",
  customersEn: "Customers",
  searchCustomers: "కస్టమర్ వెతకండి...",
  searchCustomersEn: "Search customers...",
  noCustomers: "కస్టమర్‌లు లేరు",
  noCustomersEn: "No customers",
  noMatch: "పేరు దొరకలేదు",
  noMatchEn: "No match found",
  loadCustomersError: "కస్టమర్‌లు తీసుకోలేకపోయింది.",
  loadCustomersErrorEn: "Could not load customers.",
  balance: "బాకీ",
  balanceEn: "Balance",
  noDues: "బాకీ లేదు",
  noDuesEn: "No dues",

  // Ledger
  ledger: "లెడ్జర్",
  ledgerEn: "Ledger",
  back: "వెనక్కి",
  backEn: "Back",
  currentBalance: "ప్రస్తుత బాకీ",
  currentBalanceEn: "Current Balance",
  loadLedgerError: "లెడ్జర్ తీసుకోలేకపోయింది.",
  loadLedgerErrorEn: "Could not load ledger.",
  noTransactions: "లావాదేవీలు లేవు",
  noTransactionsEn: "No transactions",
  date: "తేదీ",
  dateEn: "Date",
  voided: "రద్దు",
  voidedEn: "Voided",

  // Manual text input
  manualInput: "టైప్ చేయండి",
  manualInputEn: "Type instead",
  manualPlaceholder: "ఉదా: రాము దగ్గర 500 రూపాయలు అప్పు ఇచ్చాను",
  send: "పంపండి",
  sendEn: "Send",
  sending: "పంపుతున్నాను...",
  sendingEn: "Sending...",
  emptyText: "దయచేసి ఏదైనా టైప్ చేయండి",
  emptyTextEn: "Please type something",

  // Undo
  undo: "అన్డూ",
  undoEn: "Undo",
  undoAsk: "చివరి లావాదేవీ రద్దు చేయాలా?",
  undoAskEn: "Undo the last transaction?",
  undoing: "రద్దు చేస్తున్నాను...",
  undoingEn: "Undoing...",
  undoSuccess: "చివరి లావాదేవీ రద్దు అయింది.",
  undoSuccessEn: "Last transaction undone.",
  undoError: "అన్డూ విఫలమైంది.",
  undoErrorEn: "Undo failed.",
  nothingToUndo: "రద్దు చేయడానికి ఏమీ లేదు.",
  nothingToUndoEn: "Nothing to undo.",
  selectCustomerForUndo: "అన్డూ చేయడానికి ముందుగా కస్టమర్ లెడ్జర్ తెరవండి.",
  selectCustomerForUndoEn: "Open a customer's ledger first to enable undo.",
  undoSelectedCustomer: "ఎంచుకున్న కస్టమర్",
  undoRefreshError: "అన్డూ అయింది, కానీ లెడ్జర్‌ను మళ్లీ తీసుకురాలేకపోయింది.",
  undoRefreshErrorEn: "Undo succeeded, but the customer ledger could not be refreshed.",

  // Misc
  rupee: "₹",
  yes: "అవును",
  yesEn: "Yes",
  no: "వద్దు",
  noEn: "No",
  close: "మూసివేయి",
  closeEn: "Close",
  dismiss: "సరే",
  dismissEn: "OK",
  loading: "లోడ్ అవుతోంది...",
  loadingEn: "Loading...",
};

// Format today's date as a Telugu-friendly string.
// Example: "10 నవంబర్ 2026"
const teMonths = [
  "జనవరి", "ఫిబ్రవరి", "మార్చి", "ఏప్రిల్", "మే", "జూన్",
  "జులై", "ఆగస్ట్", "సెప్టెంబర్", "అక్టోబర్", "నవంబర్", "డిసెంబర్",
];

export function formatDateTe(d = new Date()) {
  const day = d.getDate();
  const month = teMonths[d.getMonth()];
  const year = d.getFullYear();
  return `${day} ${month} ${year}`;
}

// Format an ISO date string to a short Telugu date for ledger rows.
export function formatDateShortTe(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return `${d.getDate()} ${teMonths[d.getMonth()]} ${d.getFullYear()}`;
}

// Format a number as Indian Rupees with grouping.
export function formatRupees(n) {
  if (n === null || n === undefined || n === "") return "₹0";
  const num = Number(n);
  if (Number.isNaN(num)) return "₹0";
  // Indian numbering uses lakhs/crores grouping.
  const sign = num < 0 ? "-" : "";
  const abs = Math.abs(Math.round(num));
  const str = abs.toString();
  let last3 = str.slice(-3);
  let other = str.slice(0, -3);
  if (other) {
    last3 = "," + last3;
  }
  const formatted = other.replace(/\B(?=(\d{2})+(?!\d))/g, ",") + last3;
  return `${sign}₹${formatted}`;
}
