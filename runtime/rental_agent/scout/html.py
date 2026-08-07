from __future__ import annotations

import html as html_lib
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse


@dataclass(slots=True, frozen=True)
class ExtractedPage:
    url: str
    title: str
    text: str
    links: tuple[tuple[str, str], ...]


class _PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip_depth = 0
        self._title_depth = 0
        self._anchor_href: str | None = None
        self._anchor_text: list[str] = []
        self.title_parts: list[str] = []
        self.text_parts: list[str] = []
        self.links: list[tuple[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in {"script", "style", "noscript", "svg"}:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return
        if tag == "title":
            self._title_depth += 1
        if tag == "a":
            href = dict(attrs).get("href")
            if href:
                self._anchor_href = href
                self._anchor_text = []

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in {"script", "style", "noscript", "svg"} and self._skip_depth:
            self._skip_depth -= 1
            return
        if self._skip_depth:
            return
        if tag == "title" and self._title_depth:
            self._title_depth -= 1
        if tag == "a" and self._anchor_href:
            self.links.append((self._anchor_href, " ".join(self._anchor_text).strip()))
            self._anchor_href = None
            self._anchor_text = []

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        value = " ".join(data.split())
        if not value:
            return
        self.text_parts.append(value)
        if self._title_depth:
            self.title_parts.append(value)
        if self._anchor_href:
            self._anchor_text.append(value)


def extract_page(html: str, url: str) -> ExtractedPage:
    parser = _PageParser()
    parser.feed(html)
    title = " ".join(parser.title_parts).strip()
    text = " ".join(parser.text_parts)
    text = html_lib.unescape(re.sub(r"\s+", " ", text)).strip()
    links: list[tuple[str, str]] = []
    seen: set[str] = set()
    for href, anchor in parser.links:
        absolute = urljoin(url, href)
        if absolute not in seen:
            seen.add(absolute)
            links.append((absolute, anchor))
    return ExtractedPage(url=url, title=title, text=text, links=tuple(links))


def filter_links(page: ExtractedPage, *, hosts: set[str], pattern: re.Pattern[str], limit: int) -> tuple[str, ...]:
    result: list[str] = []
    for url, _anchor in page.links:
        parsed = urlparse(url)
        if parsed.hostname not in hosts:
            continue
        if not pattern.search(parsed.path):
            continue
        if url not in result:
            result.append(url)
        if len(result) >= limit:
            break
    return tuple(result)
