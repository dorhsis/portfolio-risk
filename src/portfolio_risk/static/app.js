// Wires the page together: the portfolio form, the report, the explanation and the language switch.

import { postJson } from "./api.js";
import { el, reducedMotion } from "./dom.js";
import { createEditor } from "./editor.js";
import { currentLanguage, setLanguage, t, translatePage } from "./i18n.js";
import { drawCharts, markCurrentSection, renderBody, renderHead, renderNav } from "./report.js";

const REPORT_TIMEOUT_MS = 90_000;
const EXPLAIN_TIMEOUT_MS = 120_000;

const REPORT_HINTS = {
  0: "error.hintNetwork",
  400: "error.hint400",
  422: "error.hint422",
  502: "error.hint502",
};

const EXPLAIN_ERRORS = {
  401: "explain.error401",
  502: "explain.error502",
  503: "explain.error503",
};

const singleColumn = window.matchMedia("(max-width: 960px)");

function startClock(textNode, clockNode, message) {
  const started = Date.now();
  textNode.textContent = message;
  const tick = () => {
    clockNode.textContent = t("status.seconds", { seconds: Math.floor((Date.now() - started) / 1000) });
  };
  tick();
  const id = setInterval(tick, 1000);
  return () => {
    clearInterval(id);
    textNode.textContent = "";
    clockNode.textContent = "";
  };
}

function init() {
  translatePage();
  const editor = createEditor();
  const form = document.getElementById("portfolio-form");
  const submit = document.getElementById("submit");
  const benchmark = document.getElementById("benchmark");
  const reportNode = document.getElementById("report");
  const empty = document.getElementById("empty");
  const skeleton = document.getElementById("skeleton");
  const errorBox = document.getElementById("error");
  const result = document.getElementById("result");
  const nav = document.getElementById("report-nav");
  const head = document.getElementById("report-head");
  const body = document.getElementById("report-body");
  const explainForm = document.getElementById("explain-form");
  const explainSubmit = document.getElementById("explain-submit");
  const explainError = document.getElementById("explain-error");
  const explanation = document.getElementById("explanation");
  let currentReport = null;
  let factorsRequested = true;
  let lastError = null;
  let lastExplainError = null;
  let sections = [];
  let navFrame = 0;

  const showError = (error) => {
    lastError = error;
    document.getElementById("error-detail").textContent = error.detail;
    document.getElementById("error-hint").textContent = t(REPORT_HINTS[error.status] ?? REPORT_HINTS[0]);
    errorBox.hidden = false;
  };

  const showExplainError = (error) => {
    lastExplainError = error;
    const key = EXPLAIN_ERRORS[error.status] ?? "explain.errorOther";
    explainError.textContent = t(key, { detail: error.detail });
    explainError.hidden = false;
  };

  const resetExplanation = () => {
    explanation.hidden = true;
    explanation.replaceChildren();
    explainError.hidden = true;
    lastExplainError = null;
  };

  const renderReport = (animate) => {
    document.getElementById("explain").dataset.nav = t("nav.explain");
    head.replaceChildren(renderHead(currentReport));
    body.replaceChildren(...renderBody(currentReport, { factorsRequested }));
    sections = [...result.querySelectorAll("[data-nav]")];
    renderNav(nav, sections);
    drawCharts(body, animate);
  };

  document.querySelectorAll('input[name="language"]').forEach((radio) => {
    radio.checked = radio.value === currentLanguage();
    radio.addEventListener("change", () => setLanguage(radio.value));
  });

  document.addEventListener("app:language", () => {
    editor.relabel();
    if (currentReport) {
      renderReport(false);
      markCurrentSection(nav, sections);
    }
    if (!errorBox.hidden && lastError) showError(lastError);
    if (!explainError.hidden && lastExplainError) showExplainError(lastExplainError);
  });

  window.addEventListener(
    "scroll",
    () => {
      navFrame ||= requestAnimationFrame(() => {
        navFrame = 0;
        markCurrentSection(nav, sections);
      });
    },
    { passive: true },
  );

  benchmark.addEventListener("blur", () => {
    benchmark.value = benchmark.value.trim().toUpperCase();
  });

  // Cmd/Ctrl+Enter runs the report from any field of the form.
  form.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) {
      event.preventDefault();
      form.requestSubmit();
    }
  });

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const portfolio = editor.portfolio();
    if (portfolio === null) return;
    factorsRequested = document.getElementById("factors").checked;
    submit.disabled = true;
    submit.setAttribute("aria-busy", "true");
    errorBox.hidden = true;
    reportNode.setAttribute("aria-busy", "true");
    // A report already on screen is dimmed while it updates; the first one gets a placeholder.
    if (result.hidden) {
      empty.hidden = true;
      skeleton.hidden = false;
    }
    const stopClock = startClock(document.getElementById("status-text"), document.getElementById("status-clock"), t("status.report"));
    try {
      currentReport = await postJson(
        "/api/report",
        {
          portfolio,
          benchmark: benchmark.value.trim().toUpperCase() || "SPY",
          lookback_years: Number(form.elements.lookback.value),
          factors: factorsRequested,
        },
        REPORT_TIMEOUT_MS,
      );
      resetExplanation();
      empty.hidden = true;
      result.hidden = false;
      renderReport(true);
      markCurrentSection(nav, sections);
      if (singleColumn.matches) {
        reportNode.scrollIntoView({ behavior: reducedMotion.matches ? "auto" : "smooth", block: "start" });
      }
    } catch (error) {
      // The previous report describes a different portfolio, so it must not stay on screen.
      currentReport = null;
      result.hidden = true;
      empty.hidden = true;
      showError(error);
    } finally {
      stopClock();
      skeleton.hidden = true;
      submit.disabled = false;
      submit.removeAttribute("aria-busy");
      reportNode.removeAttribute("aria-busy");
    }
  });

  explainForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!currentReport) return;
    explainSubmit.disabled = true;
    explainSubmit.setAttribute("aria-busy", "true");
    resetExplanation();
    const stopClock = startClock(
      document.getElementById("explain-status-text"),
      document.getElementById("explain-status-clock"),
      t("status.explain"),
    );
    try {
      const { explanation: text } = await postJson(
        "/api/explain",
        { report: currentReport, password: document.getElementById("password").value, language: currentLanguage() },
        EXPLAIN_TIMEOUT_MS,
      );
      explanation.replaceChildren(...text.split(/\n\s*\n/).map((paragraph) => el("p", { text: paragraph.trim() })));
      explanation.hidden = false;
    } catch (error) {
      showExplainError(error);
    } finally {
      stopClock();
      explainSubmit.disabled = false;
      explainSubmit.removeAttribute("aria-busy");
    }
  });
}

init();
