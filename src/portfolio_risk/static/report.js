// Renders the JSON from /api/report (the same contract as `portfolio-risk --json`).

import { el, reducedMotion } from "./dom.js";
import { fmt, hasMessage, t } from "./i18n.js";

// A position is called out when its share of risk is far from its share of value.
const HEAVY_RATIO = 1.25;
const LIGHT_RATIO = 0.5;
const FLAG_MIN_SHARE = 0.03;

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

// Messages keyed by data the server sends (scenario keys, factor and sector names) fall back to
// the server's own label when the page has no translation for it.
function translated(key, fallback) {
  return hasMessage(key) ? t(key) : fallback;
}

export function drawCharts(container, animate) {
  const charts = container.querySelectorAll(".chart");
  if (!animate || reducedMotion.matches) {
    charts.forEach((chart) => chart.classList.add("is-drawn"));
    return;
  }
  requestAnimationFrame(() => requestAnimationFrame(() => charts.forEach((chart) => chart.classList.add("is-drawn"))));
}

// `nav` is the section's label in the sticky section menu; `meta` sits next to the title.
function section({ id, title, nav, lede, meta }, ...content) {
  return el(
    "section",
    { id, class: "card", "aria-labelledby": `${id}-title`, "data-nav": nav },
    el("div", { class: "card__head" }, el("h2", { id: `${id}-title`, class: "card__title", text: title }), meta),
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

export function renderHead(report) {
  const f = fmt();
  const risk = report.risk;
  const var1d = risk.value_at_risk_1d;
  const drawdown = risk.max_drawdown;
  const confidence = Math.round(var1d.confidence * 100);
  const kpi = (label, value, note) =>
    el("div", { class: "kpi" }, el("p", { class: "kpi__label", text: label }), el("p", { class: "kpi__value", text: value }), el("p", { class: "kpi__note", text: note }));
  const chip = (text) => el("li", { class: "chip", text });

  return section(
    {
      id: "overview",
      title: t("overview.title"),
      nav: t("nav.overview"),
      meta: el(
        "ul",
        { class: "chips", "aria-label": t("overview.params") },
        chip(t("overview.asOf", { date: f.date(report.as_of) })),
        chip(t("overview.benchmark", { benchmark: report.benchmark })),
        chip(t("overview.window", { days: report.window.observations, date: f.date(report.window.start) })),
      ),
    },
    el("p", { class: "overview__label", text: t("overview.total") }),
    el("p", { class: "overview__total", text: f.usd.format(report.total_value) }),
    el(
      "div",
      { class: "kpis" },
      kpi(t("kpi.volatility"), f.pct.format(risk.volatility_annual), t("kpi.volatilityNote", { benchmark: report.benchmark, value: f.pct.format(risk.benchmark_volatility_annual) })),
      kpi(t("kpi.beta", { benchmark: report.benchmark }), f.decimal.format(risk.beta), t("kpi.betaNote")),
      kpi(t("kpi.drawdown"), f.signedPct.format(drawdown.depth), `${f.date(drawdown.peak)} → ${f.date(drawdown.trough)}`),
      kpi(
        t("kpi.var", { confidence }),
        f.signedUsd.format(-var1d.var_amount),
        t("kpi.varNote", {
          percent: f.signedPct.format(-var1d.var),
          tail: 100 - confidence,
          amount: f.signedUsd.format(-var1d.cvar_amount),
        }),
      ),
    ),
  );
}

function weightRiskFlag(position) {
  const { weight, risk_share: share } = position;
  if (share < 0) return ["light", t("weightRisk.hedge")];
  const ratio = fmt().ratio.format(share / weight);
  if (share >= FLAG_MIN_SHARE && share >= weight * HEAVY_RATIO) return ["heavy", t("weightRisk.heavy", { ratio })];
  if (weight >= FLAG_MIN_SHARE && share <= weight * LIGHT_RATIO) return ["light", t("weightRisk.light", { ratio })];
  return null;
}

function renderWeightRisk(report) {
  const f = fmt();
  const positions = [...report.positions].sort((a, b) => b.risk_share - a.risk_share);
  const scale = Math.max(...positions.flatMap((p) => [p.weight, p.risk_share]));
  const rows = positions.map((position) => {
    const flag = weightRiskFlag(position);
    const weight = f.pct.format(position.weight);
    const share = f.pct.format(position.risk_share);
    return el(
      "li",
      { class: "weight-risk__row" },
      el("span", { class: "weight-risk__ticker", text: position.ticker }),
      el("span", { class: "weight-risk__bars", "aria-hidden": "true" }, bar("yard", position.weight / scale), bar("risk", position.risk_share / scale)),
      el(
        "span",
        { class: "weight-risk__values", "aria-hidden": "true" },
        el("span", { class: "weight-risk__weight", text: weight }),
        el("span", { text: share }),
      ),
      el("span", { class: "visually-hidden", text: t("weightRisk.readout", { weight, share }) }),
      flag ? el("p", { class: `weight-risk__flag weight-risk__flag--${flag[0]}`, text: flag[1] }) : null,
    );
  });

  return section(
    {
      id: "weight-risk",
      title: t("weightRisk.title"),
      nav: t("nav.weightRisk"),
      lede: t("weightRisk.lede"),
      meta: legend([
        ["yard", t("weightRisk.legendWeight")],
        ["risk", t("weightRisk.legendRisk")],
      ]),
    },
    el("ol", { class: "weight-risk chart" }, rows),
  );
}

function renderStress(report) {
  const f = fmt();
  const tests = report.stress_tests;
  const scale = signedScale(tests.flatMap((test) => [test.portfolio_return, test.benchmark_return]));
  const proxied = new Set(tests.flatMap((test) => test.proxied_by_beta));

  const rows = tests.map((test) =>
    el(
      "tr",
      {},
      el(
        "td",
        { class: "table__label" },
        `${translated(`scenario.${test.key}`, test.scenario)}${test.proxied_by_beta.length ? " *" : ""}`,
        el("span", { class: "table__sub", text: `${f.date(test.start)} → ${f.date(test.end)}` }),
      ),
      el(
        "td",
        {},
        signedTrack("stress-track", test.portfolio_return, scale, "risk"),
        signedTrack("stress-track", test.benchmark_return, scale, "yard"),
      ),
      el("td", { class: "num", text: f.signedPct.format(test.portfolio_return) }),
      el("td", { class: "num", text: f.signedUsd.format(test.portfolio_pnl) }),
      el("td", { class: "num muted", text: f.signedPct.format(test.benchmark_return) }),
    ),
  );

  return section(
    {
      id: "stress",
      title: t("stress.title"),
      nav: t("nav.stress"),
      lede: t("stress.lede"),
      meta: legend([
        ["risk", t("stress.legendPortfolio")],
        ["yard", report.benchmark],
      ]),
    },
    el(
      "div",
      { class: "chart" },
      table(
        [
          [t("stress.colScenario"), false],
          ["", false],
          [t("stress.colPortfolio"), true],
          [t("stress.colDollars"), true],
          [report.benchmark, true],
        ],
        rows,
      ),
    ),
    proxied.size
      ? el("p", {
          class: "section-note",
          text: t("stress.proxiedNote", { tickers: [...proxied].sort().join(", "), benchmark: report.benchmark }),
        })
      : null,
  );
}

function renderStructure(report) {
  const f = fmt();
  const { concentration, correlation } = report;
  const sectors = Object.entries(report.sectors);
  const sectorScale = Math.max(0, ...sectors.map(([, weight]) => weight));
  const pairs = correlation.high_pairs;
  const threshold = f.decimal.format(correlation.alert_threshold);

  const fact = (label, value, note) =>
    el("div", { class: "fact" }, el("dt", { text: label }), el("dd", {}, value, el("span", { class: "facts__note", text: note })));

  const facts = el(
    "dl",
    { class: "facts" },
    fact(
      t("structure.effective"),
      t("structure.effectiveValue", { value: f.ratio.format(concentration.effective_positions), count: report.positions.length }),
      t("structure.effectiveNote", { hhi: f.decimal.format(concentration.hhi) }),
    ),
    fact(t("structure.top5"), f.pct.format(concentration.top5_share), t("structure.top5Note")),
    fact(
      t("structure.correlation"),
      correlation.average_pairwise === null ? "—" : f.decimal.format(correlation.average_pairwise),
      pairs.length
        ? t("structure.pairs", { threshold, pairs: pairs.map(([a, b, value]) => `${a}–${b} ${f.decimal.format(value)}`).join(", ") })
        : t("structure.noPairs", { threshold }),
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
            el("span", { text: translated(`sector.${name}`, name) }),
            el("span", { class: "share-list__value", text: f.pct.format(weight) }),
            bar("yard", weight / sectorScale),
          ),
        ),
      )
    : el("p", { class: "hint", text: t("structure.noSectors") });

  return section(
    { id: "structure", title: t("structure.title"), nav: t("nav.structure") },
    el("div", { class: "structure" }, facts, el("div", {}, el("p", { class: "subhead", text: t("structure.sectors") }), sectorBlock)),
  );
}

function renderFactors(report, factorsRequested) {
  const f = fmt();
  const exposure = report.factors;
  const heading = { id: "factors", title: t("factors.title"), nav: t("nav.factors") };
  if (!exposure) {
    const note = factorsRequested ? t("factors.failed", { reason: report.factors_note }) : t("factors.disabled");
    return section(heading, el("p", { class: "section-note", text: note }));
  }
  const entries = Object.entries(exposure.loadings);
  const scale = signedScale(entries.map(([, value]) => value));
  const rows = entries.map(([name, value]) =>
    el(
      "li",
      { class: "factor-list__row" },
      el("span", { text: translated(`factor.${name}`, name) }),
      signedTrack("factor-track", value, scale, "risk"),
      el("span", { class: "factor-list__value", text: f.signedDecimal.format(value) }),
    ),
  );

  return section(
    { ...heading, lede: t("factors.lede") },
    el("ul", { class: "factor-list chart" }, rows),
    el("p", {
      class: "section-note",
      text: t("factors.note", {
        r2: f.pct.format(exposure.r_squared),
        alpha: f.signedPct.format(exposure.alpha_annual),
        days: exposure.observations,
      }),
    }),
  );
}

function renderPositions(report) {
  const f = fmt();
  const rows = report.positions.map((p) =>
    el(
      "tr",
      {},
      el("td", { class: "ticker", text: p.ticker }),
      el("td", { class: "num", text: f.plain.format(p.shares) }),
      el("td", { class: "num", text: f.price.format(p.price) }),
      el("td", { class: "num", text: f.usd.format(p.value) }),
      el("td", { class: "num", text: f.pct.format(p.weight) }),
      el("td", { class: "num", text: f.pct.format(p.risk_share) }),
      el("td", { class: "num", text: f.decimal.format(p.beta) }),
      el("td", { class: "num", text: f.pct.format(p.volatility) }),
    ),
  );
  return section(
    { id: "positions", title: t("positions.title"), nav: t("nav.positions") },
    table(
      [
        [t("positions.ticker"), false],
        [t("positions.shares"), true],
        [t("positions.price"), true],
        [t("positions.value"), true],
        [t("positions.weight"), true],
        [t("positions.riskShare"), true],
        [t("positions.beta"), true],
        [t("positions.volatility"), true],
      ],
      rows,
    ),
  );
}

export function renderBody(report, { factorsRequested }) {
  return [renderWeightRisk(report), renderStress(report), renderStructure(report), renderFactors(report, factorsRequested), renderPositions(report)];
}

// Section menu

export function renderNav(nav, targets) {
  nav.replaceChildren(...targets.map((target) => el("a", { class: "report-nav__link", href: `#${target.id}`, text: target.dataset.nav })));
}

// The current section is the last one whose top has scrolled up to the menu. At the bottom of the
// page it is the last section, which may be too short to ever reach the menu.
export function markCurrentSection(nav, targets) {
  if (!targets.length) return;
  const line = nav.getBoundingClientRect().bottom + 16;
  const atBottom = window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 2;
  let current = 0;
  targets.forEach((target, index) => {
    if (target.getBoundingClientRect().top <= line) current = index;
  });
  if (atBottom) current = targets.length - 1;

  nav.querySelectorAll("a").forEach((link, index) => {
    if (index !== current) {
      link.removeAttribute("aria-current");
    } else if (!link.hasAttribute("aria-current")) {
      link.setAttribute("aria-current", "true");
      // On narrow screens the menu scrolls sideways; keep the current item in view.
      nav.scrollTo({
        left: link.offsetLeft - (nav.clientWidth - link.offsetWidth) / 2,
        behavior: reducedMotion.matches ? "auto" : "smooth",
      });
    }
  });
}
