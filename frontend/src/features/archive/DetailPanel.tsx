import { type ChangeEvent, type FormEvent, type KeyboardEvent, useMemo, useRef, useState } from "react";
import { Archive, Check, Download, Eye, File, Globe, LoaderCircle, Pencil, Play, RefreshCw, Trash2, Upload, X } from "lucide-react";
import type { ArchiveFile, ArchiveTag, ArchiveTask } from "../../types/domain";
import {
  fileSourceLabel,
  formatDate,
  formatFileSize,
  safeUrl,
  sourceLabel,
  statusMeta,
  stepLabel,
  taskNotices,
  taskTitle,
} from "../../utils/format";
import { cleanTag } from "../../utils/tags";

interface DetailPanelProps {
  task: ArchiveTask | null;
  files: ArchiveFile[];
  tags: ArchiveTag[];
  onClearSelection: () => void;
  onRefreshFiles: () => void;
  onUploadFile: (file: globalThis.File) => void;
  onDeleteTask: (taskId: string) => void;
  onResumeManualAction: (taskId: string, code: string) => void;
  onOpenBrowser: (taskId: string, actionCode: string) => void;
  onMarkRead: (taskId: string) => void;
  onRearchiveTask: (taskId: string) => void;
  onRenameTask: (task: ArchiveTask, customTitle: string | null) => Promise<void>;
  onUpdateTags: (task: ArchiveTask, tags: string[]) => void;
  onRenameFile: (fileName: string, displayName: string) => Promise<void>;
  onDeleteFile: (fileName: string, displayName: string) => void;
}

