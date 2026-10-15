import { describe, expect, mock, test } from "bun:test";
import { QueryClient } from "@tanstack/react-query";
import { createRef } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import {
  extractPastedUrl,
  isSearchChord,
  isTypingTarget,
  readerTabUrl,
  shortcutFor,
  wantsNewTab,
} from "../src/app/keyboard";
import { patchCachedTask } from "../src/app/useArchiveActions";
import { listKey, listOptionsForView } from "../src/app/useArchiveLists";
import { defaultView, readViewState, taskInView, type ViewState, viewHref, viewLabel } from "../src/app/viewState";
import { ATTENTION_GROUP, buildGroups, EmptyList, ListPane, relatedTags } from "../src/features/list/ListPane";
import { dayGroupLabel, Row, shortDate, StatusPill } from "../src/features/list/Row";
import {
  activeFilterCount,
  loadRecentSearches,
  rememberSearch,
  SearchBox,
  SearchFiltersBar,
  SearchResults,
  visibleSearchResults,
} from "../src/features/list/SearchPanel";
import type { SearchMatch, SearchPage, SearchTask } from "../src/features/search/api";
import { searchDefaults } from "../src/features/search/state";
import { Sidebar, unreadBadge } from "../src/features/shell/Sidebar";
import type { ArchiveTask } from "../src/types/domain";
import { archiveTag, archiveTask } from "./fixtures";

const noop = mock(() => undefined);
const now = new Date(2026, 9, 13, 12, 0, 0);
const at = (daysAgo: number, hour = 9) => new Date(2026, 9, 13 - daysAgo, hour, 30).toISOString();

const unreadView: ViewState = defaultView;
const allView: ViewState = { kind: "all", tags: [], source: "all", status: "all" };
const tagView: ViewState = { kind: "tag", tags: ["research"], source: "all", status: "all" };

function listPane(overrides: Partial<Parameters<typeof ListPane>[0]> = {}): string {
  return renderToStaticMarkup(
    <ListPane
      view={unreadView}
      groups={[]}
      total={0}
      related={[]}
      selectedId={null}
      onOpen={noop}
      onViewChange={noop}
      hasMore={false}
      onLoadMore={noop}
      isLoading={false}
      isFetchingMore={false}
      searchBox={<div className="search-wrap" />}
      now={now}
      {...overrides}
    />,
  );
}

