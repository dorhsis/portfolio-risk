"""The page and its script are separate files; these checks keep the names they share in sync."""

import re
from html.parser import HTMLParser

from portfolio_risk.web import STATIC_DIR

SCRIPT = (STATIC_DIR / "app.js").read_text()


class _PageNames(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.ids: set[str] = set()
        self.names: set[str] = set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        for attribute, value in attrs:
            if attribute == "id" and value:
                self.ids.add(value)
            if attribute == "name" and value:
                self.names.add(value)


def _page() -> _PageNames:
    page = _PageNames()
    page.feed((STATIC_DIR / "index.html").read_text())
    return page


def test_every_element_the_script_looks_up_by_id_is_in_the_page() -> None:
    wanted = set(re.findall(r'getElementById\("([^"]+)"\)', SCRIPT))

    assert wanted
    assert wanted - _page().ids == set()


def test_every_form_field_the_script_reads_by_name_is_in_the_page() -> None:
    wanted = set(re.findall(r"\.elements\.(\w+)", SCRIPT))

    assert wanted
    assert wanted - _page().names == set()
