import { useEffect, useState, type FormEvent } from "react";
import { Check, ChevronDown, ChevronLeft, ChevronRight, Rss, Search, Tag, X } from "lucide-react";
import type { ArchiveTag, ArchiveTask, TaskFilter } from "../../types/domain";
import { formatDate, safeUrl, sourceLabel, taskTitle } from "../../utils/format";

const filterLabels: Record<TaskFilter, string> = {
  unread: "未读",
  all: "全部",
  running: "处理中",
  failed: "失败",
};

interface TaskListProps {
  tasks: ArchiveTask[];
  total: number;
  selectedTaskId: string | null;
  taskFilter: TaskFilter;
  searchQuery: string;
  tags: ArchiveTag[];
  tagFilters: string[];
  tagMenuOpen: boolean;
  limit: number;
  offset: number;
  hasMore: boolean;
  onPreviousPage: () => void;
  onNextPage: () => void;
  onJumpToPage: (page: number) => void;
  onSelectTask: (taskId: string) => void;
  onSetFilter: (filter: TaskFilter) => void;
  onSearchQueryChange: (query: string) => void;
  onToggleTagMenu: () => void;
  onToggleTag: (tag: string) => void;
  onClearTags: () => void;
  onOpenRss: () => void;
}

export function TaskList({
  tasks,
  total,
  selectedTaskId,
  taskFilter,
  searchQuery,
  tags,
  tagFilters,
  tagMenuOpen,
  limit,
  offset,
  hasMore,
  onPreviousPage,
  onNextPage,
  onJumpToPage,
  onSelectTask,
  onSetFilter,
  onSearchQueryChange,
  onToggleTagMenu,
  onToggleTag,
  onClearTags,
  onOpenRss,
}: TaskListProps): JSX.Element {
  const filtered = filterTasks(tasks, taskFilter);
  const selectedCount = tagFilters.length;
  const cleanedSearch = searchQuery.trim();
  const triggerLabel = selectedCount === 0 ? "全部标签" : selectedCount === 1 ? tagFilters[0] : `已选 ${selectedCount} 个`;
  const effectiveLimit = Math.max(1, limit);
  const showPagination = total > effectiveLimit && filtered.length > 0;
  const totalPages = Math.max(1, Math.ceil(total / effectiveLimit));
  const currentPage = Math.min(totalPages, Math.floor(offset / effectiveLimit) + 1);
  const rangeStart = total === 0 ? 0 : offset + 1;
  const rangeEnd = Math.min(offset + filtered.length, total);
  const hasPrevious = offset > 0;
  const [jumpPageInput, setJumpPageInput] = useState(String(currentPage));

  useEffect(() => {
    setJumpPageInput(String(currentPage));
  }, [currentPage]);

  function submitPageJump(event: FormEvent<HTMLFormElement>): void {
    event.preventDefault();
    const input = event.currentTarget.elements.namedItem("page") as HTMLInputElement | null;
    const value = input?.value ?? jumpPageInput;
    const page = Number.parseInt(value.trim(), 10);
    if (Number.isNaN(page)) {
      setJumpPageInput("");
      window.requestAnimationFrame(() => setJumpPageInput(String(currentPage)));
      return;
    }
    onJumpToPage(page);
  }

  return (
    <section className="task-pane" aria-labelledby="taskPaneTitle">
      <div className="pane-header">
        <div>
          <h1 id="taskPaneTitle">{filterLabels[taskFilter]}</h1>
          <p>{selectedCount ? `${total} 条记录，已选 ${selectedCount} 个标签` : `${total} 条记录`}</p>
        </div>
        <button className="text-button" type="button" onClick={onOpenRss}>
          <Rss size={15} />
          订阅源
        </button>
      </div>
      <div className="task-search">
        <label className="visually-hidden" htmlFor="taskSearchInput">
          搜索存档
        </label>
        <Search className="task-search-icon" size={16} aria-hidden="true" />
        <input
          id="taskSearchInput"
          type="search"
          placeholder="搜索存档"
          value={searchQuery}
          onChange={(event) => onSearchQueryChange(event.target.value)}
        />
        {cleanedSearch ? (
          <button className="task-search-clear" type="button" aria-label="清空搜索" onClick={() => onSearchQueryChange("")}>
            <X size={15} />
          </button>
        ) : null}
      </div>
      <div className="filter-tabs" role="group" aria-label="存档记录筛选">
        {(Object.keys(filterLabels) as TaskFilter[]).map((filter) => (
          <button
            className={`filter-button ${taskFilter === filter ? "active" : ""}`}
            type="button"
            key={filter}
            aria-pressed={taskFilter === filter}
            onClick={() => onSetFilter(filter)}
          >
            {filterLabels[filter]}
          </button>
        ))}
        {tags.length ? (
          <div className="tag-filter-bar">
            <div className="tag-filter-dropdown">
              <button
                className={`tag-filter-trigger ${selectedCount ? "active" : ""}`}
                type="button"
                aria-haspopup="true"
                aria-expanded={tagMenuOpen}
                onClick={onToggleTagMenu}
              >
                <Tag size={15} />
                <span>{triggerLabel}</span>
                <ChevronDown size={14} />
              </button>
              <div className="tag-filter-menu" hidden={!tagMenuOpen}>
                <div className="tag-filter-menu-actions">
                  <button className="tag-filter-clear" type="button" disabled={!selectedCount} onClick={onClearTags}>
                    清空
                  </button>
                </div>
                <div className="tag-filter-options">
                  {tags.map((tag) => {
                    const selected = tagFilters.some((item) => item.toLowerCase() === tag.name.toLowerCase());
                    return (
                      <button
                        className={`tag-filter-option ${selected ? "selected" : ""}`}
                        key={tag.name}
                        type="button"
                        role="menuitemcheckbox"
                        aria-checked={selected}
                        onClick={() => onToggleTag(tag.name)}
                      >
                        <span className="tag-filter-check">{selected ? <Check size={15} /> : null}</span>
                        <span className="tag-filter-name">{tag.name}</span>
                        <span className="tag-filter-count">{tag.task_count}</span>
                      </button>
                    );
                  })}
                </div>
              </div>
            </div>
          </div>
        ) : null}
      </div>
      <div className="task-list" aria-live="polite">
        {filtered.length === 0 ? (
          <div className="empty-state">{emptyTaskMessage(taskFilter, cleanedSearch)}</div>
        ) : (
          groupTasks(filtered).map(([label, group]) => (
            <section className="task-group" aria-label={label} key={label}>
              <h2>{label}</h2>
              {group.map((task) => (
                <TaskRow
                  key={task.task_id}
                  task={task}
                  selected={task.task_id === selectedTaskId}
                  onSelect={() => onSelectTask(task.task_id)}
                />
              ))}
            </section>
          ))
        )}
      </div>
      {showPagination ? (
        <nav className="task-pagination" aria-label="存档记录分页">
          <div className="task-pagination-summary">
            <span>
              {rangeStart}-{rangeEnd} / 共 {total} 条
            </span>
            <span>第 {currentPage} / {totalPages} 页</span>
          </div>
          <div className="task-pagination-actions">
            <button className="pagination-button" type="button" onClick={onPreviousPage} disabled={!hasPrevious}>
              <ChevronLeft size={15} />
              上一页
            </button>
            <form className="pagination-jump" aria-label="跳转到指定页" onSubmit={submitPageJump} noValidate>
              <label htmlFor="paginationJumpInput">跳至</label>
              <input
                id="paginationJumpInput"
                name="page"
                type="number"
                inputMode="numeric"
                min="1"
                max={totalPages}
                value={jumpPageInput}
                onChange={(event) => setJumpPageInput(event.target.value)}
              />
              <span>页</span>
              <button className="pagination-button" type="submit">
                跳转
              </button>
            </form>
            <button className="pagination-button" type="button" onClick={onNextPage} disabled={!hasMore}>
              下一页
              <ChevronRight size={15} />
            </button>
          </div>
        </nav>
      ) : null}
    </section>
  );
}

