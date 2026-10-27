"use strict";

// Renders the JSON from /api/report (the same contract as `portfolio-risk --json`).
// Every value goes into the DOM through textContent, never innerHTML.

const REPORT_TIMEOUT_MS = 90_000;
const EXPLAIN_TIMEOUT_MS = 120_000;
const MAX_FILE_CHARS = 20_000;

// A position is called out when its share of risk is far from its share of value.
const HEAVY_RATIO = 1.25;
const LIGHT_RATIO = 0.5;
const FLAG_MIN_SHARE = 0.03;

const FACTOR_LABELS = {
  "Mkt-RF": "Рынок",
  SMB: "Малые компании",
  HML: "Value",
  RMW: "Прибыльность",
  CMA: "Консервативные инвестиции",
  Mom: "Моментум",
};

const formats = {
  pct: new Intl.NumberFormat("ru-RU", { style: "percent", minimumFractionDigits: 1, maximumFractionDigits: 1 }),
  signedPct: new Intl.NumberFormat("ru-RU", {
    style: "percent",
    minimumFractionDigits: 1,
    maximumFractionDigits: 1,
    signDisplay: "exceptZero",
  }),
  usd: new Intl.NumberFormat("ru-RU", { style: "currency", currency: "USD", maximumFractionDigits: 0 }),
  signedUsd: new Intl.NumberFormat("ru-RU", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
    signDisplay: "exceptZero",
  }),
  price: new Intl.NumberFormat("ru-RU", { style: "currency", currency: "USD", minimumFractionDigits: 2 }),
  decimal: new Intl.NumberFormat("ru-RU", { minimumFractionDigits: 2, maximumFractionDigits: 2 }),
  signedDecimal: new Intl.NumberFormat("ru-RU", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
    signDisplay: "exceptZero",
  }),
  ratio: new Intl.NumberFormat("ru-RU", { minimumFractionDigits: 1, maximumFractionDigits: 1 }),
  plain: new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 4 }),
};

const pct = (value) => formats.pct.format(value);
const signedPct = (value) => formats.signedPct.format(value);
const usd = (value) => formats.usd.format(value);
const date = (iso) => iso.split("-").reverse().join(".");

const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
const singleColumn = window.matchMedia("(max-width: 960px)");

class ApiError extends Error {
  constructor(status, detail) {
    super(detail);
    this.status = status;
    this.detail = detail;
  }
}

function el(tag, attributes = {}, ...children) {
  const node = document.createElement(tag);
  for (const [name, value] of Object.entries(attributes)) {
    if (value === undefined || value === null || value === false) continue;
    if (name === "text") node.textContent = value;
    else node.setAttribute(name, value === true ? "" : value);
  }
  node.append(...children.flat().filter((child) => child !== null && child !== undefined && child !== false));
  return node;
}

function bar(series, fraction, side = "right") {
  const size = `${(Math.max(0, Math.min(1, fraction)) * 100).toFixed(2)}%`;
  const className = `bar bar--${series}${side === "left" ? " bar--left" : ""}`;
  return el("span", { class: className, style: `--size: ${size}` });
}

// Two-sided track for values that can be negative: the zero line sits at the same place in
// every row because both sides are sized by the largest magnitude on each side.
function signedTrack(className, value, scale, series) {
  // Grow factors must sum to 1, otherwise flexbox hands out only that fraction of the track.
  const total = scale.negative + scale.positive || 1;
  const negative = el("span", { class: `${className}__side`, style: `flex: ${scale.negative / total} 1 0` });
  const positive = el("span", { class: `${className}__side`, style: `flex: ${scale.positive / total} 1 0` });
  if (value < 0) negative.append(bar(series, -value / scale.negative, "left"));
  if (value > 0) positive.append(bar(series, value / scale.positive));
  return el("span", { class: className, "aria-hidden": "true" }, negative, positive);
}

function signedScale(values) {
  return {
    negative: Math.max(0, ...values.map((v) => -v)),
    positive: Math.max(0, ...values.map((v) => v)),
  };
}

