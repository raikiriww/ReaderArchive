import { type FormEvent, type KeyboardEvent, useEffect, useMemo, useRef, useState } from "react";
import { Shield, SlidersHorizontal, Users, X } from "lucide-react";
import type { AppConfig, User } from "../../types/domain";

type SettingsSection = "system" | "users" | "account";

interface SettingsDialogProps {
  open: boolean;
  config: AppConfig;
  currentUser: User | null;
  users: User[];
  onClose: () => void;
  onLoadUsers: () => void;
  onUpdateConfig: (payload: { poll_interval_ms: number; rss_refresh_interval_seconds: number }) => Promise<void>;
  onCreateUser: (payload: { username: string; password: string; role: string }) => Promise<void>;
  onToggleUser: (userId: string, enabled: boolean) => void;
  onResetUserPassword: (userId: string) => void;
  onDeleteUser: (userId: string, username: string) => void;
  onChangePassword: (payload: { current_password: string; new_password: string }) => Promise<void>;
}

export function SettingsDialog({
  open,
  config,
  currentUser,
  users,
  onClose,
  onLoadUsers,
  onUpdateConfig,
  onCreateUser,
  onToggleUser,
  onResetUserPassword,
  onDeleteUser,
  onChangePassword,
}: SettingsDialogProps): JSX.Element | null {
  const closeButtonRef = useRef<HTMLButtonElement | null>(null);
  const isAdmin = currentUser?.role === "admin";
  const [activeSection, setActiveSection] = useState<SettingsSection>("system");
  const [systemDraft, setSystemDraft] = useState({
    pollSeconds: secondsFromMs(config.poll_interval_ms),
    rssMinutes: minutesFromSeconds(config.rss_refresh_interval_seconds),
  });
  const [newUser, setNewUser] = useState({ username: "", password: "", role: "user" });
  const [passwords, setPasswords] = useState({ current_password: "", new_password: "" });
  const [savingSystem, setSavingSystem] = useState(false);
  const [creating, setCreating] = useState(false);
  const [changing, setChanging] = useState(false);

  const sections = useMemo(
    () => [
      ...(isAdmin
        ? [
            { id: "system" as const, label: "系统设置", icon: SlidersHorizontal },
            { id: "users" as const, label: "用户管理", icon: Users },
          ]
        : []),
      { id: "account" as const, label: "账户安全", icon: Shield },
    ],
    [isAdmin],
  );

  useEffect(() => {
    if (!open) return;
    closeButtonRef.current?.focus();
    setActiveSection((section) => {
      if (isAdmin) return section;
      return "account";
    });
  }, [isAdmin, open]);

  useEffect(() => {
    if (!open) return;
    setSystemDraft({
      pollSeconds: secondsFromMs(config.poll_interval_ms),
      rssMinutes: minutesFromSeconds(config.rss_refresh_interval_seconds),
    });
  }, [config.poll_interval_ms, config.rss_refresh_interval_seconds, open]);

  if (!open) return null;

  function keyDown(event: KeyboardEvent<HTMLElement>): void {
    if (event.key === "Escape") onClose();
  }

  function selectSection(section: SettingsSection): void {
    setActiveSection(section);
    if (section === "users") onLoadUsers();
  }

  async function saveSystem(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    setSavingSystem(true);
    try {
      await onUpdateConfig({
        poll_interval_ms: Math.max(1, systemDraft.pollSeconds) * 1000,
        rss_refresh_interval_seconds: Math.max(1, systemDraft.rssMinutes) * 60,
      });
    } finally {
      setSavingSystem(false);
    }
  }

  async function createUser(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    setCreating(true);
    try {
      await onCreateUser(newUser);
      setNewUser({ username: "", password: "", role: "user" });
    } finally {
      setCreating(false);
    }
  }

  async function changePassword(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    setChanging(true);
    try {
      await onChangePassword(passwords);
      setPasswords({ current_password: "", new_password: "" });
    } finally {
      setChanging(false);
    }
  }

  return (
    <div className="modal-backdrop settings-backdrop" role="presentation">
      <section className="settings-dialog" role="dialog" aria-modal="true" aria-labelledby="settingsTitle" onKeyDown={keyDown}>
        <header className="settings-top">
          <div>
            <h2 id="settingsTitle">设置</h2>
            <p>{activeLabel(activeSection)}</p>
          </div>
          <button ref={closeButtonRef} className="icon-button" type="button" aria-label="关闭" onClick={onClose}>
            <X size={18} />
          </button>
        </header>

        <div className="settings-layout">
          <nav className="settings-nav" aria-label="设置分类">
            {sections.map((section) => {
              const Icon = section.icon;
              return (
                <button
                  key={section.id}
                  className={activeSection === section.id ? "active" : ""}
                  type="button"
                  onClick={() => selectSection(section.id)}
                >
                  <Icon size={17} />
                  {section.label}
                </button>
              );
            })}
          </nav>

          <div className="settings-content">
            {activeSection === "system" ? (
              <section className="settings-panel" aria-labelledby="systemSettingsTitle">
                <div className="settings-panel-title">
                  <h3 id="systemSettingsTitle">系统设置</h3>
                </div>
                <div className="semantic-status">
                  <div>
                    <span>语义检索</span>
                    <strong>{semanticStatusLabel(config.semantic_search?.status)}</strong>
                  </div>
                  <dl>
                    <div>
                      <dt>模型</dt>
                      <dd>{config.semantic_search?.model_name ?? "未启用"}</dd>
                    </div>
                    <div>
                      <dt>维度</dt>
                      <dd>{config.semantic_search?.embedding_dimensions ?? "-"}</dd>
                    </div>
                    <div>
                      <dt>已处理</dt>
                      <dd>{config.semantic_search?.indexed_count ?? 0}</dd>
                    </div>
                    <div>
                      <dt>失败</dt>
                      <dd>{config.semantic_search?.failed_count ?? 0}</dd>
                    </div>
                  </dl>
                  {config.semantic_search?.last_error ? (
                    <p className="semantic-error">{config.semantic_search.last_error}</p>
                  ) : null}
                </div>
                <form className="settings-form settings-form-card" onSubmit={saveSystem}>
                  <label htmlFor="pollIntervalSeconds">
                    刷新间隔（秒）
                    <input
                      id="pollIntervalSeconds"
                      name="poll-interval-seconds"
                      inputMode="numeric"
                      min={1}
                      max={3600}
                      required
                      type="number"
                      value={systemDraft.pollSeconds}
                      onChange={(event) =>
                        setSystemDraft((value) => ({ ...value, pollSeconds: numberValue(event.target.value) }))
                      }
                    />
                  </label>
                  <label htmlFor="rssIntervalMinutes">
                    RSS 检查间隔（分钟）
                    <input
                      id="rssIntervalMinutes"
                      name="rss-interval-minutes"
                      inputMode="numeric"
                      min={1}
                      max={1440}
                      required
                      type="number"
                      value={systemDraft.rssMinutes}
                      onChange={(event) =>
                        setSystemDraft((value) => ({ ...value, rssMinutes: numberValue(event.target.value) }))
                      }
                    />
                  </label>
                  <div className="settings-actions">
                    <button disabled={savingSystem} type="submit">
                      {savingSystem ? "保存中" : "保存设置"}
                    </button>
                  </div>
                </form>
              </section>
            ) : null}

            {activeSection === "users" && isAdmin ? (
              <section className="settings-panel" aria-labelledby="userSettingsTitle">
                <div className="settings-panel-title">
                  <h3 id="userSettingsTitle">用户管理</h3>
                  <button className="text-button" type="button" onClick={onLoadUsers}>
                    刷新
                  </button>
                </div>
                <form className="settings-form user-create-form" onSubmit={createUser}>
                  <label htmlFor="newUserUsername">
                    用户名
                    <input
                      id="newUserUsername"
                      name="username"
                      autoComplete="off"
                      required
                      value={newUser.username}
                      onChange={(event) => setNewUser((value) => ({ ...value, username: event.target.value }))}
                    />
                  </label>
                  <label htmlFor="newUserPassword">
                    初始密码
                    <input
                      id="newUserPassword"
                      name="new-password"
                      autoComplete="new-password"
                      minLength={8}
                      required
                      type="password"
                      value={newUser.password}
                      onChange={(event) => setNewUser((value) => ({ ...value, password: event.target.value }))}
                    />
                  </label>
                  <label htmlFor="newUserRole">
                    角色
                    <select
                      id="newUserRole"
                      name="role"
                      value={newUser.role}
                      onChange={(event) => setNewUser((value) => ({ ...value, role: event.target.value }))}
                    >
                      <option value="user">普通用户</option>
                      <option value="admin">管理员</option>
                    </select>
                  </label>
                  <button disabled={creating} type="submit">
                    {creating ? "添加中" : "添加用户"}
                  </button>
                </form>
                <div className="user-list">
                  {users.length === 0 ? (
                    <div className="empty-state compact">还没有用户</div>
                  ) : (
                    users.map((user) => (
                      <article className="user-item" key={user.user_id}>
                        <div className="user-main">
                          <span className="user-name">{user.username}</span>
                          <span className="user-meta">
                            {user.role === "admin" ? "管理员" : "普通用户"} · {user.enabled ? "启用" : "停用"}
                          </span>
                        </div>
                        <div className="user-actions">
                          <button type="button" onClick={() => onToggleUser(user.user_id, !user.enabled)}>
                            {user.enabled ? "停用" : "启用"}
                          </button>
                          <button type="button" onClick={() => onResetUserPassword(user.user_id)}>
                            重置密码
                          </button>
                          <button className="danger-action" type="button" onClick={() => onDeleteUser(user.user_id, user.username)}>
                            删除
                          </button>
                        </div>
                      </article>
                    ))
                  )}
                </div>
              </section>
            ) : null}

            {activeSection === "account" ? (
              <section className="settings-panel" aria-labelledby="accountSettingsTitle">
                <div className="settings-panel-title">
                  <h3 id="accountSettingsTitle">账户安全</h3>
                </div>
                <form className="settings-form settings-form-card" onSubmit={changePassword}>
                  <input
                    className="visually-hidden"
                    tabIndex={-1}
                    autoComplete="username"
                    name="username"
                    value={currentUser?.username || ""}
                    readOnly
                    aria-hidden="true"
                  />
                  <label htmlFor="currentPassword">
                    当前密码
                    <input
                      id="currentPassword"
                      name="current-password"
                      autoComplete="current-password"
                      required
                      type="password"
                      value={passwords.current_password}
                      onChange={(event) => setPasswords((value) => ({ ...value, current_password: event.target.value }))}
                    />
                  </label>
                  <label htmlFor="newPassword">
                    新密码
                    <input
                      id="newPassword"
                      name="new-password"
                      autoComplete="new-password"
                      minLength={8}
                      required
                      type="password"
                      value={passwords.new_password}
                      onChange={(event) => setPasswords((value) => ({ ...value, new_password: event.target.value }))}
                    />
                  </label>
                  <div className="settings-actions">
                    <button disabled={changing} type="submit">
                      {changing ? "保存中" : "保存密码"}
                    </button>
                  </div>
                </form>
              </section>
            ) : null}
          </div>
        </div>
      </section>
    </div>
  );
}

function secondsFromMs(value: number): number {
  return Math.max(1, Math.round(value / 1000));
}

function minutesFromSeconds(value: number): number {
  return Math.max(1, Math.round(value / 60));
}

function numberValue(value: string): number {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return 1;
  return Math.max(1, Math.round(parsed));
}

function activeLabel(section: SettingsSection): string {
  if (section === "users") return "用户管理";
  if (section === "account") return "账户安全";
  return "系统设置";
}

function semanticStatusLabel(status: string | undefined): string {
  switch (status) {
    case "ready":
      return "可用";
    case "indexing":
      return "处理中";
    case "degraded":
      return "部分可用";
    case "unavailable":
      return "不可用";
    case "disabled":
      return "已关闭";
    default:
      return "未知";
  }
}
