import { type FormEvent, useState } from "react";
import type { RssFeed } from "../../types/domain";
import { formatDate, shortError } from "../../utils/format";

interface RssPanelProps {
  feeds: RssFeed[];
  onClose: () => void;
  onCreate: (url: string) => Promise<void>;
  onRefreshAll: () => void;
  onRefreshFeed: (feedId: string) => void;
  onToggleFeed: (feedId: string, enabled: boolean) => void;
  onDeleteFeed: (feedId: string) => void;
}

export function RssPanel({
  feeds,
  onClose,
  onCreate,
  onRefreshAll,
  onRefreshFeed,
  onToggleFeed,
  onDeleteFeed,
}: RssPanelProps): JSX.Element {
  const [url, setUrl] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    const nextUrl = url.trim();
    if (!nextUrl) return;
    setSubmitting(true);
    try {
      await onCreate(nextUrl);
      setUrl("");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <section className="rss-panel" aria-labelledby="rssTitle">
      <div className="sidebar-section-header">
        <h2 id="rssTitle">RSS 来源</h2>
        <div className="rss-header-actions">
          <button className="text-button" type="button" onClick={onRefreshAll}>
            刷新
          </button>
          <button className="text-button" type="button" onClick={onClose}>
            关闭
          </button>
        </div>
      </div>
      <form className="rss-form" autoComplete="off" onSubmit={submit}>
        <label className="visually-hidden" htmlFor="feedUrlInput">
          RSS 地址
        </label>
        <input
          id="feedUrlInput"
          name="url"
          type="url"
          placeholder="https://example.com/feed.xml"
          required
          value={url}
          onChange={(event) => setUrl(event.target.value)}
        />
        <button disabled={submitting} type="submit">
          {submitting ? "添加中" : "添加"}
        </button>
      </form>
      <div className="feed-list" aria-live="polite">
        {feeds.length === 0 ? (
          <div className="empty-state compact">还没有 RSS 订阅源</div>
        ) : (
          feeds.map((feed) => (
            <article className="feed-item" key={feed.feed_id}>
              <div className="feed-main">
                <span className="feed-title">{feed.title}</span>
                <span className="feed-url">{feed.url}</span>
                <span className="feed-meta">
                  {feed.enabled ? "启用" : "停用"} · {feed.last_checked_at ? formatDate(feed.last_checked_at) : "尚未检查"}
                </span>
                {feed.last_error ? <div className="error-line">{shortError(feed.last_error)}</div> : null}
              </div>
              <div className="feed-actions">
                <button type="button" onClick={() => onRefreshFeed(feed.feed_id)}>
                  检查
                </button>
                <button type="button" onClick={() => onToggleFeed(feed.feed_id, !feed.enabled)}>
                  {feed.enabled ? "停用" : "启用"}
                </button>
                <button className="danger-action" type="button" onClick={() => onDeleteFeed(feed.feed_id)}>
                  删除
                </button>
              </div>
            </article>
          ))
        )}
      </div>
    </section>
  );
}