function drawCharts(container) {
  const charts = container.querySelectorAll(".chart");
  if (reducedMotion.matches) {
    charts.forEach((chart) => chart.classList.add("is-drawn"));
    return;
  }
  requestAnimationFrame(() => requestAnimationFrame(() => charts.forEach((chart) => chart.classList.add("is-drawn"))));
}

function section(title, lede, ...content) {
  const id = `section-${title.toLowerCase().replace(/[^a-zа-яё0-9]+/gi, "-")}`;
  return el(
    "section",
    { class: "panel", "aria-labelledby": id },
    el("h2", { id, class: "section-title", text: title }),
    lede ? el("p", { class: "section-lede", text: lede }) : null,
    ...content,
  );
}

function legend(items) {
  return el(
    "ul",
    { class: "legend", "aria-hidden": "true" },
    items.map(([series, label]) =>
      el(
        "li",
        { class: "legend__item" },
        el("span", { class: `legend__swatch swatch--${series}` }),
        el("span", { text: label }),
      ),
    ),
  );
}

function table(headers, rows) {
  return el(
    "div",
    { class: "table-scroll" },
    el(
      "table",
      { class: "table" },
      el("thead", {}, el("tr", {}, headers.map(([label, numeric]) => el("th", { class: numeric ? "num" : null, scope: "col", text: label })))),
      el("tbody", {}, rows),
    ),
  );
}

// Report sections

function renderHead(report) {
  const risk = report.risk;
  const var1d = risk.value_at_risk_1d;
  const drawdown = risk.max_drawdown;
  const kpi = (label, value, note) =>
    el("div", { class: "kpi" }, el("p", { class: "kpi__label", text: label }), el("p", { class: "kpi__value", text: value }), el("p", { class: "kpi__note", text: note }));

  return el(
    "div",
    { class: "panel" },
    el(
      "header",
      { class: "summary" },
      el("h2", { class: "summary__eyebrow", text: `Портфель на ${date(report.as_of)} · бенчмарк ${report.benchmark}` }),
      el("p", { class: "summary__total", text: usd(report.total_value) }),
      el("p", {
        class: "summary__window",
        text: `Риск оценён с ${date(report.window.start)}, торговых дней: ${report.window.observations}`,
      }),
    ),
    el(
      "div",
      { class: "kpis" },
      kpi("Волатильность за год", pct(risk.volatility_annual), `у ${report.benchmark}: ${pct(risk.benchmark_volatility_annual)}`),
      kpi(`Бета к ${report.benchmark}`, formats.decimal.format(risk.beta), "1 — движется вместе с рынком"),
      kpi("Максимальная просадка", signedPct(drawdown.depth),`${date(drawdown.peak)} → ${date(drawdown.trough)}`),
      kpi(
        `Плохой день, VaR ${Math.round(var1d.confidence * 100)}\u00a0%`,
        formats.signedUsd.format(-var1d.var_amount),
        `${signedPct(-var1d.var)}; в худших ${Math.round((1 - var1d.confidence) * 100)}\u00a0% дней в среднем ${formats.signedUsd.format(-var1d.cvar_amount)}`,
      ),
    ),
  );
}

function weightRiskFlag(position) {
  const { weight, risk_share: share } = position;
  if (share < 0) return ["light", "Снижает общий риск портфеля"];
  const ratio = formats.ratio.format(share / weight);
  if (share >= FLAG_MIN_SHARE && share >= weight * HEAVY_RATIO) return ["heavy", `Риск ×${ratio} от веса: раскачивает портфель сильнее, чем весит`];
  if (weight >= FLAG_MIN_SHARE && share <= weight * LIGHT_RATIO) return ["light", `Риск ×${ratio} от веса: гасит колебания портфеля`];
  return null;
}