function TaskRow({ task, selected, onSelect }: { task: ArchiveTask; selected: boolean; onSelect: () => void }): JSX.Element {
  const notice = task.status === "failed"
    ? task.error || task.result?.page_error || task.result?.video_error
    : task.status === "manual_action_required"
      ? task.manual_actions[0]?.message
      : null;
  return (
    <button
      className={`task-item ${selected ? "selected" : ""} ${task.is_read ? "is-read" : "is-unread"}`}
      type="button"
      aria-pressed={selected}
      onClick={onSelect}
    >
      <span className="read-marker" aria-hidden="true" />
      <span className="task-item-main">
        <span className="task-item-title">{taskTitle(task)}</span>
        <span className="task-item-url">{task.url}</span>
        {task.search_match?.excerpt ? (
          <span className="task-search-match">{task.search_match.excerpt}</span>
        ) : null}
        <span className="archive-methods" role="group" aria-label="存档方式状态">
          <ArchiveMethod tool="singlefile" label={archiveMethodLabel(task, "page")} state={archiveMethodState(task, "page")} />
          <ArchiveMethod tool="yt-dlp" label={archiveMethodLabel(task, "video")} state={archiveMethodState(task, "video")} />
        </span>
        {task.tags.length ? (
          <span className="task-tags">
            {task.tags.slice(0, 3).map((tag) => (
              <span className="tag-chip" key={tag}>
                {tag}
              </span>
            ))}
          </span>
        ) : null}
        {notice ? <span className="error-line">{String(notice).split(/\r?\n/)[0]}</span> : null}
        <span className="task-item-meta">
          <span>{sourceLabel(task)}</span>
          <span>{safeUrl(task.url)?.hostname || "—"}</span>
          <span>{formatDate(task.created_at)}</span>
        </span>
      </span>
      {task.status === "failed" ? (
        <span className="task-status failed">失败</span>
      ) : task.status === "manual_action_required" ? (
        <span className="task-status running">需手动处理</span>
      ) : ["queued", "running"].includes(task.status) ? (
        <span className="task-status running">处理中</span>
      ) : null}
    </button>
  );
}

