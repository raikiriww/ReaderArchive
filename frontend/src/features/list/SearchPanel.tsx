import { useInfiniteQuery } from "@tanstack/react-query";
import { History, Search, SlidersHorizontal, X } from "lucide-react";
import { type MouseEvent, type RefObject, useEffect, useMemo, useRef, useState } from "react";
import type { ArchiveTag, ArchiveTask } from "../../types/domain";
import { type SearchFilters, type SearchPage, type SearchTask, searchArchives } from "../search/api";
import { searchDefaults } from "../search/state";
import { Row } from "./Row";

/* ---------- recent searches (sessionStorage) ---------- */

const RECENT_KEY = "reader-recent-searches";
const RECENT_LIMIT = 6;

export function loadRecentSearches(storage: Pick<Storage, "getItem"> | null = safeSession()): string[] {
  try {
    const value = JSON.parse(storage?.getItem(RECENT_KEY) || "[]");
    return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string").slice(0, RECENT_LIMIT) : [];
  } catch {
    return [];
  }
}

export function rememberSearch(recent: string[], query: string): string[] {
  const value = query.trim();
  if (!value) return recent;
  return [value, ...recent.filter((item) => item !== value)].slice(0, RECENT_LIMIT);
}

export function saveRecentSearches(recent: string[]): void {
  try {
    const storage = safeSession();
    if (!storage) return;
    if (recent.length) storage.setItem(RECENT_KEY, JSON.stringify(recent));
    else storage.removeItem(RECENT_KEY);
  } catch {
    /* storage unavailable: recents just do not persist */
  }
}

function safeSession(): Storage | null {
  try {
    return typeof window === "undefined" ? null : window.sessionStorage;
  } catch {
    return null;
  }
}

/* ---------- data ---------- */

/** Possible matches after the first direct match collapse; leading semantic answers stay visible. */
export function splitSearchResults(items: SearchTask[]): { firstStrong: number; collapsible: number } {
  const firstStrong = items.findIndex((item) => item.search_match?.strength !== "possible");
  const collapsible = items.filter(
    (item, index) => item.search_match?.strength === "possible" && firstStrong >= 0 && index > firstStrong,
  ).length;
  return { firstStrong, collapsible };
}

export function visibleSearchResults(items: SearchTask[], showPossible: boolean): SearchTask[] {
  if (showPossible) return items;
  const { firstStrong } = splitSearchResults(items);
  return items.filter(
    (item, index) => !(item.search_match?.strength === "possible" && firstStrong >= 0 && index > firstStrong),
  );
}

export function searchTaskToArchiveTask(task: SearchTask): ArchiveTask {
  return { ...task, search_match: null };
}

export function activeFilterCount(filters: SearchFilters): number {
  return (
    Number(filters.content_type !== "all") +
    Number(Boolean(filters.source)) +
    Number(Boolean(filters.date_from)) +
    filters.tags.length +
    Number(!filters.include_read) +
    Number(filters.exact)
  );
}

export interface ArchiveSearchResult {
  items: SearchTask[];
  page: SearchPage | null;
  isLoading: boolean;
  isFetching: boolean;
  error: Error | null;
  hasMore: boolean;
  loadMore(): void;
  refetch(): void;
}

export function useArchiveSearch(query: string, filters: SearchFilters): ArchiveSearchResult {
  const q = query.trim();
  const search = useInfiniteQuery({
    queryKey: ["archive-search", q, filters],
    enabled: Boolean(q),
    staleTime: 30_000,
    initialPageParam: 0,
    queryFn: ({ pageParam, signal }) => searchArchives(q, filters, pageParam, signal),
    getNextPageParam: (last) => (last.has_more ? last.offset + last.items.length : undefined),
  });
  const items = useMemo(() => {
    const seen = new Set<string>();
    const result: SearchTask[] = [];
    for (const page of search.data?.pages ?? []) {
      for (const item of page.items) {
        if (seen.has(item.task_id)) continue;
        seen.add(item.task_id);
        result.push(item);
      }
    }
    return result;
  }, [search.data]);
  return {
    items,
    page: search.data?.pages[0] ?? null,
    isLoading: search.isLoading,
    isFetching: search.isFetching,
    error: (search.error as Error | null) ?? null,
    hasMore: Boolean(search.hasNextPage),
    loadMore: () => {
      if (search.hasNextPage && !search.isFetchingNextPage) void search.fetchNextPage();
    },
    refetch: () => void search.refetch(),
  };
}

/* ---------- search box ---------- */

export interface SearchBoxProps {
  inputRef: RefObject<HTMLInputElement | null>;
  query: string;
  onQuery(query: string): void;
  onCommit(query: string): void;
  recent: string[];
  onClearRecent(): void;
  /** Called on ArrowDown so keyboard users can move into the results. */
  onLeave?(): void;
}

