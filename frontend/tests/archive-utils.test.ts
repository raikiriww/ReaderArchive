import { describe, expect, test } from "bun:test";
import { formatFileSize, shortError, sourceLabel, taskNotices, taskTitle } from "../src/utils/format";
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
    expect(shortError("")).toBe("存档失败");
  });

  test("builds source labels and task notices", () => {
    expect(sourceLabel(archiveTask())).toBe("手动");
    expect(sourceLabel(archiveTask({ source_type: "rss", source_title: "Daily Feed" }))).toBe("RSS：Daily Feed");

    const notices = taskNotices(
      archiveTask({
        status: "browser_login_required",
        error: "task failed",
        result: {
          file_name: "reader.html",
          download_url: "/download",
          view_url: "/view",
          video_file_name: null,
          video_download_url: null,
          video_error: "video failed",
          page_error: null,
        },
      }),
    ).map((notice) => notice.text);

    expect(notices).toContain("task failed");
    expect(notices).toContain("网页已保存，未下载到视频：video failed");
    expect(notices).toContain("打开浏览器完成登录后，再继续下载。");
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
