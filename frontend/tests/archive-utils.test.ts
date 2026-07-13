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
    expect(shortError("https://example.com/?poc_token=secret&target=page")).toBe(
      "https://example.com/?poc_token=[已隐藏]&target=page",
    );
    expect(shortError("")).toBe("存档失败");
  });

  test("builds source labels and task notices", () => {
    expect(sourceLabel(archiveTask())).toBe("手动");
    expect(sourceLabel(archiveTask({ source_type: "rss", source_title: "Daily Feed" }))).toBe("RSS：Daily Feed");

    const notices = taskNotices(
      archiveTask({
        status: "manual_action_required",
        manual_actions: [
          {
            code: "video_browser_login",
            kind: "login",
            target: "video",
            message: "请完成登录",
            resume: "continue_video",
            rule_id: "video.browser_login",
          },
        ],
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
    expect(notices).toContain("网页已保存，视频未保存：video failed");
    expect(notices).toContain("请完成登录");
  });

  test("does not claim the page was saved when a manual page action is pending", () => {
    const notices = taskNotices(
      archiveTask({
        status: "manual_action_required",
        manual_actions: [
          {
            code: "wechat_article_verification",
            kind: "verification",
            target: "page",
            message: "请完成微信验证",
            resume: "retry_page",
            rule_id: "wechat.mp_article.verification",
          },
        ],
        result: {
          file_name: null,
          download_url: null,
          view_url: null,
          video_file_name: null,
          video_download_url: null,
          video_error: "unsupported",
          page_error: null,
        },
      }),
    ).map((notice) => notice.text);

    expect(notices).toContain("视频未保存：unsupported");
    expect(notices).not.toContain("网页已保存，视频未保存：unsupported");
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
