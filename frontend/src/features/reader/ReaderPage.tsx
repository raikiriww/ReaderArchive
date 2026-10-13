import { useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import { ApiError, listArchiveTags, readArchiveTask } from "../../api/client";
import type { ArchiveTaskRead } from "../../client/types.gen";
import { isTypingTarget, readerTabUrl } from "../../app/keyboard";
import { ToastProvider } from "../../app/toast";
import { useArchiveActions, useArchiveBroadcastSync } from "../../app/useArchiveActions";
import type { ArchiveTask } from "../../types/domain";
import { taskTitle } from "../../utils/format";
import { ConfirmProvider } from "../dialogs/ConfirmDialog";
import { Reader } from "./Reader";
import type { ReaderActions, ReaderMode } from "./types";

const ACTIVE_STATUSES = new Set(["queued", "running", "manual_action_required"]);

function toArchiveTask(task: ArchiveTaskRead): ArchiveTask {
  return {
    ...task,
    is_read: task.is_read ?? false,
    started_at: task.started_at ?? null,
    finished_at: task.finished_at ?? null,
    current_step: task.current_step ?? null,
    source_type: task.source_type === "rss" ? "rss" : "manual",
    tags: task.tags ?? [],
    search_match: task.search_match ?? null,
  } as ArchiveTask;
}

interface ReaderPageProps {
  taskId: string;
  query?: string;
}

/** Standalone reader tab at `/?read=<id>&q=`. */
export function ReaderPage(props: ReaderPageProps): JSX.Element {
  return (
    <ToastProvider>
      <ConfirmProvider>
        <ReaderPageContent {...props} />
      </ConfirmProvider>
    </ToastProvider>
  );
}

function ReaderPageContent({ taskId: initialId, query = "" }: ReaderPageProps): JSX.Element {
  useArchiveBroadcastSync();
  const baseActions = useArchiveActions();
  const [taskId, setTaskId] = useState(initialId);
  const [mode, setMode] = useState<ReaderMode>(query.trim() ? "text" : "archive");
  const [detailsOpen, setDetailsOpen] = useState(false);
  const [titleEditSignal, setTitleEditSignal] = useState(0);
  const [deleted, setDeleted] = useState(false);
  const tagInputRef = useRef<HTMLInputElement | null>(null);

  const taskQuery = useQuery({
    queryKey: ["archive-task", taskId],
    queryFn: async () => toArchiveTask(await readArchiveTask(taskId)),
    enabled: !deleted,
    refetchInterval: (state) => (state.state.data && ACTIVE_STATUSES.has(state.state.data.status) ? 3000 : false),
  });
  const tagsQuery = useQuery({ queryKey: ["archive-tags"], queryFn: listArchiveTags, staleTime: 60_000 });
  const task = deleted ? null : (taskQuery.data ?? null);

  const actions = useMemo<ReaderActions>(
    () => ({
      ...baseActions,
      async remove(target) {
        const removed = await baseActions.remove(target);
        if (removed && target.task_id === taskId) {
          setDeleted(true);
          window.setTimeout(() => window.close(), 400);
        }
        return removed;
      },
    }),
    [baseActions, taskId],
  );

  useEffect(() => {
    const title = task ? taskTitle(task) : "";
    document.title = title ? `${title.slice(0, 40)} · Reader Archive` : "Reader Archive";
  }, [task]);

  useEffect(() => {
    function onKey(event: KeyboardEvent): void {
      if (!task || event.defaultPrevented || event.metaKey || event.ctrlKey || event.altKey) return;
      if (isTypingTarget(document.activeElement) || isTypingTarget(event.target)) return;
      const done = task.status === "succeeded";
      const key = event.key === "Escape" ? "Escape" : event.key.toLowerCase();
      if (key === "e") {
        event.preventDefault();
        actions.toggleRead(task);
      } else if (key === "t" && done) {
        event.preventDefault();
        tagInputRef.current?.focus();
      } else if (key === "r" && done) {
        event.preventDefault();
        setTitleEditSignal((value) => value + 1);
      } else if (key === "v" && done) {
        event.preventDefault();
        setMode((value) => (value === "archive" ? "text" : "archive"));
      } else if (key === "i") {
        event.preventDefault();
        setDetailsOpen((value) => !value);
      } else if (key === "o") {
        event.preventDefault();
        window.open(task.url, "_blank", "noopener,noreferrer");
      } else if (key === "Escape" && detailsOpen) {
        event.preventDefault();
        setDetailsOpen(false);
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [actions, detailsOpen, task]);

  function switchVersion(nextId: string): void {
    setDetailsOpen(false);
    setTaskId(nextId);
    window.history.pushState(window.history.state, "", readerTabUrl(nextId, query));
  }

  const missing = deleted || (taskQuery.error instanceof ApiError && taskQuery.error.status === 404);

  let content: JSX.Element;
  if (task) {
    content = (
      <Reader
        task={task}
        container="page"
        searchQuery={query}
        allTags={tagsQuery.data ?? []}
        mode={mode}
        onModeChange={setMode}
        detailsOpen={detailsOpen}
        onDetailsOpenChange={setDetailsOpen}
        titleEditSignal={titleEditSignal}
        tagInputRef={tagInputRef}
        onSwitchVersion={switchVersion}
        actions={actions}
      />
    );
  } else if (missing) {
    content = (
      <div className="rd-page-msg">
        <p>这条存档不存在，可能已经被删除。</p>
        <a className="rd-text-btn" href="/">
          回到 Reader
        </a>
      </div>
    );
  } else if (taskQuery.isError) {
    content = (
      <div className="rd-page-msg">
        <p>{taskQuery.error instanceof Error ? taskQuery.error.message : "读取存档失败"}</p>
        <button className="rd-text-btn" type="button" onClick={() => void taskQuery.refetch()}>
          重试
        </button>
      </div>
    );
  } else {
    content = (
      <div className="rd-page-msg">
        <p>正在加载…</p>
      </div>
    );
  }

  return (
    <div className="rd-page">
      <div className="rd-strip">
        <a href="/" className="rd-brand">
          <img src="/static/favicon.svg" alt="" />
          Reader Archive
        </a>
        <span>这是独立的阅读标签页。在这里改的标签、名称和已读状态，会同步到列表页。</span>
      </div>
      {content}
    </div>
  );
}
