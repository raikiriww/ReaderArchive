import { useQuery } from "@tanstack/react-query";
import { Download, Eye, File, Pencil, RefreshCw, Trash2, Upload, Video, X } from "lucide-react";
import { type ChangeEvent, useRef, useState } from "react";
import { listArchiveTaskFiles } from "../../api/client";
import type { ArchiveFile, ArchiveTask } from "../../types/domain";
import {
  fileSourceLabel,
  formatDate,
  formatFileSize,
  isVideoNoise,
  safeUrl,
  shortError,
  taskFileKey,
} from "../../utils/format";
import type { ReaderActions } from "./types";

export type DrawerNotice = { kind: "warning"; text: string } | { kind: "quiet"; text: string };

export function drawerNotices(task: ArchiveTask): DrawerNotice[] {
  const notices: DrawerNotice[] = [];
  const result = task.result;
  if (result?.page_error) {
    const prefix = result.video_file_name ? "视频已保存，网页未保存" : "网页未保存";
    notices.push({ kind: "warning", text: `${prefix}：${shortError(result.page_error)}` });
  }
  if (result?.video_error) {
    if (isVideoNoise(result.video_error)) {
      notices.push({ kind: "quiet", text: "此网址不含视频" });
    } else {
      const prefix = result.file_name ? "网页已保存，视频未保存" : "视频未保存";
      notices.push({ kind: "warning", text: `${prefix}：${shortError(result.video_error)}` });
    }
  }
  return notices;
}

const STATUS_TEXT: Record<ArchiveTask["status"], string> = {
  queued: "排队中",
  running: "处理中",
  manual_action_required: "等待手动处理",
  succeeded: "已完成",
  failed: "失败",
};

interface DetailsDrawerProps {
  task: ArchiveTask;
  actions: ReaderActions;
  onClose(): void;
}

export function DetailsDrawer({ task, actions, onClose }: DetailsDrawerProps): JSX.Element {
  const [prepare, setPrepare] = useState(false);
  const fileInput = useRef<HTMLInputElement | null>(null);
  const filesQuery = useQuery({
    queryKey: ["archive-files", task.task_id, taskFileKey(task)],
    queryFn: () => listArchiveTaskFiles(task.task_id),
  });
  const files = filesQuery.data ?? [];
  const notices = drawerNotices(task);
  const warnings = notices.filter((notice) => notice.kind === "warning");
  const quiet = notices.filter((notice) => notice.kind === "quiet");
  const busy = task.status === "queued" || task.status === "running";
  const waiting = task.status === "manual_action_required";
  const host = safeUrl(task.url)?.hostname.replace(/^www\./, "") || "—";

  function uploadChanged(event: ChangeEvent<HTMLInputElement>): void {
    const [file] = event.target.files || [];
    event.target.value = "";
    if (file) actions.uploadFile(task, file);
  }

  return (
    <aside className="rd-drawer" aria-label="存档详情">
      <header>
        <h3>存档详情</h3>
        <button className="rd-icon-btn" type="button" onClick={onClose} title="关闭 I" aria-label="关闭详情">
          <X size={16} aria-hidden="true" />
        </button>
      </header>
      {warnings.length ? (
        <section>
          {warnings.map((notice) => (
            <div className="rd-notice" key={notice.text}>
              {notice.text}
            </div>
          ))}
        </section>
      ) : null}
      <section>
        <div className="rd-label">
          文件
          <span className="rd-label-acts">
            <button
              className="rd-text-btn small"
              type="button"
              disabled={filesQuery.isFetching}
              onClick={() => void filesQuery.refetch()}
            >
              <RefreshCw size={12} aria-hidden="true" />
              刷新
            </button>
            <button className="rd-text-btn small" type="button" onClick={() => fileInput.current?.click()}>
              <Upload size={13} aria-hidden="true" />
              上传
            </button>
          </span>
        </div>
        <input ref={fileInput} type="file" hidden onChange={uploadChanged} aria-label="上传文件" />
        {filesQuery.isPending ? (
          <p className="rd-quiet">正在读取文件…</p>
        ) : filesQuery.isError ? (
          <p className="rd-quiet">文件列表读取失败，点「刷新」重试。</p>
        ) : files.length === 0 ? (
          <p className="rd-quiet">还没有可查看的文件</p>
        ) : (
          files.map((file) => <FileRow key={file.file_name} task={task} file={file} actions={actions} />)
        )}
        {quiet.map((notice) => (
          <p className="rd-quiet" key={notice.text}>
            {notice.text}
          </p>
        ))}
      </section>
      {!waiting ? (
        <section>
          <div className="rd-label">重新归档</div>
          <p className="rd-help">会替换这条存档的文件。名称、标签和已读状态保持不变。</p>
          <label className="rd-check">
            <input type="checkbox" checked={prepare} onChange={(event) => setPrepare(event.target.checked)} />
            <span>
              保存前手动处理
              <small>先在内置浏览器里关弹窗、展开全文，再保存</small>
            </span>
          </label>
          <button
            className="rd-btn"
            type="button"
            disabled={busy}
            onClick={() => {
              actions.rearchive(task, prepare);
              onClose();
            }}
          >
            <RefreshCw size={15} aria-hidden="true" />
            {prepare ? "打开并等待处理" : "重新归档"}
          </button>
        </section>
      ) : null}
      <section>
        <div className="rd-label">信息</div>
        <dl className="rd-kv">
          <dt>状态</dt>
          <dd>{STATUS_TEXT[task.status] ?? task.status}</dd>
          <dt>来源</dt>
          <dd>{task.source_type === "rss" ? `RSS · ${task.source_title || "订阅"}` : "手动保存"}</dd>
          <dt>保存于</dt>
          <dd>{formatDate(task.created_at)}</dd>
          <dt>完成于</dt>
          <dd>{task.status === "succeeded" ? formatDate(task.finished_at) : "—"}</dd>
          <dt>网站</dt>
          <dd>{host}</dd>
          <dt>已读</dt>
          <dd>{task.is_read ? "是" : "否"}</dd>
          <dt>名称</dt>
          <dd>{task.custom_title ? "已手动修改" : "使用网页标题"}</dd>
        </dl>
      </section>
      <section className="rd-drawer-danger">
        <button
          className="rd-link-danger"
          type="button"
          disabled={task.status === "running"}
          onClick={() => void actions.remove(task)}
        >
          <Trash2 size={14} aria-hidden="true" />
          {waiting ? "取消等待并删除" : "删除这条存档"}
        </button>
      </section>
    </aside>
  );
}

