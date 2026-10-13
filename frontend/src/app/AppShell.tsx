import { useQuery, useQueryClient } from "@tanstack/react-query";
import { type MouseEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  changePassword as changePasswordRequest,
  createArchiveTask,
  createRssFeed,
  createUser as createUserRequest,
  deleteRssFeed,
  deleteUser as deleteUserRequest,
  listArchiveTags,
  listRssFeeds,
  listUsers,
  logout as logoutRequest,
  readArchiveTask,
  refreshRssFeed,
  resetUserPassword as resetUserPasswordRequest,
  updateAppConfig,
  updateArchiveTask,
  updateRssFeed,
  updateUser,
} from "../api/client";
import { useConfirm } from "../features/dialogs/ConfirmDialog";
import { FeedsDialog } from "../features/dialogs/FeedsDialog";
import { modKeyLabel, SaveDialog, type SaveDialogPayload } from "../features/dialogs/SaveDialog";
import { ShortcutHelp } from "../features/dialogs/ShortcutHelp";
import { buildGroups, ListPane, relatedTags } from "../features/list/ListPane";
import {
  loadRecentSearches,
  rememberSearch,
  SearchBox,
  SearchFiltersBar,
  SearchResults,
  saveRecentSearches,
  searchTaskToArchiveTask,
  splitSearchResults,
  useArchiveSearch,
  visibleSearchResults,
} from "../features/list/SearchPanel";
import { Reader } from "../features/reader/Reader";
import { ReaderPopup } from "../features/reader/ReaderPopup";
import type { ReaderActions, ReaderMode } from "../features/reader/types";
import type { SearchFilters } from "../features/search/api";
import { readSearchLocation, writeSearchLocation } from "../features/search/state";
import { SettingsDialog } from "../features/settings/SettingsDialog";
import { type SettingsSection, Sidebar } from "../features/shell/Sidebar";
import type { AppConfig, AppConfigUpdate, ArchiveTask, User } from "../types/domain";
import { validTagFilters } from "../utils/tags";
import { extractPastedUrl, isSearchChord, isTypingTarget, readerTabUrl, shortcutFor, wantsNewTab } from "./keyboard";
import { useToast } from "./toast";
import { archiveKeys, invalidateArchive, useArchiveActions, useArchiveBroadcastSync } from "./useArchiveActions";
import { useArchiveCounts, useArchiveList } from "./useArchiveLists";
import { needsAttention, taskInView, useViewState, type ViewState, viewLabel } from "./viewState";

const SEARCH_DEBOUNCE_MS = 250;

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof Error && error.message ? error.message : fallback;
}

/** Inserts a task into a created_at-desc list (used to keep the pinned item in place). */
function insertByDate(list: ArchiveTask[], task: ArchiveTask): ArchiveTask[] {
  const index = list.findIndex((item) => item.created_at < task.created_at);
  if (index < 0) return [...list, task];
  return [...list.slice(0, index), task, ...list.slice(index)];
}

function anyDialogOpen(): boolean {
  return typeof document !== "undefined" && Boolean(document.querySelector(".dlg-overlay"));
}

function isInteractive(target: EventTarget | null): boolean {
  if (!(target instanceof Element)) return false;
  return Boolean(target.closest("button, a[href], [role='menuitem']"));
}

export interface AppShellProps {
  currentUser: User | null;
  config: AppConfig;
}