export function DetailPanel({
  task,
  files,
  tags,
  onClearSelection,
  onRefreshFiles,
  onUploadFile,
  onDeleteTask,
  onResumeManualAction,
  onOpenBrowser,
  onMarkRead,
  onRearchiveTask,
  onRenameTask,
  onUpdateTags,
  onRenameFile,
  onDeleteFile,
}: DetailPanelProps): JSX.Element {
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const [editingTitle, setEditingTitle] = useState(false);
  const [titleValue, setTitleValue] = useState("");
  const [savingTitle, setSavingTitle] = useState(false);
  const [editingFile, setEditingFile] = useState<string | null>(null);
  const [fileValue, setFileValue] = useState("");
  const [renamingFile, setRenamingFile] = useState<string | null>(null);
  const [tagInput, setTagInput] = useState("");

  const notices = useMemo(() => (task ? taskNotices(task) : []), [task]);

  if (!task) {
    return (
      <aside className="detail-pane" aria-live="polite">
        <div className="empty-detail">
          <Archive size={32} />
          <h2>选择一条存档记录</h2>
          <p>右侧会显示这个任务的真实状态、文件和可用操作。</p>
        </div>
      </aside>
    );
  }

  const activeTask = task;
  const meta = statusMeta[activeTask.status] || statusMeta.queued;
  const url = safeUrl(activeTask.url);
  const rearchiveDisabled = ["queued", "running"].includes(activeTask.status);
  const hasManualActions = activeTask.manual_actions.length > 0;

  async function submitTitle(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    setSavingTitle(true);
    try {
      await onRenameTask(activeTask, titleValue.trim() || null);
      setEditingTitle(false);
    } finally {
      setSavingTitle(false);
    }
  }

  async function submitFileName(event: FormEvent<HTMLFormElement>, fileName: string): Promise<void> {
    event.preventDefault();
    const displayName = fileValue.trim();
    if (!displayName) return;
    setRenamingFile(fileName);
    try {
      await onRenameFile(fileName, displayName);
      setEditingFile(null);
    } finally {
      setRenamingFile(null);
    }
  }

  function uploadChanged(event: ChangeEvent<HTMLInputElement>): void {
    const [file] = event.target.files || [];
    event.target.value = "";
    if (file) onUploadFile(file);
  }

  function startTitleEdit(): void {
    setTitleValue(activeTask.custom_title || activeTask.display_title || taskTitle(activeTask));
    setEditingTitle(true);
  }

  function startFileEdit(file: ArchiveFile): void {
    setEditingFile(file.file_name);
    setFileValue(file.display_name || file.file_name);
  }

  function addTag(value: string): void {
    const tag = cleanTag(value);
    if (!tag) return;
    if (activeTask.tags.some((item) => item.toLowerCase() === tag.toLowerCase())) return;
    onUpdateTags(activeTask, [...activeTask.tags, tag]);
    setTagInput("");
  }

  function tagKeyDown(event: KeyboardEvent<HTMLInputElement>): void {
    if (event.key !== "Enter") return;
    event.preventDefault();
    addTag(matchingTags[0] || tagInput);
  }

  const existingTags = new Set(task.tags.map((tag) => tag.toLowerCase()));
  const matchingTags = tags
    .map((tag) => tag.name)
    .filter((tag) => !existingTags.has(tag.toLowerCase()))
    .filter((tag) => tag.toLowerCase().includes(tagInput.trim().toLowerCase()))
    .slice(0, 6);

  return (
    <aside className="detail-pane" aria-live="polite">
      <div className="detail-header">
        <div>
          <span className={`status-label ${meta.className}`}>
            <span className={`status-dot ${meta.className === "failed" ? "fail" : meta.className === "queued" || meta.className === "manual-action" ? "warning" : "ok"}`} />
            {meta.label}
          </span>
          <div className="detail-title-wrap">
            {editingTitle ? (
              <form className="title-rename-form" onSubmit={submitTitle}>
                <input
                  maxLength={200}
                  value={titleValue}
                  disabled={savingTitle}
                  aria-label="存档名称"
                  onChange={(event) => setTitleValue(event.target.value)}
                />
                <button type="submit" title="保存" aria-label="保存" disabled={savingTitle}>
                  <Check size={16} />
                </button>
                <button type="button" title="取消" aria-label="取消" disabled={savingTitle} onClick={() => setEditingTitle(false)}>
                  <X size={16} />
                </button>
              </form>
            ) : (
              <h2>{taskTitle(task)}</h2>
            )}
          </div>
          <a className="detail-url" href={task.url} target="_blank" rel="noopener noreferrer">
            {task.url}
          </a>
        </div>
        <button className="icon-button" type="button" onClick={onClearSelection} aria-label="关闭详情" title="关闭详情">
          <X size={18} />
        </button>
      </div>

      {task.status === "manual_action_required" ? (
        <section className="manual-action-list" aria-label="待手动处理事项">
          {task.manual_actions.map((action) => {
            const tabState = action.browser_tab_state ?? "not_opened";
            const tabStateLabel = tabState === "available"
              ? "已连接"
              : tabState === "missing"
                ? "原标签页已丢失"
                : "尚未打开";
            const openLabel = tabState === "available"
              ? "切回处理页面"
              : tabState === "missing"
                ? "重新打开处理页面"
                : "打开处理页面";
            return (
              <div className="manual-action-row" key={action.code}>
                <div className="manual-action-copy">
                  <div className="manual-action-heading">
                    <strong>{action.target === "video" ? "视频操作" : "网页操作"}</strong>
                    <span className={`manual-tab-state ${tabState}`}>{tabStateLabel}</span>
                  </div>
                  <p>
                    {action.message}
                    {action.target === "page" ? " 继续前请确认处理页面显示的是要保存的内容。" : ""}
                  </p>
                </div>
                <div className="manual-action-buttons">
                  <button
                    className="primary-action"
                    type="button"
                    onClick={() => onOpenBrowser(task.task_id, action.code)}
                  >
                    <Globe size={16} />
                    {openLabel}
                  </button>
                  <button
                    className="primary-action"
                    type="button"
                    disabled={tabState !== "available"}
                    onClick={() => onResumeManualAction(task.task_id, action.code)}
                  >
                    {action.resume === "continue_video" ? <LoaderCircle size={16} /> : <Play size={16} />}
                    {action.resume === "continue_video" ? "登录后继续下载" : "继续处理"}
                  </button>
                </div>
              </div>
            );
          })}
        </section>
      ) : null}

      <div className="detail-actions">
        {task.result?.view_url ? (
          <a className="primary-action filled" href={task.result.view_url} target="_blank" rel="noopener noreferrer">
            <Eye size={16} />
            查看文件
          </a>
        ) : null}
        <a className="primary-action" href={task.url} target="_blank" rel="noopener noreferrer">
          <Globe size={16} />
          打开原网页
        </a>
        {!hasManualActions ? (
          <button className="primary-action" type="button" disabled={rearchiveDisabled} onClick={() => onRearchiveTask(task.task_id)}>
            <RefreshCw size={16} />
            重新归档
          </button>
        ) : null}
        {!task.is_read ? (
          <button className="primary-action" type="button" onClick={() => onMarkRead(task.task_id)}>
            <Check size={16} />
            标记已读
          </button>
        ) : null}
        <button className="primary-action" type="button" onClick={startTitleEdit}>
          <Pencil size={16} />
          修改名称
        </button>
        <button
          className="primary-action danger"
          type="button"
          disabled={task.status === "running"}
          onClick={() => onDeleteTask(task.task_id)}
        >
          <Trash2 size={16} />
          删除
        </button>
      </div>

      <section className="detail-section">
        <div className="section-line">
          <h3>存档文件</h3>
          <div className="section-actions">
            <button className="text-button" type="button" onClick={() => fileInputRef.current?.click()}>
              <Upload size={15} />
              上传文件
            </button>
            <button className="text-button" type="button" onClick={onRefreshFiles}>
              刷新
            </button>
          </div>
        </div>
        <input id="fileUpload" name="file" className="visually-hidden" ref={fileInputRef} type="file" onChange={uploadChanged} />
        <div className="file-list">
          {files.length === 0 ? (
            <div className="empty-state compact">暂无可查看文件</div>
          ) : (
            files.map((file) => (
              <div className="file-row" key={file.file_name}>
                <FileToolIcon file={file} />
                <div className="file-main">
                  {editingFile === file.file_name ? (
                    <form className="file-rename-form" onSubmit={(event) => submitFileName(event, file.file_name)}>
                      <input
                        maxLength={240}
                        value={fileValue}
                        disabled={renamingFile === file.file_name}
                        aria-label="文件名称"
                        onChange={(event) => setFileValue(event.target.value)}
                      />
                      <button type="submit" title="保存" aria-label="保存" disabled={renamingFile === file.file_name}>
                        <Check size={15} />
                      </button>
                      <button type="button" title="取消" aria-label="取消" disabled={renamingFile === file.file_name} onClick={() => setEditingFile(null)}>
                        <X size={15} />
                      </button>
                    </form>
                  ) : (
                    <span className="file-name" title={file.file_name}>
                      {file.display_name || file.file_name}
                    </span>
                  )}
                  <span className="file-size">
                    {fileSourceLabel(file.tool, file.source_type)} · {formatFileSize(file.size_bytes)}
                  </span>
                </div>
                <span className="file-actions">
                  <a href={file.view_url} target="_blank" rel="noopener noreferrer" title="打开">
                    <Eye size={16} />
                  </a>
                  <a href={file.download_url} download={file.display_name || file.file_name} title="下载">
                    <Download size={16} />
                  </a>
                  <button type="button" onClick={() => startFileEdit(file)} title="改名" aria-label="改名">
                    <Pencil size={16} />
                  </button>
                  <button className="danger-action" type="button" onClick={() => onDeleteFile(file.file_name, file.display_name || file.file_name)} title="删除" aria-label="删除">
                    <Trash2 size={16} />
                  </button>
                </span>
              </div>
            ))
          )}
        </div>
      </section>

      <section className="detail-section">
        <h3>标签</h3>
        <div className="tag-editor">
          <div className="tag-list">
            {task.tags.length ? (
              task.tags.map((tag) => (
                <span className="editable-tag" key={tag}>
                  <span>{tag}</span>
                  <button type="button" aria-label={`移除 ${tag}`} onClick={() => onUpdateTags(task, task.tags.filter((item) => item !== tag))}>
                    ×
                  </button>
                </span>
              ))
            ) : (
              <div className="empty-state compact">暂无标签</div>
            )}
          </div>
          <div className="tag-input-wrap">
            <label className="visually-hidden" htmlFor="tagInput">
              添加标签
            </label>
            <input
              id="tagInput"
              name="tag"
              type="text"
              autoComplete="off"
              placeholder="输入标签"
              value={tagInput}
              onChange={(event) => setTagInput(event.target.value)}
              onKeyDown={tagKeyDown}
            />
            <div className="tag-suggestions" hidden={!tagInput.trim() || !matchingTags.length}>
              {matchingTags.map((tag) => (
                <button type="button" key={tag} onClick={() => addTag(tag)}>
                  {tag}
                </button>
              ))}
            </div>
          </div>
        </div>
      </section>

      <section className="detail-section">
        <h3>任务信息</h3>
        <dl className="detail-grid">
          <div>
            <dt>来源</dt>
            <dd>{sourceLabel(task)}</dd>
          </div>
          <div>
            <dt>状态</dt>
            <dd>{meta.label}</dd>
          </div>
          <div>
            <dt>创建</dt>
            <dd>{formatDate(task.created_at)}</dd>
          </div>
          <div>
            <dt>完成</dt>
            <dd>{formatDate(task.finished_at)}</dd>
          </div>
          <div>
            <dt>当前步骤</dt>
            <dd>{stepLabel(task.current_step)}</dd>
          </div>
          <div>
            <dt>已读</dt>
            <dd>{task.is_read ? "是" : "否"}</dd>
          </div>
          <div>
            <dt>域名</dt>
            <dd>{url?.hostname || "—"}</dd>
          </div>
        </dl>
      </section>

      {notices.length ? (
        <section className="detail-section">
          <h3>任务提醒</h3>
          <div className="notice-list">
            {notices.map((notice) => (
              <div className={`notice-card ${notice.type}`} key={notice.text}>
                {notice.text}
              </div>
            ))}
          </div>
        </section>
      ) : null}

      {task.source_type === "rss" ? (
        <section className="detail-section">
          <h3>RSS 信息</h3>
          <dl className="detail-grid">
            <div>
              <dt>来源标题</dt>
              <dd>{task.source_title || "RSS"}</dd>
            </div>
            <div>
              <dt>来源类型</dt>
              <dd>RSS</dd>
            </div>
          </dl>
        </section>
      ) : null}
    </aside>
  );
}

function FileToolIcon({ file }: { file: ArchiveFile }): JSX.Element {
  if (file.source_type === "upload" || file.tool === "upload") {
    return (
      <span className="icon file-tool-icon" role="img" aria-label="手动上传" title="手动上传">
        <Upload size={17} />
      </span>
    );
  }
  const tool = file.tool === "yt-dlp"
    ? { name: "yt-dlp", logo: "/static/vendor-icons/yt-dlp.png" }
    : file.tool === "singlefile"
      ? { name: "SingleFile", logo: "/static/vendor-icons/singlefile.png" }
      : null;
  if (!tool) {
    return (
      <span className="icon file-tool-icon">
        <File size={17} />
      </span>
    );
  }
  return (
    <span className="file-tool-icon" role="img" aria-label={tool.name} title={tool.name}>
      <img className="file-tool-logo" src={tool.logo} alt="" />
    </span>
  );
}
