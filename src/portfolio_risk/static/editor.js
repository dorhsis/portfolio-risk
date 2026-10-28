// Portfolio editor: one row per holding with a ticker search, a quantity in shares or dollars,
// ready-made examples, imports (file button, drag and drop, pasting a list) and checks while
// typing. It hands the report the same text the CLI reads, and pasted lists and files are parsed
// by the server, so the Python parser stays the only one.

import { getJson, postJson } from "./api.js";
import { el } from "./dom.js";
import { t } from "./i18n.js";

const MAX_ROWS = 50;
const MAX_FILE_CHARS = 20_000;
const SEARCH_DELAY_MS = 200;
const SEARCH_TIMEOUT_MS = 10_000;
const PARSE_TIMEOUT_MS = 15_000;
const VERIFY_CONCURRENCY = 3;
// A ticker as opposed to a company name being searched for: BRK.B, BF-B, QQQ.
const TICKER = /^[A-Z][A-Z0-9.-]{0,9}$/;
// Pasted text holding a ticker and a quantity, which is imported instead of typed into one field.
const LIST_LINE = /^\S+[\s,;]+\$?\s?[\d.,]+\s?\$?$/;
const SVG_NS = "http://www.w3.org/2000/svg";

const PRESETS = {
  example: {
    unit: "shares",
    rows: [
      ["AAPL", 40, "Apple Inc."],
      ["MSFT", 25, "Microsoft Corporation"],
      ["NVDA", 60, "NVIDIA Corporation"],
      ["GOOGL", 30, "Alphabet Inc."],
      ["BRK.B", 15, "Berkshire Hathaway Inc."],
      ["JPM", 20, "JPMorgan Chase & Co."],
      ["XOM", 30, "Exxon Mobil Corporation"],
      ["QQQ", 10, "Invesco QQQ Trust"],
      ["PLTR", 50, "Palantir Technologies Inc."],
      ["ARM", 20, "Arm Holdings plc"],
    ],
  },
  tech: {
    unit: "usd",
    rows: [
      ["AAPL", 5000, "Apple Inc."],
      ["MSFT", 5000, "Microsoft Corporation"],
      ["NVDA", 4000, "NVIDIA Corporation"],
      ["GOOGL", 3000, "Alphabet Inc."],
      ["AMZN", 3000, "Amazon.com, Inc."],
      ["META", 2000, "Meta Platforms, Inc."],
    ],
  },
  broad: {
    unit: "usd",
    rows: [
      ["VTI", 6000, "Vanguard Total Stock Market ETF"],
      ["VXUS", 2500, "Vanguard Total International Stock ETF"],
      ["BND", 1500, "Vanguard Total Bond Market ETF"],
    ],
  },
  dividends: {
    unit: "usd",
    rows: [
      ["SCHD", 4000, "Schwab U.S. Dividend Equity ETF"],
      ["JNJ", 2000, "Johnson & Johnson"],
      ["PG", 2000, "The Procter & Gamble Company"],
      ["KO", 1500, "The Coca-Cola Company"],
      ["XOM", 1500, "Exxon Mobil Corporation"],
    ],
  },
};

const searchCache = new Map();

function search(query, signal) {
  const key = query.toUpperCase();
  if (searchCache.has(key)) return Promise.resolve(searchCache.get(key));
  return getJson(`/api/search?q=${encodeURIComponent(query)}`, SEARCH_TIMEOUT_MS, signal).then(({ results }) => {
    searchCache.set(key, results);
    return results;
  });
}

// Accepts what people type: "40", "2,5", "5 000". Returns null unless it is a positive number.
function parseQuantity(text) {
  const normalized = text.replace(/[\s ]/g, "").replace(",", ".");
  if (!/^\d*\.?\d+$/.test(normalized)) return null;
  const value = Number(normalized);
  return Number.isFinite(value) && value > 0 ? value : null;
}

