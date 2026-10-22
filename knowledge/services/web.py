"""Fetch web documentation pages into the knowledge base (used by skills).

Only public http(s) URLs are fetched: hosts that resolve to private, loopback
or link-local addresses are refused so a skill file can't make the server
probe its own network. Pages are size- and time-limited and stored as text.
"""
import io
import ipaddress
import re
import socket
from html.parser import HTMLParser
from urllib.parse import urlparse

import httpx

from ..models import Document

MAX_BYTES = 3 * 1024 * 1024
TIMEOUT = 20
TEXT_TYPES = ("text/html", "text/plain", "text/markdown", "application/xhtml+xml")
SKIP_TAGS = {"script", "style", "noscript", "svg", "nav", "footer", "header", "aside", "form", "button"}
BLOCK_TAGS = {"p", "div", "section", "article", "li", "tr", "br", "table", "ul", "ol", "dl", "dt", "dd", "blockquote"}


class FetchError(Exception):
    pass


def check_public_url(url):
    """Raise FetchError unless url is http(s) on a public host."""
    u = urlparse(url)
    if u.scheme not in ("http", "https") or not u.hostname:
        raise FetchError("Only http(s) URLs can be fetched.")
    try:
        infos = socket.getaddrinfo(u.hostname, u.port or (443 if u.scheme == "https" else 80))
    except socket.gaierror as e:
        raise FetchError(f"Can't resolve {u.hostname}.") from e
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            raise FetchError(f"{u.hostname} points to a private address; refusing to fetch it.")


class _TextExtractor(HTMLParser):
    """HTML → text with markdown-style headings and fenced <pre> blocks."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out, self.skip, self.in_pre, self.title, self._in_title = [], 0, 0, "", False

    def handle_starttag(self, tag, attrs):
        if tag in SKIP_TAGS:
            self.skip += 1
        elif tag == "title":
            self._in_title = True
        elif re.fullmatch(r"h[1-6]", tag):
            self.out.append("\n\n" + "#" * int(tag[1]) + " ")
        elif tag == "pre":
            self.in_pre += 1
            self.out.append("\n\n```\n")
        elif tag in BLOCK_TAGS:
            self.out.append("\n")

    def handle_endtag(self, tag):
        if tag in SKIP_TAGS:
            self.skip = max(0, self.skip - 1)
        elif tag == "title":
            self._in_title = False
        elif tag == "pre":
            self.in_pre = max(0, self.in_pre - 1)
            self.out.append("\n```\n\n")
        elif re.fullmatch(r"h[1-6]", tag):
            self.out.append("\n\n")
        elif tag in BLOCK_TAGS:
            self.out.append("\n")

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        if self.skip:
            return
        self.out.append(data if self.in_pre else re.sub(r"\s+", " ", data))

    def text(self):
        text = "".join(self.out).replace("¶", "")  # doc sites append ¶ permalinks to headings
        text = re.sub(r"[ \t]+\n", "\n", text)
        return re.sub(r"\n{3,}", "\n\n", text).strip()


def fetch_text(url):
    """Download url and return (title, text)."""
    check_public_url(url)
    headers = {"User-Agent": "CodeLens-RAG/1.0 (documentation fetcher)"}
    try:
        with httpx.stream("GET", url, headers=headers, timeout=TIMEOUT, follow_redirects=True) as resp:
            if resp.status_code >= 400:
                raise FetchError(f"HTTP {resp.status_code} for {url}")
            check_public_url(str(resp.url))  # redirects must stay public too
            ctype = resp.headers.get("content-type", "").split(";")[0].strip().lower()
            if ctype and not ctype.startswith(TEXT_TYPES):
                raise FetchError(f"{url} is {ctype}, not a text/HTML page.")
            body = b""
            for part in resp.iter_bytes():
                body += part
                if len(body) > MAX_BYTES:
                    raise FetchError(f"{url} is larger than 3 MB.")
            raw = body.decode(resp.encoding or "utf-8", errors="replace")
    except httpx.HTTPError as e:
        raise FetchError(f"Couldn't fetch {url}: {e}") from e
    if ctype in ("text/plain", "text/markdown"):
        return urlparse(url).path.rsplit("/", 1)[-1] or url, raw
    parser = _TextExtractor()
    parser.feed(raw)
    return parser.title.strip() or url, parser.text()


def ingest_url(url):
    """Fetch url into the knowledge base (re-uses an existing doc for the same URL)."""
    from .ingest import ingest_file

    existing = Document.objects.filter(source_url=url).first()
    if existing and existing.indexed:
        return existing, False
    title, text = fetch_text(url)
    if len(text) < 200:
        raise FetchError(f"{url} had almost no readable text.")
    if existing:
        from .ingest import delete_document

        delete_document(existing)
    slug = re.sub(r"[^a-z0-9]+", "_", (urlparse(url).netloc + urlparse(url).path).lower()).strip("_")[:80]
    doc = ingest_file(io.BytesIO(f"# {title}\n\nSource: {url}\n\n{text}".encode()), f"{slug}.txt",
                      title=f"web: {title[:120]}", source_url=url)
    return doc, True
