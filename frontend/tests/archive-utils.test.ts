import { describe, expect, test } from "bun:test";
import {
  cleanSummary,
  formatFileSize,
  hostSourceLabel,
  isVideoNoise,
  rowHasWarning,
  shortError,
  sourceLabelFor,
  taskTitle,
} from "../src/utils/format";
import { cleanTag, validTagFilters } from "../src/utils/tags";
import { archiveTask } from "./fixtures";

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

  test("only a failed page flags the row; video errors never do", () => {
    const result = archiveTask().result;
    expect(rowHasWarning(archiveTask({ result: { ...result, video_error: "HTTP Error 403" } }))).toBe(false);
    expect(rowHasWarning(archiveTask({ result: { ...result, video_error: "[Weibo] 1: No video formats found!" } }))).toBe(
      false,
    );
    expect(rowHasWarning(archiveTask({ result: { ...result, page_error: "crash" } }))).toBe(true);
    expect(rowHasWarning(archiveTask({ result: null }))).toBe(false);
  });

  test("recognizes yt-dlp no-video noise", () => {
    expect(isVideoNoise("ERROR: [Weibo] 5: No video formats found!; please report this issue on https://x")).toBe(true);
    expect(isVideoNoise("ERROR: Failed to parse JSON (caused by JSONDecodeError)")).toBe(true);
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
