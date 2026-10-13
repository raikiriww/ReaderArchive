import { describe, expect, mock, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import { LoginPage } from "../src/features/auth/LoginPage";
import {
  ConfirmDialog,
  ConfirmProvider,
  useConfirm,
} from "../src/features/dialogs/ConfirmDialog";
import { FeedsDialog } from "../src/features/dialogs/FeedsDialog";
import {
  isSavableUrl,
  SaveDialog,
} from "../src/features/dialogs/SaveDialog";
import {
  ShortcutHelp,
  shortcutRows,
} from "../src/features/dialogs/ShortcutHelp";
import { SettingsDialog } from "../src/features/settings/SettingsDialog";
import type { AppConfig, RssFeed, User } from "../src/types/domain";
import { archiveTag } from "./fixtures";
import { hostSourceLabel } from "../src/utils/format";

const noop = mock(() => undefined);
const asyncNoop = mock(async () => undefined);

function feed(overrides: Partial<RssFeed> = {}): RssFeed {
  return {
    feed_id: "feed-1",
    url: "https://example.com/feed.xml",
    title: "Example feed",
    enabled: true,
    created_at: "2026-06-01T08:00:00Z",
    updated_at: "2026-06-01T08:00:00Z",
    last_checked_at: null,
    last_error: null,
    ...overrides,
  };
}

function user(overrides: Partial<User> = {}): User {
  return {
    user_id: "user-1",
    username: "alice",
    role: "user",
    enabled: true,
    created_at: "2026-06-01T08:00:00Z",
    updated_at: "2026-06-01T08:00:00Z",
    ...overrides,
  } as User;
}

const config: AppConfig = {
  desktop_url: "http://localhost:3001",
  archive_dir: "/data",
  poll_interval_ms: 3000,
  rss_refresh_interval_seconds: 1800,
  semantic_search: {
    enabled: true,
    available: true,
    status: "ready",
    model_name: "test-embedding-model",
    embedding_dimensions: 384,
    text_version: "v1",
    indexed_count: 12,
    failed_count: 1,
  },
};

function renderSave(initialUrl: string, count = 0): string {
  return renderToStaticMarkup(
    <SaveDialog
      initialUrl={initialUrl}
      existingUrls={() => ({ count, latestAt: "2026-06-21T08:30:00Z" })}
      tags={[archiveTag("research", 3), archiveTag("later")]}
      onSubmit={asyncNoop}
      onClose={noop}
    />,
  );
}

describe("save dialog", () => {
  test("validates http(s) urls", () => {
    expect(isSavableUrl("https://example.com/a")).toBe(true);
    expect(isSavableUrl("  http://example.com  ")).toBe(true);
    expect(isSavableUrl("example.com")).toBe(false);
    expect(isSavableUrl("ftp://example.com")).toBe(false);
    expect(isSavableUrl("https://exa mple.com")).toBe(false);
    expect(isSavableUrl("")).toBe(false);
  });

  test("labels known sources and falls back to the hostname", () => {
    expect(hostSourceLabel("https://weibo.com/123/abc")).toBe("微博");
    expect(hostSourceLabel("https://m.weibo.cn/status/1")).toBe("微博");
    expect(hostSourceLabel("https://mp.weixin.qq.com/s/xyz")).toBe("公众号");
    expect(hostSourceLabel("https://x.com/someone/status/1")).toBe("X");
    expect(hostSourceLabel("https://www.example.com/post")).toBe("example.com");
  });

  test("shows an error for an invalid url and disables submit", () => {
    const html = renderSave("not a url");
    expect(html).toContain("请以 http:// 或 https:// 开头");
    expect(html).toMatch(
      /<button class="dlg-btn dlg-btn-primary" type="submit" disabled=""/,
    );
    expect(html).not.toContain("添加标签（可选）");
  });

  test("shows the source, optional tags, and no duplicate notice for a new url", () => {
    const html = renderSave("https://www.example.com/post");
    expect(html).toContain("example.com");
    expect(html).toContain("添加标签（可选）");
    expect(html).toContain("research");
    expect(html).not.toContain("会另存一个新版本");
    expect(html).not.toContain("dlg-chip-on");
  });

  test("warns that a saved url becomes a new version", () => {
    const html = renderSave("https://www.example.com/post", 2);
    expect(html).toContain("这个网址已保存过 2 次");
    expect(html).toContain("会另存一个新版本");
  });

  test("offers manual preparation with its hint", () => {
    const html = renderSave("");
    expect(html).toContain("保存前手动处理");
    expect(html).toContain("只对这一次保存生效");
    expect(html).toContain("保存网页");
  });
});

describe("confirm dialog", () => {
  test("renders a danger confirmation", () => {
    const html = renderToStaticMarkup(
      <ConfirmDialog
        request={{
          title: "删除存档",
          message: "删除后无法恢复。",
          confirmLabel: "删除",
          danger: true,
        }}
        onDone={noop}
      />,
    );
    expect(html).toContain("删除存档");
    expect(html).toContain("删除后无法恢复。");
    expect(html).toContain("dlg-btn-danger");
    expect(html).toContain(">删除</button>");
    expect(html).not.toContain("<input");
  });

  test("renders an input prompt with a min length hint", () => {
    const html = renderToStaticMarkup(
      <ConfirmDialog
        request={{
          kind: "input",
          title: "重置密码",
          label: "新密码",
          inputType: "password",
          minLength: 8,
        }}
        onDone={noop}
      />,
    );
    expect(html).toContain("新密码");
    expect(html).toContain('type="password"');
    expect(html).toContain("至少 8 位");
    expect(html).toContain("dlg-btn-primary");
    expect(html).toMatch(/type="submit" disabled=""/);
  });

  test("provider exposes ask both as a function and a property", () => {
    let handle: ReturnType<typeof useConfirm> | null = null;
    function Probe(): null {
      handle = useConfirm();
      return null;
    }
    const html = renderToStaticMarkup(
      <ConfirmProvider>
        <Probe />
      </ConfirmProvider>,
    );
    expect(html).toBe("");
    expect(typeof handle).toBe("function");
    expect(typeof (handle as unknown as { ask: unknown }).ask).toBe("function");
  });
});

describe("feeds dialog", () => {
  function render(feeds: RssFeed[]): string {
    return renderToStaticMarkup(
      <FeedsDialog
        feeds={feeds}
        onCreate={asyncNoop}
        onRefresh={asyncNoop}
        onToggle={asyncNoop}
        onDelete={asyncNoop}
        onClose={noop}
      />,
    );
  }

  test("renders an empty state", () => {
    const html = render([]);
    expect(html).toContain("订阅源");
    expect(html).toContain("还没有订阅源");
  });

  test("renders enabled, disabled, and failing feeds", () => {
    const html = render([
      feed({ last_checked_at: "2026-06-21T08:30:00Z" }),
      feed({ feed_id: "feed-2", title: "Paused feed", enabled: false }),
      feed({
        feed_id: "feed-3",
        title: "Broken feed",
        last_error: "HTTP 500\nstack trace",
      }),
    ]);
    expect(html).toContain("Example feed");
    expect(html).toContain("https://example.com/feed.xml");
    expect(html).toContain("启用 · 上次检查");
    expect(html).toContain("尚未检查");
    expect(html).toContain("已停用");
    expect(html).toContain("dlg-feed-row dlg-off");
    expect(html).toContain("HTTP 500");
    expect(html).not.toContain("stack trace");
    expect(html).toContain("立即检查");
    expect(html).toContain('role="switch"');
    expect(html).toContain("删除 Broken feed");
  });
});

describe("shortcut help", () => {
  test("lists every shortcut from the spec", () => {
    const html = renderToStaticMarkup(<ShortcutHelp onClose={noop} />);
    for (const key of [
      "J / K",
      "Enter",
      "⇧ Enter",
      "Esc",
      "E",
      "T",
      "R",
      "V",
      "I",
      "O",
      "N",
      "?",
    ]) {
      expect(html).toContain(`>${key}</kbd>`);
    }
    expect(html).toMatch(/\/ 或 (⌘|Ctrl)K/);
    expect(shortcutRows("⌘").map(([keys]) => keys)).not.toContain("[");
  });
});

describe("settings dialog", () => {
  function render(
    currentUser: User,
    users: User[] = [],
    initialSection?: "system" | "users" | "account",
  ): string {
    return renderToStaticMarkup(
      <SettingsDialog
        open
        initialSection={initialSection}
        config={config}
        currentUser={currentUser}
        users={users}
        onClose={noop}
        onLoadUsers={noop}
        onUpdateConfig={asyncNoop}
        onCreateUser={asyncNoop}
        onToggleUser={noop}
        onResetUserPassword={noop}
        onDeleteUser={noop}
        onChangePassword={asyncNoop}
      />,
    );
  }

  test("admins see system, users, and account sections with the semantic status card", () => {
    const html = render(user({ role: "admin" }));
    expect(html).toContain("系统设置");
    expect(html).toContain("用户管理");
    expect(html).toContain("账户安全");
    expect(html).toContain("dlg-sem-ok");
    expect(html).toContain("可用");
    expect(html).toContain("test-embedding-model");
    expect(html).toContain("刷新间隔（秒）");
    expect(html).toContain('value="3"');
    expect(html).toContain('value="30"');
  });

  test("opens admins on the requested section", () => {
    const html = render(user({ role: "admin" }), [], "account");
    expect(html).toContain("当前密码");
    expect(html).not.toContain("刷新间隔（秒）");
  });

  test("regular users only see account security", () => {
    const html = render(user());
    expect(html).not.toContain("系统设置");
    expect(html).not.toContain("用户管理");
    expect(html).toContain("账户安全");
    expect(html).toContain("当前密码");
    expect(html).toContain("新密码");
  });

  test("renders nothing when closed", () => {
    const html = renderToStaticMarkup(
      <SettingsDialog
        open={false}
        config={config}
        currentUser={user()}
        users={[]}
        onClose={noop}
        onLoadUsers={noop}
        onUpdateConfig={asyncNoop}
        onCreateUser={asyncNoop}
        onToggleUser={noop}
        onResetUserPassword={noop}
        onDeleteUser={noop}
        onChangePassword={asyncNoop}
      />,
    );
    expect(html).toBe("");
  });
});

describe("login page", () => {
  test("renders the restyled login form", () => {
    const html = renderToStaticMarkup(<LoginPage />);
    expect(html).toContain("Reader Archive");
    expect(html).toContain("用户名");
    expect(html).toContain("密码");
    expect(html).toContain("登录");
    expect(html).toContain("current-password");
  });
});
