import { describe, expect, test } from "bun:test";
import {
  archiveToolMarks,
  cleanSummary,
  formatFileSize,
  hostSourceLabel,
  isVideoNoise,
  shortError,
  sourceLabelFor,
  taskTitle,
} from "../src/utils/format";
import { cleanTag, validTagFilters } from "../src/utils/tags";
import { archiveTask } from "./fixtures";
import type { ArchiveTask } from "../src/types/domain";

describe("archive formatting helpers", () => {
  test("formats task titles from explicit titles, feed entries, and URLs", () => {
    expect(taskTitle(archiveTask({ display_title: "Saved title" }))).toBe("Saved title");
    expect(taskTitle(archiveTask({ display_title: "", entry_title: "Feed title" }))).toBe("Feed title");
    expect(taskTitle(archiveTask({ display_title: "", url: "https://example.com/path/" }))).toBe("example.com/path");
    expect(taskTitle(archiveTask({ display_title: "", url: "not-a-url" }))).toBe("未命名网页");
  });

  test("formats file sizes and short errors defensively", () => {
    expect(formatFileSize(512)).toBe("512 B");
    expect(formatFileSize(1536)).toBe("1.5 KB");
    expect(formatFileSize(-1)).toBe("—");
    expect(shortError("first line\nsecond line")).toBe("first line");
    expect(shortError("https://example.com/?poc_token=secret&target=page")).toBe(
      "https://example.com/?poc_token=[已隐藏]&target=page",
    );
    expect(shortError("")).toBe("存档失败");
  });

  test("builds source labels", () => {
    expect(sourceLabelFor(archiveTask())).toBe("手动");
    expect(sourceLabelFor(archiveTask({ url: "https://weibo.com/1/abc" }))).toBe("手动");
    expect(sourceLabelFor(archiveTask({ source_type: "rss", source_title: "Daily Feed" }))).toBe("Daily Feed");
    expect(sourceLabelFor(archiveTask({ source_type: "rss", source_title: null }))).toBe("RSS");
  });
});

describe("list row helpers", () => {
  test("labels urls by known platform or bare hostname", () => {
    expect(hostSourceLabel("https://m.weibo.cn/status/1")).toBe("微博");
    expect(hostSourceLabel("https://weibo.cn/x")).toBe("微博");
    expect(hostSourceLabel("https://mp.weixin.qq.com/s/x")).toBe("公众号");
    expect(hostSourceLabel("https://twitter.com/a")).toBe("X");
    expect(hostSourceLabel("https://www.example.org/a")).toBe("example.org");
    expect(hostSourceLabel("nope")).toBe("");
  });

  test("cleans summaries of whitespace and platform boilerplate", () => {
    expect(cleanSummary("公开 26-10-10 13:55 发布于 北京 来自 微博网页版 已编辑 今天天气\n不错")).toBe("今天天气 不错");
    expect(cleanSummary("Daily Hacker News for 2026-10-10   Top story")).toBe("Top story");
    expect(cleanSummary("  plain   text ")).toBe("plain text");
    expect(cleanSummary(null)).toBe("");
  });

  test("shows SingleFile always and yt-dlp only when it matters", () => {
    const result = archiveTask().result;
    const marks = (overrides: Partial<ArchiveTask>) =>
      archiveToolMarks(archiveTask(overrides)).map((mark) => `${mark.tool}:${mark.state}`);
    const action = (target: string) =>
      ({ code: "c1", kind: `${target}.login_required`, target, message: "", resume: "retry_page" }) as unknown as ArchiveTask["manual_actions"][number];

    expect(marks({})).toEqual(["singlefile:ok"]);
    expect(marks({ result: { ...result, video_error: "[Weibo] 1: No video formats found!" } })).toEqual(["singlefile:ok"]);
    expect(marks({ result: { ...result, video_error: "HTTP Error 403: Forbidden" } })).toEqual([
      "singlefile:ok",
      "yt-dlp:failed",
    ]);
    expect(marks({ result: { ...result, video_file_name: "v.mp4" } })).toEqual(["singlefile:ok", "yt-dlp:ok"]);
    expect(marks({ result: { ...result, file_name: null, video_file_name: "v.mp4", page_error: "crash" } })).toEqual([
      "singlefile:failed",
      "yt-dlp:ok",
    ]);
    expect(marks({ status: "queued", result: null })).toEqual(["singlefile:running", "yt-dlp:running"]);
    expect(marks({ status: "manual_action_required", manual_actions: [action("page")], result: null })).toEqual([
      "singlefile:waiting",
    ]);
    expect(marks({ status: "manual_action_required", manual_actions: [action("video")] })).toEqual([
      "singlefile:ok",
      "yt-dlp:waiting",
    ]);
    expect(marks({ status: "failed", result: null })).toEqual(["singlefile:failed"]);
    expect(archiveToolMarks(archiveTask({ result: { ...result, video_error: "HTTP Error 403" } }))[1].label).toBe(
      "视频下载失败",
    );
  });

  test("recognizes yt-dlp no-video noise", () => {
    expect(isVideoNoise('[Substack] some-post: Page type "newsletter" is not supported; please report this issue')).toBe(
      true,
    );
    expect(isVideoNoise("[generic] Extracting URL: https://example.com/weekly/issue-1.html")).toBe(true);
    expect(isVideoNoise("[generic] Unable to download webpage: HTTP Error 404: Not Found")).toBe(false);
    expect(isVideoNoise("Postprocessing: Error opening input files: Invalid data found when processing input")).toBe(false);
    expect(isVideoNoise("ERROR: [Weibo] 5: No video formats found!; please report this issue on https://x")).toBe(true);
    expect(isVideoNoise("ERROR: Failed to parse JSON (caused by JSONDecodeError)")).toBe(false);
    expect(isVideoNoise("Unsupported URL: https://example.com")).toBe(true);
    expect(isVideoNoise("HTTP Error 403: Forbidden")).toBe(false);
  });

  test("short errors drop the yt-dlp ERROR prefix and report-issue boilerplate", () => {
    expect(shortError("ERROR: [generic] boom; please report this issue on https://github.com/yt-dlp/yt-dlp/issues")).toBe(
      "[generic] boom",
    );
    expect(shortError("x".repeat(400)).length).toBe(163);
  });
});

describe("tag helpers", () => {
  test("cleans tags and keeps only valid filters", () => {
    expect(cleanTag("  weekly   read  ")).toBe("weekly read");
    expect(validTagFilters(["work", "WORK", "missing", "later"], [{ name: "Work" }, { name: "Later" }])).toEqual([
      "Work",
      "Later",
    ]);
  });
});
