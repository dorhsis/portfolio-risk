"""Find numbers in an LLM explanation that the report it explains does not contain.

The explanation may round report numbers, but not invent or compute them: a sum of two weights or
a ratio is not grounded. Russian and English prose are both read, since the page explains in
either language. The report arrives from the browser in /api/explain, so any shape is tolerated:
whatever is missing simply grounds nothing.
"""

import re
from collections.abc import Iterator, Mapping
from datetime import date
from typing import Any, NamedTuple

# Numbers the prose may use without them being report values: the 1-day VaR horizon, the
# top-5 share and 100% as the whole portfolio.
PLAIN_CONSTANTS = (1.0, 5.0)
PERCENT_CONSTANTS = (100.0,)


class Number(NamedTuple):
    text: str
    value: float
    # The rounding step the number was written with: 0.1 for "21,9", 1000 for "92 тысячи".
    unit: float
    percent: bool
    year: bool
    # The % was written once for this number and the next ("1,44 и 30,1%" or "23–24%"), so it
    # may stand for a share or for a plain value.
    shared_percent: bool = False

    def matches(self, value: float) -> bool:
        """True when `value` rounds or truncates to this number at its written precision.

        Rounding through one extra digit also counts (9 790,4999 -> 9 790,5 -> 9 791), so the
        lower bound reaches 0.55 of a step. Years are compared exactly: 2008 is not a
        truncated 2008.7.
        """
        magnitude = abs(value)
        # Floats like 65.65 - 0.05 land a hair outside an exactly representable boundary.
        slack = 1e-9 * max(1.0, self.value)
        upper = self.value + (self.unit / 2 if self.year else self.unit)
        return self.value - 0.55 * self.unit - slack <= magnitude < upper


class _DateMention(NamedTuple):
    text: str
    day: int
    month: int
    year: int | None  # "8 апреля" names no year

    def matches(self, known: date) -> bool:
        same_day = (known.day, known.month) == (self.day, self.month)
        return same_day and self.year in (None, known.year)


# Names that contain digits but are not numbers from the report.
_NAMED_ENTITIES = re.compile(r"S&P\s*500|COVID-19|Fama[\s–-]*French(?:\s*\d)?|R²", re.IGNORECASE)
_RUSSIAN_MONTHS = (
    "января",
    "февраля",
    "марта",
    "апреля",
    "мая",
    "июня",
    "июля",
    "августа",
    "сентября",
    "октября",
    "ноября",
    "декабря",
)
_ENGLISH_MONTHS = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)
# English months are matched case-sensitively, so "the top 5 may exceed" is not 5 May.
_ENGLISH_MONTH = (
    r"(?-i:\b(?:"
    + "|".join(_ENGLISH_MONTHS)
    + r"|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sept|Sep|Oct|Nov|Dec)\b\.?)"
)
_DATES = re.compile(
    r"(?<!\d)(?P<d1>\d{1,2})\.(?P<m1>\d{1,2})\.(?P<y1>\d{4})(?!\d)"
    r"|(?<!\d)(?P<y2>\d{4})-(?P<m2>\d{2})-(?P<d2>\d{2})(?!\d)"
    rf"|(?<![\d.,])(?P<d3>\d{{1,2}})(?:-?(?:го|е|ое))?\s+(?P<m3>{'|'.join(_RUSSIAN_MONTHS)})"
    r"(?:\s+(?P<y3>\d{4}))?"
    rf"|(?P<m4>{_ENGLISH_MONTH})\s+(?P<d4>\d{{1,2}})(?!\d)(?:st|nd|rd|th)?(?:,?\s+(?P<y4>\d{{4}}))?"
    rf"|(?<![\d.,])(?P<d5>\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?(?P<m5>{_ENGLISH_MONTH})"
    r"(?:,?\s+(?P<y5>\d{4}))?",
    re.IGNORECASE,
)
_NUMBER = re.compile(
    r"(?<![\w.,])"
    r"(?P<integer>[1-9]\d{0,2}(?:[ \u00a0\u202f]\d{3})+(?!\d)"
    r"|[1-9]\d{0,2}(?:,\d{3})+(?!\d|,\d)"
    r"|\d+)"
    r"(?:[.,](?P<fraction>\d+))?"
    r"(?P<percent>\s*-?\s*(?:%|процент\w*|percent\w*|п\.\s?п\.))?"
    r"(?P<multiplier>\s*(?:тыс|млн|млрд)\w*\.?|\s+(?:thousand|million|billion)\b)?",
    re.IGNORECASE,
)
_MULTIPLIERS = {
    "тыс": 1e3,
    "млн": 1e6,
    "млрд": 1e9,
    "thousand": 1e3,
    "million": 1e6,
    "billion": 1e9,
}
# "23–24%", "24,5 и 24 процента", "32.2 and 34.4 percent": the unit written once covers both.
_SHARED_PERCENT = re.compile(
    r"(?<![\w.,])(\d+(?:[.,]\d+)?)"
    r"(?=\s*(?:[-–—]|и|или|and|or|to)\s*\d+(?:[.,]\d+)?\s*(?:%|процент|percent))",
    re.IGNORECASE,
)


def ungrounded_numbers(text: str, report: Mapping[str, Any]) -> list[str]:
    """Numbers and dates in `text`, as written, that no report value rounds to."""
    plain, percent = _plain_candidates(report), _percent_candidates(report)
    ungrounded = [
        n.text
        for n in numbers(text)
        if not any(n.matches(c) for c in _candidates_for(n, plain, percent))
    ]
    known_dates = _report_dates(report)
    ungrounded += [
        d.text for d in _date_mentions(text) if not any(d.matches(k) for k in known_dates)
    ]
    return ungrounded