function closeIcon() {
  const svg = document.createElementNS(SVG_NS, "svg");
  svg.setAttribute("class", "icon");
  svg.setAttribute("viewBox", "0 0 16 16");
  svg.setAttribute("aria-hidden", "true");
  const path = document.createElementNS(SVG_NS, "path");
  path.setAttribute("d", "M4.5 4.5l7 7M11.5 4.5l-7 7");
  svg.append(path);
  return svg;
}

function filesIn(event) {
  return [...(event.dataTransfer?.types ?? [])].includes("Files");
}

export function createEditor() {
  const list = document.getElementById("holdings");
  const addButton = document.getElementById("add-row");
  const clearButton = document.getElementById("clear-rows");
  const notice = document.getElementById("editor-notice");
  const noticeText = document.getElementById("editor-notice-text");
  const undoButton = document.getElementById("undo");
  const errorNode = document.getElementById("editor-error");
  const live = document.getElementById("editor-live");
  const fileInput = document.getElementById("csv-file");
  const dropTarget = document.getElementById("portfolio-form");

  let rows = [];
  let nextId = 1;
  // Untouched example rows are replaced, not extended, by an import.
  let isSample = false;
  let undoSnapshot = null;
  // Notice and error texts are kept as functions so a language switch can redraw them.
  let noticeMessage = null;
  let errorMessage = null;
  let searchTimer = 0;
  let searchAbort = null;
  let openRow = null;
  let dragDepth = 0;

  function makeRow({ ticker = "", quantity = "", unit = "shares", name = null } = {}) {
    const id = nextId++;
    const symbol = el("input", {
      class: "input input--code holding__symbol",
      type: "text",
      role: "combobox",
      "aria-autocomplete": "list",
      "aria-expanded": "false",
      "aria-controls": `suggestions-${id}`,
      "aria-describedby": `name-${id} message-${id}`,
      autocomplete: "off",
      autocapitalize: "characters",
      spellcheck: "false",
    });
    const amount = el("input", {
      class: "input input--code holding__quantity",
      type: "text",
      inputmode: "decimal",
      autocomplete: "off",
      "aria-describedby": `message-${id}`,
    });
    const unitSelect = el("select", { class: "input holding__unit" }, el("option", { value: "shares" }), el("option", { value: "usd" }));
    const suggestions = el("ul", { id: `suggestions-${id}`, class: "suggestions", role: "listbox" });
    const searchStatus = el("p", { class: "suggestions__status" });
    const nodes = {
      symbol,
      quantity: amount,
      unit: unitSelect,
      suggestions,
      searchStatus,
      name: el("span", { id: `name-${id}`, class: "holding__name" }),
      remove: el("button", { type: "button", class: "icon-button holding__remove" }, closeIcon()),
      panel: el("div", { class: "suggestions-panel", hidden: true }, suggestions, searchStatus),
      message: el("p", { id: `message-${id}`, class: "holding__message", hidden: true }),
    };
    nodes.item = el(
      "li",
      { class: "holding" },
      el("div", { class: "holding__symbol-cell" }, symbol, nodes.name),
      amount,
      el("span", { class: "select" }, unitSelect),
      nodes.remove,
      nodes.panel,
      nodes.message,
    );
    symbol.value = ticker;
    amount.value = String(quantity);
    unitSelect.value = unit;

    const row = { id, nodes, name, status: name ? "found" : "idle", touched: false, results: [], active: -1 };
    wire(row);
    showName(row);
    return row;
  }

  function wire(row) {
    const { item, symbol, quantity, unit, remove, suggestions } = row.nodes;
    symbol.addEventListener("input", () => onSymbolInput(row));
    symbol.addEventListener("keydown", (event) => onSymbolKey(row, event));
    symbol.addEventListener("blur", () => onSymbolBlur(row));
    symbol.addEventListener("paste", onPaste);
    quantity.addEventListener("input", () => onQuantityInput(row));
    quantity.addEventListener("keydown", (event) => onQuantityKey(row, event));
    quantity.addEventListener("paste", onPaste);
    unit.addEventListener("change", edited);
    remove.addEventListener("click", () => removeRow(row));
    // Choosing with the mouse must not blur the field first, or the list closes under the pointer.
    suggestions.addEventListener("mousedown", (event) => event.preventDefault());
    suggestions.addEventListener("click", (event) => {
      const option = event.target.closest("[role=option]");
      if (option) choose(row, Number(option.dataset.index));
    });
    // Problems show once the reader leaves the row, not while they are still filling it in.
    item.addEventListener("focusout", (event) => {
      if (!item.contains(event.relatedTarget)) touch(row);
    });
  }

  // Rows

  function isEmpty(row) {
    return !row.nodes.symbol.value.trim() && !row.nodes.quantity.value.trim();
  }

  function problem(row) {
    const ticker = row.nodes.symbol.value.trim();
    const quantity = row.nodes.quantity.value.trim();
    if (!ticker && !quantity) return null;
    if (!ticker) return { level: "error", field: "symbol", text: t("editor.errorNoTicker") };
    if (!TICKER.test(ticker.toUpperCase())) return { level: "error", field: "symbol", text: t("editor.errorPick") };
    if (!quantity) return { level: "error", field: "quantity", text: t("editor.errorNoQuantity") };
    if (parseQuantity(quantity) === null) return { level: "error", field: "quantity", text: t("editor.errorQuantity") };
    if (row.status === "missing") return { level: "warning", field: "symbol", text: t("editor.warningMissing", { ticker }) };
    return null;
  }

  function showProblem(row) {
    const issue = row.touched ? problem(row) : null;
    const { message, symbol, quantity } = row.nodes;
    message.hidden = !issue;
    message.textContent = issue?.text ?? "";
    message.className = `holding__message${issue ? ` holding__message--${issue.level}` : ""}`;
    for (const [field, input] of [["symbol", symbol], ["quantity", quantity]]) {
      if (issue?.level === "error" && issue.field === field) input.setAttribute("aria-invalid", "true");
      else input.removeAttribute("aria-invalid");
    }
  }

  function touch(row) {
    row.touched = true;
    showProblem(row);
  }

  // The company name is drawn after the ticker inside the field; --chars places it.
  function showName(row) {
    const { item, name, symbol } = row.nodes;
    name.textContent = row.status === "found" && row.name ? row.name : "";
    item.style.setProperty("--chars", String(symbol.value.length));
  }

  function relabelRow(row, index) {
    const n = index + 1;
    const { symbol, quantity, unit, remove } = row.nodes;
    symbol.setAttribute("aria-label", t("editor.symbolLabel", { n }));
    symbol.setAttribute("placeholder", t("editor.symbolPlaceholder"));
    quantity.setAttribute("aria-label", t("editor.quantityLabel", { n }));
    quantity.setAttribute("placeholder", "0");
    unit.setAttribute("aria-label", t("editor.unitLabel", { n }));
    unit.options[0].textContent = t("editor.unitShares");
    unit.options[1].textContent = t("editor.unitUsd");
    remove.setAttribute("aria-label", t("editor.remove", { n }));
    showProblem(row);
  }

  function renderRows() {
    list.replaceChildren(...rows.map((row) => row.nodes.item));
    rows.forEach(relabelRow);
    addButton.disabled = rows.length >= MAX_ROWS;
  }

  function edited() {
    isSample = false;
    hideNotice();
    hideError();
  }

  function addRow() {
    if (rows.length >= MAX_ROWS) return;
    const row = makeRow();
    rows.push(row);
    renderRows();
    edited();
    row.nodes.symbol.focus();
  }

  function removeRow(row) {
    const index = rows.indexOf(row);
    if (index < 0) return;
    closeSuggestions(row);
    rows.splice(index, 1);
    if (!rows.length) rows.push(makeRow());
    renderRows();
    edited();
    rows[Math.min(index, rows.length - 1)].nodes.symbol.focus();
    announce(t("editor.removed"));
  }

  function snapshot() {
    return {
      isSample,
      rows: rows.map((row) => ({
        ticker: row.nodes.symbol.value,
        quantity: row.nodes.quantity.value,
        unit: row.nodes.unit.value,
        name: row.status === "found" ? row.name : null,
      })),
    };
  }

  // Bulk changes (examples, imports, clearing) can be undone from the notice they leave.
  function replaceRows(next, message) {
    undoSnapshot = snapshot();
    rows.forEach(closeSuggestions);
    rows = next.length ? next : [makeRow()];
    renderRows();
    hideError();
    showNotice(message);
  }

  function undo() {
    if (!undoSnapshot) return;
    rows = undoSnapshot.rows.map(makeRow);
    isSample = undoSnapshot.isSample;
    renderRows();
    hideNotice();
    rows[0].nodes.symbol.focus();
  }

  function loadPreset(button) {
    const preset = PRESETS[button.dataset.preset];
    replaceRows(
      preset.rows.map(([ticker, quantity, name]) => makeRow({ ticker, quantity, unit: preset.unit, name })),
      () => t("editor.noticePreset", { name: t(button.dataset.i18n) }),
    );
    isSample = true;
  }

  // Notices and errors

  function showNotice(message) {
    noticeMessage = message;
    noticeText.textContent = message();
    notice.hidden = false;
    announce(noticeText.textContent);
  }

  function hideNotice() {
    noticeMessage = null;
    undoSnapshot = null;
    notice.hidden = true;
  }

  function showError(message) {
    errorMessage = message;
    errorNode.textContent = message();
    errorNode.hidden = false;
  }

  function hideError() {
    errorMessage = null;
    errorNode.hidden = true;
  }

  function announce(text) {
    live.textContent = text;
  }

  // Ticker search

  function onSymbolInput(row) {
    row.name = null;
    row.status = "idle";
    showName(row);
    if (row.touched) showProblem(row);
    edited();
    clearTimeout(searchTimer);
    const query = row.nodes.symbol.value.trim();
    if (!query) {
      closeSuggestions(row);
      return;
    }
    searchTimer = setTimeout(() => runSearch(row, query), SEARCH_DELAY_MS);
  }

  async function runSearch(row, query) {
    searchAbort?.abort();
    const controller = new AbortController();
    searchAbort = controller;
    showSearchStatus(row, t("search.loading"));
    try {
      const results = await search(query, controller.signal);
      if (row.nodes.symbol.value.trim() !== query || document.activeElement !== row.nodes.symbol) return;
      showResults(row, results);
    } catch {
      if (controller.signal.aborted) return;
      showSearchStatus(row, t("search.unavailable"));
    }
  }

  function openPanel(row) {
    if (openRow && openRow !== row) closeSuggestions(openRow);
    openRow = row;
    row.nodes.panel.hidden = false;
    row.nodes.symbol.setAttribute("aria-expanded", String(row.results.length > 0));
  }

  function closeSuggestions(row) {
    row.nodes.panel.hidden = true;
    row.nodes.symbol.setAttribute("aria-expanded", "false");
    row.nodes.symbol.removeAttribute("aria-activedescendant");
    row.results = [];
    row.active = -1;
    if (openRow === row) openRow = null;
  }

  function showSearchStatus(row, text) {
    row.results = [];
    row.active = -1;
    row.nodes.suggestions.replaceChildren();
    row.nodes.searchStatus.textContent = text;
    row.nodes.searchStatus.hidden = false;
    openPanel(row);
  }

  function showResults(row, results) {
    if (!results.length) {
      showSearchStatus(row, t("search.none"));
      announce(t("search.none"));
      return;
    }
    row.results = results;
    row.active = -1;
    row.nodes.suggestions.replaceChildren(
      ...results.map((match, index) =>
        el(
          "li",
          { id: `option-${row.id}-${index}`, class: "suggestion", role: "option", "aria-selected": "false", "data-index": index },
          el("span", { class: "suggestion__symbol", text: match.symbol }),
          el("span", { class: "suggestion__name", text: match.name }),
          el("span", { class: "suggestion__meta", text: `${match.exchange} · ${match.kind === "etf" ? t("search.etf") : t("search.stock")}` }),
        ),
      ),
    );
    row.nodes.searchStatus.hidden = true;
    openPanel(row);
    announce(t("search.count", { count: results.length }));
  }

  function moveActive(row, step) {
    const count = row.results.length;
    row.active = row.active < 0 ? (step > 0 ? 0 : count - 1) : (row.active + step + count) % count;
    row.nodes.suggestions.querySelectorAll("[role=option]").forEach((option, index) => {
      option.setAttribute("aria-selected", String(index === row.active));
      if (index === row.active) option.scrollIntoView({ block: "nearest" });
    });
    row.nodes.symbol.setAttribute("aria-activedescendant", `option-${row.id}-${row.active}`);
  }

  function choose(row, index) {
    const match = row.results[index];
    row.nodes.symbol.value = match.symbol;
    row.name = match.name;
    row.status = "found";
    closeSuggestions(row);
    showName(row);
    edited();
    if (row.touched) showProblem(row);
    row.nodes.quantity.focus();
    row.nodes.quantity.select();
  }

  function onSymbolKey(row, event) {
    const open = !row.nodes.panel.hidden && row.results.length > 0;
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      if (!open) return;
      event.preventDefault();
      moveActive(row, event.key === "ArrowDown" ? 1 : -1);
    } else if (event.key === "Enter" && !event.metaKey && !event.ctrlKey) {
      event.preventDefault();
      if (open && row.active >= 0) {
        choose(row, row.active);
      } else {
        closeSuggestions(row);
        row.nodes.quantity.focus();
      }
    } else if (event.key === "Escape" && !row.nodes.panel.hidden) {
      event.preventDefault();
      closeSuggestions(row);
    }
  }

  // A typed ticker (not one picked from the list) is checked against the search on the way out.
  function onSymbolBlur(row) {
    clearTimeout(searchTimer);
    closeSuggestions(row);
    const value = row.nodes.symbol.value.trim();
    if (!value || /\s/.test(value)) return;
    row.nodes.symbol.value = value.toUpperCase();
    showName(row);
    if (row.status === "idle" && TICKER.test(row.nodes.symbol.value)) verify(row);
  }

  async function verify(row) {
    const ticker = row.nodes.symbol.value;
    row.status = "checking";
    try {
      const match = (await search(ticker)).find((result) => result.symbol === ticker);
      if (row.nodes.symbol.value !== ticker) return;
      row.status = match ? "found" : "missing";
      row.name = match?.name ?? null;
    } catch {
      if (row.nodes.symbol.value !== ticker) return;
      // Search is down: say nothing rather than call a real ticker unknown.
      row.status = "unknown";
    }
    showName(row);
    showProblem(row);
  }

  async function verifyAll(targets) {
    const queue = targets.filter((row) => TICKER.test(row.nodes.symbol.value));
    const worker = async () => {
      while (queue.length) await verify(queue.shift());
    };
    await Promise.all(Array.from({ length: VERIFY_CONCURRENCY }, worker));
  }

  // Quantity

  function onQuantityInput(row) {
    const { quantity, unit } = row.nodes;
    // "$5000" typed into the field means dollars, the same as in a pasted list.
    if (quantity.value.includes("$")) {
      quantity.value = quantity.value.replace(/\$/g, "").trim();
      unit.value = "usd";
    }
    edited();
    if (row.touched) showProblem(row);
  }

  function onQuantityKey(row, event) {
    if (event.key !== "Enter" || event.metaKey || event.ctrlKey) return;
    event.preventDefault();
    const next = rows[rows.indexOf(row) + 1];
    if (next) next.nodes.symbol.focus();
    else addRow();
  }

  // Imports

  async function importText(text) {
    hideError();
    if (text.length > MAX_FILE_CHARS) {
      showError(() => t("editor.errorTooLong", { max: MAX_FILE_CHARS }));
      return;
    }
    let holdings;
    try {
      ({ holdings } = await postJson("/api/parse", { portfolio: text }, PARSE_TIMEOUT_MS));
    } catch (error) {
      showError(() => t("editor.errorImport", { detail: error.detail }));
      return;
    }
    const imported = holdings.flatMap(({ ticker, shares, amount }) => [
      shares > 0 ? makeRow({ ticker, quantity: shares }) : null,
      amount > 0 ? makeRow({ ticker, quantity: amount, unit: "usd" }) : null,
    ]).filter(Boolean);
    const kept = isSample ? [] : rows.filter((row) => !isEmpty(row));
    if (kept.length + imported.length > MAX_ROWS) {
      showError(() => t("editor.errorTooMany", { max: MAX_ROWS }));
      return;
    }
    const count = imported.length;
    replaceRows([...kept, ...imported], () => t("editor.noticeImported", { count }));
    isSample = false;
    imported.forEach((row) => {
      row.touched = true;
    });
    verifyAll(imported);
  }

  async function importFile(file) {
    importText(await file.text());
  }

  function onPaste(event) {
    const text = (event.clipboardData?.getData("text") ?? "").trim();
    if (!/[\r\n]/.test(text) && !LIST_LINE.test(text)) return;
    event.preventDefault();
    importText(text);
  }

  // Wiring

  addButton.addEventListener("click", addRow);
  clearButton.addEventListener("click", () => {
    replaceRows([], () => t("editor.noticeCleared"));
    isSample = false;
    rows[0].nodes.symbol.focus();
  });
  undoButton.addEventListener("click", undo);
  document.querySelectorAll("[data-preset]").forEach((button) => {
    button.addEventListener("click", () => loadPreset(button));
  });

  fileInput.addEventListener("change", () => {
    const [file] = fileInput.files;
    fileInput.value = "";
    if (file) importFile(file);
  });

  dropTarget.addEventListener("dragenter", (event) => {
    if (!filesIn(event)) return;
    event.preventDefault();
    dragDepth += 1;
    dropTarget.classList.add("is-dropping");
  });
  dropTarget.addEventListener("dragover", (event) => {
    if (!filesIn(event)) return;
    event.preventDefault();
    event.dataTransfer.dropEffect = "copy";
  });
  dropTarget.addEventListener("dragleave", (event) => {
    if (!filesIn(event)) return;
    dragDepth = Math.max(0, dragDepth - 1);
    if (!dragDepth) dropTarget.classList.remove("is-dropping");
  });
  dropTarget.addEventListener("drop", (event) => {
    if (!filesIn(event)) return;
    event.preventDefault();
    dragDepth = 0;
    dropTarget.classList.remove("is-dropping");
    const [file] = event.dataTransfer.files;
    if (file) importFile(file);
  });
  // A file dropped beside the card would otherwise replace the page and lose the portfolio.
  for (const type of ["dragover", "drop"]) {
    window.addEventListener(type, (event) => {
      if (filesIn(event)) event.preventDefault();
    });
  }

  rows = PRESETS.example.rows.map(([ticker, quantity, name]) => makeRow({ ticker, quantity, unit: PRESETS.example.unit, name }));
  isSample = true;
  renderRows();

  return {
    // Redraws every generated string after a language switch.
    relabel() {
      announce("");
      rows.forEach(closeSuggestions);
      rows.forEach(relabelRow);
      if (noticeMessage) noticeText.textContent = noticeMessage();
      if (errorMessage) errorNode.textContent = errorMessage();
    },

    // The portfolio as text for /api/report, or null after pointing the reader at what to fix.
    portfolio() {
      rows.forEach(touch);
      const invalid = rows.find((row) => problem(row)?.level === "error");
      if (invalid) {
        showError(() => t("editor.fixRows"));
        const issue = problem(invalid);
        (issue.field === "symbol" ? invalid.nodes.symbol : invalid.nodes.quantity).focus();
        return null;
      }
      const filled = rows.filter((row) => !isEmpty(row));
      if (!filled.length) {
        showError(() => t("editor.empty"));
        rows[0].nodes.symbol.focus();
        return null;
      }
      hideError();
      return filled
        .map(({ nodes }) => {
          const prefix = nodes.unit.value === "usd" ? "$" : "";
          return `${nodes.symbol.value.trim().toUpperCase()} ${prefix}${parseQuantity(nodes.quantity.value)}`;
        })
        .join("\n");
    },
  };
}
