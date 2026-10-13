import { Archive, ExternalLink, Globe, Hash, Inbox, KeyRound, LogOut, Plus, Rss, Search, Settings } from "lucide-react";
import { useState } from "react";
import type { ArchiveCounts } from "../../app/useArchiveLists";
import type { ViewState } from "../../app/viewState";
import { usePopover } from "../../components/Popover";
import type { ArchiveTag, User } from "../../types/domain";

export const SIDEBAR_TAG_LIMIT = 10;

export type SettingsSection = "system" | "account";

export interface SidebarProps {
  view: ViewState;
  onView(view: ViewState): void;
  counts: ArchiveCounts;
  tags: ArchiveTag[];
  user: Pick<User, "username" | "role"> | null;
  /** Platform modifier label, e.g. ⌘ or Ctrl. */
  modKey?: string;
  onSave(): void;
  onSearch(): void;
  onManageFeeds(): void;
  onBrowser(): void;
  onSettings(section: SettingsSection): void;
  onLogout(): void;
}

/** Unread badge: unread archives plus everything that needs attention. */
export function unreadBadge(counts: ArchiveCounts): { count: number; alert: boolean } {
  return { count: counts.unread + counts.attention, alert: counts.problems > 0 };
}

export function Sidebar({
  view,
  onView,
  counts,
  tags,
  user,
  modKey = "⌘",
  onSave,
  onSearch,
  onManageFeeds,
  onBrowser,
  onSettings,
  onLogout,
}: SidebarProps): JSX.Element {
  const [tagFilter, setTagFilter] = useState("");
  const [allTags, setAllTags] = useState(false);
  const popover = usePopover<"user">();
  const badge = unreadBadge(counts);
  const needle = tagFilter.trim().toLowerCase();
  const sortedTags = [...tags].sort((a, b) => b.task_count - a.task_count || a.name.localeCompare(b.name));
  const shown = needle ? sortedTags.filter((tag) => tag.name.toLowerCase().includes(needle)) : sortedTags;
  const limited = allTags || needle ? shown : shown.slice(0, SIDEBAR_TAG_LIMIT);
  const activeTag = view.kind === "tag" && view.tags.length === 1 ? view.tags[0].toLowerCase() : null;
  const name = user?.username ?? "";

  const go = (next: Partial<ViewState> & Pick<ViewState, "kind">) =>
    onView({ kind: next.kind, tags: next.tags ?? [], source: "all", status: "all" });

  return (
    <aside className="sidebar" aria-label="导航">
      <div className="brand-row">
        <img src="/static/favicon.svg" alt="" className="brand-mark" />
        <span className="brand-name">Reader Archive</span>
      </div>

      <div className="sidebar-actions">
        <button className="save-btn" type="button" onClick={onSave}>
          <Plus size={16} strokeWidth={2.2} aria-hidden="true" />
          <span className="nav-label">保存网页</span>
          <kbd className="kbd">N</kbd>
        </button>
        <button className="search-btn" type="button" onClick={onSearch}>
          <Search size={15} aria-hidden="true" />
          <span className="nav-label">搜索</span>
          <kbd className="kbd">{modKey}K</kbd>
        </button>
      </div>

      <nav className="nav-group" aria-label="视图">
        <button
          type="button"
          className={`nav-item ${view.kind === "unread" ? "active" : ""}`}
          aria-current={view.kind === "unread" ? "page" : undefined}
          onClick={() => go({ kind: "unread" })}
        >
          <Inbox size={16} aria-hidden="true" />
          <span className="nav-label">未读</span>
          {badge.count ? (
            <span className={`nav-count ${badge.alert ? "alert" : ""}`} title={badge.alert ? "有失败或等待处理的任务" : undefined}>
              {badge.count}
            </span>
          ) : null}
        </button>
        <button
          type="button"
          className={`nav-item ${view.kind === "all" ? "active" : ""}`}
          aria-current={view.kind === "all" ? "page" : undefined}
          onClick={() => go({ kind: "all" })}
        >
          <Archive size={16} aria-hidden="true" />
          <span className="nav-label">全部存档</span>
        </button>
      </nav>

      <div className="nav-section tags-section">
        <div className="nav-section-head">
          <span>标签</span>
        </div>
        <input
          className="tag-filter"
          placeholder="筛选标签"
          aria-label="筛选标签"
          value={tagFilter}
          onChange={(event) => setTagFilter(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && shown[0]) go({ kind: "tag", tags: [shown[0].name] });
            if (event.key === "Escape" && tagFilter) {
              event.stopPropagation();
              setTagFilter("");
            }
          }}
        />
        <div className="tag-nav">
          {limited.map((tag) => (
            <button
              key={tag.name}
              type="button"
              className={`nav-item tag-item ${activeTag === tag.name.toLowerCase() ? "active" : ""}`}
              onClick={() => go({ kind: "tag", tags: [tag.name] })}
            >
              <Hash size={14} aria-hidden="true" />
              <span className="nav-label">{tag.name}</span>
              <span className="nav-count quiet">{tag.task_count}</span>
            </button>
          ))}
          {shown.length === 0 ? <p className="nav-empty">{tags.length ? "没有匹配的标签" : "还没有标签"}</p> : null}
        </div>
        {!needle && shown.length > SIDEBAR_TAG_LIMIT ? (
          <button className="nav-more" type="button" onClick={() => setAllTags((value) => !value)}>
            {allTags ? "收起" : `全部 ${shown.length} 个标签`}
          </button>
        ) : null}
      </div>

      <div className="sidebar-foot">
        <button className="nav-item" type="button" onClick={onManageFeeds}>
          <Rss size={16} aria-hidden="true" />
          <span className="nav-label">订阅源</span>
        </button>
        <button className="nav-item" type="button" onClick={onBrowser}>
          <Globe size={16} aria-hidden="true" />
          <span className="nav-label">内置浏览器</span>
          <ExternalLink size={12} className="foot-ext" aria-hidden="true" />
        </button>
        <button className="nav-item" type="button" onClick={() => onSettings("system")}>
          <Settings size={16} aria-hidden="true" />
          <span className="nav-label">设置</span>
        </button>
        <div className="pop-anchor" ref={popover.anchorRef}>
          <button
            className="nav-item user-btn"
            type="button"
            aria-haspopup="menu"
            aria-expanded={popover.open === "user"}
            onClick={() => popover.toggle("user")}
          >
            <span className="avatar">{name.slice(0, 1).toUpperCase() || "?"}</span>
            <span className="nav-label">{name || "未登录"}</span>
          </button>
          {popover.open === "user" ? (
            <div className="flyout up" role="menu">
              <div className="flyout-user">
                <strong>{name}</strong>
                <span>{user?.role === "admin" ? "管理员" : "普通用户"}</span>
              </div>
              <button
                type="button"
                role="menuitem"
                className="menu-row"
                onClick={() => {
                  popover.setOpen(null);
                  onSettings("account");
                }}
              >
                <KeyRound size={14} aria-hidden="true" />
                修改密码
              </button>
              <button
                type="button"
                role="menuitem"
                className="menu-row"
                onClick={() => {
                  popover.setOpen(null);
                  onLogout();
                }}
              >
                <LogOut size={14} aria-hidden="true" />
                退出登录
              </button>
            </div>
          ) : null}
        </div>
      </div>
    </aside>
  );
}
