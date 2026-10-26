import { describe, expect, mock, test } from "bun:test";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { DetailsDrawer, drawerNotices } from "../src/features/reader/DetailsDrawer";
import { Reader } from "../src/features/reader/Reader";
import { ReaderPopup } from "../src/features/reader/ReaderPopup";
import { isDeadVideoSource, Snapshot, snapshotLinkTarget, snapshotSource } from "../src/features/reader/Snapshot";
import { StatusPanel } from "../src/features/reader/StatusPanel";
import { TagEditor } from "../src/features/reader/TagEditor";
import { cleanSearchQuery, countHitParagraphs, highlightText, TextView } from "../src/features/reader/TextView";
import type { ReaderActions, ReaderProps } from "../src/features/reader/types";
import { readableVersions, VersionsMenuView } from "../src/features/reader/VersionsMenu";
import { isVideoNoise, sourceLabelFor, taskFileKey } from "../src/utils/format";
import { archiveFile, archiveTag, archiveTask } from "./fixtures";

function makeActions(): ReaderActions {
  return {
    toggleRead: mock(() => undefined),
    rename: mock(async () => undefined),
    setTags: mock(() => undefined),
    rearchive: mock(() => undefined),
    remove: mock(async () => false),
    openManualAction: mock(() => undefined),
    resumeManualAction: mock(async () => undefined),
    uploadFile: mock(() => undefined),
    renameFile: mock(async () => undefined),
    deleteFile: mock(() => undefined),
    toast: mock(() => undefined),
  };
}

function render(node: ReactElement, seed?: (client: QueryClient) => void): string {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Number.POSITIVE_INFINITY } } });
  seed?.(client);
  return renderToStaticMarkup(<QueryClientProvider client={client}>{node}</QueryClientProvider>);
}

function readerProps(overrides: Partial<ReaderProps> = {}): ReaderProps {
  return {
    task: archiveTask(),
    container: "popup",
    allTags: [archiveTag("research", 3)],
    mode: "archive",
    onModeChange: mock(() => undefined),
    detailsOpen: false,
    onDetailsOpenChange: mock(() => undefined),
    titleEditSignal: 0,
    tagInputRef: { current: null },
    onClose: mock(() => undefined),
    onOpenInTab: mock(() => undefined),
    onSwitchVersion: mock(() => undefined),
    actions: makeActions(),
    ...overrides,
  };
}

describe("snapshot source", () => {
  test("uses the /files/ route and never result.view_url", () => {
    const task = archiveTask({ task_id: "task 1/x" });
    const source = snapshotSource(task);
    expect(source).toEqual({
      kind: "page",
      src: "/api/v1/archive-tasks/task%201%2Fx/files/reader.html",
    });
    const html = render(<Snapshot task={task} />);
    expect(html).toContain('sandbox="allow-same-origin"');
    expect(html).toContain("/api/v1/archive-tasks/task%201%2Fx/files/reader.html");
    expect(html).not.toContain(task.result?.view_url as string);
    expect(html).not.toContain("/view");
    expect(html).not.toContain("allow-scripts");
  });

  test("encodes file names", () => {
    const task = archiveTask({ result: { ...archiveTask().result, file_name: "页面 #1.html" } });
    expect(snapshotSource(task)).toEqual({
      kind: "page",
      src: `/api/v1/archive-tasks/task-1/files/${encodeURIComponent("页面 #1.html")}`,
    });
  });

  test("renders PDFs without a sandbox", () => {
    const task = archiveTask({ result: { ...archiveTask().result, file_name: "paper.PDF" } });
    expect(snapshotSource(task).kind).toBe("pdf");
    const html = render(<Snapshot task={task} />);
    expect(html).toContain("<iframe");
    expect(html).not.toContain("sandbox");
    expect(html).toContain("/files/paper.PDF");
  });

  test("plays the video file when there is no page file", () => {
    const task = archiveTask({
      result: {
        ...archiveTask().result,
        file_name: null,
        view_url: "/api/v1/archive-tasks/task-1/files",
        video_file_name: "clip.mp4",
      },
    });
    const html = render(<Snapshot task={task} />);
    expect(html).toContain("<video");
    expect(html).toContain("controls");
    expect(html).toContain('src="/api/v1/archive-tasks/task-1/files/clip.mp4"');
    expect(html).not.toContain('src="/api/v1/archive-tasks/task-1/files"');
  });

  test("shows an empty state without any file", () => {
    const task = archiveTask({ result: null });
    expect(snapshotSource(task)).toEqual({ kind: "none" });
    const html = render(<Snapshot task={task} />);
    expect(html).not.toContain("<iframe");
    expect(html).toContain("没有可以显示的文件");
  });

  test("opens http(s) links in a new tab but leaves in-page anchors alone", () => {
    const page = "https://reader.test/api/v1/archive-tasks/task-1/files/page.html";
    expect(snapshotLinkTarget("https://example.com/a", "https://example.com/a")).toBe("https://example.com/a");
    expect(snapshotLinkTarget("//example.org/b", "https://example.org/b")).toBe("https://example.org/b");
    expect(snapshotLinkTarget("#comments", `${page}#comments`)).toBeNull();
    expect(snapshotLinkTarget("javascript:void(0)", "javascript:void(0)")).toBeNull();
    expect(snapshotLinkTarget("mailto:a@example.com", "mailto:a@example.com")).toBeNull();
    expect(snapshotLinkTarget(null, page)).toBeNull();
  });

  test("treats snapshot videos without a playable source as dead", () => {
    expect(isDeadVideoSource(null, [])).toBe(true);
    expect(isDeadVideoSource("", [])).toBe(true);
    expect(isDeadVideoSource("blob:https://www.youtube.com/1f2e", [])).toBe(true);
    expect(isDeadVideoSource(null, ["", null])).toBe(true);
    expect(isDeadVideoSource("https://example.com/clip.mp4", [])).toBe(false);
    expect(isDeadVideoSource(null, ["data:video/mp4;base64,AAAA"])).toBe(false);
  });

  test("lets the snapshot go fullscreen", () => {
    const task = archiveTask({ result: { ...archiveTask().result, video_file_name: "clip.mp4" } });
    expect(render(<Snapshot task={task} />)).toContain("allowFullScreen");
  });
});

