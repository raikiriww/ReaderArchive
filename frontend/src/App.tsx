import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  changePassword as changePasswordRequest,
  continueArchiveVideo,
  createArchiveTask,
  createRssFeed,
  createUser as createUserRequest,
  deleteArchiveTask,
  deleteArchiveTaskFile,
  deleteRssFeed,
  deleteUser as deleteUserRequest,
  listArchiveTags,
  listArchiveTaskFiles,
  listArchiveTasks,
  listRssFeeds,
  listUsers,
  logout as logoutRequest,
  markArchiveTaskRead,
  openArchiveTaskInBrowser,
  readAppConfig,
  readCurrentUser,
  rearchiveTask as rearchiveTaskRequest,
  refreshRssFeed,
  resetUserPassword as resetUserPasswordRequest,
  updateAppConfig,
  updateArchiveTask,
  updateArchiveTaskFile,
  updateRssFeed,
  updateUser,
  uploadArchiveTaskFile,
} from "./api/client";
import { AppDialog, type AppDialogRequest } from "./components/AppDialog";
import { Toast } from "./components/Toast";
import { DetailPanel } from "./features/archive/DetailPanel";
import { TaskList } from "./features/archive/TaskList";
import { Topbar } from "./features/archive/Topbar";
import { LoginPage } from "./features/auth/LoginPage";
import { RssPanel } from "./features/rss/RssPanel";
import { SettingsDialog } from "./features/settings/SettingsDialog";
import type {
  AppConfig,
  AppConfigUpdate,
  ArchiveTask,
  TaskFilter,
} from "./types/domain";
import { taskFileKey } from "./utils/format";
import { validTagFilters } from "./utils/tags";

const defaultConfig: AppConfig = {
  desktop_url: "/browser/",
  archive_dir: "data/archive",
  poll_interval_ms: 4000,
  rss_refresh_interval_seconds: 1800,
  semantic_search: null,
};

const taskPageSize = 50;

export function LoginRoute(): JSX.Element {
  return (
    <div className="login-body">
      <LoginPage />
    </div>
  );
}