describe("list grouping", () => {
  test("labels days as 今天/昨天/本周/本月/更早", () => {
    expect(dayGroupLabel(at(0), now)).toBe("今天");
    expect(dayGroupLabel(at(1), now)).toBe("昨天");
    expect(dayGroupLabel(at(4), now)).toBe("本周");
    expect(dayGroupLabel(at(20), now)).toBe("本月");
    expect(dayGroupLabel(at(90), now)).toBe("更早");
    expect(shortDate(at(1), now)).toBe("昨天");
    expect(shortDate(at(3), now)).toBe("3 天前");
  });

  test("puts the attention group first and groups the rest by day in order", () => {
    const failed = archiveTask({ task_id: "failed", status: "failed", created_at: at(5) });
    const today = archiveTask({ task_id: "today", created_at: at(0) });
    const yesterday = archiveTask({ task_id: "yesterday", created_at: at(1) });
    const older = archiveTask({ task_id: "older", created_at: at(60) });
    const groups = buildGroups([failed], [today, yesterday, older], now);
    expect(groups.map(([label, tasks]) => [label, tasks.map((task) => task.task_id)])).toEqual([
      [ATTENTION_GROUP, ["failed"]],
      ["今天", ["today"]],
      ["昨天", ["yesterday"]],
      ["更早", ["older"]],
    ]);
  });

  test("suggests co-occurring tags for the tag view", () => {
    const items = [
      archiveTask({ task_id: "a", tags: ["research", "ai", "paper"] }),
      archiveTask({ task_id: "b", tags: ["Research", "ai"] }),
    ];
    expect(relatedTags(items, ["research"])).toEqual([
      ["ai", 2],
      ["paper", 1],
    ]);
  });

  test("renders groups with counts, the selected row and a load-more footer", () => {
    const html = listPane({
      groups: buildGroups([], [archiveTask({ task_id: "t1", created_at: at(0) })], now),
      selectedId: "t1",
      total: 1,
      hasMore: true,
    });
    expect(html).toContain("今天<span>1</span>");
    expect(html).toContain('aria-selected="true"');
    expect(html).toContain("加载更多");
    expect(html).toContain("所有还没读的存档");
  });

  test("shows the unread empty state", () => {
    const html = listPane();
    expect(html).toContain("没有未读的存档");
    expect(html).toContain("新保存的网页和新的订阅文章会出现在这里。");
  });

  test("shows other empty states", () => {
    expect(renderToStaticMarkup(<EmptyList view={allView} />)).toContain("这里还没有存档");
    expect(renderToStaticMarkup(<EmptyList view={{ ...allView, status: "problem" }} />)).toContain("没有符合筛选条件的存档");
    expect(renderToStaticMarkup(<EmptyList view={tagView} />)).toContain("没有同时带这些标签的存档");
  });

  test("all view offers source and status filters", () => {
    const html = listPane({ view: { ...allView, status: "problem" }, total: 3 });
    for (const label of ["全部来源", "手动保存", "订阅", "未读", "有问题"]) expect(html).toContain(label);
    expect(html).toContain('aria-pressed="true">有问题');
    expect(html).toContain("3 条");
  });

  test("tag view shows combined tags and related tag chips", () => {
    const html = listPane({ view: { ...tagView, tags: ["research", "ai"] }, related: [["paper", 4]] });
    expect(html).toContain("research + ai");
    expect(html).toContain("移除标签 research");
    expect(html).toContain("再加一个标签：");
    expect(html).toContain("+ paper");
  });

  test("search content replaces header and rows", () => {
    const html = listPane({ searchContent: <p>SEARCHING</p> });
    expect(html).toContain("SEARCHING");
    expect(html).not.toContain("没有未读的存档");
  });
});

describe("row", () => {
  const pill = (task: ArchiveTask) => renderToStaticMarkup(<StatusPill task={task} />);

  test("shows a status pill for every unfinished state", () => {
    expect(pill(archiveTask({ status: "queued" }))).toContain("排队中");
    expect(pill(archiveTask({ status: "running" }))).toContain("保存中");
    expect(pill(archiveTask({ status: "failed" }))).toContain("失败");
    const waiting = archiveTask({
      status: "manual_action_required",
      manual_actions: [
        {
          code: "c1",
          kind: "page.prepare_manually",
          target: "page",
          message: "请处理页面",
          resume: "retry_page",
          rule_id: "r",
          browser_tab_state: "not_opened",
        } as unknown as ArchiveTask["manual_actions"][number],
      ],
    });
    expect(pill(waiting)).toContain("等你处理");
    const lost = { ...waiting, manual_actions: [{ ...waiting.manual_actions[0], browser_tab_state: "missing" }] } as ArchiveTask;
    expect(pill(lost)).toContain("处理页面已丢失");
    expect(pill(archiveTask())).toBe("");
  });

  test("renders unread state, source, tags and search match label", () => {
    const html = renderToStaticMarkup(
      <Row
        task={archiveTask({ tags: ["a", "b", "c", "d"], created_at: at(0, 8) })}
        selected={false}
        onOpen={noop}
        now={now}
        match={{
          excerpt: "hello world",
          score: 1,
          kind: "body",
          highlights: [{ start: 0, end: 5 }],
          strength: "strong",
          version_count: 3,
        }}
      />,
    );
    expect(html).toContain("row  unread");
    expect(html).toContain("正文命中 · 3 个保存版本");
    expect(html).toContain("<mark");
    expect(html).toContain("#c");
    expect(html).not.toContain("#d");
    expect(html).toContain("手动");
    expect(html).not.toContain("row-summary");
  });

  test("shows a cleaned body summary and flags only page failures", () => {
    const base = archiveTask();
    const html = renderToStaticMarkup(
      <Row
        task={archiveTask({
          url: "https://weibo.com/1/abc",
          summary: "公开 26-10-10 13:55 发布于 北京 来自 微博网页版 已编辑 正文内容",
          result: { ...base.result, video_error: "Unsupported URL" },
        } as Partial<ArchiveTask>)}
        selected={false}
        onOpen={noop}
        now={now}
      />,
    );
    expect(html).toContain("row-summary");
    expect(html).toContain(">正文内容<");
    expect(html).not.toContain("发布于");
    expect(html).toContain("手动");
    expect(html).toContain('aria-label="SingleFile：网页已保存"');
    expect(html).not.toContain("yt-dlp");

    const rss = renderToStaticMarkup(
      <Row
        task={archiveTask({ source_type: "rss", source_title: "Feed A", result: { ...base.result, file_name: null, page_error: "boom" } })}
        selected={false}
        onOpen={noop}
        now={now}
      />,
    );
    expect(rss).toContain("Feed A");
    expect(rss).toContain("row-tool failed");
    expect(rss).toContain('aria-label="SingleFile：网页保存失败"');
    expect(rss).not.toContain("row-summary");
  });
});