def numbers(text: str) -> list[Number]:
    """Every number written in `text`, dates and named entities like "S&P 500" excluded."""
    text = _DATES.sub(" ", _NAMED_ENTITIES.sub(" ", text))
    shared = {match.start() for match in _SHARED_PERCENT.finditer(text)}
    return [_parse_number(match, match.start() in shared) for match in _NUMBER.finditer(text)]


def _candidates_for(number: Number, plain: list[float], percent: list[float]) -> list[float]:
    if number.shared_percent:
        return percent + plain
    return percent if number.percent else plain


def _date_mentions(text: str) -> list[_DateMention]:
    mentions = []
    for match in _DATES.finditer(text):
        year: int | None
        if match["d1"]:
            day, month, year = int(match["d1"]), int(match["m1"]), int(match["y1"])
        elif match["y2"]:
            day, month, year = int(match["d2"]), int(match["m2"]), int(match["y2"])
        elif match["d3"]:
            day, month = int(match["d3"]), _RUSSIAN_MONTHS.index(match["m3"].lower()) + 1
            year = int(match["y3"]) if match["y3"] else None
        else:
            day = int(match["d4"] or match["d5"])
            month = _english_month(match["m4"] or match["m5"])
            raw_year = match["y4"] or match["y5"]
            year = int(raw_year) if raw_year else None
        mentions.append(_DateMention(match.group(), day, month, year))
    return mentions


def _english_month(name: str) -> int:
    prefix = name[:3].lower()
    return next(i for i, month in enumerate(_ENGLISH_MONTHS, 1) if month.lower().startswith(prefix))


def _parse_number(match: re.Match[str], shared_percent: bool) -> Number:
    digits = re.sub(r"\D", "", match["integer"])
    fraction = match["fraction"] or ""
    multiplier_word = (match["multiplier"] or "").strip().lower()
    multiplier = next(
        (m for prefix, m in _MULTIPLIERS.items() if multiplier_word.startswith(prefix)), 1.0
    )

    value = float(f"{digits}.{fraction or 0}") * multiplier
    percent = bool(match["percent"]) or shared_percent
    year = _is_year(value, multiplier, percent)
    unit = 10.0 ** -len(fraction) * multiplier
    if not fraction and not year:
        # Trailing zeros of an integer are rounding, but only down to two significant digits:
        # "92 000" was rounded to thousands, "90 000" for 92 040 is too rough to count.
        trailing_zeros = len(digits) - len(digits.rstrip("0"))
        significant = len(digits) - trailing_zeros
        unit *= 10.0 ** min(trailing_zeros, max(0, len(digits) - max(significant, 2)))
    return Number(match.group().strip(), value, unit, percent, year, shared_percent)


def _is_year(value: float, multiplier: float, percent: bool) -> bool:
    return multiplier == 1 and not percent and value.is_integer() and 1900 <= value <= 2100


def _numeric_leaves(value: Any) -> Iterator[float]:
    if isinstance(value, bool) or value is None:
        return
    if isinstance(value, int | float):
        yield float(value)
    elif isinstance(value, Mapping):
        for item in value.values():
            yield from _numeric_leaves(item)
    elif isinstance(value, list):
        for item in value:
            yield from _numeric_leaves(item)


def _string_leaves(value: Any) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, Mapping):
        for item in value.values():
            yield from _string_leaves(item)
    elif isinstance(value, list):
        for item in value:
            yield from _string_leaves(item)


def _report_dates(report: Mapping[str, Any]) -> set[date]:
    return {day for day in map(_date, _string_leaves(report)) if day is not None}


def _plain_candidates(report: Mapping[str, Any]) -> list[float]:
    """Values a number written without % may stand for."""
    candidates = [abs(v) for v in _numeric_leaves(report)]
    candidates += PLAIN_CONSTANTS
    scenarios = _list(report.get("stress_tests"))
    for scenario in scenarios:
        start, end = _date(_field(scenario, "start")), _date(_field(scenario, "end"))
        if start and end:
            candidates += range(start.year, end.year + 1)
        candidates.append(_count(_field(scenario, "proxied_by_beta")))
    candidates += (day.year for day in _report_dates(report))
    for text in _string_leaves(report):
        candidates += (float(year) for year in re.findall(r"\b\d{4}\b", text))
    window_start, as_of = _date(_field(report.get("window"), "start")), _date(report.get("as_of"))
    if window_start and as_of:
        candidates.append(round((as_of - window_start).days / 365.25))
    candidates += (_count(report.get(key)) for key in ("positions", "sectors"))
    candidates.append(len(scenarios))
    candidates.append(_count(_field(report.get("correlation"), "high_pairs")))
    return candidates


def _percent_candidates(report: Mapping[str, Any]) -> list[float]:
    """Values a number written with % may stand for: every decimal share times 100."""
    candidates = [abs(v) * 100 for v in _numeric_leaves(report)]
    confidence = _field(_field(report.get("risk"), "value_at_risk_1d"), "confidence")
    if isinstance(confidence, int | float) and not isinstance(confidence, bool):
        candidates.append((1 - confidence) * 100)
    candidates += PERCENT_CONSTANTS
    return candidates


def _field(value: Any, key: str) -> Any:
    return value.get(key) if isinstance(value, Mapping) else None


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _count(value: Any) -> int:
    return len(value) if isinstance(value, list | Mapping) else 0


def _date(value: Any) -> date | None:
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None