export function SearchBox({ inputRef, query, onQuery, onCommit, recent, onClearRecent, onLeave }: SearchBoxProps): JSX.Element {
  const [focus, setFocus] = useState(false);
  const blurTimer = useRef<number | null>(null);
  useEffect(
    () => () => {
      if (blurTimer.current !== null) window.clearTimeout(blurTimer.current);
    },
    [],
  );
  const showRecent = focus && !query && recent.length > 0;
  return (
    <div className="search-wrap">
      <div className="search-row">
        <Search size={15} className="search-icon" aria-hidden="true" />
        <input
          ref={inputRef}
          className="search-input"
          type="search"
          aria-label="搜索存档"
          placeholder="搜索标题、正文、标签，或描述大意"
          value={query}
          onChange={(event) => onQuery(event.target.value)}
          onFocus={() => setFocus(true)}
          onBlur={() => {
            blurTimer.current = window.setTimeout(() => setFocus(false), 150);
          }}
          onKeyDown={(event) => {
            if (event.key === "Escape") {
              event.preventDefault();
              event.stopPropagation();
              if (query) onQuery("");
              else event.currentTarget.blur();
            } else if (event.key === "Enter") {
              event.preventDefault();
              event.stopPropagation();
              onCommit(query);
              event.currentTarget.blur();
            } else if (event.key === "ArrowDown") {
              event.preventDefault();
              event.stopPropagation();
              event.currentTarget.blur();
              onLeave?.();
            }
          }}
        />
        {query ? (
          <button className="ghost-icon" type="button" onClick={() => onQuery("")} aria-label="清除搜索" title="清除 Esc">
            <X size={14} aria-hidden="true" />
          </button>
        ) : (
          <kbd className="kbd">⌘K</kbd>
        )}
      </div>
      {showRecent ? (
        <div className="recent-pop">
          <div className="recent-head">
            最近搜索
            <button
              type="button"
              onMouseDown={(event) => {
                event.preventDefault();
                onClearRecent();
              }}
            >
              清空
            </button>
          </div>
          {recent.map((item) => (
            <button
              key={item}
              type="button"
              onMouseDown={(event) => {
                event.preventDefault();
                onQuery(item);
                onCommit(item);
              }}
            >
              <History size={14} aria-hidden="true" />
              {item}
            </button>
          ))}
          <p>只保存在当前浏览器会话里</p>
        </div>
      ) : null}
    </div>
  );
}

/* ---------- filters + notice ---------- */

const typeOptions: Array<[SearchFilters["content_type"], string]> = [
  ["all", "全部"],
  ["web", "网页"],
  ["video", "视频"],
  ["file", "文件"],
];

export interface SearchFiltersBarProps {
  query: string;
  filters: SearchFilters;
  onFilters(filters: SearchFilters): void;
  tags: ArchiveTag[];
  page: SearchPage | null;
  resultCount: number;
  possibleCount: number;
  onRefresh?(): void;
}