describe("keyboard", () => {
  test("detects typing targets", () => {
    expect(isTypingTarget({ tagName: "INPUT" } as unknown as Element)).toBe(true);
    expect(isTypingTarget({ tagName: "textarea" } as unknown as Element)).toBe(true);
    expect(isTypingTarget({ tagName: "SELECT" } as unknown as Element)).toBe(true);
    expect(isTypingTarget({ tagName: "DIV", isContentEditable: true } as unknown as Element)).toBe(true);
    expect(isTypingTarget({ tagName: "BUTTON" } as unknown as Element)).toBe(false);
    expect(isTypingTarget(null)).toBe(false);
  });

  test("maps keys to actions and ignores modified keys", () => {
    expect(shortcutFor({ key: "j" })).toBe("next");
    expect(shortcutFor({ key: "K" })).toBe("prev");
    expect(shortcutFor({ key: "Enter" })).toBe("open");
    expect(shortcutFor({ key: "Enter", shiftKey: true })).toBe("openTab");
    expect(shortcutFor({ key: "e" })).toBe("toggleRead");
    expect(shortcutFor({ key: "?" })).toBe("help");
    expect(shortcutFor({ key: "/" })).toBe("search");
    expect(shortcutFor({ key: "n" })).toBe("save");
    expect(shortcutFor({ key: "e", metaKey: true })).toBeNull();
    expect(shortcutFor({ key: "x" })).toBeNull();
    expect(isSearchChord({ key: "k", metaKey: true })).toBe(true);
    expect(isSearchChord({ key: "k", ctrlKey: true })).toBe(true);
    expect(isSearchChord({ key: "k" })).toBe(false);
  });

  test("recognizes pasted http(s) urls only", () => {
    expect(extractPastedUrl("  https://example.com/a?b=1 ")).toBe("https://example.com/a?b=1");
    expect(extractPastedUrl("http://example.com")).toBe("http://example.com");
    expect(extractPastedUrl("ftp://example.com")).toBeNull();
    expect(extractPastedUrl("see https://example.com")).toBeNull();
    expect(extractPastedUrl("https://exa mple.com")).toBeNull();
    expect(extractPastedUrl("")).toBeNull();
  });

  test("builds standalone reader urls and detects new-tab clicks", () => {
    expect(readerTabUrl("t1")).toBe("/?read=t1");
    expect(readerTabUrl("t1", " 苹果 ")).toBe(`/?read=t1&q=${encodeURIComponent("苹果")}`);
    expect(wantsNewTab({ metaKey: true })).toBe(true);
    expect(wantsNewTab({ ctrlKey: true })).toBe(true);
    expect(wantsNewTab({ button: 1 })).toBe(true);
    expect(wantsNewTab({ button: 0 })).toBe(false);
  });
});

