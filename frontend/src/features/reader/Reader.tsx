import {
  AlignLeft,
  AppWindow,
  Check,
  ChevronDown,
  ChevronUp,
  Ellipsis,
  ExternalLink,
  File,
  Info,
  Link,
  Maximize2,
  Pencil,
  RefreshCw,
  Trash2,
  X,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { usePopover } from "../../components/Popover";
import type { ArchiveTask } from "../../types/domain";
import { formatDate, sourceLabelFor, taskTitle } from "../../utils/format";
import { DetailsDrawer } from "./DetailsDrawer";
import { archiveFileUrl, Snapshot } from "./Snapshot";
import { StatusPanel } from "./StatusPanel";
import { TagEditor } from "./TagEditor";
import { TextView } from "./TextView";
import type { ReaderProps } from "./types";
import { VersionsMenu } from "./VersionsMenu";

/** Source label for the meta row: feed name for RSS, 手动 for manual saves. */

function archiveFileHref(task: ArchiveTask): string | null {
  const name = task.result?.file_name || task.result?.video_file_name;
  return name ? archiveFileUrl(task.task_id, name) : null;
}

export function Reader(props: ReaderProps): JSX.Element {
  const {
    task,
    container,
    nav,
    searchQuery,
    allTags,
    mode,
    onModeChange,
    detailsOpen,
    onDetailsOpenChange,
    titleEditSignal,
    tagInputRef,
    onClose,
    onOpenInTab,
    onSwitchVersion,
    actions,
  } = props;
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const menu = usePopover<"more">();
  const lastSignal = useRef(titleEditSignal);
  const done = task.status === "succeeded";
  const title = taskTitle(task);
  const waiting = task.status === "manual_action_required";
  const fileHref = archiveFileHref(task);
  const { setOpen: setMenuOpen } = menu;

  // biome-ignore lint/correctness/useExhaustiveDependencies: reset local UI only when the task changes
  useEffect(() => {
    setEditing(false);
    setMenuOpen(null);
  }, [task.task_id, setMenuOpen]);

  useEffect(() => {
    if (titleEditSignal === lastSignal.current) return;
    lastSignal.current = titleEditSignal;
    if (!done) return;
    setDraft(title);
    setEditing(true);
  }, [titleEditSignal, done, title]);

  function startEdit(): void {
    setDraft(title);
    setEditing(true);
  }

  function commit(): void {
    setEditing(false);
    const value = draft.trim();
    if (value === title) return;
    actions.rename(task, value || null).catch(() => undefined);
  }

  function copyUrl(): void {
    const clipboard = typeof navigator === "undefined" ? undefined : navigator.clipboard;
    if (!clipboard) {
      actions.toast("无法访问剪贴板");
      return;
    }
    clipboard.writeText(task.url).then(
      () => actions.toast("已复制原网址"),
      () => actions.toast("复制失败"),
    );
  }

  function pick(run: () => void): () => void {
    return () => {
      menu.setOpen(null);
      run();
    };
  }

  return (
    <section className={`rd-reader rd-in-${container}`}>
      <header className="rd-head">
        <div className="rd-bar">
          {container === "popup" && onClose ? (
            <button className="rd-icon-btn" type="button" onClick={onClose} title="关闭 Esc" aria-label="关闭">
              <X size={17} aria-hidden="true" />
            </button>
          ) : null}
          {nav ? (
            <div className="rd-nav" title={nav.label}>
              <button
                className="rd-icon-btn"
                type="button"
                onClick={nav.onPrev}
                disabled={nav.index <= 1}
                title="上一条 K"
                aria-label="上一条"
              >
                <ChevronUp size={15} aria-hidden="true" />
              </button>
              <button
                className="rd-icon-btn"
                type="button"
                onClick={nav.onNext}
                disabled={nav.index < 1 || nav.index >= nav.total}
                title="下一条 J"
                aria-label="下一条"
              >
                <ChevronDown size={15} aria-hidden="true" />
              </button>
              {nav.index >= 1 ? (
                <span className="rd-nav-pos">
                  {nav.index} / {nav.total}
                </span>
              ) : null}
            </div>
          ) : null}
          {editing ? (
            <input
              className="rd-title-edit"
              // biome-ignore lint/a11y/noAutofocus: editing starts from an explicit click or the R shortcut
              autoFocus
              value={draft}
              maxLength={200}
              aria-label="存档名称"
              onChange={(event) => setDraft(event.target.value)}
              onBlur={commit}
              onKeyDown={(event) => {
                if (event.key === "Enter") {
                  event.preventDefault();
                  event.stopPropagation();
                  commit();
                } else if (event.key === "Escape") {
                  event.preventDefault();
                  event.stopPropagation();
                  setEditing(false);
                }
              }}
            />
          ) : done ? (
            <h1 className="rd-title">
              <button type="button" className="rd-title-btn" title={`${title}\n点击修改名称 R`} onClick={startEdit}>
                {title}
              </button>
            </h1>
          ) : (
            <h1 className="rd-title mono" title={title}>
              {title}
            </h1>
          )}
          <div className="rd-tools">
            {done ? (
              <button
                type="button"
                className={`rd-read-state ${task.is_read ? "is-read" : ""}`}
                onClick={() => actions.toggleRead(task)}
                title={task.is_read ? "标为未读 E" : "标为已读 E"}
              >
                <span className="rd-rs-dot" aria-hidden="true" />
                {task.is_read ? "已读" : "未读"}
              </button>
            ) : null}
            {done ? <VersionsMenu task={task} onSwitchVersion={onSwitchVersion} /> : null}
            {done ? (
              <div className="rd-seg" role="group" aria-label="阅读方式">
                <button
                  type="button"
                  className={mode === "archive" ? "on" : ""}
                  aria-pressed={mode === "archive"}
                  onClick={() => onModeChange("archive")}
                  title="存档原貌 V"
                >
                  <AppWindow size={14} aria-hidden="true" />
                  原貌
                </button>
                <button
                  type="button"
                  className={mode === "text" ? "on" : ""}
                  aria-pressed={mode === "text"}
                  onClick={() => onModeChange("text")}
                  title="提取的正文 V"
                >
                  <AlignLeft size={14} aria-hidden="true" />
                  正文
                </button>
              </div>
            ) : null}
            {done && container === "popup" && onOpenInTab ? (
              <button
                className="rd-icon-btn"
                type="button"
                title="在新标签页阅读"
                aria-label="在新标签页阅读"
                onClick={onOpenInTab}
              >
                <Maximize2 size={15} aria-hidden="true" />
              </button>
            ) : null}
            <button
              className={`rd-icon-btn ${detailsOpen ? "on" : ""}`}
              type="button"
              title="详情、文件、重新归档 I"
              aria-label="详情"
              aria-pressed={detailsOpen}
              onClick={() => onDetailsOpenChange(!detailsOpen)}
            >
              <Info size={16} aria-hidden="true" />
            </button>
            <div className="rd-anchor" ref={menu.anchorRef}>
              <button
                className={`rd-icon-btn ${menu.open ? "on" : ""}`}
                type="button"
                title="更多"
                aria-label="更多"
                aria-haspopup="menu"
                aria-expanded={menu.open === "more"}
                onClick={() => menu.toggle("more")}
              >
                <Ellipsis size={16} aria-hidden="true" />
              </button>
              {menu.open === "more" ? (
                <div className="rd-menu" role="menu">
                  {done ? (
                    <button type="button" role="menuitem" onClick={pick(startEdit)}>
                      <Pencil size={14} aria-hidden="true" />
                      修改名称<kbd className="rd-kbd">R</kbd>
                    </button>
                  ) : null}
                  {done ? (
                    <button type="button" role="menuitem" onClick={pick(() => actions.toggleRead(task))}>
                      <Check size={14} aria-hidden="true" />
                      {task.is_read ? "标为未读" : "标为已读"}
                      <kbd className="rd-kbd">E</kbd>
                    </button>
                  ) : null}
                  {fileHref ? (
                    <button
                      type="button"
                      role="menuitem"
                      onClick={pick(() => window.open(fileHref, "_blank", "noopener,noreferrer"))}
                    >
                      <File size={14} aria-hidden="true" />
                      打开存档文件
                    </button>
                  ) : null}
                  <button type="button" role="menuitem" onClick={pick(copyUrl)}>
                    <Link size={14} aria-hidden="true" />
                    复制原网址
                  </button>
                  {!waiting ? (
                    <button type="button" role="menuitem" onClick={pick(() => onDetailsOpenChange(true))}>
                      <RefreshCw size={14} aria-hidden="true" />
                      重新归档…
                    </button>
                  ) : null}
                  <hr />
                  <button
                    type="button"
                    role="menuitem"
                    className="danger"
                    disabled={task.status === "running"}
                    onClick={pick(() => void actions.remove(task))}
                  >
                    <Trash2 size={14} aria-hidden="true" />
                    {waiting ? "取消等待并删除" : "删除"}
                  </button>
                </div>
              ) : null}
            </div>
          </div>
        </div>
        <div className="rd-meta">
          <span className="rd-src">{sourceLabelFor(task)}</span>
          <span className="rd-date">{formatDate(task.created_at)}</span>
          <a href={task.url} target="_blank" rel="noopener noreferrer" className="rd-orig" title="打开原网页 O">
            原网页
            <ExternalLink size={12} aria-hidden="true" />
          </a>
          {done ? <span className="rd-sep" aria-hidden="true" /> : null}
          {done ? (
            <TagEditor
              key={task.task_id}
              tags={task.tags}
              allTags={allTags}
              inputRef={tagInputRef}
              onChange={(tags) => actions.setTags(task, tags)}
            />
          ) : null}
        </div>
      </header>
      <div className="rd-body">
        {!done ? (
          <StatusPanel task={task} actions={actions} />
        ) : mode === "archive" ? (
          <div className="rd-frame-wrap">
            <Snapshot task={task} />
          </div>
        ) : (
          <TextView task={task} searchQuery={searchQuery} />
        )}
        {detailsOpen ? (
          <DetailsDrawer task={task} actions={actions} onClose={() => onDetailsOpenChange(false)} />
        ) : null}
      </div>
    </section>
  );
}