function renderWeightRisk(report) {
  const positions = [...report.positions].sort((a, b) => b.risk_share - a.risk_share);
  const scale = Math.max(...positions.flatMap((p) => [p.weight, p.risk_share]));
  const rows = positions.map((position) => {
    const flag = weightRiskFlag(position);
    return el(
      "li",
      { class: "weight-risk__row" },
      el("span", { class: "weight-risk__ticker", text: position.ticker }),
      el("span", { class: "weight-risk__bars", "aria-hidden": "true" }, bar("yard", position.weight / scale), bar("risk", position.risk_share / scale)),
      el(
        "span",
        { class: "weight-risk__values", "aria-hidden": "true" },
        el("span", { class: "weight-risk__weight", text: pct(position.weight) }),
        el("span", { text: pct(position.risk_share) }),
      ),
      el("span", { class: "visually-hidden", text: `Вес ${pct(position.weight)}, доля риска ${pct(position.risk_share)}.` }),
      flag ? el("p", { class: `weight-risk__flag weight-risk__flag--${flag[0]}`, text: flag[1] }) : null,
    );
  });

  return section(
    "Вес против риска",
    "Сколько позиция весит в портфеле и какую долю общего риска она даёт. Риск считается с учётом того, как бумаги двигаются вместе, поэтому он редко совпадает с весом.",
    legend([
      ["yard", "Вес в портфеле"],
      ["risk", "Доля риска"],
    ]),
    el("ol", { class: "weight-risk chart" }, rows),
  );
}

function renderStress(report) {
  const tests = report.stress_tests;
  const scale = signedScale(tests.flatMap((t) => [t.portfolio_return, t.benchmark_return]));
  const proxied = new Set(tests.flatMap((t) => t.proxied_by_beta));

  const rows = tests.map((test) =>
    el(
      "tr",
      {},
      el(
        "td",
        { class: "table__label" },
        `${test.scenario}${test.proxied_by_beta.length ? " *" : ""}`,
        el("span", { class: "table__sub", text: `${date(test.start)} → ${date(test.end)}` }),
      ),
      el(
        "td",
        {},
        signedTrack("stress-track", test.portfolio_return, scale, "risk"),
        signedTrack("stress-track", test.benchmark_return, scale, "yard"),
      ),
      el("td", { class: "num", text: signedPct(test.portfolio_return) }),
      el("td", { class: "num", text: formats.signedUsd.format(test.portfolio_pnl) }),
      el("td", { class: "num muted", text: signedPct(test.benchmark_return) }),
    ),
  );

  return section(
    "Если бы кризис повторился",
    "Текущие веса портфеля в окнах от пика до дна индекса S&P 500.",
    legend([
      ["risk", "Портфель"],
      ["yard", report.benchmark],
    ]),
    el(
      "div",
      { class: "chart" },
      table(
        [
          ["Сценарий", false],
          ["", false],
          ["Портфель", true],
          ["В долларах", true],
          [report.benchmark, true],
        ],
        rows,
      ),
    ),
    proxied.size
      ? el("p", {
          class: "section-note",
          text: `* Часть бумаг тогда ещё не торговалась (${[...proxied].sort().join(", ")}), их результат оценён как бета × доходность ${report.benchmark}.`,
        })
      : null,
  );
}

function renderStructure(report) {
  const { concentration, correlation } = report;
  const positionsCount = report.positions.length;
  const sectors = Object.entries(report.sectors);
  const sectorScale = Math.max(0, ...sectors.map(([, weight]) => weight));
  const pairs = correlation.high_pairs;
  const threshold = formats.decimal.format(correlation.alert_threshold);

  const fact = (label, value, note) => [el("dt", { text: label }), el("dd", {}, value, el("span", { class: "facts__note", text: note }))];

  const facts = el(
    "dl",
    { class: "facts" },
    fact(
      "Эффективное число позиций",
      `${formats.ratio.format(concentration.effective_positions)} из ${positionsCount}`,
      `Столько равных позиций дали бы такую же концентрацию. Индекс Херфиндаля ${formats.decimal.format(concentration.hhi)}.`,
    ),
    fact("Пять крупнейших позиций", pct(concentration.top5_share), "Доля стоимости портфеля"),
    fact(
      "Средняя корреляция между бумагами",
      correlation.average_pairwise === null ? "—" : formats.decimal.format(correlation.average_pairwise),
      pairs.length
        ? `От ${threshold} и выше: ${pairs.map(([a, b, value]) => `${a}–${b} ${formats.decimal.format(value)}`).join(", ")}`
        : `Пар с корреляцией от ${threshold} нет`,
    ),
  );

  const sectorBlock = sectors.length
    ? el(
        "ul",
        { class: "share-list chart" },
        sectors.map(([name, weight]) =>
          el(
            "li",
            { class: "share-list__row" },
            el("span", { text: name }),
            el("span", { class: "share-list__value", text: pct(weight) }),
            bar("yard", weight / sectorScale),
          ),
        ),
      )
    : el("p", { class: "hint", text: "Секторы не удалось определить." });

  return section(
    "Концентрация",
    null,
    el("div", { class: "structure" }, facts, el("div", {}, el("p", { class: "subhead", text: "Секторы по стоимости" }), sectorBlock)),
  );
}

