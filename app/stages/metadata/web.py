# book cards from the web: schema.org Book/Product markup on pages the book names, on shop pages those link to,
# and on book sites a local metasearch returns for the title and author
import html
import json
import os
import re
from functools import cache
from urllib.parse import urlparse

import httpx
import net
import settings
import yaml

from stages.metadata.candidates import SourceResult
from stages.metadata.catalogues import YEAR_IN, _matches
from stages.metadata.title_pages import normalise_isbn, same_isbn

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36"
URL_IN_TEXT = re.compile(r"(?:https?://|www\.)[^\s<>\"'«»()\[\]]+[^\s<>\"'«»()\[\].,;:!?]")
LD_JSON = re.compile(r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', re.S)


@cache
def conf() -> dict:
    return yaml.safe_load((settings.CONFIG_DIR / "web_sources.yaml").read_text())


def _domain(url: str) -> str:
    host = urlparse(url if "://" in url else "https://" + url).netloc.lower()
    return host[4:] if host.startswith("www.") else host


def _listed(domain: str, names: list[str]) -> bool:
    return any(domain == n or domain.endswith("." + n) for n in names)


def links_in(text: str) -> list[str]:
    out = []
    for raw in URL_IN_TEXT.findall(text):
        url = raw if "://" in raw else "https://" + raw
        if not _listed(_domain(url), conf()["skip_domains"]):
            out.append(url)
    return list(dict.fromkeys(out))


def _client() -> net.Client:
    return net.Client(headers={"Accept-Language": "ru,en;q=0.8"})


def _items(ld):
    if isinstance(ld, list):
        for x in ld:
            yield from _items(x)
    elif isinstance(ld, dict):
        if "@graph" in ld:
            yield from _items(ld["@graph"])
        types = ld.get("@type")
        types = types if isinstance(types, list) else [types]
        if any(t in ("Book", "Product") for t in types):
            yield ld
        if isinstance(ld.get("workExample"), (list, dict)):
            yield from _items(ld["workExample"])


def _names(value) -> list[str]:
    values = value if isinstance(value, list) else [value]
    out = []
    for v in values:
        name = v.get("name") if isinstance(v, dict) else v
        if isinstance(name, str) and name.strip():
            out.append(html.unescape(name).strip())
    return out


def _publisher(value) -> str | None:
    sellers = {s.lower() for s in conf().get("sellers", [])}
    name = (_names(value) or [None])[0]
    return None if name is None or name.lower() in sellers else name


def card_from(url: str, page: str) -> list[dict]:
    cards = []
    for raw in LD_JSON.findall(page):
        try:
            data = json.loads(raw.strip())
        except json.JSONDecodeError:
            continue
        for it in _items(data):
            isbn = normalise_isbn(it.get("isbn") or it.get("gtin13"))
            date = str(it.get("datePublished") or it.get("copyrightYear") or "")
            year = YEAR_IN.search(date)
            card = {"url": url, "title": html.unescape(str(it.get("name") or "")).strip(),
                    "authors": _names(it.get("author")), "publisher": _publisher(it.get("publisher")),
                    "isbn": isbn if len(isbn) in (10, 13) else None, "year": int(year.group(0)) if year else None,
                    "edition": it.get("bookEdition"), "pages": it.get("numberOfPages"),
                    "language": it.get("inLanguage") if isinstance(it.get("inLanguage"), str) else None,
                    "format": str(it.get("bookFormat") or "").rsplit("/", 1)[-1] or None}
            if card["title"]:
                cards.append(card)
    return cards


def _fetch(client: net.Client, url: str) -> str | None:
    try:
        seen = client.get(url)
        return seen.text if seen.status_code == 200 else None
    except httpx.HTTPError:
        return None


def search(query: str) -> list[str]:
    urls = []
    base = os.getenv("SEARXNG_URL")
    if base:
        try:
            seen = net.get(base + "/search", params={"q": query, "format": "json"}, timeout=40)
            urls += [r["url"] for r in seen.json().get("results", [])]
        except (httpx.HTTPError, ValueError):
            pass
    key = os.getenv("BRAVE_API_KEY")
    if key:
        try:
            seen = net.get("https://api.search.brave.com/res/v1/web/search", params={"q": query},
                             headers={"X-Subscription-Token": key, "Accept": "application/json"}, timeout=30)
            urls += [r["url"] for r in seen.json().get("web", {}).get("results", [])]
        except (httpx.HTTPError, ValueError):
            pass
    return list(dict.fromkeys(urls))[: conf()["search_results"] * 2]


# book pages named in the text, the shop pages they link to, then search results on book sites
def cards_for(text: str, title: str | None, authors: list[str] | None,
              isbn: str | None = None) -> tuple[list[dict], list[str]]:
    budget, books = conf()["link_pages"], conf()["book_domains"]
    named = links_in(text)
    named_domains = {_domain(u) for u in named}
    visited, cards, log = set(), [], []
    with _client() as client:
        def visit(url: str) -> str | None:
            nonlocal budget
            if url in visited or budget <= 0:
                return None
            visited.add(url)
            budget -= 1
            page = _fetch(client, url)
            log.append(f"{url} -> {'ok' if page else 'no answer'}")
            if page:
                cards.extend(card_from(url, page))
            return page
        hop2 = []
        for url in named:
            page = visit(url)
            if page:
                hop2 += [u for u in re.findall(r'href="(https?://[^"#]+)"', page)
                         if _listed(_domain(u), books) and not _listed(_domain(u), conf()["skip_domains"])]
        for url in list(dict.fromkeys(hop2)):
            visit(url)
        # search has its own budget, so a technical book's many links do not starve it
        budget = conf()["search_pages"]
        queries = ([isbn] if isbn else []) + ([" ".join([title, *(authors or [])[:1]])] if title else [])
        for query in queries:
            for url in search(query)[: conf()["search_results"]]:
                if _listed(_domain(url), books) or _domain(url) in named_domains:
                    visit(url)
    return [c for c in cards if _matches(c["title"], c["authors"], title, authors)] if title else cards, log


def read(text: str, title: str | None, authors: list[str] | None, own_isbn: str | None,
         language: str | None = None) -> SourceResult:
    out = SourceResult("web", covers=("publisher", "year", "editions"))
    try:
        cards, log = cards_for(text, title, authors, own_isbn)
    except Exception as e:
        out.failed = f"web lookup failed: {e}"
        return out
    # another language is another translation, not an edition of this book
    cards = [c for c in cards if not (language and c.get("language") and c["language"][:2].lower() != language)]
    if not cards:
        out.failed = f"no matching book card in {len(log)} pages: {log[:6]}"
        return out
    editions, seen = [], set()
    for c in cards:
        entry = {k: c[k] for k in ("isbn", "publisher", "year", "pages", "format", "url") if c.get(k)}
        page = re.sub(r"^https?://(www\.)?", "", entry.get("url", "")).rstrip("/")
        key = (page, entry.get("isbn"), entry.get("year"))
        if len(entry) > 1 and key not in seen:
            seen.add(key)
            editions.append(entry)
    out.add("editions", editions, 0.6, f"{len(cards)} book cards from {len(log)} pages")
    # a card with the book's own ISBN describes the same edition
    same = [c for c in cards if same_isbn(c.get("isbn"), own_isbn)]
    for c in same[:1]:
        where = f"web card with the book's own ISBN: {c['url']}"
        out.add("publisher", c.get("publisher"), 0.6, where)
        out.add("year", c.get("year"), 0.55, where)
    # a matching title and author is not the same edition: the web never sets the book's own ISBN
    return out