describe("reader header", () => {
  test("shows the unread pill, mode switch, and popup-only controls", () => {
    const html = render(
      <Reader
        {...readerProps({
          nav: { label: "未读 · 今天", index: 2, total: 9, onPrev: () => undefined, onNext: () => undefined },
        })}
      />,
    );
    expect(html).toContain("rd-read-state");
    expect(html).toContain("未读");
    expect(html).not.toContain("is-read");
    expect(html).toContain('title="未读 · 今天"');
    expect(html).toContain("2 / 9");
    expect(html).toContain("原貌");
    expect(html).toContain("正文");
    expect(html).toContain('aria-label="在新标签页阅读"');
    expect(html).toContain('aria-label="关闭"');
    expect(html).toContain("Reader article");
    expect(html).toContain("example.com");
    expect(html).toContain("原网页");
    expect(html).toContain('placeholder="+ 标签  T"');
    expect(html).toContain('sandbox="allow-same-origin"');
  });

  test("shows 已读 for read tasks and hides popup controls on the page", () => {
    const html = render(<Reader {...readerProps({ task: archiveTask({ is_read: true }), container: "page" })} />);
    expect(html).toContain("is-read");
    expect(html).toContain("已读");
    expect(html).not.toContain("在新标签页阅读");
    expect(html).not.toContain('aria-label="关闭"');
  });

  test("shows the versions chip only with more than one version", () => {
    const task = archiveTask({ task_id: "v2" });
    const one = render(<Reader {...readerProps({ task })} />, (client) =>
      client.setQueryData(["archive-versions", "v2"], [task]),
    );
    expect(one).not.toContain("个版本");
    const two = render(<Reader {...readerProps({ task })} />, (client) =>
      client.setQueryData(
        ["archive-versions", "v2"],
        [task, archiveTask({ task_id: "v1", created_at: "2026-05-01T08:00:00Z" })],
      ),
    );
    expect(two).toContain("2 个版本");
  });

  test("renders the text view when mode is text", () => {
    const html = render(<Reader {...readerProps({ mode: "text" })} />, (client) =>
      client.setQueryData(["archive-search-text", "task-1"], {
        title: "Text title",
        paragraphs: ["First paragraph"],
        file_name: "reader.html",
      }),
    );
    expect(html).toContain("Text title");
    expect(html).toContain("First paragraph");
    expect(html).not.toContain("<iframe");
  });

  test("renders the status panel instead of the snapshot for unfinished tasks", () => {
    const html = render(<Reader {...readerProps({ task: archiveTask({ status: "queued", result: null }) })} />);
    expect(html).toContain("排队等待保存");
    expect(html).not.toContain("<iframe");
    expect(html).not.toContain("rd-read-state");
    expect(html).not.toContain("在新标签页阅读");
  });

  test("offers the video tab only when a page snapshot also has a video", () => {
    const withVideo = archiveTask({ result: { ...archiveTask().result, video_file_name: "clip.mp4" } });
    const html = render(<Reader {...readerProps({ task: withVideo })} />);
    expect(html).toContain("视频");
    expect(render(<Reader {...readerProps()} />)).not.toContain("视频</button>");
    const videoOnly = archiveTask({
      result: { ...archiveTask().result, file_name: null, video_file_name: "clip.mp4" },
    });
    expect(render(<Reader {...readerProps({ task: videoOnly })} />)).not.toContain("视频</button>");
  });

  test("plays the video in video mode and falls back to the snapshot without one", () => {
    const withVideo = archiveTask({ result: { ...archiveTask().result, video_file_name: "clip.mp4" } });
    const html = render(<Reader {...readerProps({ task: withVideo, mode: "video" })} />);
    expect(html).toContain('<video class="rd-video"');
    expect(html).toContain("/files/clip.mp4");
    expect(html).not.toContain("<iframe");
    const fallback = render(<Reader {...readerProps({ mode: "video" })} />);
    expect(fallback).toContain('sandbox="allow-same-origin"');
  });

  test("renders the details drawer when open", () => {
    const html = render(<Reader {...readerProps({ detailsOpen: true })} />);
    expect(html).toContain("存档详情");
  });

  test("source labels", () => {
    expect(sourceLabelFor(archiveTask({ url: "https://www.example.org/a" }))).toBe("手动");
    expect(sourceLabelFor(archiveTask({ source_type: "rss", source_title: "Daily" }))).toBe("Daily");
    expect(sourceLabelFor(archiveTask({ url: "https://mp.weixin.qq.com/s/x" }))).toBe("手动");
  });

  test("hides the list position when the task is not in the current list", () => {
    const html = render(
      <Reader
        {...readerProps({
          nav: { label: "未读", index: 0, total: 9, onPrev: () => undefined, onNext: () => undefined },
        })}
      />,
    );
    expect(html).toContain('title="未读"');
    expect(html).not.toContain("0 / 9");
    expect(html).not.toContain("rd-nav-pos");
    expect((html.match(/disabled=""/g) ?? []).length).toBeGreaterThanOrEqual(2);
  });
});