function ArchiveMethod({ tool, label, state }: { tool: "singlefile" | "yt-dlp"; label: string; state: string }): JSX.Element {
  const logo = tool === "singlefile" ? "/static/vendor-icons/singlefile.png" : "/static/vendor-icons/yt-dlp.png";
  const name = tool === "singlefile" ? "SingleFile" : "yt-dlp";
  return (
    <span className={`archive-method ${state} tool-${tool}`} role="img" aria-label={`${name}：${label}`} title={`${name}：${label}`}>
      <img className="archive-method-logo" src={logo} alt="" loading="lazy" />
    </span>
  );
}

export function filterTasks(tasks: ArchiveTask[], taskFilter: TaskFilter): ArchiveTask[] {
  if (taskFilter === "all") return tasks;
  if (taskFilter === "running") return tasks.filter((task) => ["queued", "running", "manual_action_required"].includes(task.status));
  if (taskFilter === "failed") return tasks.filter((task) => task.status === "failed");
  return tasks.filter((task) => !task.is_read);
}

function groupTasks(tasks: ArchiveTask[]): Array<[string, ArchiveTask[]]> {
  const groups = new Map<string, ArchiveTask[]>([
    ["今日", []],
    ["昨日", []],
    ["更早", []],
  ]);
  const now = new Date();
  const todayKey = dateKey(now);
  const yesterday = new Date(now);
  yesterday.setDate(now.getDate() - 1);
  const yesterdayKey = dateKey(yesterday);

  tasks.forEach((task) => {
    const key = dateKey(new Date(task.created_at));
    if (key === todayKey) groups.get("今日")?.push(task);
    else if (key === yesterdayKey) groups.get("昨日")?.push(task);
    else groups.get("更早")?.push(task);
  });

  return [...groups.entries()].filter(([, group]) => group.length);
}

function dateKey(date: Date): string {
  if (Number.isNaN(date.getTime())) return "";
  return `${date.getFullYear()}-${date.getMonth()}-${date.getDate()}`;
}

function archiveMethodState(task: ArchiveTask, method: "page" | "video"): string {
  const waitsForManualAction = task.manual_actions.some((action) => action.target === method);
  if (method === "page") {
    if (task.result?.file_name) return "succeeded";
    if (waitsForManualAction) return "running";
    if (task.result?.page_error || task.status === "failed") return "failed";
    if (["queued", "running"].includes(task.status)) return "running";
    return "failed";
  }
  if (task.result?.video_file_name) return "succeeded";
  if (task.result?.video_error) return "failed";
  if (waitsForManualAction || ["queued", "running"].includes(task.status)) return "running";
  return "failed";
}

function archiveMethodLabel(task: ArchiveTask, method: "page" | "video"): string {
  const waitsForManualAction = task.manual_actions.some((action) => action.target === method);
  if (method === "page") {
    if (task.result?.file_name) return "网页已保存";
    if (waitsForManualAction) return "网页等待手动处理";
    if (task.result?.page_error || task.status === "failed") return "网页保存失败";
    return "正在保存网页";
  }
  if (task.result?.video_file_name) return "视频已下载";
  if (task.result?.video_error) return "视频下载失败";
  if (waitsForManualAction) return "视频等待手动处理";
  if (["queued", "running"].includes(task.status)) return "正在尝试下载视频";
  return "视频下载失败";
}

function emptyTaskMessage(filter: TaskFilter, searchQuery: string): string {
  if (searchQuery) return "没有匹配的存档记录";
  if (filter === "unread") return "没有未读存档记录";
  if (filter === "running") return "没有正在处理的任务";
  if (filter === "failed") return "没有失败记录";
  return "还没有存档记录";
}
