from __future__ import annotations

import ssl
from dataclasses import dataclass
from datetime import UTC
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit
from urllib.request import Request, urlopen

import certifi
import feedparser

TRACKING_QUERY_PREFIXES = ("utm_",)
TRACKING_QUERY_NAMES = {
    "fbclid",
    "gclid",
    "igshid",
    "mc_cid",
    "mc_eid",
    "mkt_tok",
    "spm",
}


@dataclass(frozen=True)
class ParsedFeedEntry:
    title: str | None
    url: str
    normalized_url: str
    published_at: str | None


@dataclass(frozen=True)
class ParsedFeed:
    title: str | None
    entries: list[ParsedFeedEntry]


class RssFeedFetcher:
    def __init__(self, timeout_seconds: int) -> None:
        self.timeout_seconds = timeout_seconds

    def fetch(self, feed_url: str) -> ParsedFeed:
        request = Request(
            feed_url,
            headers={
                "User-Agent": "ReaderArchive/0.1 (+https://localhost)",
                "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*",
            },
        )
        ssl_context = ssl.create_default_context(cafile=certifi.where())
        with urlopen(request, timeout=self.timeout_seconds, context=ssl_context) as response:
            content = response.read()
            final_url = response.geturl()

        parsed = feedparser.parse(content)
        if parsed.bozo and not parsed.entries:
            error = getattr(parsed, "bozo_exception", None)
            msg = str(error) if error else "RSS 解析失败。"
            raise RuntimeError(msg)

        feed_title = _clean_text(parsed.feed.get("title")) if parsed.feed else None
        entries = []
        seen: set[str] = set()
        for entry in parsed.entries:
            url = _entry_url(entry, final_url)
            if not url:
                continue
            normalized_url = normalize_article_url(url)
            if normalized_url in seen:
                continue
            seen.add(normalized_url)
            entries.append(
                ParsedFeedEntry(
                    title=_clean_text(entry.get("title")) or None,
                    url=url,
                    normalized_url=normalized_url,
                    published_at=_entry_datetime(entry),
                )
            )
        return ParsedFeed(title=feed_title, entries=entries)


def normalize_article_url(url: str) -> str:
    parts = urlsplit(url.strip())
    scheme = parts.scheme.lower()
    hostname = (parts.hostname or "").lower()
    if not scheme or not hostname:
        return url.strip()

    port = parts.port
    netloc = hostname
    if parts.username:
        auth = parts.username
        if parts.password:
            auth = f"{auth}:{parts.password}"
        netloc = f"{auth}@{netloc}"
    if port and not ((scheme == "http" and port == 80) or (scheme == "https" and port == 443)):
        netloc = f"{netloc}:{port}"

    query = urlencode(
        [
            (key, value)
            for key, value in parse_qsl(parts.query, keep_blank_values=True)
            if not _is_tracking_query_param(key)
        ],
        doseq=True,
    )
    path = parts.path or "/"
    return urlunsplit((scheme, netloc, path, query, ""))


def title_from_url(url: str) -> str:
    parts = urlsplit(url)
    path = parts.path.strip("/")
    return f"{parts.netloc}/{path}" if path else parts.netloc


def _entry_url(entry: dict[str, Any], base_url: str) -> str | None:
    link = entry.get("link")
    if isinstance(link, str) and link.strip():
        return urljoin(base_url, link.strip())
    links = entry.get("links") or []
    for item in links:
        href = item.get("href") if isinstance(item, dict) else None
        if href:
            return urljoin(base_url, str(href).strip())
    return None


def _entry_datetime(entry: dict[str, Any]) -> str | None:
    for key in ("published", "updated", "created"):
        value = entry.get(key)
        if not value:
            continue
        try:
            parsed = parsedate_to_datetime(str(value))
        except (TypeError, ValueError):
            continue
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC).isoformat()
    return None


def _clean_text(value: object) -> str:
    return " ".join(str(value or "").split())


def _is_tracking_query_param(name: str) -> bool:
    lowered = name.lower()
    return lowered in TRACKING_QUERY_NAMES or lowered.startswith(TRACKING_QUERY_PREFIXES)
