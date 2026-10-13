import { type QueryClient, type QueryKey, useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo } from "react";
import {
  deleteArchiveTask,
  deleteArchiveTaskFile,
  openArchiveTaskInBrowser,
  rearchiveTask,
  resumeManualAction,
  setArchiveTaskRead,
  updateArchiveTask,
  updateArchiveTaskFile,
  uploadArchiveTaskFile,
} from "../api/client";
import { useConfirm } from "../features/dialogs/ConfirmDialog";
import type { ReaderActions } from "../features/reader/types";
import type { ArchiveTask } from "../types/domain";
import { useToast } from "./toast";

const ARCHIVE_CHANNEL = "reader-archive";

/** Query key roots that hold archive task data (see plan §3.3). */
export const archiveKeys = {
  list: ["archive-list"],
  counts: ["archive-counts"],
  task: ["archive-task"],
  versions: ["archive-versions"],
  files: ["archive-files"],
  searchText: ["archive-search-text"],
  search: ["archive-search"],
  tags: ["archive-tags"],
} as const satisfies Record<string, QueryKey>;

const taskDataKeys: QueryKey[] = [
  archiveKeys.list,
  archiveKeys.counts,
  archiveKeys.task,
  archiveKeys.versions,
  archiveKeys.search,
];

const allArchiveKeys: QueryKey[] = Object.values(archiveKeys);

interface BroadcastMessage {
  type: "invalidate";
  sender: string;
  keys: QueryKey[];
}

const tabId = Math.random().toString(36).slice(2);
let channel: BroadcastChannel | null | undefined;

function getChannel(): BroadcastChannel | null {
  if (channel !== undefined) return channel;
  channel = typeof BroadcastChannel === "undefined" ? null : new BroadcastChannel(ARCHIVE_CHANNEL);
  return channel;
}

function broadcast(keys: QueryKey[]): void {
  try {
    getChannel()?.postMessage({ type: "invalidate", sender: tabId, keys } satisfies BroadcastMessage);
  } catch {
    /* other tabs simply refresh on their next poll */
  }
}

export async function invalidateArchive(queryClient: QueryClient, keys: QueryKey[] = allArchiveKeys): Promise<void> {
  broadcast(keys);
  await Promise.all(keys.map((queryKey) => queryClient.invalidateQueries({ queryKey })));
}

/** Listens for invalidations posted by other tabs (list ⇄ standalone reader page). */
export function useArchiveBroadcastSync(): void {
  const queryClient = useQueryClient();
  useEffect(() => {
    if (typeof BroadcastChannel === "undefined") return;
    const listener = new BroadcastChannel(ARCHIVE_CHANNEL);
    listener.onmessage = (event: MessageEvent<BroadcastMessage>) => {
      const data = event.data;
      if (data?.type !== "invalidate" || data.sender === tabId) return;
      const keys = Array.isArray(data.keys) && data.keys.length ? data.keys : allArchiveKeys;
      for (const queryKey of keys) void queryClient.invalidateQueries({ queryKey });
    };
    return () => listener.close();
  }, [queryClient]);
}

/** Replaces a task wherever it sits in cached lists/pages so the UI updates before the refetch. */
export function patchCachedTask(queryClient: QueryClient, taskId: string, patch: Partial<ArchiveTask>): void {
  const visit = (value: unknown): unknown => {
    if (Array.isArray(value)) {
      let changed = false;
      const next = value.map((item) => {
        const patched = visit(item);
        if (patched !== item) changed = true;
        return patched;
      });
      return changed ? next : value;
    }
    if (value && typeof value === "object") {
      const record = value as Record<string, unknown>;
      if (record.task_id === taskId) return { ...record, ...patch };
      let changed = false;
      const next: Record<string, unknown> = {};
      for (const [key, item] of Object.entries(record)) {
        const patched = key === "items" || key === "pages" ? visit(item) : item;
        if (patched !== item) changed = true;
        next[key] = patched;
      }
      return changed ? next : value;
    }
    return value;
  };
  for (const queryKey of [archiveKeys.list, archiveKeys.task, archiveKeys.versions, archiveKeys.search]) {
    queryClient.setQueriesData({ queryKey }, (data: unknown) => visit(data));
  }
}

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof Error && error.message ? error.message : fallback;
}

