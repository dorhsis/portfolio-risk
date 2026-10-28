"""The page, its scripts and its translations are separate files; these checks keep the names they
share in sync."""

import json
import re
from html.parser import HTMLParser

from portfolio_risk.factors import FACTOR_COLUMNS
from portfolio_risk.stress import HISTORICAL_SCENARIOS
from portfolio_risk.web import STATIC_DIR

SCRIPTS = "\n".join(path.read_text() for path in sorted(STATIC_DIR.glob("*.js")))
MESSAGES: dict[str, dict[str, str]] = json.loads((STATIC_DIR / "messages.json").read_text())
I18N_ATTRIBUTES = ("data-i18n", "data-i18n-label", "data-i18n-placeholder")


class _Page(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.ids: set[str] = set()
        self.names: set[str] = set()
        self.message_keys: set[str] = set()
        self.presets: set[str] = set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        for attribute, value in attrs:
            if not value:
                continue
            if attribute == "id":
                self.ids.add(value)
            elif attribute == "name":
                self.names.add(value)
            elif attribute in I18N_ATTRIBUTES:
                self.message_keys.add(value)
            elif attribute == "data-preset":
                self.presets.add(value)


def _page() -> _Page:
    page = _Page()
    page.feed((STATIC_DIR / "index.html").read_text())
    return page


def _script_message_keys() -> set[str]:
    """Quoted literals in a message namespace, such as "editor.add" or "error.hint400"."""
    namespaces = "|".join({key.split(".")[0] for key in MESSAGES["ru"]})
    return set(re.findall(rf'"((?:{namespaces})\.[A-Za-z0-9]+)"', SCRIPTS))


def _placeholders(text: str) -> set[str]:
    return set(re.findall(r"\{(\w+)\}", text))


def test_every_element_the_scripts_look_up_by_id_is_in_the_page() -> None:
    wanted = set(re.findall(r'getElementById\("([^"]+)"\)', SCRIPTS))

    assert wanted
    assert wanted - _page().ids == set()


def test_every_form_field_the_scripts_read_by_name_is_in_the_page() -> None:
    wanted = set(re.findall(r"\.elements\.(\w+)", SCRIPTS))

    assert wanted
    assert wanted - _page().names == set()


def test_every_example_button_has_an_example_portfolio() -> None:
    presets = _page().presets

    assert presets
    assert {name for name in presets if not re.search(rf"\b{name}: \{{", SCRIPTS)} == set()


def test_every_language_has_the_same_messages() -> None:
    assert MESSAGES.keys() == {"ru", "en"}
    assert MESSAGES["en"].keys() == MESSAGES["ru"].keys()


def test_translations_keep_the_placeholders_of_the_original() -> None:
    mismatched = {
        key
        for key, text in MESSAGES["ru"].items()
        if _placeholders(MESSAGES["en"][key]) != _placeholders(text)
    }

    assert mismatched == set()


def test_every_message_the_page_and_scripts_use_exists() -> None:
    used = _page().message_keys | _script_message_keys()

    assert len(used) > 50
    assert used - MESSAGES["ru"].keys() == set()


def test_every_stress_scenario_and_factor_has_a_translated_name() -> None:
    wanted = {f"scenario.{s.key}" for s in HISTORICAL_SCENARIOS}
    wanted |= {f"factor.{name}" for name in FACTOR_COLUMNS}

    assert wanted - MESSAGES["ru"].keys() == set()
