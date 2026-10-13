import { CheckCheck, Hash, X } from "lucide-react";
import { type MouseEvent, type ReactNode, useEffect, useRef } from "react";
import type { ArchiveTask } from "../../types/domain";
import { type SourceFilter, type StatusFilter, type ViewState, viewLabel } from "../../app/viewState";
import { dayGroupLabel, Row } from "./Row";

export type TaskGroup = [label: string, tasks: ArchiveTask[]];

export const ATTENTION_GROUP = "需要处理";

/** Attention group first (unread view), then the rest grouped by day in list order. */
export function buildGroups(attention: ArchiveTask[], items: ArchiveTask[], now: Date = new Date()): TaskGroup[] {
  const groups: TaskGroup[] = attention.length ? [[ATTENTION_GROUP, attention]] : [];
  const byDay = new Map<string, ArchiveTask[]>();
  for (const task of items) {
    const label = dayGroupLabel(task.created_at, now);
    const bucket = byDay.get(label);
    if (bucket) bucket.push(task);
    else byDay.set(label, [task]);
  }
  return [...groups, ...byDay.entries()];
}

/** Tags that co-occur most with the current tag filter, for 「再加一个标签」. */
export function relatedTags(items: ArchiveTask[], current: string[], limit = 6): Array<[string, number]> {
  const selected = new Set(current.map((tag) => tag.toLowerCase()));
  const counts = new Map<string, number>();
  for (const task of items) {
    for (const tag of task.tags) {
      if (selected.has(tag.toLowerCase())) continue;
      counts.set(tag, (counts.get(tag) ?? 0) + 1);
    }
  }
  return [...counts.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0])).slice(0, limit);
}

const sourceOptions: Array<[SourceFilter, string]> = [
  ["all", "全部来源"],
  ["manual", "手动保存"],
  ["rss", "订阅"],
];
const statusOptions: Array<[StatusFilter, string]> = [
  ["all", "全部"],
  ["unread", "未读"],
  ["problem", "有问题"],
];

export interface ListHeaderProps {
  view: ViewState;
  total: number;
  related: Array<[string, number]>;
  onViewChange(view: ViewState): void;
}

export function ListHeader({ view, total, related, onViewChange }: ListHeaderProps): JSX.Element {
  const subtitle =
    view.kind === "unread" ? "所有还没读的存档（手动保存和订阅），以及需要你处理的任务" : `${total} 条`;
  return (
    <header className="list-head-wrap">
      <div className="list-head">
        <div className="list-title">
          <h1>
            {view.kind === "tag" ? <Hash size={17} aria-hidden="true" /> : null}
            {viewLabel(view)}
          </h1>
          <p>{subtitle}</p>
        </div>
        {view.kind === "all" ? (
          <div className="list-head-actions">
            <div className="mini-seg" role="group" aria-label="来源">
              {sourceOptions.map(([value, label]) => (
                <button
                  key={value}
                  type="button"
                  className={view.source === value ? "on" : ""}
                  aria-pressed={view.source === value}
                  onClick={() => onViewChange({ ...view, source: value })}
                >
                  {label}
                </button>
              ))}
            </div>
            <div className="mini-seg" role="group" aria-label="状态">
              {statusOptions.map(([value, label]) => (
                <button
                  key={value}
                  type="button"
                  className={view.status === value ? "on" : ""}
                  aria-pressed={view.status === value}
                  onClick={() => onViewChange({ ...view, status: value })}
                >
                  {label}
                </button>
              ))}
            </div>
          </div>
        ) : null}
      </div>
      {view.kind === "tag" && (view.tags.length > 1 || related.length) ? (
        <div className="scope-row">
          {view.tags.length > 1
            ? view.tags.map((tag) => (
                <button
                  key={tag}
                  className="chip-toggle on"
                  type="button"
                  aria-label={`移除标签 ${tag}`}
                  onClick={() => onViewChange({ ...view, tags: view.tags.filter((item) => item !== tag) })}
                >
                  {tag}
                  <X size={12} aria-hidden="true" />
                </button>
              ))
            : null}
          {related.length ? <span className="scope-label">再加一个标签：</span> : null}
          {related.map(([tag, count]) => (
            <button
              key={tag}
              className="chip-toggle"
              type="button"
              onClick={() => onViewChange({ ...view, tags: [...view.tags, tag] })}
            >
              + {tag}
              <span className="chip-count">{count}</span>
            </button>
          ))}
        </div>
      ) : null}
    </header>
  );
}