/** All archive mutations used by the list shell and the reader (popup or standalone page). */
export function useArchiveActions(): ReaderActions {
  const queryClient = useQueryClient();
  const confirm = useConfirm();
  const toast = useToast();
  const mutation = useMutation({ mutationFn: (run: () => Promise<unknown>) => run() });
  const { mutateAsync } = mutation;

  return useMemo<ReaderActions>(() => {
    const run = <T>(fn: () => Promise<T>) => mutateAsync(fn) as Promise<T>;
    const refresh = (keys: QueryKey[] = taskDataKeys) => invalidateArchive(queryClient, keys);
    const fileKeys = (taskId: string): QueryKey[] => [
      [...archiveKeys.files, taskId],
      archiveKeys.list,
      archiveKeys.task,
      archiveKeys.searchText,
    ];

    async function setRead(task: ArchiveTask, isRead: boolean): Promise<void> {
      patchCachedTask(queryClient, task.task_id, { is_read: isRead });
      try {
        await run(() => setArchiveTaskRead(task.task_id, isRead));
      } catch (error) {
        patchCachedTask(queryClient, task.task_id, { is_read: !isRead });
        toast(errorMessage(error, "标记失败"));
        return;
      } finally {
        void refresh();
      }
      toast(isRead ? "已标为已读" : "已标为未读", () => void setRead(task, !isRead));
    }

    return {
      toggleRead(task) {
        void setRead(task, !task.is_read);
      },

      async rename(task, title) {
        try {
          const updated = await run(() => updateArchiveTask(task.task_id, { custom_title: title }));
          patchCachedTask(queryClient, task.task_id, updated as Partial<ArchiveTask>);
          toast("名称已保存");
        } catch (error) {
          toast(errorMessage(error, "保存名称失败"));
          throw error;
        } finally {
          void refresh();
        }
      },

      setTags(task, tags) {
        const previous = task.tags;
        patchCachedTask(queryClient, task.task_id, { tags });
        void run(() => updateArchiveTask(task.task_id, { tags }))
          .then(() => toast("标签已更新"))
          .catch((error) => {
            patchCachedTask(queryClient, task.task_id, { tags: previous });
            toast(errorMessage(error, "更新标签失败"));
          })
          .finally(() => void refresh([...taskDataKeys, archiveKeys.tags]));
      },

      rearchive(task, prepareManually) {
        void run(() => rearchiveTask(task.task_id, prepareManually))
          .then(() => toast(prepareManually ? "正在打开网页，等待你处理后保存" : "已开始重新归档"))
          .catch((error) => toast(errorMessage(error, "重新归档失败")))
          .finally(() => void refresh(allArchiveKeys));
      },

      async remove(task) {
        const waiting = task.status === "manual_action_required" || task.status === "queued";
        const confirmed = await confirm({
          title: waiting ? "取消等待并删除" : "删除存档",
          message: waiting ? "将关闭这个任务的处理页面，并删除任务和已有文件。" : "这条存档和相关文件都会被删除，无法恢复。",
          confirmLabel: waiting ? "取消等待并删除" : "删除",
          danger: true,
        });
        if (confirmed !== true) return false;
        try {
          await run(() => deleteArchiveTask(task.task_id));
        } catch (error) {
          toast(errorMessage(error, "删除失败"));
          return false;
        }
        queryClient.removeQueries({ queryKey: [...archiveKeys.task, task.task_id] });
        toast(waiting ? "已取消并删除" : "已删除存档");
        void refresh(allArchiveKeys);
        return true;
      },

      openManualAction(task, code) {
        // Open synchronously inside the user gesture so popup blockers allow it.
        const browserTab = window.open("about:blank", "_blank");
        void run(() => openArchiveTaskInBrowser(task.task_id, code || undefined))
          .then((result) => {
            if (browserTab && result.desktop_url) browserTab.location.href = result.desktop_url;
            toast("已在浏览器打开对应网页");
          })
          .catch((error) => {
            browserTab?.close();
            toast(errorMessage(error, "打开浏览器失败"));
          })
          .finally(() => void refresh());
      },

      async resumeManualAction(task, code) {
        try {
          await run(() => resumeManualAction(task.task_id, code));
          toast("已继续处理");
        } catch (error) {
          toast(errorMessage(error, "继续处理失败"));
        } finally {
          void refresh();
        }
      },

      uploadFile(task, file) {
        void run(() => uploadArchiveTaskFile(task.task_id, file))
          .then(() => toast("文件已上传"))
          .catch((error) => toast(errorMessage(error, "上传失败")))
          .finally(() => void refresh(fileKeys(task.task_id)));
      },

      async renameFile(task, fileName, displayName) {
        try {
          await run(() => updateArchiveTaskFile(task.task_id, fileName, displayName));
          toast("文件名称已保存");
        } catch (error) {
          toast(errorMessage(error, "文件改名失败"));
          throw error;
        } finally {
          void refresh(fileKeys(task.task_id));
        }
      },

      deleteFile(task, fileName, displayName) {
        void (async () => {
          const confirmed = await confirm({
            title: "删除文件",
            message: `确定删除“${displayName || fileName}”？`,
            confirmLabel: "删除",
            danger: true,
          });
          if (confirmed !== true) return;
          try {
            await run(() => deleteArchiveTaskFile(task.task_id, fileName));
            toast("文件已删除");
          } catch (error) {
            toast(errorMessage(error, "删除文件失败"));
          } finally {
            void refresh(fileKeys(task.task_id));
          }
        })();
      },

      toast,
    };
  }, [confirm, mutateAsync, queryClient, toast]);
}
