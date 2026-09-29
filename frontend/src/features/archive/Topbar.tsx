import { useEffect, useState } from "react";
import type { FormEvent, RefObject } from "react";
import { Globe, LogOut, Link, Settings, Search } from "lucide-react";
import type { AppConfig, User } from "../../types/domain";

interface TopbarProps {
  settingsButtonRef: RefObject<HTMLButtonElement | null>;
  config: AppConfig;
  currentUser: User | null;
  draftUrl: string;
  onSubmitUrl: (url: string, prepareManually: boolean) => Promise<void>;
  onOpenSettings: () => void;
  onLogout: () => void;
  onDraftConsumed: () => void;
  onOpenSearch: () => void;
  searchOpen: boolean;
}

export function Topbar({
  settingsButtonRef,
  config,
  currentUser,
  draftUrl,
  onSubmitUrl,
  onOpenSettings,
  onLogout,
  onDraftConsumed,
  onOpenSearch,
  searchOpen,
}: TopbarProps): JSX.Element {
  const [url, setUrl] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [prepareManually, setPrepareManually] = useState(false);

  useEffect(() => {
    if (!draftUrl) return;
    setUrl(draftUrl);
    onDraftConsumed();
  }, [draftUrl, onDraftConsumed]);

  async function submit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    const nextUrl = url.trim();
    if (!nextUrl) return;
    setSubmitting(true);
    try {
      await onSubmitUrl(nextUrl, prepareManually);
      setPrepareManually(false);
      setUrl("");
    } catch {
      // Keep the address available for retry; the caller presents the error.
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <header className="topbar">
      <div className="topbar-brand" role="group" aria-label="Reader Archive">
        <img className="brand-mark" src="/static/favicon.svg" alt="" aria-hidden="true" />
        <span>Reader Archive</span>
      </div>
      <form className="capture-form" autoComplete="off" onSubmit={submit}>
        <label className="visually-hidden" htmlFor="urlInput">
          要存档的 URL
        </label>
        <Link className="capture-icon" size={18} aria-hidden="true" />
        <input
          id="urlInput"
          name="url"
          type="url"
          placeholder="粘贴网页地址，新建存档"
          required
          value={url}
          onChange={(event) => setUrl(event.target.value)}
        />
        <button disabled={submitting} type="submit">
          {submitting ? "提交中" : prepareManually ? "打开并等待处理" : "保存网页"}
        </button>
        <label className="capture-manual-option">
          <input type="checkbox" checked={prepareManually} disabled={submitting} onChange={(event) => setPrepareManually(event.target.checked)} />
          <span>保存前手动处理</span>
          <span className="capture-manual-hint">先关闭弹窗、展开内容，再确认保存</span>
        </label>
      </form>
      <div className="topbar-actions" role="group" aria-label="全局操作">
        <button className={`text-button search-entry ${searchOpen ? "active" : ""}`} type="button" onClick={onOpenSearch}><Search size={16} /><span>搜索存档</span><kbd>⌘ K</kbd></button>
        <a className="text-button" aria-label="打开浏览器" title="打开浏览器" href={config.desktop_url} target="_blank" rel="noreferrer">
          <Globe size={15} />
          <span>打开浏览器</span>
        </a>
        <button ref={settingsButtonRef} aria-label="设置" title="设置" className="text-button" type="button" onClick={onOpenSettings}>
          <Settings size={15} />
          <span>设置</span>
        </button>
      </div>
      <div className="account-strip" role="group" aria-label="当前用户">
        <span>
          {currentUser ? (currentUser.role === "admin" ? `${currentUser.username} · 管理员` : currentUser.username) : "读取用户"}
        </span>
        <button className="text-button" type="button" aria-label="退出登录" onClick={onLogout}>
          <LogOut size={15} />
          <span>退出</span>
        </button>
      </div>
    </header>
  );
}