describe("versions menu", () => {
  test("keeps readable versions and the current one", () => {
    const versions = [
      { task_id: "a", created_at: "2026-06-01T00:00:00Z", status: "succeeded" },
      { task_id: "b", created_at: "2026-05-01T00:00:00Z", status: "failed" },
      { task_id: "c", created_at: "2026-04-01T00:00:00Z", status: "queued" },
    ];
    expect(readableVersions(versions, "c").map((v) => v.task_id)).toEqual(["a", "c"]);
  });

  test("lists versions with the newest marked", () => {
    const html = renderToStaticMarkup(
      <VersionsMenuView
        currentId="b"
        open={true}
        onToggle={() => undefined}
        onPick={() => undefined}
        versions={[
          { task_id: "a", created_at: "2026-06-01T00:00:00Z", status: "succeeded" },
          { task_id: "b", created_at: "2026-05-01T00:00:00Z", status: "succeeded" },
        ]}
      />,
    );
    expect(html).toContain("同一网址的保存版本");
    expect(html).toContain("最新");
    expect(html).toContain('class="on"');
  });
});

describe("status panel", () => {
  test("running shows steps", () => {
    const html = render(
      <StatusPanel task={archiveTask({ status: "running", current_step: "page", result: null })} actions={makeActions()} />,
    );
    expect(html).toContain("正在保存");
    expect(html).toContain("保存网页");
    expect(html).toContain('class="now"');
  });

  test("manual prepare with an available tab enables resume", () => {
    const task = archiveTask({
      status: "manual_action_required",
      manual_actions: [
        {
          code: "page.prepare_manually",
          kind: "browser_action",
          target: "page",
          message: "请在浏览器里处理页面",
          resume: "continue_archive",
          rule_id: "r1",
          browser_tab_state: "available",
        },
      ] as unknown as ReturnType<typeof archiveTask>["manual_actions"],
    });
    const html = render(<StatusPanel task={task} actions={makeActions()} />);
    expect(html).toContain("等你在内置浏览器里处理这个网页");
    expect(html).toContain("处理页面已连接");
    expect(html).toContain("切回处理页面");
    expect(html).toContain("处理完成，保存当前页面");
    expect(html).not.toMatch(/<button[^>]*disabled[^>]*>.*处理完成/);
    expect(html).toContain("取消等待并删除");
  });

  test("login action with a missing tab disables resume", () => {
    const task = archiveTask({
      status: "manual_action_required",
      manual_actions: [
        {
          code: "site.login",
          kind: "login",
          target: "page",
          message: "需要登录",
          resume: "retry_page",
          rule_id: "r2",
          browser_tab_state: "missing",
        },
      ] as unknown as ReturnType<typeof archiveTask>["manual_actions"],
    });
    const html = render(<StatusPanel task={task} actions={makeActions()} />);
    expect(html).toContain("这个网站需要先登录");
    expect(html).toContain("原来的处理页面已经丢失");
    expect(html).toContain("重新打开处理页面");
    expect(html).toMatch(/<button[^>]*disabled=""[^>]*>.*已登录，继续保存/);
  });

  test("not opened tab", () => {
    const task = archiveTask({
      status: "manual_action_required",
      manual_actions: [
        { code: "site.login", kind: "login", target: "page", message: "", resume: "retry_page", rule_id: "r" },
      ] as unknown as ReturnType<typeof archiveTask>["manual_actions"],
    });
    const html = render(<StatusPanel task={task} actions={makeActions()} />);
    expect(html).toContain("处理页面还没打开");
    expect(html).toContain("打开处理页面");
  });

  test("failed shows the error and retry actions", () => {
    const html = render(
      <StatusPanel task={archiveTask({ status: "failed", error: "Timeout while saving", result: null })} actions={makeActions()} />,
    );
    expect(html).toContain("保存失败");
    expect(html).toContain("Timeout while saving");
    expect(html).toContain("手动处理后重试");
    expect(html).toContain("直接重试");
    expect(html).toContain("删除这条记录");
  });

  test("renders nothing for succeeded tasks", () => {
    expect(render(<StatusPanel task={archiveTask()} actions={makeActions()} />)).toBe("");
  });
});