function renderFactors(report) {
  const exposure = report.factors;
  if (!exposure) {
    return section("Факторный профиль", null, el("p", { class: "section-note", text: `Факторы не посчитаны: ${report.factors_note}.` }));
  }
  const entries = Object.entries(exposure.loadings);
  const scale = signedScale(entries.map(([, value]) => value));
  const rows = entries.map(([name, value]) =>
    el(
      "li",
      { class: "factor-list__row" },
      el("span", { text: FACTOR_LABELS[name] ?? name }),
      signedTrack("factor-track", value, scale, "risk"),
      el("span", { class: "factor-list__value", text: formats.signedDecimal.format(value) }),
    ),
  );

  return section(
    "Факторный профиль",
    "Регрессия доходности на факторы Fama–French и моментум. Рынок около 1 — портфель движется как рынок; плюс у остальных — наклон в сторону фактора, минус — против него.",
    el("ul", { class: "factor-list chart" }, rows),
    el("p", {
      class: "section-note",
      text:
        `Факторы объясняют ${pct(exposure.r_squared)} колебаний портфеля. ` +
        `Альфа в прошлом: ${signedPct(exposure.alpha_annual)} в год. Дней в расчёте: ${exposure.observations}.` +
        (report.factors_note ? ` ${report.factors_note}.` : ""),
    }),
  );
}

function renderPositions(report) {
  const rows = report.positions.map((p) =>
    el(
      "tr",
      {},
      el("td", { class: "ticker", text: p.ticker }),
      el("td", { class: "num", text: formats.plain.format(p.shares) }),
      el("td", { class: "num", text: formats.price.format(p.price) }),
      el("td", { class: "num", text: usd(p.value) }),
      el("td", { class: "num", text: pct(p.weight) }),
      el("td", { class: "num", text: pct(p.risk_share) }),
      el("td", { class: "num", text: formats.decimal.format(p.beta) }),
      el("td", { class: "num", text: pct(p.volatility) }),
    ),
  );
  return section(
    "Позиции",
    null,
    table(
      [
        ["Тикер", false],
        ["Акций", true],
        ["Цена", true],
        ["Стоимость", true],
        ["Вес", true],
        ["Доля риска", true],
        ["Бета", true],
        ["Волатильность", true],
      ],
      rows,
    ),
  );
}

// Network

async function postJson(url, body, timeoutMs) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal: controller.signal,
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new ApiError(response.status, typeof payload.detail === "string" ? payload.detail : `HTTP ${response.status}`);
    }
    return payload;
  } catch (error) {
    if (error instanceof ApiError) throw error;
    throw new ApiError(0, error.name === "AbortError" ? "сервер не ответил вовремя" : "нет связи с сервером");
  } finally {
    clearTimeout(timer);
  }
}

function startClock(textNode, clockNode, message) {
  const started = Date.now();
  textNode.textContent = message;
  const tick = () => {
    clockNode.textContent = `${Math.floor((Date.now() - started) / 1000)} с`;
  };
  tick();
  const id = setInterval(tick, 1000);
  return () => {
    clearInterval(id);
    textNode.textContent = "";
    clockNode.textContent = "";
  };
}

const REPORT_HINTS = {
  0: "Проверьте подключение и попробуйте ещё раз.",
  400: "Проверьте позиции: формат ticker,shares, по строке на бумагу, количество акций — положительное число.",
  422: "Проверьте поля формы.",
  502: "Источник котировок не вернул данные. Проверьте тикеры; если они верные, Yahoo мог временно ограничить запросы — попробуйте через минуту.",
};