describe("view state", () => {
  test("reads and writes the url", () => {
    expect(readViewState("http://x/")).toEqual(defaultView);
    expect(readViewState("http://x/?view=tag&tags=a,b")).toEqual({ ...defaultView, kind: "tag", tags: ["a", "b"] });
    expect(readViewState("http://x/?view=all&source=rss&status=problem")).toEqual({
      ...allView,
      source: "rss",
      status: "problem",
    });
    expect(readViewState("http://x/?view=tag")).toEqual(defaultView);
    const href = viewHref({ ...allView, source: "manual" }, "http://x/?reader_search=%7B%7D");
    expect(href).toContain("view=all");
    expect(href).toContain("source=manual");
    expect(href).toContain("reader_search");
    expect(viewLabel(tagView)).toBe("research");
  });

  test("decides whether a task still belongs to the view", () => {
    const readDone = archiveTask({ is_read: true });
    const readFailed = archiveTask({ is_read: true, status: "failed" });
    expect(taskInView(readDone, unreadView)).toBe(false);
    expect(taskInView(readFailed, unreadView)).toBe(true);
    expect(taskInView(readDone, { ...allView, status: "unread" })).toBe(false);
    expect(taskInView(readFailed, { ...allView, status: "problem" })).toBe(true);
    expect(taskInView(readDone, { ...allView, source: "rss" })).toBe(false);
    expect(taskInView(archiveTask({ tags: ["Research"] }), tagView)).toBe(true);
    expect(taskInView(archiveTask({ tags: [] }), tagView)).toBe(false);
  });

  test("maps views to list queries", () => {
    expect(listOptionsForView(unreadView)).toMatchObject({ includeRead: false, status: "succeeded" });
    expect(listOptionsForView({ ...allView, status: "problem", source: "rss" })).toMatchObject({
      includeRead: true,
      status: "problem",
      source: "rss",
    });
    expect(listOptionsForView({ ...allView, status: "unread" })).toMatchObject({ includeRead: false });
    expect(listOptionsForView(tagView)).toMatchObject({ tags: ["research"], tagsMatch: "all" });
    expect(listKey(tagView)[0]).toBe("archive-list");
  });

  test("patches a task inside cached infinite lists", () => {
    const client = new QueryClient();
    client.setQueryData(["archive-list", "unread", {}], {
      pages: [{ items: [archiveTask({ task_id: "a" }), archiveTask({ task_id: "b" })] }],
      pageParams: [0],
    });
    patchCachedTask(client, "b", { is_read: true });
    const data = client.getQueryData<{ pages: Array<{ items: ArchiveTask[] }> }>(["archive-list", "unread", {}]);
    expect(data?.pages[0].items.map((task) => task.is_read)).toEqual([false, true]);
  });
});

describe("sidebar", () => {
  const render = (counts = { unread: 5, attention: 2, problems: 1 }, tagCount = 12) =>
    renderToStaticMarkup(
      <Sidebar
        view={unreadView}
        onView={noop}
        counts={counts}
        tags={Array.from({ length: tagCount }, (_, index) => archiveTag(`tag${index}`, 100 - index))}
        user={{ username: "alice", role: "admin" }}
        onSave={noop}
        onSearch={noop}
        onManageFeeds={noop}
        onBrowser={noop}
        onSettings={noop}
        onLogout={noop}
      />,
    );

  test("shows unread count in orange when problems exist", () => {
    expect(unreadBadge({ unread: 5, attention: 2, problems: 1 })).toEqual({ count: 7, alert: true });
    const html = render();
    expect(html).toContain('nav-count alert"');
    expect(html).toContain(">7</span>");
    const calm = render({ unread: 3, attention: 1, problems: 0 });
    expect(calm).not.toContain("nav-count alert");
    expect(calm).toContain(">4</span>");
  });

  test("renders the nav entries, top 10 tags with expand, and footer", () => {
    const html = render();
    for (const label of ["保存网页", "搜索", "未读", "全部存档", "订阅源", "内置浏览器", "设置", "alice"]) {
      expect(html).toContain(label);
    }
    expect(html).toContain("tag9");
    expect(html).not.toContain("tag10<");
    expect(html).toContain("全部 12 个标签");
    expect(render(undefined, 0)).toContain("还没有标签");
  });
});