export function AppShell({ currentUser, config }: AppShellProps): JSX.Element {
  const queryClient = useQueryClient();
  const confirm = useConfirm();
  const toast = useToast();
  const baseActions = useArchiveActions();
  useArchiveBroadcastSync();

  const [view, setViewRaw] = useViewState();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [pinnedId, setPinnedId] = useState<string | null>(null);
  const [readerOpen, setReaderOpen] = useState(false);
  const [mode, setMode] = useState<ReaderMode>("archive");
  const [detailsOpen, setDetailsOpen] = useState(false);
  const [titleEditSignal, setTitleEditSignal] = useState(0);
  const tagInputRef = useRef<HTMLInputElement | null>(null);

  const [save, setSave] = useState<{ url: string; key: number } | null>(null);
  const [feedsOpen, setFeedsOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [settingsSection, setSettingsSection] = useState<SettingsSection>("system");
  const [helpOpen, setHelpOpen] = useState(false);

  const initialSearch = useMemo(() => readSearchLocation(), []);
  const [query, setQuery] = useState(initialSearch.query);
  const [debouncedQuery, setDebouncedQuery] = useState(initialSearch.query);
  const [filters, setFilters] = useState<SearchFilters>(initialSearch.filters);
  const [showPossible, setShowPossible] = useState(false);
  const [recent, setRecent] = useState<string[]>(() => loadRecentSearches());
  const searchInputRef = useRef<HTMLInputElement | null>(null);
  const searching = Boolean(query.trim());

  const signedIn = Boolean(currentUser);
  const pollMs = config.poll_interval_ms;
  const counts = useArchiveCounts(signedIn, pollMs);
  const list = useArchiveList(view, signedIn, pollMs);
  const search = useArchiveSearch(debouncedQuery, filters);

  const tagsQuery = useQuery({ queryKey: archiveKeys.tags, queryFn: listArchiveTags, enabled: signedIn });
  const allTags = tagsQuery.data ?? [];
  const feedsQuery = useQuery({ queryKey: ["rss-feeds"], queryFn: listRssFeeds, enabled: signedIn && feedsOpen });
  const usersQuery = useQuery({
    queryKey: ["users"],
    queryFn: listUsers,
    enabled: currentUser?.role === "admin" && settingsOpen,
  });

  /* ---------- search state <-> URL ---------- */
  useEffect(() => {
    const timer = window.setTimeout(() => setDebouncedQuery(query), SEARCH_DEBOUNCE_MS);
    return () => window.clearTimeout(timer);
  }, [query]);

  useEffect(() => {
    const url = new URL(window.location.href);
    const q = debouncedQuery.trim();
    if (!q) {
      if (url.searchParams.has("reader_search")) {
        url.searchParams.delete("reader_search");
        window.history.replaceState({ ...window.history.state }, "", url);
      }
      return;
    }
    writeSearchLocation({ query: q, filters, offset: 0, selectedId: null, reading: false });
  }, [debouncedQuery, filters]);

  useEffect(() => {
    const restore = () => {
      const state = readSearchLocation();
      setQuery(state.query);
      setDebouncedQuery(state.query);
      setFilters(state.filters);
    };
    window.addEventListener("popstate", restore);
    return () => window.removeEventListener("popstate", restore);
  }, []);

  // Drop tag filters that no longer exist (e.g. after the last tagged item was deleted).
  useEffect(() => {
    if (view.kind !== "tag" || !tagsQuery.data) return;
    const valid = validTagFilters(view.tags, tagsQuery.data);
    if (valid.length !== view.tags.length) {
      setViewRaw(valid.length ? { ...view, tags: valid } : { ...view, kind: "unread", tags: [] });
    }
  }, [setViewRaw, tagsQuery.data, view]);

  /* ---------- selection + pinned item ---------- */
  const loaded = useMemo(() => {
    const map = new Map<string, ArchiveTask>();
    for (const task of list.attention) map.set(task.task_id, task);
    for (const task of list.items) map.set(task.task_id, task);
    for (const task of search.items) if (!map.has(task.task_id)) map.set(task.task_id, searchTaskToArchiveTask(task));
    return map;
  }, [list.attention, list.items, search.items]);

  const inLists = selectedId ? loaded.get(selectedId) : undefined;
  const selectedQuery = useQuery({
    queryKey: [...archiveKeys.task, selectedId],
    queryFn: async () => (await readArchiveTask(selectedId ?? "")) as unknown as ArchiveTask,
    enabled: signedIn && Boolean(selectedId) && !inLists,
    refetchInterval: (query) => (query.state.data && query.state.data.status !== "succeeded" ? pollMs : false),
  });

  const [snapshot, setSnapshot] = useState<ArchiveTask | null>(null);
  const fresh = inLists ?? (selectedQuery.data?.task_id === selectedId ? selectedQuery.data : undefined);
  useEffect(() => {
    if (fresh && fresh !== snapshot) setSnapshot(fresh);
  }, [fresh, snapshot]);
  const selectedTask: ArchiveTask | null =
    fresh ?? (snapshot && snapshot.task_id === selectedId ? snapshot : null);

  const { attention, items } = useMemo(() => {
    let attentionList = list.attention;
    let itemList = list.items;
    if (selectedTask && pinnedId === selectedTask.task_id && !searching) {
      const present =
        attentionList.some((task) => task.task_id === pinnedId) || itemList.some((task) => task.task_id === pinnedId);
      if (!present) {
        if (view.kind === "unread" && needsAttention(selectedTask)) attentionList = insertByDate(attentionList, selectedTask);
        else itemList = insertByDate(itemList, selectedTask);
      }
    }
    return { attention: attentionList, items: itemList };
  }, [list.attention, list.items, pinnedId, searching, selectedTask, view.kind]);

  const groups = useMemo(() => buildGroups(attention, items), [attention, items]);
  const visibleResults = useMemo(() => visibleSearchResults(search.items, showPossible), [search.items, showPossible]);
  const ordered = useMemo<ArchiveTask[]>(
    () => (searching ? visibleResults.map(searchTaskToArchiveTask) : groups.flatMap(([, tasks]) => tasks)),
    [groups, searching, visibleResults],
  );
  const selIndex = selectedId ? ordered.findIndex((task) => task.task_id === selectedId) : -1;
  const related = useMemo(() => (view.kind === "tag" ? relatedTags(items, view.tags) : []), [items, view]);

  const select = useCallback((taskId: string | null) => {
    setSelectedId(taskId);
    // Only the item being read stays pinned.
    setPinnedId(taskId);
  }, []);

  const changeView = useCallback(
    (next: ViewState) => {
      setViewRaw(next);
      setQuery("");
      setDebouncedQuery("");
      select(null);
      setReaderOpen(false);
      setDetailsOpen(false);
    },
    [select, setViewRaw],
  );

  const closeReader = useCallback(() => {
    if (!searching && selectedTask && !taskInView(selectedTask, view)) {
      const index = ordered.findIndex((task) => task.task_id === selectedTask.task_id);
      const after =
        ordered.slice(index + 1).find((task) => taskInView(task, view)) ??
        ordered
          .slice(0, Math.max(0, index))
          .reverse()
          .find((task) => taskInView(task, view));
      setSelectedId(after?.task_id ?? null);
    }
    setPinnedId(null);
    setReaderOpen(false);
    setDetailsOpen(false);
  }, [ordered, searching, selectedTask, view]);

  const move = useCallback(
    (delta: number) => {
      if (!ordered.length) return;
      const index =
        selIndex < 0 ? (delta > 0 ? 0 : ordered.length - 1) : Math.min(ordered.length - 1, Math.max(0, selIndex + delta));
      select(ordered[index].task_id);
    },
    [ordered, select, selIndex],
  );

  const openTab = useCallback(
    (taskId: string) => {
      select(taskId);
      window.open(readerTabUrl(taskId, searching ? query : undefined), "_blank");
    },
    [query, searching, select],
  );

  const openItem = useCallback(
    (task: ArchiveTask, event?: MouseEvent<HTMLButtonElement>) => {
      if (event && wantsNewTab(event)) {
        event.preventDefault();
        openTab(task.task_id);
        return;
      }
      select(task.task_id);
      setReaderOpen(true);
    },
    [openTab, select],
  );

  const focusSearch = useCallback(() => {
    if (readerOpen) closeReader();
    window.requestAnimationFrame(() => {
      searchInputRef.current?.focus();
      searchInputRef.current?.select();
    });
  }, [closeReader, readerOpen]);

  const openSave = useCallback((url: string) => setSave({ url, key: Date.now() }), []);

  const commitSearch = useCallback((value: string) => {
    const next = value.trim();
    if (!next) return;
    setDebouncedQuery(value);
    setRecent((current) => {
      const updated = rememberSearch(current, next);
      saveRecentSearches(updated);
      return updated;
    });
  }, []);

  /* ---------- actions (remove moves the cursor) ---------- */
  const actions = useMemo<ReaderActions>(
    () => ({
      ...baseActions,
      async remove(task) {
        const index = ordered.findIndex((item) => item.task_id === task.task_id);
        const fits = (item: ArchiveTask) => item.task_id !== task.task_id && (searching || taskInView(item, view));
        const nextId =
          index >= 0
            ? (ordered.slice(index + 1).find(fits)?.task_id ??
              ordered
                .slice(0, index)
                .reverse()
                .find(fits)?.task_id ??
              null)
            : null;
        const removed = await baseActions.remove(task);
        if (removed && task.task_id === selectedId) {
          select(nextId);
          setDetailsOpen(false);
          if (!nextId) setReaderOpen(false);
        }
        return removed;
      },
    }),
    [baseActions, ordered, searching, select, selectedId, view],
  );

  /* ---------- keyboard + paste ---------- */
  const keyState = useRef({
    readerOpen,
    detailsOpen,
    selectedTask,
    query,
    move,
    closeReader,
    focusSearch,
    openTab,
    openSave,
    actions,
  });
  keyState.current = {
    readerOpen,
    detailsOpen,
    selectedTask,
    query,
    move,
    closeReader,
    focusSearch,
    openTab,
    openSave,
    actions,
  };

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent): void {
      const state = keyState.current;
      const dialog = anyDialogOpen();
      const typing = isTypingTarget(event.target) || isTypingTarget(document.activeElement);
      if (event.defaultPrevented) return;
      if (isSearchChord(event)) {
        event.preventDefault();
        if (!dialog) state.focusSearch();
        return;
      }
      if (event.key === "Escape") {
        if (dialog || typing) return;
        if (state.detailsOpen) setDetailsOpen(false);
        else if (state.readerOpen) state.closeReader();
        else if (state.query) {
          setQuery("");
          setDebouncedQuery("");
        } else return;
        event.preventDefault();
        return;
      }
      if (typing || dialog) return;
      const action = shortcutFor(event);
      if (!action) return;
      const task = state.selectedTask;
      if (action === "open" || action === "openTab") {
        // Let Enter activate focused controls inside the reader or sidebar.
        const target = event.target instanceof Element ? event.target : null;
        if (isInteractive(target) && !target?.closest(".rows")) return;
        if (!task) return;
        event.preventDefault();
        if (action === "openTab") state.openTab(task.task_id);
        else setReaderOpen(true);
        return;
      }
      switch (action) {
        case "next":
        case "prev":
          event.preventDefault();
          state.move(action === "next" ? 1 : -1);
          break;
        case "toggleRead":
          if (task) state.actions.toggleRead(task);
          break;
        case "focusTags":
          if (state.readerOpen && task?.status === "succeeded") {
            event.preventDefault();
            tagInputRef.current?.focus();
          }
          break;
        case "rename":
          if (state.readerOpen && task) {
            event.preventDefault();
            setTitleEditSignal((value) => value + 1);
          }
          break;
        case "toggleMode":
          if (state.readerOpen) setMode((value) => (value === "archive" ? "text" : "archive"));
          break;
        case "toggleDetails":
          if (state.readerOpen) setDetailsOpen((value) => !value);
          break;
        case "openOriginal":
          if (task) window.open(task.url, "_blank", "noopener,noreferrer");
          break;
        case "save":
          event.preventDefault();
          state.openSave("");
          break;
        case "search":
          event.preventDefault();
          state.focusSearch();
          break;
        case "help":
          event.preventDefault();
          setHelpOpen(true);
          break;
      }
    }

    function onPaste(event: ClipboardEvent): void {
      if (isTypingTarget(event.target) || isTypingTarget(document.activeElement) || anyDialogOpen()) return;
      const url = extractPastedUrl(event.clipboardData?.getData("text"));
      if (!url) return;
      event.preventDefault();
      keyState.current.openSave(url);
    }

    window.addEventListener("keydown", onKeyDown);
    window.addEventListener("paste", onPaste);
    return () => {
      window.removeEventListener("keydown", onKeyDown);
      window.removeEventListener("paste", onPaste);
    };
  }, []);

  /* ---------- save / feeds / settings ---------- */
  const existingUrls = useCallback(
    (url: string) => {
      const matches = [...loaded.values()].filter((task) => task.url === url);
      const latestAt = matches.map((task) => task.created_at).sort().at(-1);
      return { count: matches.length, latestAt };
    },
    [loaded],
  );

  async function submitSave(payload: SaveDialogPayload): Promise<void> {
    try {
      const created = await createArchiveTask(payload.url, payload.prepareManually);
      if (payload.tags.length) {
        try {
          await updateArchiveTask(created.task_id, { tags: payload.tags });
        } catch (error) {
          toast(errorMessage(error, "标签没有保存"));
        }
      }
      setSave(null);
      if (view.kind !== "unread" || searching) changeView({ kind: "unread", tags: [], source: "all", status: "all" });
      select(created.task_id);
      toast(payload.prepareManually ? "已创建任务。打开处理页面，处理好后点「处理完成」" : "已开始保存，完成后在「未读」里阅读");
      void invalidateArchive(queryClient);
    } catch (error) {
      toast(errorMessage(error, "保存失败"));
      throw error;
    }
  }

  const refreshFeedsAndArchive = () =>
    Promise.all([queryClient.invalidateQueries({ queryKey: ["rss-feeds"] }), invalidateArchive(queryClient)]);

  async function createFeed(url: string): Promise<void> {
    try {
      const result = await createRssFeed(url);
      toast(`已添加订阅源，创建 ${result.created_task_count} 个存档任务`);
      await refreshFeedsAndArchive();
    } catch (error) {
      toast(errorMessage(error, "添加订阅失败"));
      throw error;
    }
  }

  async function refreshFeed(feedId: string): Promise<void> {
    try {
      const result = await refreshRssFeed(feedId);
      toast(`检查完成，创建 ${result.created_task_count} 个存档任务`);
      await refreshFeedsAndArchive();
    } catch (error) {
      toast(errorMessage(error, "检查失败"));
    }
  }

  async function toggleFeed(feedId: string, enabled: boolean): Promise<void> {
    try {
      await updateRssFeed(feedId, { enabled });
      await queryClient.invalidateQueries({ queryKey: ["rss-feeds"] });
    } catch (error) {
      toast(errorMessage(error, "更新订阅失败"));
    }
  }

  async function deleteFeed(feedId: string): Promise<void> {
    try {
      await deleteRssFeed(feedId);
      toast("已删除订阅源");
      await queryClient.invalidateQueries({ queryKey: ["rss-feeds"] });
    } catch (error) {
      toast(errorMessage(error, "删除订阅失败"));
    }
  }

  const loadUsers = useCallback(() => {
    if (currentUser?.role === "admin") void queryClient.invalidateQueries({ queryKey: ["users"] });
  }, [currentUser?.role, queryClient]);

  async function updateConfig(payload: AppConfigUpdate): Promise<void> {
    try {
      await updateAppConfig(payload);
      toast("设置已保存");
      await queryClient.invalidateQueries({ queryKey: ["app-config"] });
    } catch (error) {
      toast(errorMessage(error, "保存设置失败"));
      throw error;
    }
  }

  async function createUser(payload: { username: string; password: string; role: string }): Promise<void> {
    try {
      await createUserRequest(payload);
      toast("用户已添加");
      loadUsers();
    } catch (error) {
      toast(errorMessage(error, "添加用户失败"));
      throw error;
    }
  }

  async function toggleUser(userId: string, enabled: boolean): Promise<void> {
    try {
      await updateUser(userId, { enabled });
      loadUsers();
    } catch (error) {
      toast(errorMessage(error, "更新用户失败"));
    }
  }

  async function resetUserPassword(userId: string): Promise<void> {
    const password = await confirm({
      kind: "input",
      title: "重置密码",
      message: "输入新的临时密码。",
      label: "新密码",
      inputType: "password",
      minLength: 8,
      confirmLabel: "保存",
    });
    if (typeof password !== "string" || !password) return;
    try {
      await resetUserPasswordRequest(userId, { password });
      toast("密码已重置");
    } catch (error) {
      toast(errorMessage(error, "重置密码失败"));
    }
  }

  async function deleteUser(userId: string, username: string): Promise<void> {
    const confirmed = await confirm({
      title: "删除用户",
      message: `确定删除用户 ${username}？`,
      confirmLabel: "删除",
      danger: true,
    });
    if (confirmed !== true) return;
    try {
      await deleteUserRequest(userId);
      toast("用户已删除");
      loadUsers();
    } catch (error) {
      toast(errorMessage(error, "删除用户失败"));
    }
  }

  async function changePassword(payload: { current_password: string; new_password: string }): Promise<void> {
    try {
      await changePasswordRequest(payload);
      toast("密码已修改");
    } catch (error) {
      toast(errorMessage(error, "修改密码失败"));
      throw error;
    }
  }

  async function logout(): Promise<void> {
    try {
      await logoutRequest();
    } finally {
      queryClient.clear();
      window.location.href = "/login";
    }
  }

  function openSettings(section: SettingsSection): void {
    setSettingsSection(section);
    setSettingsOpen(true);
    loadUsers();
  }

  /* ---------- render ---------- */
  const { collapsible } = splitSearchResults(search.items);
  const possibleCount = search.items.filter((item) => item.search_match?.strength === "possible").length;
  const searchBox = (
    <SearchBox
      inputRef={searchInputRef}
      query={query}
      onQuery={(value) => {
        setQuery(value);
        setShowPossible(false);
      }}
      onCommit={commitSearch}
      recent={recent}
      onClearRecent={() => {
        setRecent([]);
        saveRecentSearches([]);
      }}
      onLeave={() => {
        if (!selectedId && ordered.length) select(ordered[0].task_id);
      }}
    />
  );
  const searchContent = searching ? (
    <>
      <SearchFiltersBar
        query={query}
        filters={filters}
        onFilters={(next) => {
          setFilters(next);
          setShowPossible(false);
        }}
        tags={allTags}
        page={search.page}
        resultCount={search.items.length}
        possibleCount={possibleCount}
        onRefresh={search.refetch}
      />
      <SearchResults
        query={query}
        items={search.items}
        selectedId={selectedId}
        onOpen={(task, event) => openItem(searchTaskToArchiveTask(task), event)}
        showPossible={showPossible || collapsible === 0}
        onShowPossible={setShowPossible}
        isLoading={search.isLoading || debouncedQuery !== query}
        error={search.error}
        hasMore={search.hasMore}
        onLoadMore={search.loadMore}
      />
    </>
  ) : null;

  const mod = modKeyLabel();

  return (
    <div className="app-shell">
      <Sidebar
        view={view}
        onView={changeView}
        counts={counts}
        tags={allTags}
        user={currentUser}
        modKey={mod}
        onSave={() => openSave("")}
        onSearch={focusSearch}
        onManageFeeds={() => setFeedsOpen(true)}
        onBrowser={() => window.open(config.desktop_url, "_blank", "noopener,noreferrer")}
        onSettings={openSettings}
        onLogout={() => void logout()}
      />
      <ListPane
        view={view}
        groups={groups}
        total={list.total}
        related={related}
        selectedId={selectedId}
        onOpen={openItem}
        onViewChange={changeView}
        hasMore={list.hasMore}
        onLoadMore={list.loadMore}
        isLoading={list.isLoading}
        isFetchingMore={list.isFetchingMore}
        error={list.error}
        searchBox={searchBox}
        searchContent={searchContent}
      />

      {readerOpen && selectedTask ? (
        <ReaderPopup onClose={closeReader}>
          <Reader
            task={selectedTask}
            container="popup"
            nav={{
              label: searching ? "搜索结果" : viewLabel(view),
              index: selIndex + 1,
              total: ordered.length,
              onPrev: () => move(-1),
              onNext: () => move(1),
            }}
            searchQuery={searching ? query.trim() : undefined}
            allTags={allTags}
            mode={mode}
            onModeChange={setMode}
            detailsOpen={detailsOpen}
            onDetailsOpenChange={setDetailsOpen}
            titleEditSignal={titleEditSignal}
            tagInputRef={tagInputRef}
            onClose={closeReader}
            onOpenInTab={() => openTab(selectedTask.task_id)}
            onSwitchVersion={(taskId) => select(taskId)}
            actions={actions}
          />
        </ReaderPopup>
      ) : null}

      {save ? (
        <SaveDialog
          key={save.key}
          initialUrl={save.url}
          existingUrls={existingUrls}
          tags={allTags}
          onSubmit={submitSave}
          onClose={() => setSave(null)}
        />
      ) : null}
      {feedsOpen ? (
        <FeedsDialog
          feeds={feedsQuery.data ?? []}
          onCreate={createFeed}
          onRefresh={refreshFeed}
          onToggle={toggleFeed}
          onDelete={deleteFeed}
          onClose={() => setFeedsOpen(false)}
        />
      ) : null}
      <SettingsDialog
        open={settingsOpen}
        initialSection={settingsSection}
        config={config}
        currentUser={currentUser}
        users={usersQuery.data ?? []}
        onClose={() => setSettingsOpen(false)}
        onLoadUsers={loadUsers}
        onUpdateConfig={updateConfig}
        onCreateUser={createUser}
        onToggleUser={(userId, enabled) => void toggleUser(userId, enabled)}
        onResetUserPassword={(userId) => void resetUserPassword(userId)}
        onDeleteUser={(userId, username) => void deleteUser(userId, username)}
        onChangePassword={changePassword}
      />
      {helpOpen ? <ShortcutHelp onClose={() => setHelpOpen(false)} /> : null}
    </div>
  );
}