const EXPLAIN_MESSAGES = {
  401: () => "Неверный пароль.",
  503: () => "Объяснение на этом сайте выключено: владелец не задал пароль.",
  502: (detail) => `Модель не ответила: ${detail}`,
};

// Wiring

function init() {
  const form = document.getElementById("portfolio-form");
  const submit = document.getElementById("submit");
  const portfolio = document.getElementById("portfolio");
  const benchmark = document.getElementById("benchmark");
  const fileInput = document.getElementById("csv-file");
  const reportNode = document.getElementById("report");
  const empty = document.getElementById("empty");
  const errorBox = document.getElementById("error");
  const result = document.getElementById("result");
  const head = document.getElementById("report-head");
  const body = document.getElementById("report-body");
  const explainForm = document.getElementById("explain-form");
  const explainSubmit = document.getElementById("explain-submit");
  const explainError = document.getElementById("explain-error");
  const explanation = document.getElementById("explanation");
  let currentReport = null;

  const showError = (error) => {
    document.getElementById("error-detail").textContent = error.detail;
    document.getElementById("error-hint").textContent = REPORT_HINTS[error.status] ?? REPORT_HINTS[0];
    errorBox.hidden = false;
  };

  const resetExplanation = () => {
    explanation.hidden = true;
    explanation.replaceChildren();
    explainError.hidden = true;
  };

  fileInput.addEventListener("change", async () => {
    const [file] = fileInput.files;
    if (!file) return;
    const text = await file.text();
    fileInput.value = "";
    if (text.length > MAX_FILE_CHARS) {
      showError(new ApiError(400, `файл длиннее ${MAX_FILE_CHARS} символов`));
      return;
    }
    errorBox.hidden = true;
    portfolio.value = text.trim();
    portfolio.focus();
  });

  benchmark.addEventListener("blur", () => {
    benchmark.value = benchmark.value.trim().toUpperCase();
  });

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    submit.disabled = true;
    errorBox.hidden = true;
    reportNode.setAttribute("aria-busy", "true");
    const stopClock = startClock(
      document.getElementById("status-text"),
      document.getElementById("status-clock"),
      "Загружаю котировки и считаю риск, обычно это 10–30 секунд…",
    );
    try {
      const report = await postJson(
        "/api/report",
        {
          portfolio: portfolio.value,
          benchmark: benchmark.value.trim().toUpperCase() || "SPY",
          lookback_years: Number(document.getElementById("lookback").value),
          factors: document.getElementById("factors").checked,
        },
        REPORT_TIMEOUT_MS,
      );
      currentReport = report;
      head.replaceChildren(renderHead(report));
      body.replaceChildren(renderWeightRisk(report), renderStress(report), renderStructure(report), renderFactors(report), renderPositions(report));
      resetExplanation();
      empty.hidden = true;
      result.hidden = false;
      drawCharts(body);
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
      submit.disabled = false;
      reportNode.removeAttribute("aria-busy");
    }
  });

  explainForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!currentReport) return;
    explainSubmit.disabled = true;
    resetExplanation();
    const stopClock = startClock(
      document.getElementById("explain-status-text"),
      document.getElementById("explain-status-clock"),
      "Модель читает отчёт, обычно это 15–30 секунд…",
    );
    try {
      const { explanation: text } = await postJson(
        "/api/explain",
        { report: currentReport, password: document.getElementById("password").value },
        EXPLAIN_TIMEOUT_MS,
      );
      explanation.replaceChildren(...text.split(/\n\s*\n/).map((paragraph) => el("p", { text: paragraph.trim() })));
      explanation.hidden = false;
    } catch (error) {
      const message = EXPLAIN_MESSAGES[error.status];
      explainError.textContent = message ? message(error.detail) : `Не получилось: ${error.detail}`;
      explainError.hidden = false;
    } finally {
      stopClock();
      explainSubmit.disabled = false;
    }
  });
}

init();