function FileRow({ task, file, actions }: { task: ArchiveTask; file: ArchiveFile; actions: ReaderActions }): JSX.Element {
  const display = file.display_name || file.file_name;
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(display);
  const [saving, setSaving] = useState(false);
  const Icon = file.tool === "yt-dlp" ? Video : file.tool === "upload" || file.source_type === "upload" ? Upload : File;

  async function commit(): Promise<void> {
    const next = value.trim();
    if (!next || next === display) {
      setEditing(false);
      return;
    }
    setSaving(true);
    try {
      await actions.renameFile(task, file.file_name, next);
      setEditing(false);
    } catch {
      /* the action already showed a toast; keep the editor open */
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="rd-file">
      <Icon size={16} className="rd-file-icon" aria-hidden="true" />
      <div className="rd-file-main">
        {editing ? (
          <input
            className="rd-file-edit"
            // biome-ignore lint/a11y/noAutofocus: the editor opens on an explicit rename click
            autoFocus
            maxLength={240}
            value={value}
            disabled={saving}
            aria-label="文件名称"
            onChange={(event) => setValue(event.target.value)}
            onBlur={() => void commit()}
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                event.preventDefault();
                event.stopPropagation();
                void commit();
              } else if (event.key === "Escape") {
                event.preventDefault();
                event.stopPropagation();
                setEditing(false);
              }
            }}
          />
        ) : (
          <strong title={file.file_name}>{display}</strong>
        )}
        <small>
          {fileSourceLabel(file.tool, file.source_type)} · {formatFileSize(file.size_bytes)}
        </small>
      </div>
      <span className="rd-file-acts">
        <a className="rd-icon-btn" href={file.view_url} target="_blank" rel="noopener noreferrer" title="打开" aria-label="打开">
          <Eye size={14} aria-hidden="true" />
        </a>
        <a className="rd-icon-btn" href={file.download_url} download={display} title="下载" aria-label="下载">
          <Download size={14} aria-hidden="true" />
        </a>
        <button
          className="rd-icon-btn"
          type="button"
          title="改名"
          aria-label="改名"
          onClick={() => {
            setValue(display);
            setEditing(true);
          }}
        >
          <Pencil size={14} aria-hidden="true" />
        </button>
        <button
          className="rd-icon-btn danger"
          type="button"
          title="删除"
          aria-label="删除"
          onClick={() => actions.deleteFile(task, file.file_name, display)}
        >
          <Trash2 size={14} aria-hidden="true" />
        </button>
      </span>
    </div>
  );
}
