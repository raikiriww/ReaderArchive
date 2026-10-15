import { AlertTriangle, Clock, Hand, Loader2 } from "lucide-react";
import type { MouseEvent } from "react";
import type { ArchiveTask } from "../../types/domain";
import { archiveToolMarks, cleanSummary, sourceLabelFor, taskTitle } from "../../utils/format";
import { Highlighted } from "../search/Highlighted";
import type { SearchMatch } from "../search/api";

export const MATCH_LABELS: Record<SearchMatch["kind"], string> = {
  title: "标题命中",
  tag: "标签命中",
  url: "网址命中",
  body: "正文命中",
  semantic: "意思可能相关",
};

function dayDiff(date: Date, now: Date): number {
  const start = (value: Date) => new Date(value.getFullYear(), value.getMonth(), value.getDate()).getTime();
  return Math.round((start(now) - start(date)) / 86_400_000);
}

/** 今天 / 昨天 / 本周 / 本月 / 更早 */
export function dayGroupLabel(value: string, now: Date = new Date()): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "更早";
  const diff = dayDiff(date, now);
  if (diff <= 0) return "今天";
  if (diff === 1) return "昨天";
  if (diff < 7) return "本周";
  if (diff < 31) return "本月";
  return "更早";
}

export function shortDate(value: string, now: Date = new Date()): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  const diff = dayDiff(date, now);
  if (diff <= 0) return `${String(date.getHours()).padStart(2, "0")}:${String(date.getMinutes()).padStart(2, "0")}`;
  if (diff === 1) return "昨天";
  if (diff < 7) return `${diff} 天前`;
  if (date.getFullYear() === now.getFullYear()) return `${date.getMonth() + 1}月${date.getDate()}日`;
  return `${date.getFullYear()}/${date.getMonth() + 1}/${date.getDate()}`;
}

export function StatusPill({ task }: { task: ArchiveTask }): JSX.Element | null {
  if (task.status === "queued")
    return (
      <span className="pill running">
        <Clock size={12} aria-hidden="true" />
        排队中
      </span>
    );
  if (task.status === "running")
    return (
      <span className="pill running">
        <Loader2 size={12} className="spin" aria-hidden="true" />
        保存中
      </span>
    );
  if (task.status === "manual_action_required") {
    const lost = task.manual_actions.some((action) => action.browser_tab_state === "missing");
    return (
      <span className="pill waiting">
        <Hand size={12} aria-hidden="true" />
        {lost ? "处理页面已丢失" : "等你处理"}
      </span>
    );
  }
  if (task.status === "failed")
    return (
      <span className="pill failed">
        <AlertTriangle size={12} aria-hidden="true" />
        失败
      </span>
    );
  return null;
}

function ToolMarks({ task }: { task: ArchiveTask }): JSX.Element | null {
  const marks = archiveToolMarks(task);
  if (!marks.length) return null;
  return (
    <span className="row-tools" role="group" aria-label="存档方式">
      {marks.map((mark) => (
        <span
          key={mark.tool}
          className={`row-tool ${mark.state}`}
          role="img"
          aria-label={`${mark.name}：${mark.label}`}
          title={`${mark.name}：${mark.label}`}
        >
          <img src={`/static/vendor-icons/${mark.tool}.png`} alt="" />
        </span>
      ))}
    </span>
  );
}

export interface RowProps {
  task: ArchiveTask;
  selected: boolean;
  onOpen(event: MouseEvent<HTMLButtonElement>): void;
  match?: SearchMatch | null;
  now?: Date;
}

export function Row({ task, selected, onOpen, match, now }: RowProps): JSX.Element {
  const notDone = task.status !== "succeeded";
  const title = taskTitle(task);
  const versions = match?.version_count ?? 0;
  const summary = match || notDone ? "" : cleanSummary(task.summary);
  return (
    <button
      type="button"
      role="option"
      aria-selected={selected}
      data-task-id={task.task_id}
      className={`row ${selected ? "selected" : ""} ${task.is_read ? "read" : "unread"}`}
      onClick={onOpen}
      onAuxClick={(event) => {
        if (event.button === 1) onOpen(event);
      }}
      onMouseDown={(event) => {
        // Keep middle-click from starting autoscroll.
        if (event.button === 1) event.preventDefault();
      }}
    >
      <span className="row-dot" aria-hidden="true" />
      <span className="row-main">
        {match ? (
          <span className={`match-label ${match.strength === "possible" ? "possible" : "strong"}`}>
            {MATCH_LABELS[match.kind] ?? "命中"}
            {versions > 1 ? ` · ${versions} 个保存版本` : ""}
          </span>
        ) : null}
        <span className="row-top">
          <span className={`row-title ${notDone && title === task.url ? "mono" : ""}`}>
            {match?.kind === "title" ? <Highlighted match={match} fallback={title} /> : title}
          </span>
          <span className="row-date">{shortDate(task.created_at, now)}</span>
        </span>
        {match?.excerpt && match.kind !== "title" ? (
          <span className="row-excerpt">
            <Highlighted match={match} fallback={match.excerpt} />
          </span>
        ) : summary ? (
          <span className="row-excerpt row-summary">{summary}</span>
        ) : null}
        <span className="row-meta">
          {notDone ? <StatusPill task={task} /> : null}
          <ToolMarks task={task} />
          <span className="row-source">{sourceLabelFor(task)}</span>
          {task.tags.slice(0, 3).map((tag) => (
            <span className="row-tag" key={tag}>
              #{tag}
            </span>
          ))}
        </span>
      </span>
    </button>
  );
}