export function SearchFiltersBar({
  query,
  filters,
  onFilters,
  tags,
  page,
  resultCount,
  possibleCount,
  onRefresh,
}: SearchFiltersBarProps): JSX.Element {
  const [open, setOpen] = useState(false);
  const count = activeFilterCount(filters);
  const set = (patch: Partial<SearchFilters>) => onFilters({ ...filters, ...patch });
  const exact = filters.exact || /^".+"$/.test(query.trim());
  const total = page?.total ?? resultCount;
  return (
    <div className="search-filters">
      <div className="sf-line">
        <div className="mini-seg" role="group" aria-label="类型">
          {typeOptions.map(([value, label]) => (
            <button
              key={value}
              type="button"
              className={filters.content_type === value ? "on" : ""}
              aria-pressed={filters.content_type === value}
              onClick={() => set({ content_type: value })}
            >
              {label}
            </button>
          ))}
        </div>
        <button
          type="button"
          className={`chip-toggle ${open || count ? "on" : ""}`}
          aria-expanded={open}
          onClick={() => setOpen((value) => !value)}
        >
          <SlidersHorizontal size={13} aria-hidden="true" />
          筛选{count ? ` ${count}` : ""}
        </button>
        <select
          className="sort-select"
          value={filters.sort}
          aria-label="排序"
          onChange={(event) => set({ sort: event.target.value as SearchFilters["sort"] })}
        >
          <option value="relevance">最相关</option>
          <option value="newest">最新保存</option>
          <option value="oldest">最早保存</option>
        </select>
      </div>
      {open ? (
        <div className="sf-panel">
          <label>
            来源
            <select value={filters.source} onChange={(event) => set({ source: event.target.value as SearchFilters["source"] })}>
              <option value="">全部来源</option>
              <option value="manual">手动保存</option>
              <option value="rss">RSS 订阅</option>
            </select>
          </label>
          <label>
            保存日期起
            <input type="date" value={filters.date_from} onChange={(event) => set({ date_from: event.target.value })} />
          </label>
          <label>
            标签
            <select
              value={filters.tags[0] || ""}
              onChange={(event) => set({ tags: event.target.value ? [event.target.value] : [] })}
            >
              <option value="">全部标签</option>
              {tags.map((tag) => (
                <option key={tag.name} value={tag.name}>
                  {tag.name}
                </option>
              ))}
            </select>
          </label>
          <label className="check">
            <input
              type="checkbox"
              checked={!filters.include_read}
              onChange={(event) => set({ include_read: !event.target.checked })}
            />
            仅未读
          </label>
          <label className="check">
            <input type="checkbox" checked={filters.exact} onChange={(event) => set({ exact: event.target.checked })} />
            只匹配原词（或给短语加引号）
          </label>
          {count ? (
            <button className="text-btn small" type="button" onClick={() => onFilters({ ...searchDefaults, sort: filters.sort })}>
              清除筛选
            </button>
          ) : null}
        </div>
      ) : null}
      {page ? (
        <p className="sf-notice" role="status">
          {exact
            ? "正在按原词查找。"
            : page.mode === "keyword"
              ? "当前按关键词查找，按大意查找暂不可用。"
              : "结合关键词和内容大意查找。"}
          <span>
            {" "}
            共 {page.total_is_exact === false ? "约 " : ""}
            {total} 条{possibleCount ? `，其中 ${possibleCount} 条只是意思可能相关` : ""}。
          </span>
          {page.coverage?.pending > 0 ? (
            <span className="sf-pending">
              {page.coverage.pending} 篇正文正在准备，结果会陆续补齐。
              {onRefresh ? (
                <button className="text-btn small" type="button" onClick={onRefresh}>
                  刷新
                </button>
              ) : null}
            </span>
          ) : null}
          {page.coverage?.unavailable > 0 ? (
            <span className="sf-unavailable">
              {page.coverage.unavailable} 篇暂无可搜索正文，仍可按标题、标签和网址查找。
            </span>
          ) : null}
        </p>
      ) : null}
    </div>
  );
}

/* ---------- results ---------- */

export interface SearchResultsProps {
  query: string;
  items: SearchTask[];
  selectedId: string | null;
  onOpen(task: SearchTask, event: MouseEvent<HTMLButtonElement>): void;
  showPossible: boolean;
  onShowPossible(show: boolean): void;
  isLoading: boolean;
  error: Error | null;
  hasMore: boolean;
  onLoadMore(): void;
  now?: Date;
}

export function SearchResults({
  query,
  items,
  selectedId,
  onOpen,
  showPossible,
  onShowPossible,
  isLoading,
  error,
  hasMore,
  onLoadMore,
  now,
}: SearchResultsProps): JSX.Element {
  const rowsRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    if (!selectedId) return;
    rowsRef.current?.querySelector(`[data-task-id="${CSS.escape(selectedId)}"]`)?.scrollIntoView({ block: "nearest" });
  }, [selectedId]);

  const q = query.trim().replace(/^"(.+)"$/, "$1");
  const { collapsible } = splitSearchResults(items);
  const visible = visibleSearchResults(items, showPossible);

  let body: JSX.Element;
  if (error) {
    body = (
      <div className="list-empty">
        <p>搜索未完成</p>
        <small>{error.message}</small>
      </div>
    );
  } else if (isLoading && !items.length) {
    body = <p className="list-loading">正在查找…</p>;
  } else if (!items.length) {
    body = (
      <div className="list-empty">
        <Search size={26} aria-hidden="true" />
        <p>没有找到「{q}」</p>
        <small>试试更短的关键词、标题里的词，或者去掉筛选条件。</small>
      </div>
    );
  } else {
    body = (
      <>
        {visible.map((item) => (
          <Row
            key={item.task_id}
            task={searchTaskToArchiveTask(item)}
            match={item.search_match}
            now={now}
            selected={item.task_id === selectedId}
            onOpen={(event) => onOpen(item, event)}
          />
        ))}
        {collapsible ? (
          <button className="possible-toggle" type="button" onClick={() => onShowPossible(!showPossible)}>
            {showPossible ? "收起意思可能相关的结果" : `展开其余 ${collapsible} 条意思可能相关的结果`}
          </button>
        ) : null}
        {hasMore ? (
          <div className="list-foot">
            <button className="text-btn small" type="button" onClick={onLoadMore}>
              加载更多结果
            </button>
          </div>
        ) : null}
      </>
    );
  }

  return (
    <div className="rows" ref={rowsRef} role="listbox" aria-label="搜索结果">
      {body}
    </div>
  );
}