export function EmptyList({ view }: { view: ViewState }): JSX.Element {
  if (view.kind === "unread")
    return (
      <div className="list-empty">
        <CheckCheck size={28} aria-hidden="true" />
        <p>没有未读的存档</p>
        <small>新保存的网页和新的订阅文章会出现在这里。</small>
      </div>
    );
  if (view.kind === "all" && (view.source !== "all" || view.status !== "all"))
    return (
      <div className="list-empty">
        <p>没有符合筛选条件的存档</p>
        <small>换一个来源或状态试试。</small>
      </div>
    );
  if (view.kind === "tag")
    return (
      <div className="list-empty">
        <p>没有同时带这些标签的存档</p>
      </div>
    );
  return (
    <div className="list-empty">
      <p>这里还没有存档</p>
      <small>按 N 或直接粘贴网址保存第一个网页。</small>
    </div>
  );
}

export interface ListPaneProps {
  view: ViewState;
  groups: TaskGroup[];
  total: number;
  related: Array<[string, number]>;
  selectedId: string | null;
  onOpen(task: ArchiveTask, event: MouseEvent<HTMLButtonElement>): void;
  onViewChange(view: ViewState): void;
  hasMore: boolean;
  onLoadMore(): void;
  isLoading: boolean;
  isFetchingMore: boolean;
  error?: Error | null;
  /** Search box shown above everything. */
  searchBox: ReactNode;
  /** When set, replaces the header and rows (active search). */
  searchContent?: ReactNode;
  now?: Date;
}

export function ListPane({
  view,
  groups,
  total,
  related,
  selectedId,
  onOpen,
  onViewChange,
  hasMore,
  onLoadMore,
  isLoading,
  isFetchingMore,
  error,
  searchBox,
  searchContent,
  now,
}: ListPaneProps): JSX.Element {
  const rowsRef = useRef<HTMLDivElement | null>(null);
  const sentinelRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!selectedId) return;
    const row = rowsRef.current?.querySelector(`[data-task-id="${CSS.escape(selectedId)}"]`);
    row?.scrollIntoView({ block: "nearest" });
  }, [selectedId]);

  useEffect(() => {
    const sentinel = sentinelRef.current;
    if (!sentinel || !hasMore || searchContent || typeof IntersectionObserver === "undefined") return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) onLoadMore();
      },
      { root: rowsRef.current, rootMargin: "400px 0px" },
    );
    observer.observe(sentinel);
    return () => observer.disconnect();
  }, [hasMore, onLoadMore, searchContent]);

  const empty = groups.every(([, tasks]) => tasks.length === 0);

  return (
    <section className="list-pane wide" aria-label="存档列表">
      {searchBox}
      {searchContent ?? (
        <>
          <ListHeader view={view} total={total} related={related} onViewChange={onViewChange} />
          <div className="rows" ref={rowsRef} role="listbox" aria-label={viewLabel(view)}>
            {error ? <p className="list-error">列表加载失败：{error.message}</p> : null}
            {isLoading && empty ? (
              <p className="list-loading">正在加载…</p>
            ) : empty ? (
              <EmptyList view={view} />
            ) : (
              groups.map(([label, tasks]) => (
                <div className="row-group" key={label}>
                  <div className="group-label">
                    {label}
                    <span>{tasks.length}</span>
                  </div>
                  {tasks.map((task) => (
                    <Row
                      key={task.task_id}
                      task={task}
                      now={now}
                      selected={task.task_id === selectedId}
                      onOpen={(event) => onOpen(task, event)}
                    />
                  ))}
                </div>
              ))
            )}
            {hasMore ? (
              <div className="list-foot" ref={sentinelRef}>
                <button className="text-btn small" type="button" disabled={isFetchingMore} onClick={onLoadMore}>
                  {isFetchingMore ? "正在加载…" : "加载更多"}
                </button>
              </div>
            ) : null}
          </div>
        </>
      )}
    </section>
  );
}
