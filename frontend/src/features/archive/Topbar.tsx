import { useEffect, useState } from "react";
import type { FormEvent, RefObject } from "react";
import { Globe, LogOut, Link, Settings } from "lucide-react";
import type { AppConfig, User } from "../../types/domain";

interface TopbarProps {
  settingsButtonRef: RefObject<HTMLButtonElement | null>;
  config: AppConfig;
  currentUser: User | null;
  draftUrl: string;
  onSubmitUrl: (url: string) => Promise<void>;
  onOpenSettings: () => void;
  onLogout: () => void;
  onDraftConsumed: () => void;
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
}: TopbarProps): JSX.Element {
  const [url, setUrl] = useState("");
  const [submitting, setSubmitting] = useState(false);

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
      await onSubmitUrl(nextUrl);
      setUrl("");
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
          {submitting ? "保存中" : "保存网页"}
        </button>
      </form>
      <div className="topbar-actions" role="group" aria-label="全局操作">
        <a className="text-button" href={config.desktop_url} target="_blank" rel="noreferrer">
          <Globe size={15} />
          打开浏览器
        </a>
        <button ref={settingsButtonRef} className="text-button" type="button" onClick={onOpenSettings}>
          <Settings size={15} />
          设置
        </button>
      </div>
      <div className="account-strip" role="group" aria-label="当前用户">
        <span>
          {currentUser ? (currentUser.role === "admin" ? `${currentUser.username} · 管理员` : currentUser.username) : "读取用户"}
        </span>
        <button className="text-button" type="button" onClick={onLogout}>
          <LogOut size={15} />
          退出
        </button>
      </div>
    </header>
  );
}
