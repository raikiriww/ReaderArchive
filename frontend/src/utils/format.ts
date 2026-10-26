import type { ArchiveTask } from "../types/domain";

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
  const cleaned = firstLine
    .replace(/([?&](?:access_token|auth|key|poc_token|sig|signature|token)=)[^&\s]+/gi, "$1[已隐藏]")
    .replace(/\s+/g, " ")
    .replace(/^ERROR:\s*/i, "")
    .replace(/;?\s*please report this issue on .*$/i, "")
    .replace(/;?\s*Confirm you are on the latest version.*$/i, "")
    .trim();
  return cleaned.length > 160 ? `${cleaned.slice(0, 160)}...` : cleaned;
}

/** Short source label for a URL: known platforms by name, otherwise the hostname without www. */
export function hostSourceLabel(value: string): string {
  const host = safeUrl(value.trim())?.hostname.toLowerCase().replace(/^www\./, "") || "";
  if (/(^|\.)weibo\.(com|cn)$/.test(host)) return "微博";
  if (host === "mp.weixin.qq.com") return "公众号";
  if (host === "x.com" || host === "twitter.com" || host.endsWith(".x.com") || host.endsWith(".twitter.com")) return "X";
  return host;
}

/** Source label for a task: feed title for RSS items, 手动 for manual saves. */
export function sourceLabelFor(task: ArchiveTask): string {
  if (task.source_type === "rss") return task.source_title || "RSS";
  return "手动";
}

const WEIBO_PREFIX =
  /^公开\s*\S*?\s*\d{2,4}-\d{1,2}-\d{1,2}\s*\d{1,2}:\d{2}\s*(?:发布于\s*\S+)?\s*(?:来自\s*(?:微博 weibo\.com|\S+))?\s*(?:已编辑)?\s*/;
const HN_PREFIX = /^Daily Hacker News for \d{4}-\d{2}-\d{2}\s*/i;

/** Clean a list-row body summary: collapse whitespace and strip platform boilerplate prefixes. */
export function cleanSummary(summary: string | null | undefined): string {
  return String(summary || "")
    .replace(/\s+/g, " ")
    .trim()
    .replace(WEIBO_PREFIX, "")
    .replace(HN_PREFIX, "")
    .trim();
}

export function stepLabel(value: string | null): string {
  if (value === "queued") return "排队中";
  if (value === "page+video") return "保存网页和下载视频";
  if (value === "video") return "尝试下载视频";
  if (value === "manual_action") return "等待手动处理";
  if (value === "page") return "保存网页";
  return "—";
}

export function fileSourceLabel(tool: string, sourceType: string): string {
  if (sourceType === "upload" || tool === "upload") return "手动上传";
  if (tool === "singlefile") return "网页存档";
  if (tool === "yt-dlp") return "视频下载";
  return "文件";
}

/** yt-dlp errors that only mean "this page has no video"; shown as a quiet line, not a warning. */
const VIDEO_NOISE = [
  /unsupported url/i,
  /no video/i,
  /no media/i,
  /not a video/i,
  /no suitable (?:extractor|formats?)/i,
  /does not contain (?:a |any )?video/i,
  /no video formats found/i,
  /page type "[^"]*" is not supported/i, // Substack newsletters
  /^\[generic\] extracting url:/i, // only the progress line survived; the generic extractor found nothing
  /不支持(?:该|这个)?网址/,
  /没有(?:找到)?视频/,
];

export function isVideoNoise(error: string | null | undefined): boolean {
  if (!error) return false;
  return VIDEO_NOISE.some((pattern) => pattern.test(error));
}

export type ArchiveToolState = "ok" | "running" | "waiting" | "failed";

export interface ArchiveToolMark {
  tool: "singlefile" | "yt-dlp";
  name: string;
  state: ArchiveToolState;
  label: string;
}

const PAGE_LABELS: Record<ArchiveToolState, string> = {
  ok: "网页已保存",
  running: "正在保存网页",
  waiting: "网页等你处理",
  failed: "网页保存失败",
};

const VIDEO_LABELS: Record<ArchiveToolState, string> = {
  ok: "视频已下载",
  running: "正在尝试下载视频",
  waiting: "视频等你处理",
  failed: "视频下载失败",
};

/**
 * The archiving tools a list row shows, and how each one went. SingleFile always shows;
 * yt-dlp only when it got a video, is still trying, or really failed ("no video" errors are noise).
 */
export function archiveToolMarks(task: ArchiveTask): ArchiveToolMark[] {
  const result = task.result;
  const busy = task.status === "queued" || task.status === "running";
  const waits = (target: string) => task.manual_actions.some((action) => action.target === target);

  let page: ArchiveToolState | null = null;
  if (waits("page")) page = "waiting";
  else if (busy) page = "running";
  else if (result?.file_name) page = "ok";
  else if (result?.page_error || task.status === "failed") page = "failed";

  let video: ArchiveToolState | null = null;
  if (waits("video")) video = "waiting";
  else if (busy) video = "running";
  else if (result?.video_file_name) video = "ok";
  else if (result?.video_error && !isVideoNoise(result.video_error)) video = "failed";

  const marks: ArchiveToolMark[] = [];
  if (page) marks.push({ tool: "singlefile", name: "SingleFile", state: page, label: PAGE_LABELS[page] });
  if (video) marks.push({ tool: "yt-dlp", name: "yt-dlp", state: video, label: VIDEO_LABELS[video] });
  return marks;
}

export function taskFileKey(task: ArchiveTask): string {
  return [
    task.status,
    task.result?.file_name || "",
    task.result?.video_file_name || "",
    task.result?.page_error || "",
    task.result?.video_error || "",
    task.manual_actions.map((action) => action.code).join(","),
  ].join("|");
}
