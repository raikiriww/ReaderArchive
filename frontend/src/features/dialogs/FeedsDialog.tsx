import { type FormEvent, useState } from "react";
import { Loader2, Rss, Trash2, X } from "lucide-react";
import type { RssFeed } from "../../types/domain";
import { formatDate, shortError } from "../../utils/format";
import { DialogOverlay, useConfirm } from "./ConfirmDialog";

export interface FeedsDialogProps {
  feeds: RssFeed[];
  /** Add a feed. Resolve to clear the input; throw to keep it (caller shows the error). */
  onCreate: (url: string) => Promise<void>;
  onRefresh: (feedId: string) => Promise<void>;
  onToggle: (feedId: string, enabled: boolean) => Promise<void>;
  /** Called after the user confirms deletion inside this dialog. */
  onDelete: (feedId: string) => Promise<void>;
  onClose: () => void;
}

function isFeedUrl(value: string): boolean {
  return /^https?:\/\/\S+$/i.test(value.trim());
}

export function FeedsDialog({
  feeds,
  onCreate,
  onRefresh,
  onToggle,
  onDelete,
  onClose,
}: FeedsDialogProps): JSX.Element {
  const ask = useConfirm();
  const [url, setUrl] = useState("");
  const [adding, setAdding] = useState(false);
  const [checking, setChecking] = useState<ReadonlySet<string>>(new Set());
  const [toggling, setToggling] = useState<ReadonlySet<string>>(new Set());
  const valid = isFeedUrl(url);

  async function add(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    if (!valid || adding) return;
    setAdding(true);
    try {
      await onCreate(url.trim());
      setUrl("");
    } catch {
      // Keep the address; the caller presents the error.
    } finally {
      setAdding(false);
    }
  }

  async function withBusy(
    setter: typeof setChecking,
    feedId: string,
    action: () => Promise<void>,
  ): Promise<void> {
    setter((items) => new Set(items).add(feedId));
    try {
      await action();
    } catch {
      // The caller presents the error.
    } finally {
      setter((items) => {
        const next = new Set(items);
        next.delete(feedId);
        return next;
      });
    }
  }

  async function remove(feed: RssFeed): Promise<void> {
    const confirmed = await ask({
      title: "删除订阅源",
      message: `删除后不再自动检查「${feed.title || feed.url}」。已经保存的文章会保留。`,
      confirmLabel: "删除",
      danger: true,
    });
    if (!confirmed) return;
    try {
      await onDelete(feed.feed_id);
    } catch {
      // The caller presents the error.
    }
  }

  return (
    <DialogOverlay onClose={onClose} labelledBy="dlgFeedsTitle">
      <section className="dlg-dialog dlg-feeds">
        <header className="dlg-head">
          <h2 id="dlgFeedsTitle">订阅源</h2>
          <button
            className="dlg-icon-btn"
            type="button"
            aria-label="关闭"
            onClick={onClose}
          >
            <X size={16} />
          </button>
        </header>
        <form className="dlg-feed-add" autoComplete="off" onSubmit={add}>
          <div className="dlg-url-field dlg-url-field-small">
            <Rss size={15} aria-hidden="true" />
            <input
              aria-label="RSS 地址"
              name="url"
              placeholder="RSS 地址，例如 https://example.com/feed.xml"
              value={url}
              onChange={(event) => setUrl(event.target.value)}
            />
          </div>
          <button
            className="dlg-btn dlg-btn-primary"
            type="submit"
            disabled={!valid || adding}
          >
            {adding ? "添加中…" : "添加"}
          </button>
        </form>
        <p className="dlg-help dlg-feeds-help">
          订阅源的新文章会自动保存成存档。想单独查看，可以在「全部存档」里把来源选成「订阅」。
        </p>
        <div className="dlg-feed-list" aria-live="polite">
          {feeds.length === 0 ? (
            <p className="dlg-quiet dlg-feed-empty">还没有订阅源</p>
          ) : (
            feeds.map((feed) => {
              const isChecking = checking.has(feed.feed_id);
              const isToggling = toggling.has(feed.feed_id);
              return (
                <div
                  className={`dlg-feed-row ${feed.enabled ? "" : "dlg-off"}`}
                  key={feed.feed_id}
                >
                  <div className="dlg-feed-main">
                    <span className="dlg-feed-name">
                      {feed.title || feed.url}
                    </span>
                    <span className="dlg-feed-url" title={feed.url}>
                      {feed.url}
                    </span>
                    <span className="dlg-feed-meta">
                      {feed.enabled ? "启用" : "已停用"} · 上次检查{" "}
                      {feed.last_checked_at
                        ? formatDate(feed.last_checked_at)
                        : "尚未检查"}
                    </span>
                    {feed.last_error ? (
                      <span className="dlg-error">
                        {shortError(feed.last_error)}
                      </span>
                    ) : null}
                  </div>
                  <div className="dlg-feed-acts">
                    <button
                      className="dlg-text-btn"
                      type="button"
                      disabled={isChecking || !feed.enabled}
                      onClick={() =>
                        void withBusy(setChecking, feed.feed_id, () =>
                          onRefresh(feed.feed_id),
                        )
                      }
                    >
                      {isChecking ? (
                        <>
                          <Loader2
                            size={12}
                            className="dlg-spin"
                            aria-hidden="true"
                          />
                          检查中
                        </>
                      ) : (
                        "立即检查"
                      )}
                    </button>
                    <label
                      className="dlg-switch"
                      title={feed.enabled ? "停用" : "启用"}
                    >
                      <input
                        type="checkbox"
                        role="switch"
                        aria-checked={feed.enabled}
                        aria-label={
                          feed.enabled
                            ? `停用 ${feed.title}`
                            : `启用 ${feed.title}`
                        }
                        checked={feed.enabled}
                        disabled={isToggling}
                        onChange={() =>
                          void withBusy(setToggling, feed.feed_id, () =>
                            onToggle(feed.feed_id, !feed.enabled),
                          )
                        }
                      />
                      <span />
                    </label>
                    <button
                      className="dlg-icon-btn dlg-icon-danger"
                      type="button"
                      title="删除"
                      aria-label={`删除 ${feed.title}`}
                      onClick={() => void remove(feed)}
                    >
                      <Trash2 size={14} />
                    </button>
                  </div>
                </div>
              );
            })
          )}
        </div>
      </section>
    </DialogOverlay>
  );
}
