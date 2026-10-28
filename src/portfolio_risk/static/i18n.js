// Interface language. The page's HTML is written in Russian; elements carrying data-i18n,
// data-i18n-label or data-i18n-placeholder are rewritten from messages.json when the language
// changes, and scripts build every other string with t().

const LANGUAGES = ["ru", "en"];
const STORAGE_KEY = "language";
// Browsers set to these languages get the Russian interface; everyone else gets English.
const RUSSIAN_READERS = /^(ru|kk|be|ky)\b/i;
const LOCALES = { ru: "ru-RU", en: "en-US" };
const DATE_OPTIONS = {
  ru: { day: "2-digit", month: "2-digit", year: "numeric", timeZone: "UTC" },
  en: { month: "short", day: "numeric", year: "numeric", timeZone: "UTC" },
};

const messages = await fetch(new URL("messages.json", import.meta.url)).then((response) => response.json());
let language = detectLanguage();
const formatCache = new Map();

function detectLanguage() {
  const requested = new URLSearchParams(window.location.search).get("lang");
  if (LANGUAGES.includes(requested)) return requested;
  const saved = readSaved();
  if (LANGUAGES.includes(saved)) return saved;
  const preferred = navigator.languages?.[0] ?? navigator.language ?? "ru";
  return RUSSIAN_READERS.test(preferred) ? "ru" : "en";
}

// Storage can be unavailable (private windows, blocked site data); the choice then lasts the visit.
function readSaved() {
  try {
    return window.localStorage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
}

function save(value) {
  try {
    window.localStorage.setItem(STORAGE_KEY, value);
  } catch {
    // Nothing to do: the language still applies to this visit.
  }
}

export function currentLanguage() {
  return language;
}

export function hasMessage(key) {
  return key in messages[language];
}

export function t(key, params = {}) {
  const template = messages[language][key] ?? key;
  return template.replace(/\{(\w+)\}/g, (match, name) => (name in params ? String(params[name]) : match));
}

export function setLanguage(next) {
  if (!LANGUAGES.includes(next) || next === language) return;
  language = next;
  save(next);
  // A ?lang= link would otherwise win over the new choice on the next reload.
  const url = new URL(window.location.href);
  if (url.searchParams.has("lang")) {
    url.searchParams.set("lang", next);
    window.history.replaceState(null, "", url);
  }
  translatePage();
  document.dispatchEvent(new CustomEvent("app:language"));
}

export function translatePage() {
  document.documentElement.lang = language;
  document.title = t("meta.title");
  document.querySelectorAll("[data-i18n]").forEach((node) => {
    node.textContent = t(node.dataset.i18n);
  });
  document.querySelectorAll("[data-i18n-label]").forEach((node) => {
    node.setAttribute("aria-label", t(node.dataset.i18nLabel));
  });
  document.querySelectorAll("[data-i18n-placeholder]").forEach((node) => {
    node.setAttribute("placeholder", t(node.dataset.i18nPlaceholder));
  });
}

export function fmt() {
  if (!formatCache.has(language)) formatCache.set(language, makeFormats(LOCALES[language], DATE_OPTIONS[language]));
  return formatCache.get(language);
}

function makeFormats(locale, dateOptions) {
  const percent = { style: "percent", minimumFractionDigits: 1, maximumFractionDigits: 1 };
  const currency = { style: "currency", currency: "USD", maximumFractionDigits: 0 };
  const twoDecimals = { minimumFractionDigits: 2, maximumFractionDigits: 2 };
  const dates = new Intl.DateTimeFormat(locale, dateOptions);
  return {
    pct: new Intl.NumberFormat(locale, percent),
    signedPct: new Intl.NumberFormat(locale, { ...percent, signDisplay: "exceptZero" }),
    usd: new Intl.NumberFormat(locale, currency),
    signedUsd: new Intl.NumberFormat(locale, { ...currency, signDisplay: "exceptZero" }),
    price: new Intl.NumberFormat(locale, { style: "currency", currency: "USD", minimumFractionDigits: 2 }),
    decimal: new Intl.NumberFormat(locale, twoDecimals),
    signedDecimal: new Intl.NumberFormat(locale, { ...twoDecimals, signDisplay: "exceptZero" }),
    ratio: new Intl.NumberFormat(locale, { minimumFractionDigits: 1, maximumFractionDigits: 1 }),
    plain: new Intl.NumberFormat(locale, { maximumFractionDigits: 4 }),
    // Report dates are ISO calendar days; reading them as UTC keeps the day from shifting.
    date: (iso) => dates.format(new Date(`${iso}T00:00:00Z`)),
  };
}
