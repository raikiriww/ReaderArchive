import { describe, expect, mock, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import { DetailPanel } from "../src/features/archive/DetailPanel";
import { filterTasks, TaskList } from "../src/features/archive/TaskList";
import { LoginPage } from "../src/features/auth/LoginPage";
import { archiveFile, archiveTag, archiveTask } from "./fixtures";

const noop = mock(() => undefined);
const asyncNoop = mock(async () => undefined);

describe("archive task list", () => {
  test("filters tasks by the active view", () => {
    const unread = archiveTask({ task_id: "unread", is_read: false });
    const read = archiveTask({ task_id: "read", is_read: true });
    const running = archiveTask({ task_id: "running", status: "running" });
    const failed = archiveTask({ task_id: "failed", status: "failed" });

    expect(filterTasks([unread, read, running, failed], "unread").map((task) => task.task_id)).toEqual([
      "unread",
      "running",
      "failed",
    ]);
    expect(filterTasks([unread, read, running, failed], "all")).toHaveLength(4);
    expect(filterTasks([unread, read, running, failed], "running")).toEqual([running]);
    expect(filterTasks([unread, read, running, failed], "failed")).toEqual([failed]);
  });

  test("renders selected tasks, search matches, tags, and the RSS action", () => {
    const html = renderToStaticMarkup(
      <TaskList
        tasks={[
          archiveTask({
            task_id: "task-a",
            tags: ["research"],
            search_match: { excerpt: "matching archive excerpt", score: 0.92 },
          }),
        ]}
        total={1}
        selectedTaskId="task-a"
        taskFilter="all"
        searchQuery="archive"
        tags={[archiveTag("research", 3)]}
        tagFilters={["research"]}
        tagMenuOpen={true}
        limit={50}
        offset={0}
        hasMore={false}
        onPreviousPage={noop}
        onNextPage={noop}
        onJumpToPage={noop}
        onSelectTask={noop}
        onSetFilter={noop}
        onSearchQueryChange={noop}
        onToggleTagMenu={noop}
        onToggleTag={noop}
        onClearTags={noop}
        onOpenRss={noop}
      />,
    );

    expect(html).toContain("Reader article");
    expect(html).toContain("matching archive excerpt");
    expect(html).toContain("research");
    expect(html).toContain("订阅源");
    expect(html).toContain("aria-pressed=\"true\"");
  });

  test("shows the searched empty state", () => {
    const html = renderToStaticMarkup(
      <TaskList
        tasks={[]}
        total={0}
        selectedTaskId={null}
        taskFilter="all"
        searchQuery="missing"
        tags={[]}
        tagFilters={[]}
        tagMenuOpen={false}
        limit={50}
        offset={0}
        hasMore={false}
        onPreviousPage={noop}
        onNextPage={noop}
        onJumpToPage={noop}
        onSelectTask={noop}
        onSetFilter={noop}
        onSearchQueryChange={noop}
        onToggleTagMenu={noop}
        onToggleTag={noop}
        onClearTags={noop}
        onOpenRss={noop}
      />,
    );

    expect(html).toContain("没有匹配的存档记录");
  });

  test("renders compact pagination when records exceed one page", () => {
    const html = renderToStaticMarkup(
      <TaskList
        tasks={Array.from({ length: 50 }, (_, index) => archiveTask({ task_id: `task-page-2-${index}` }))}
        total={137}
        selectedTaskId={null}
        taskFilter="all"
        searchQuery=""
        tags={[]}
        tagFilters={[]}
        tagMenuOpen={false}
        limit={50}
        offset={50}
        hasMore={true}
        onPreviousPage={noop}
        onNextPage={noop}
        onJumpToPage={noop}
        onSelectTask={noop}
        onSetFilter={noop}
        onSearchQueryChange={noop}
        onToggleTagMenu={noop}
        onToggleTag={noop}
        onClearTags={noop}
        onOpenRss={noop}
      />,
    );

    expect(html).toContain("51-100 / 共 137 条");
    expect(html).toContain("第 2 / 3 页");
    expect(html).toContain("跳至");
    expect(html).toContain("跳转");
    expect(html).toContain("上一页");
    expect(html).toContain("下一页");
  });
});

describe("archive detail panel", () => {
  test("renders an empty state when no task is selected", () => {
    const html = renderDetail(null);

    expect(html).toContain("选择一条存档记录");
  });

  test("renders task actions, files, tags, and login-required controls", () => {
    const html = renderDetail(
      archiveTask({
        status: "browser_login_required",
        current_step: "browser_login",
        tags: ["video"],
        result: {
          file_name: "reader.html",
          download_url: "/download",
          view_url: "/view",
          video_file_name: null,
          video_download_url: null,
          video_error: "needs login",
          page_error: null,
        },
      }),
    );

    expect(html).toContain("Reader article");
    expect(html).toContain("标记已读");
    expect(html).toContain("打开浏览器");
    expect(html).toContain("继续下载");
    expect(html).toContain("Reader saved page.html");
    expect(html).toContain("video");
    expect(html).toContain("打开浏览器完成登录后，再继续下载。");
  });
});

describe("login page", () => {
  test("renders the login form", () => {
    const html = renderToStaticMarkup(<LoginPage />);

    expect(html).toContain("Reader Archive");
    expect(html).toContain("用户名");
    expect(html).toContain("密码");
    expect(html).toContain("登录");
  });
});

function renderDetail(task: Parameters<typeof DetailPanel>[0]["task"]): string {
  return renderToStaticMarkup(
    <DetailPanel
      task={task}
      files={task ? [archiveFile()] : []}
      tags={[archiveTag("video"), archiveTag("later")]}
      onClearSelection={noop}
      onRefreshFiles={noop}
      onUploadFile={noop}
      onDeleteTask={noop}
      onContinueVideo={noop}
      onOpenBrowser={noop}
      onMarkRead={noop}
      onRearchiveTask={noop}
      onRenameTask={asyncNoop}
      onUpdateTags={noop}
      onRenameFile={asyncNoop}
      onDeleteFile={noop}
    />,
  );
}