describe("text view", () => {
  test("strips quotes and highlights without injecting HTML", () => {
    expect(cleanSearchQuery(' "reader" ')).toBe("reader");
    expect(cleanSearchQuery("“阅读”")).toBe("阅读");
    const html = renderToStaticMarkup(<p>{highlightText("Reader <b>reads</b> READER", "reader")}</p>);
    expect(html).toBe("<p><mark>Reader</mark> &lt;b&gt;reads&lt;/b&gt; <mark>READER</mark></p>");
    expect(countHitParagraphs(["a reader", "nothing", "Reader again"], "READER")).toBe(2);
  });

  test("shows the hit note and marks", () => {
    const html = render(<TextView task={archiveTask()} searchQuery={'"archive"'} />, (client) =>
      client.setQueryData(["archive-search-text", "task-1"], {
        title: "Saved",
        paragraphs: ["An archive paragraph", "Unrelated", "Archive again"],
        file_name: "reader.html",
      }),
    );
    expect(html).toContain("「archive」在正文中出现在 2 段");
    expect(html).toContain("<mark>archive</mark>");
    expect(html).toContain("<mark>Archive</mark>");
  });

  test("explains missing text", () => {
    const html = render(<TextView task={archiveTask()} />, (client) =>
      client.setQueryData(["archive-search-text", "task-1"], { title: "", paragraphs: [], file_name: null }),
    );
    expect(html).toContain("这篇存档目前没有可阅读的正文");
    expect(html).toContain("扫描版 PDF");
  });
});

