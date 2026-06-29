from app.rss import RssFeedFetcher


class FakeResponse:
    def __init__(self, content: str, final_url: str = "https://example.com/feed.xml") -> None:
        self.content = content.encode()
        self.final_url = final_url

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return self.content

    def geturl(self) -> str:
        return self.final_url


def test_fetcher_allows_repeated_url_when_item_link_is_feed_site(monkeypatch) -> None:
    rss = """<?xml version="1.0"?>
<rss version="2.0">
  <channel>
    <title>Daily Feed</title>
    <link>https://example.com/daily</link>
    <item>
      <title>Daily Brief</title>
      <link>https://example.com/daily</link>
      <pubDate>Mon, 29 Jun 2026 00:00:00 GMT</pubDate>
    </item>
  </channel>
</rss>"""

    def fake_urlopen(*args: object, **kwargs: object) -> FakeResponse:
        return FakeResponse(rss)

    monkeypatch.setattr("app.rss.urlopen", fake_urlopen)

    feed = RssFeedFetcher(timeout_seconds=5).fetch("https://example.com/feed.xml")

    assert len(feed.entries) == 1
    entry = feed.entries[0]
    assert entry.allow_repeated_url is True
    assert entry.entry_key == (
        "published:https://example.com/daily|2026-06-29T00:00:00+00:00"
    )


def test_fetcher_uses_url_key_for_normal_published_item(monkeypatch) -> None:
    rss = """<?xml version="1.0"?>
<rss version="2.0">
  <channel>
    <title>Normal Feed</title>
    <link>https://example.com/</link>
    <item>
      <title>Article</title>
      <link>https://example.com/articles/1</link>
      <pubDate>Mon, 29 Jun 2026 00:00:00 GMT</pubDate>
    </item>
  </channel>
</rss>"""

    def fake_urlopen(*args: object, **kwargs: object) -> FakeResponse:
        return FakeResponse(rss)

    monkeypatch.setattr("app.rss.urlopen", fake_urlopen)

    feed = RssFeedFetcher(timeout_seconds=5).fetch("https://example.com/feed.xml")

    assert len(feed.entries) == 1
    entry = feed.entries[0]
    assert entry.allow_repeated_url is False
    assert entry.entry_key == "url:https://example.com/articles/1"