describe("search panel", () => {
  const result = (id: string, strength: "strong" | "possible", kind: SearchMatch["kind"] = "body"): SearchTask => ({
    ...archiveTask({ task_id: id, display_title: `Title ${id}` }),
    search_match: { excerpt: `excerpt ${id}`, score: 1, kind, highlights: [], strength },
  });

  test("keeps leading semantic answers and collapses later possible matches", () => {
    const items = [result("lead", "possible", "semantic"), result("direct", "strong"), result("later", "possible", "semantic")];
    expect(visibleSearchResults(items, false).map((item) => item.task_id)).toEqual(["lead", "direct"]);
    expect(visibleSearchResults(items, true)).toHaveLength(3);
    const html = renderToStaticMarkup(
      <SearchResults
        query="apple"
        items={items}
        selectedId="direct"
        onOpen={noop}
        showPossible={false}
        onShowPossible={noop}
        isLoading={false}
        error={null}
        hasMore={false}
        onLoadMore={noop}
        now={now}
      />,
    );
    expect(html).toContain("Title lead");
    expect(html).not.toContain("Title later");
    expect(html).toContain("展开其余 1 条意思可能相关的结果");
    expect(html).toContain("意思可能相关");
    expect(html).toContain("正文命中");
  });

  test("renders the empty search state", () => {
    const html = renderToStaticMarkup(
      <SearchResults
        query={'"apple pie"'}
        items={[]}
        selectedId={null}
        onOpen={noop}
        showPossible={false}
        onShowPossible={noop}
        isLoading={false}
        error={null}
        hasMore={false}
        onLoadMore={noop}
      />,
    );
    expect(html).toContain("没有找到「apple pie」");
  });

  test("shows filters, counts and index coverage", () => {
    const page: SearchPage = {
      items: [],
      total: 9,
      limit: 20,
      offset: 0,
      has_more: false,
      mode: "hybrid",
      coverage: { total: 20, ready: 10, pending: 4, unavailable: 2 },
      total_is_exact: true,
    };
    const html = renderToStaticMarkup(
      <SearchFiltersBar
        query="apple"
        filters={{ ...searchDefaults, source: "rss" }}
        onFilters={noop}
        tags={[archiveTag("ai")]}
        page={page}
        resultCount={9}
        possibleCount={2}
      />,
    );
    expect(html).toContain("结合关键词和内容大意查找。");
    expect(html).toContain("共 9 条，其中 2 条只是意思可能相关");
    expect(html).toContain("4 篇正文正在准备");
    expect(html).toContain("2 篇暂无可搜索正文");
    expect(html).toContain("筛选 1");
    const keyword = renderToStaticMarkup(
      <SearchFiltersBar
        query="apple"
        filters={searchDefaults}
        onFilters={noop}
        tags={[]}
        page={{ ...page, mode: "keyword", coverage: { total: 0, ready: 0, pending: 0, unavailable: 0 } }}
        resultCount={9}
        possibleCount={0}
      />,
    );
    expect(keyword).toContain("按大意查找暂不可用");
    expect(keyword).not.toContain("正在准备");
    expect(activeFilterCount({ ...searchDefaults, include_read: false, exact: true, tags: ["a"] })).toBe(3);
  });

  test("renders the search box and remembers recent searches", () => {
    const html = renderToStaticMarkup(
      <SearchBox inputRef={createRef()} query="" onQuery={noop} onCommit={noop} recent={["a"]} onClearRecent={noop} />,
    );
    expect(html).toContain("搜索标题、正文、标签，或描述大意");
    expect(html).toContain("⌘K");
    expect(rememberSearch(["b", "a"], " a ")).toEqual(["a", "b"]);
    expect(rememberSearch(["1", "2", "3", "4", "5", "6"], "7")).toHaveLength(6);
    expect(loadRecentSearches({ getItem: () => '["x", 1]' })).toEqual(["x"]);
    expect(loadRecentSearches({ getItem: () => "oops" })).toEqual([]);
  });
});
