import { type QueryKey, useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo } from "react";
import { listArchiveTasks } from "../api/client";
import type { ArchiveTask, ArchiveTaskListPage } from "../types/domain";
import type { ViewState } from "./viewState";

export const LIST_PAGE_SIZE = 50;
export const ATTENTION_LIMIT = 100;

type ListOptions = Parameters<typeof listArchiveTasks>[0];

export interface ArchiveCounts {
  /** Unread, successfully saved archives. */
  unread: number;
  /** queued / running / manual_action_required / failed, read or not. */
  attention: number;
  /** manual_action_required / failed. */
  problems: number;
}

export interface ArchiveListResult {
  /** Unread view only: tasks that need attention (shown first). */
  attention: ArchiveTask[];
  items: ArchiveTask[];
  total: number;
  hasMore: boolean;
  loadMore(): void;
  isLoading: boolean;
  isFetchingMore: boolean;
  error: Error | null;
}

function asPage(page: Awaited<ReturnType<typeof listArchiveTasks>>): ArchiveTaskListPage {
  return page as unknown as ArchiveTaskListPage;
}

/** Query options for the paged part of each view (§3.3). */
export function listOptionsForView(view: ViewState): Omit<ListOptions, "limit" | "offset"> {
  if (view.kind === "unread") return { includeRead: false, status: "succeeded", tags: [] };
  if (view.kind === "tag") return { includeRead: true, tags: view.tags, tagsMatch: "all" };
  return {
    includeRead: view.status !== "unread",
    status: view.status === "problem" ? "problem" : undefined,
    source: view.source === "all" ? undefined : view.source,
    tags: [],
  };
}

export function listKey(view: ViewState): QueryKey {
  if (view.kind === "unread") return ["archive-list", "unread", {}];
  if (view.kind === "tag") return ["archive-list", "tag", { tags: view.tags }];
  return ["archive-list", "all", { source: view.source, status: view.status }];
}

function pageSignature(items: ArchiveTask[] | undefined): string {
  return (items || [])
    .map((task) => [task.task_id, task.status, task.is_read, task.display_title, task.tags.join(",")].join(":"))
    .join("|");
}

export function useArchiveCounts(enabled: boolean, pollMs: number): ArchiveCounts {
  const query = useQuery({
    queryKey: ["archive-counts"],
    enabled,
    refetchInterval: pollMs,
    queryFn: async (): Promise<ArchiveCounts> => {
      const [unread, attention, problems] = await Promise.all([
        listArchiveTasks({ includeRead: false, status: "succeeded", limit: 1, tags: [] }),
        listArchiveTasks({ includeRead: true, status: "attention", limit: 1, tags: [] }),
        listArchiveTasks({ includeRead: true, status: "problem", limit: 1, tags: [] }),
      ]);
      return { unread: unread.total, attention: attention.total, problems: problems.total };
    },
  });
  return query.data ?? { unread: 0, attention: 0, problems: 0 };
}

/**
 * Loads the list for the current view with infinite paging.
 * Only the first page is polled: while one page is loaded the infinite query polls itself;
 * once more pages are loaded a small "head" query polls page one and refetches everything
 * only when it changed.
 */
export function useArchiveList(view: ViewState, enabled: boolean, pollMs: number): ArchiveListResult {
  const key = listKey(view);
  const options = listOptionsForView(view);

  const attentionQuery = useQuery({
    queryKey: ["archive-list", "unread-attention"],
    enabled: enabled && view.kind === "unread",
    refetchInterval: pollMs,
    queryFn: async () =>
      asPage(await listArchiveTasks({ includeRead: true, status: "attention", limit: ATTENTION_LIMIT, tags: [] })),
  });

  const pagesQuery = useInfiniteQuery({
    queryKey: key,
    enabled,
    initialPageParam: 0,
    queryFn: async ({ pageParam }) => asPage(await listArchiveTasks({ ...options, limit: LIST_PAGE_SIZE, offset: pageParam })),
    getNextPageParam: (last) => (last.has_more ? last.offset + last.items.length : undefined),
    refetchInterval: (query) => ((query.state.data?.pages.length ?? 0) <= 1 ? pollMs : false),
  });

  const pageCount = pagesQuery.data?.pages.length ?? 0;
  const headQuery = useQuery({
    queryKey: [...key, "head"],
    enabled: enabled && pageCount > 1,
    refetchInterval: pollMs,
    queryFn: async () => asPage(await listArchiveTasks({ ...options, limit: LIST_PAGE_SIZE, offset: 0 })),
  });

  const firstPage = pagesQuery.data?.pages[0];
  const { refetch } = pagesQuery;
  useEffect(() => {
    if (!headQuery.data || !firstPage) return;
    if (pageSignature(headQuery.data.items) !== pageSignature(firstPage.items)) void refetch();
  }, [headQuery.data, firstPage, refetch]);

  const attention = useMemo(
    () => (view.kind === "unread" ? (attentionQuery.data?.items ?? []) : []),
    [attentionQuery.data, view.kind],
  );

  const items = useMemo(() => {
    const seen = new Set(attention.map((task) => task.task_id));
    const result: ArchiveTask[] = [];
    for (const page of pagesQuery.data?.pages ?? []) {
      for (const task of page.items) {
        if (seen.has(task.task_id)) continue;
        seen.add(task.task_id);
        result.push(task);
      }
    }
    return result;
  }, [attention, pagesQuery.data]);

  const { fetchNextPage, hasNextPage, isFetchingNextPage } = pagesQuery;
  const loadMore = useCallback(() => {
    if (hasNextPage && !isFetchingNextPage) void fetchNextPage();
  }, [fetchNextPage, hasNextPage, isFetchingNextPage]);

  return {
    attention,
    items,
    total: (firstPage?.total ?? 0) + (view.kind === "unread" ? (attentionQuery.data?.total ?? 0) : 0),
    hasMore: Boolean(hasNextPage),
    loadMore,
    isLoading: pagesQuery.isLoading || (view.kind === "unread" && attentionQuery.isLoading),
    isFetchingMore: isFetchingNextPage,
    error: (pagesQuery.error as Error | null) ?? (attentionQuery.error as Error | null) ?? null,
  };
}