export function MainApp(): JSX.Element {
  const queryClient = useQueryClient();
  const [tagFilters, setTagFilters] = useState<string[]>([]);
  const [tagMenuOpen, setTagMenuOpen] = useState(false);
  const [taskFilter, setTaskFilter] = useState<TaskFilter>("unread");
  const [searchQuery, setSearchQuery] = useState("");
  const [taskOffset, setTaskOffset] = useState(0);
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [rssOpen, setRssOpen] = useState(false);
  const [dialogRequest, setDialogRequest] = useState<AppDialogRequest | null>(null);
  const [toast, setToast] = useState("");
  const [draftUrl, setDraftUrl] = useState("");
  const toastTimerRef = useRef<number | null>(null);
  const settingsButtonRef = useRef<HTMLButtonElement | null>(null);

  const currentUserQuery = useQuery({
    queryKey: ["current-user"],
    queryFn: readCurrentUser,
    retry: false,
  });

  const currentUser = currentUserQuery.data?.user ?? null;

  const configQuery = useQuery({
    queryKey: ["app-config"],
    queryFn: readAppConfig,
    enabled: Boolean(currentUser),
  });
  const config = configQuery.data ?? defaultConfig;
  const cleanedSearchQuery = searchQuery.trim();

  const tasksQuery = useQuery({
    queryKey: ["archive-tasks", taskFilter, tagFilters, cleanedSearchQuery, taskOffset],
    queryFn: () =>
      listArchiveTasks({
        includeRead: taskFilter !== "unread",
        limit: taskPageSize,
        offset: taskOffset,
        status: taskFilter === "running" || taskFilter === "failed" ? taskFilter : undefined,
        tags: tagFilters,
        q: cleanedSearchQuery || undefined,
      }),
    enabled: Boolean(currentUser),
    refetchInterval: config.poll_interval_ms,
  });
  const tasksPage = tasksQuery.data ?? {
    items: [],
    total: 0,
    limit: taskPageSize,
    offset: taskOffset,
    has_more: false,
  };
  const tasks = tasksPage.items as ArchiveTask[];

  const tagsQuery = useQuery({
    queryKey: ["archive-tags"],
    queryFn: listArchiveTags,
    enabled: Boolean(currentUser),
  });
  const tags = tagsQuery.data ?? [];

  const feedsQuery = useQuery({
    queryKey: ["rss-feeds"],
    queryFn: listRssFeeds,
    enabled: Boolean(currentUser),
  });
  const feeds = feedsQuery.data ?? [];

  const usersQuery = useQuery({
    queryKey: ["users"],
    queryFn: listUsers,
    enabled: currentUser?.role === "admin" && settingsOpen,
  });
  const users = usersQuery.data ?? [];

  const selectedTask = useMemo(
    () => tasks.find((task) => task.task_id === selectedTaskId) || null,
    [selectedTaskId, tasks],
  );

  const showToast = useCallback((message: string) => {
    setToast(message);
    if (toastTimerRef.current !== null) window.clearTimeout(toastTimerRef.current);
    toastTimerRef.current = window.setTimeout(() => setToast(""), 3200);
  }, []);

  const askConfirm = useCallback(
    (request: Omit<Extract<AppDialogRequest, { kind: "confirm" }>, "kind" | "resolve">) =>
      new Promise<boolean>((resolve) => {
        setDialogRequest({ kind: "confirm", ...request, resolve });
      }),
    [],
  );

  const askInput = useCallback(
    (request: Omit<Extract<AppDialogRequest, { kind: "input" }>, "kind" | "resolve">) =>
      new Promise<string | null>((resolve) => {
        setDialogRequest({ kind: "input", ...request, resolve });
      }),
    [],
  );

  useEffect(() => {
    return () => {
      if (toastTimerRef.current !== null) window.clearTimeout(toastTimerRef.current);
    };
  }, []);

  const invalidateArchiveData = useCallback(async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["archive-tasks"] }),
      queryClient.invalidateQueries({ queryKey: ["archive-tags"] }),
      queryClient.invalidateQueries({ queryKey: ["archive-files"] }),
    ]);
  }, [queryClient]);

  const invalidateRssData = useCallback(async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["rss-feeds"] }),
      queryClient.invalidateQueries({ queryKey: ["archive-tasks"] }),
      queryClient.invalidateQueries({ queryKey: ["archive-tags"] }),
    ]);
  }, [queryClient]);

  const loadUsers = useCallback(async () => {
    if (currentUser?.role !== "admin") return;
    await queryClient.invalidateQueries({ queryKey: ["users"] });
  }, [currentUser?.role, queryClient]);

  const selectedFileKey = selectedTask ? taskFileKey(selectedTask) : "";

  const filesQuery = useQuery({
    queryKey: ["archive-files", selectedTask?.task_id, selectedFileKey],
    queryFn: () => listArchiveTaskFiles(selectedTask?.task_id ?? ""),
    enabled: Boolean(selectedTask),
  });
  const files = filesQuery.data ?? [];

  useEffect(() => {
    setTagFilters((current) => {
      const next = validTagFilters(current, tags);
      if (current.length === next.length && current.every((tag, index) => tag === next[index])) return current;
      setTaskOffset(0);
      return next;
    });
  }, [tags]);

  useEffect(() => {
    setTaskOffset((current) => {
      if (tasksPage.total === 0 || current < tasksPage.total) return current;
      return Math.max(0, Math.floor((tasksPage.total - 1) / taskPageSize) * taskPageSize);
    });
  }, [tasksPage.total]);

  useEffect(() => {
    setSelectedTaskId((current) => {
      if (!current || tasks.some((task) => task.task_id === current)) return current;
      return null;
    });
  }, [tasks]);

  const refreshFiles = useCallback(
    async (force = false) => {
      if (!selectedTask) return;
      if (force) {
        await queryClient.invalidateQueries({ queryKey: ["archive-files", selectedTask.task_id] });
      } else {
        await filesQuery.refetch();
      }
    },
    [filesQuery, queryClient, selectedTask],
  );

  const closeSettings = useCallback(() => {
    setSettingsOpen(false);
    window.requestAnimationFrame(() => settingsButtonRef.current?.focus());
  }, []);

  async function submitArchive(url: string): Promise<void> {
    try {
      const result = await createArchiveTask(url);
      setSelectedTaskId(result.task_id);
      showToast("已开始保存网页");
      await invalidateArchiveData();
    } catch (error) {
      showToast(error instanceof Error ? error.message : "保存失败");
    }
  }

  async function createFeed(url: string): Promise<void> {
    try {
      const result = await createRssFeed(url);
      showToast(`已添加订阅源，创建 ${result.created_task_count} 个存档任务`);
      await invalidateRssData();
    } catch (error) {
      showToast(error instanceof Error ? error.message : "添加订阅失败");
    }
  }

  async function refreshFeed(feedId: string): Promise<void> {
    try {
      const result = await refreshRssFeed(feedId);
      showToast(`检查完成，创建 ${result.created_task_count} 个存档任务`);
      await invalidateRssData();
    } catch (error) {
      showToast(error instanceof Error ? error.message : "检查失败");
    }
  }

  async function toggleFeed(feedId: string, enabled: boolean): Promise<void> {
    try {
      await updateRssFeed(feedId, { enabled });
      await queryClient.invalidateQueries({ queryKey: ["rss-feeds"] });
    } catch (error) {
      showToast(error instanceof Error ? error.message : "更新订阅失败");
    }
  }

  async function deleteFeed(feedId: string): Promise<void> {
    const confirmed = await askConfirm({
      title: "删除 RSS 来源",
      message: "删除后，这个 RSS 来源不会再自动检查。",
      confirmLabel: "删除",
      tone: "danger",
    });
    if (!confirmed) return;
    try {
      await deleteRssFeed(feedId);
      showToast("已删除订阅源");
      await queryClient.invalidateQueries({ queryKey: ["rss-feeds"] });
    } catch (error) {
      showToast(error instanceof Error ? error.message : "删除订阅失败");
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

  async function deleteTask(taskId: string): Promise<void> {
    const confirmed = await askConfirm({
      title: "删除存档记录",
      message: "这条记录和相关文件都会被删除。",
      confirmLabel: "删除",
      tone: "danger",
    });
    if (!confirmed) return;
    try {
      await deleteArchiveTask(taskId);
      if (selectedTaskId === taskId) {
        setSelectedTaskId(null);
      }
      showToast("已删除存档记录");
      await invalidateArchiveData();
    } catch (error) {
      showToast(error instanceof Error ? error.message : "删除失败");
    }
  }

  async function continueVideo(taskId: string): Promise<void> {
    try {
      await continueArchiveVideo(taskId);
      showToast("已继续下载视频");
      await invalidateArchiveData();
    } catch (error) {
      showToast(error instanceof Error ? error.message : "继续下载失败");
    }
  }

  async function openTaskInBrowser(taskId: string): Promise<void> {
    const browserTab = window.open("about:blank", "_blank");
    try {
      const result = await openArchiveTaskInBrowser(taskId);
      if (browserTab && result.desktop_url) browserTab.location.href = result.desktop_url;
      showToast("已在浏览器打开对应网页");
    } catch (error) {
      if (browserTab) browserTab.close();
      showToast(error instanceof Error ? error.message : "打开浏览器失败");
    }
  }

  async function markRead(taskId: string): Promise<void> {
    try {
      await markArchiveTaskRead(taskId);
      showToast("已标记为已读");
      await invalidateArchiveData();
    } catch (error) {
      showToast(error instanceof Error ? error.message : "标记失败");
    }
  }

  async function rearchiveTask(taskId: string): Promise<void> {
    const confirmed = await askConfirm({
      title: "重新归档",
      message: "这会替换当前条目的归档文件，名称、标签和已读状态会保留。",
      confirmLabel: "重新归档",
    });
    if (!confirmed) return;
    try {
      const updated = await rearchiveTaskRequest(taskId);
      setSelectedTaskId(updated.task_id);
      showToast("已开始重新归档");
      await invalidateArchiveData();
    } catch (error) {
      showToast(error instanceof Error ? error.message : "重新归档失败");
    }
  }

  async function uploadFile(file: File): Promise<void> {
    if (!selectedTask) return;
    try {
      await uploadArchiveTaskFile(selectedTask.task_id, file);
      showToast("文件已上传");
      await refreshFiles(true);
    } catch (error) {
      showToast(error instanceof Error ? error.message : "上传失败");
    }
  }

  async function renameTask(task: ArchiveTask, customTitle: string | null): Promise<void> {
    try {
      const updated = await updateArchiveTask(task.task_id, { custom_title: customTitle });
      setSelectedTaskId(updated.task_id);
      showToast("名称已保存");
      await invalidateArchiveData();
    } catch (error) {
      showToast(error instanceof Error ? error.message : "保存名称失败");
      throw error;
    }
  }

  async function updateTags(task: ArchiveTask, nextTags: string[]): Promise<void> {
    try {
      const updated = await updateArchiveTask(task.task_id, { tags: nextTags });
      setSelectedTaskId(updated.task_id);
      showToast("标签已更新");
      await invalidateArchiveData();
    } catch (error) {
      showToast(error instanceof Error ? error.message : "更新标签失败");
    }
  }

  async function renameFile(fileName: string, displayName: string): Promise<void> {
    if (!selectedTask) return;
    try {
      await updateArchiveTaskFile(selectedTask.task_id, fileName, displayName);
      showToast("文件名称已保存");
      await refreshFiles(true);
    } catch (error) {
      showToast(error instanceof Error ? error.message : "文件改名失败");
      throw error;
    }
  }

  async function deleteFile(fileName: string, displayName: string): Promise<void> {
    if (!selectedTask) return;
    const confirmed = await askConfirm({
      title: "删除文件",
      message: `确定删除“${displayName || fileName}”？`,
      confirmLabel: "删除",
      tone: "danger",
    });
    if (!confirmed) return;
    try {
      await deleteArchiveTaskFile(selectedTask.task_id, fileName);
      showToast("文件已删除");
      await queryClient.invalidateQueries({ queryKey: ["archive-tasks"] });
      await refreshFiles(true);
    } catch (error) {
      showToast(error instanceof Error ? error.message : "删除文件失败");
    }
  }

  async function createUser(payload: { username: string; password: string; role: string }): Promise<void> {
    try {
      await createUserRequest(payload);
      showToast("用户已添加");
      await loadUsers();
    } catch (error) {
      showToast(error instanceof Error ? error.message : "添加用户失败");
      throw error;
    }
  }

  async function updateConfig(payload: AppConfigUpdate): Promise<void> {
    try {
      await updateAppConfig(payload);
      showToast("设置已保存");
      await queryClient.invalidateQueries({ queryKey: ["app-config"] });
    } catch (error) {
      showToast(error instanceof Error ? error.message : "保存设置失败");
      throw error;
    }
  }

  async function toggleUser(userId: string, enabled: boolean): Promise<void> {
    try {
      await updateUser(userId, { enabled });
      await loadUsers();
    } catch (error) {
      showToast(error instanceof Error ? error.message : "更新用户失败");
    }
  }

  async function resetUserPassword(userId: string): Promise<void> {
    const password = await askInput({
      title: "重置密码",
      message: "输入新的临时密码。",
      label: "新密码",
      inputType: "password",
      minLength: 8,
      confirmLabel: "保存",
    });
    if (!password) return;
    try {
      await resetUserPasswordRequest(userId, { password });
      showToast("密码已重置");
    } catch (error) {
      showToast(error instanceof Error ? error.message : "重置密码失败");
    }
  }

  async function deleteUser(userId: string, username: string): Promise<void> {
    const confirmed = await askConfirm({
      title: "删除用户",
      message: `确定删除用户 ${username}？`,
      confirmLabel: "删除",
      tone: "danger",
    });
    if (!confirmed) return;
    try {
      await deleteUserRequest(userId);
      showToast("用户已删除");
      await loadUsers();
    } catch (error) {
      showToast(error instanceof Error ? error.message : "删除用户失败");
    }
  }

  async function changePassword(payload: { current_password: string; new_password: string }): Promise<void> {
    try {
      await changePasswordRequest(payload);
      showToast("密码已修改");
    } catch (error) {
      showToast(error instanceof Error ? error.message : "修改密码失败");
      throw error;
    }
  }

  function toggleTagFilter(tag: string): void {
    setTagFilters((current) => {
      const key = tag.toLowerCase();
      if (current.some((item) => item.toLowerCase() === key)) {
        return current.filter((item) => item.toLowerCase() !== key);
      }
      return [...current, tag];
    });
  }

  return (
    <div className="app-shell">
      <main className="main-area">
        <Topbar
          settingsButtonRef={settingsButtonRef}
          config={config}
          currentUser={currentUser}
          draftUrl={draftUrl}
          onDraftConsumed={() => setDraftUrl("")}
          onSubmitUrl={submitArchive}
            onOpenSettings={() => {
              setSettingsOpen(true);
              void loadUsers();
          }}
          onLogout={() => void logout()}
        />
        <div className="workspace">
          <TaskList
            tasks={tasks}
            total={tasksPage.total}
            selectedTaskId={selectedTaskId}
            taskFilter={taskFilter}
            searchQuery={searchQuery}
            tags={tags}
            tagFilters={tagFilters}
            tagMenuOpen={tagMenuOpen}
            limit={tasksPage.limit}
            offset={tasksPage.offset ?? taskOffset}
            hasMore={tasksPage.has_more}
            onPreviousPage={() => {
              setTaskOffset((current) => Math.max(0, current - taskPageSize));
            }}
            onNextPage={() => {
              if (tasksPage.has_more) setTaskOffset((current) => current + taskPageSize);
            }}
            onJumpToPage={(page) => {
              const totalPages = Math.max(1, Math.ceil(tasksPage.total / taskPageSize));
              const nextPage = Math.min(totalPages, Math.max(1, page));
              setTaskOffset((nextPage - 1) * taskPageSize);
            }}
            onSelectTask={(taskId) => {
              setSelectedTaskId(taskId);
            }}
            onSetFilter={(filter) => {
              setTaskFilter(filter);
              setTaskOffset(0);
            }}
            onSearchQueryChange={(query) => {
              setSearchQuery(query);
              setTaskOffset(0);
            }}
            onToggleTagMenu={() => setTagMenuOpen((value) => !value)}
            onToggleTag={(tag) => {
              toggleTagFilter(tag);
              setTaskOffset(0);
            }}
            onClearTags={() => {
              setTagFilters([]);
              setTaskOffset(0);
            }}
            onOpenRss={() => setRssOpen(true)}
          />
          <DetailPanel
            task={selectedTask}
            files={files}
            tags={tags}
            onClearSelection={() => {
              setSelectedTaskId(null);
            }}
            onRefreshFiles={() => void refreshFiles(true)}
            onUploadFile={(file) => void uploadFile(file)}
            onDeleteTask={(taskId) => void deleteTask(taskId)}
            onContinueVideo={(taskId) => void continueVideo(taskId)}
            onOpenBrowser={(taskId) => void openTaskInBrowser(taskId)}
            onMarkRead={(taskId) => void markRead(taskId)}
            onRearchiveTask={(taskId) => void rearchiveTask(taskId)}
            onRenameTask={renameTask}
            onUpdateTags={(task, nextTags) => void updateTags(task, nextTags)}
            onRenameFile={renameFile}
            onDeleteFile={(fileName, displayName) => void deleteFile(fileName, displayName)}
          />
        </div>
      </main>

      {rssOpen ? (
        <div className="rss-drawer-layer">
          <button className="rss-drawer-backdrop" type="button" aria-label="关闭 RSS 来源" onClick={() => setRssOpen(false)} />
          <aside className="rss-drawer" role="dialog" aria-modal="true" aria-labelledby="rssTitle">
            <RssPanel
              feeds={feeds}
              onClose={() => setRssOpen(false)}
              onCreate={createFeed}
              onRefreshAll={() => void queryClient.invalidateQueries({ queryKey: ["rss-feeds"] })}
              onRefreshFeed={(feedId) => void refreshFeed(feedId)}
              onToggleFeed={(feedId, enabled) => void toggleFeed(feedId, enabled)}
              onDeleteFeed={(feedId) => void deleteFeed(feedId)}
            />
          </aside>
        </div>
      ) : null}

      <SettingsDialog
        open={settingsOpen}
        config={config}
        currentUser={currentUser}
        users={users}
        onClose={closeSettings}
        onLoadUsers={() => void loadUsers()}
        onUpdateConfig={updateConfig}
        onCreateUser={createUser}
        onToggleUser={(userId, enabled) => void toggleUser(userId, enabled)}
        onResetUserPassword={(userId) => void resetUserPassword(userId)}
        onDeleteUser={(userId, username) => void deleteUser(userId, username)}
        onChangePassword={changePassword}
      />
      <AppDialog request={dialogRequest} onClose={() => setDialogRequest(null)} />
      <Toast message={toast} />
    </div>
  );
}