describe("details drawer", () => {
  test("turns unsupported-URL video errors into a quiet line", () => {
    const task = archiveTask({
      result: { ...archiveTask().result, video_error: "ERROR: Unsupported URL: https://example.com/articles/reader" },
    });
    expect(isVideoNoise(task.result?.video_error)).toBe(true);
    expect(drawerNotices(task)).toEqual([{ kind: "quiet", text: "此网址不含视频" }]);
    const html = render(<DetailsDrawer task={task} actions={makeActions()} onClose={() => undefined} />);
    expect(html).toContain("此网址不含视频");
    expect(html).not.toContain("rd-notice");
    expect(html).not.toContain("Unsupported URL");
  });

  test("treats Weibo no-format errors as quiet noise", () => {
    const video_error =
      "ERROR: [Weibo] 5012345: No video formats found!; please report this issue on https://github.com/yt-dlp/yt-dlp/issues";
    const task = archiveTask({ result: { ...archiveTask().result, video_error } });
    expect(drawerNotices(task)).toEqual([{ kind: "quiet", text: "此网址不含视频" }]);
  });

  test("shows Weibo JSON parse failures as real video errors", () => {
    const video_error = "ERROR: [Weibo] 5012345: Failed to parse JSON (caused by JSONDecodeError('Expecting value'))";
    const task = archiveTask({ result: { ...archiveTask().result, video_error } });
    const [notice] = drawerNotices(task);
    expect(notice.kind).toBe("warning");
    expect(notice.text).toContain("Failed to parse JSON");
  });

  test("shortens long real video errors", () => {
    const task = archiveTask({
      result: { ...archiveTask().result, video_error: `ERROR: HTTP Error 403: ${"y".repeat(500)}\nTraceback` },
    });
    const [notice] = drawerNotices(task);
    expect(notice.kind).toBe("warning");
    expect(notice.text.startsWith("网页已保存，视频未保存：HTTP Error 403")).toBe(true);
    expect(notice.text.length).toBeLessThan(200);
  });

  test("shows real video and page errors as notices", () => {
    const task = archiveTask({
      result: { ...archiveTask().result, video_error: "HTTP Error 403: Forbidden", page_error: "Page crashed" },
    });
    const notices = drawerNotices(task);
    expect(notices.map((notice) => notice.kind)).toEqual(["warning", "warning"]);
    const html = render(<DetailsDrawer task={task} actions={makeActions()} onClose={() => undefined} />);
    expect(html).toContain("rd-notice");
    expect(html).toContain("HTTP Error 403");
    expect(html).toContain("Page crashed");
  });

  test("lists files, rearchive, and info", () => {
    const task = archiveTask({ is_read: true, custom_title: "Mine" });
    const html = render(<DetailsDrawer task={task} actions={makeActions()} onClose={() => undefined} />, (client) =>
      client.setQueryData(["archive-files", "task-1", taskFileKey(task)], [archiveFile()]),
    );
    expect(html).toContain("Reader saved page.html");
    expect(html).toContain("网页存档");
    expect(html).toContain("重新归档");
    expect(html).toContain("保存前手动处理");
    expect(html).toContain("已手动修改");
    expect(html).toContain("删除这条存档");
  });

  test("hides rearchive while waiting and disables it while running", () => {
    const waiting = render(
      <DetailsDrawer task={archiveTask({ status: "manual_action_required" })} actions={makeActions()} onClose={() => undefined} />,
    );
    expect(waiting).not.toContain("保存前手动处理");
    expect(waiting).toContain("取消等待并删除");
    const running = render(
      <DetailsDrawer task={archiveTask({ status: "running" })} actions={makeActions()} onClose={() => undefined} />,
    );
    expect(running).toMatch(/<button[^>]*disabled=""[^>]*>.*重新归档<\/button>/);
  });
});

describe("tag editor", () => {
  test("renders tags with remove buttons and the input", () => {
    const html = renderToStaticMarkup(
      <TagEditor tags={["research", "读书"]} allTags={[archiveTag("research", 3)]} onChange={() => undefined} />,
    );
    expect(html).toContain("#research");
    expect(html).toContain("#读书");
    expect(html).toContain('aria-label="移除 research"');
    expect(html).toContain('placeholder="+ 标签  T"');
    expect(html).not.toContain("rd-tag-menu");
  });
});

describe("reader popup", () => {
  test("wraps children in the overlay", () => {
    const html = renderToStaticMarkup(
      <ReaderPopup onClose={() => undefined}>
        <span>inside</span>
      </ReaderPopup>,
    );
    expect(html).toContain("rd-pop-layer");
    expect(html).toContain('<div class="rd-pop"><span>inside</span></div>');
  });
});

describe("drawer notices regression", () => {
  test("does not claim the page was saved when no page file exists", () => {
    const task = archiveTask({ result: { file_name: null, download_url: null, view_url: null,
      video_file_name: null, video_download_url: null, video_error: "HTTP Error 403", page_error: null } });
    const texts = drawerNotices(task).map((notice) => notice.text);
    expect(texts).toContain("视频未保存：HTTP Error 403");
    expect(texts.some((text) => text.includes("网页已保存"))).toBe(false);
  });

  test("failed prepared capture does not claim a video was saved", () => {
    const task = archiveTask({ result: { file_name: null, download_url: null, view_url: null,
      video_file_name: null, video_download_url: null, video_error: null, page_error: "capture failed" } });
    const texts = drawerNotices(task).map((notice) => notice.text);
    expect(texts).toContain("网页未保存：capture failed");
    expect(texts.some((text) => text.includes("视频已保存"))).toBe(false);
  });
});
