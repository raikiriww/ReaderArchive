import type { ArchiveTask, ArchiveTaskStatus } from "../types/domain";

export const statusMeta: Record<ArchiveTaskStatus, { label: string; className: string }> = {
  queued: { label: "排队中", className: "queued" },
  running: { label: "处理中", className: "running" },
  browser_login_required: { label: "需登录", className: "login-required" },
  succeeded: { label: "已完成", className: "succeeded" },
  failed: { label: "失败", className: "failed" },
};

export function formatDate(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).format(date).replace(/\//g, "-");
}

export function formatFileSize(size: number): string {
  let value = Number(size);
  if (!Number.isFinite(value) || value < 0) return "—";
  for (const unit of ["B", "KB", "MB", "GB"]) {
    if (value < 1024 || unit === "GB") {
      return unit === "B" ? `${value} B` : `${value.toFixed(1)} ${unit}`;
    }
    value /= 1024;
  }
  return `${size} B`;
}

export function safeUrl(value: string): URL | null {
  try {
    return new URL(value);
  } catch {
    return null;
  }
}

export function taskTitle(task: ArchiveTask): string {
  const url = safeUrl(task.url);
  if (task.display_title) return task.display_title;
  if (task.entry_title) return task.entry_title;
  if (!url) return "未命名网页";
  const path = url.pathname === "/" ? "" : url.pathname.replace(/\/$/, "");
  return `${url.hostname}${path}`;
}

export function shortError(value: string | null | undefined): string {
  const firstLine = String(value || "").split(/\r?\n/).find(Boolean) || "存档失败";
  const cleaned = firstLine.replace(/\s+/g, " ").trim();
  return cleaned.length > 160 ? `${cleaned.slice(0, 160)}...` : cleaned;
}

export function sourceLabel(task: ArchiveTask): string {
  if (task.source_type === "rss") {
    return task.source_title ? `RSS：${task.source_title}` : "RSS";
  }
  return "手动";
}

export function stepLabel(value: string | null): string {
  if (value === "queued") return "排队中";
  if (value === "page+video") return "保存网页和下载视频";
  if (value === "video") return "尝试下载视频";
  if (value === "browser_login") return "等待浏览器登录确认";
  if (value === "page") return "保存网页";
  return "—";
}

export function fileSourceLabel(tool: string, sourceType: string): string {
  if (sourceType === "upload" || tool === "upload") return "手动上传";
  if (tool === "singlefile") return "网页存档";
  if (tool === "yt-dlp") return "视频下载";
  return "文件";
}

export function taskNotices(task: ArchiveTask): Array<{ type: "error" | "warning"; text: string }> {
  const notices: Array<{ type: "error" | "warning"; text: string }> = [];
  if (task.error) notices.push({ type: "error", text: shortError(task.error) });
  if (task.result?.page_error) {
    notices.push({ type: "warning", text: `视频已保存，网页未保存：${shortError(task.result.page_error)}` });
  }
  if (task.result?.video_error) {
    notices.push({ type: "warning", text: `网页已保存，未下载到视频：${shortError(task.result.video_error)}` });
  }
  if (task.status === "browser_login_required") {
    notices.push({ type: "warning", text: "打开浏览器完成登录后，再继续下载。" });
  }
  return notices;
}

export function taskFileKey(task: ArchiveTask): string {
  return [
    task.status,
    task.result?.file_name || "",
    task.result?.video_file_name || "",
    task.result?.page_error || "",
    task.result?.video_error || "",
  ].join("|");
}
