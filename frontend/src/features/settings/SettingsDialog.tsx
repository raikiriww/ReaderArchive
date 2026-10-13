import { type FormEvent, useEffect, useMemo, useRef, useState } from "react";
import { RefreshCw, Shield, SlidersHorizontal, Users, X } from "lucide-react";
import type { AppConfig, User } from "../../types/domain";
import { DialogOverlay } from "../dialogs/ConfirmDialog";

export type SettingsSection = "system" | "users" | "account";

interface SettingsDialogProps {
  open: boolean;
  /** Section to show when the dialog opens; non-admins always land on account. */
  initialSection?: SettingsSection;
  config: AppConfig;
  currentUser: User | null;
  users: User[];
  onClose: () => void;
  onLoadUsers: () => void;
  onUpdateConfig: (payload: {
    poll_interval_ms: number;
    rss_refresh_interval_seconds: number;
  }) => Promise<void>;
  onCreateUser: (payload: {
    username: string;
    password: string;
    role: string;
  }) => Promise<void>;
  onToggleUser: (userId: string, enabled: boolean) => void;
  onResetUserPassword: (userId: string) => void;
  onDeleteUser: (userId: string, username: string) => void;
  onChangePassword: (payload: {
    current_password: string;
    new_password: string;
  }) => Promise<void>;
}

export function SettingsDialog({
  open,
  initialSection,
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
  const [activeSection, setActiveSection] = useState<SettingsSection>(
    isAdmin ? (initialSection ?? "system") : "account",
  );
  const [systemDraft, setSystemDraft] = useState({
    pollSeconds: secondsFromMs(config.poll_interval_ms),
    rssMinutes: minutesFromSeconds(config.rss_refresh_interval_seconds),
  });
  const [newUser, setNewUser] = useState({
    username: "",
    password: "",
    role: "user",
  });
  const [passwords, setPasswords] = useState({
    current_password: "",
    new_password: "",
  });
  const [passwordError, setPasswordError] = useState("");
  const [savingSystem, setSavingSystem] = useState(false);
  const [creating, setCreating] = useState(false);
  const [changing, setChanging] = useState(false);

  const sections = useMemo(
    () => [
      ...(isAdmin
        ? [
            {
              id: "system" as const,
              label: "系统设置",
              icon: SlidersHorizontal,
            },
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
      if (!isAdmin) return "account";
      return initialSection ?? section;
    });
  }, [initialSection, isAdmin, open]);

  useEffect(() => {
    if (!open) return;
    setSystemDraft({
      pollSeconds: secondsFromMs(config.poll_interval_ms),
      rssMinutes: minutesFromSeconds(config.rss_refresh_interval_seconds),
    });
  }, [config.poll_interval_ms, config.rss_refresh_interval_seconds, open]);

  if (!open) return null;

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
    if (!newUser.username.trim() || newUser.password.length < 8) return;
    setCreating(true);
    try {
      await onCreateUser({ ...newUser, username: newUser.username.trim() });
      setNewUser({ username: "", password: "", role: "user" });
    } finally {
      setCreating(false);
    }
  }

  async function changePassword(
    event: FormEvent<HTMLFormElement>,
  ): Promise<void> {
    event.preventDefault();
    if (!passwords.current_password) {
      setPasswordError("请输入当前密码");
      return;
    }
    if (passwords.new_password.length < 8) {
      setPasswordError("新密码至少 8 位");
      return;
    }
    setPasswordError("");
    setChanging(true);
    try {
      await onChangePassword(passwords);
      setPasswords({ current_password: "", new_password: "" });
    } finally {
      setChanging(false);
    }
  }

  const semantic = config.semantic_search ?? null;
  const semanticStatus = semantic?.status ?? "unknown";

  return (
    <DialogOverlay onClose={onClose} labelledBy="settingsTitle">
      <section className="dlg-dialog dlg-settings">
        <header className="dlg-head">
          <h2 id="settingsTitle">设置</h2>
          <button
            ref={closeButtonRef}
            className="dlg-icon-btn"
            type="button"
            aria-label="关闭"
            onClick={onClose}
          >
            <X size={16} />
          </button>
        </header>

        <div className="dlg-settings-body">
          <nav className="dlg-settings-nav" aria-label="设置分类">
            {sections.map((section) => {
              const Icon = section.icon;
              return (
                <button
                  key={section.id}
                  className={activeSection === section.id ? "dlg-on" : ""}
                  aria-current={
                    activeSection === section.id ? "page" : undefined
                  }
                  type="button"
                  onClick={() => selectSection(section.id)}
                >
                  <Icon size={15} aria-hidden="true" />
                  {section.label}
                </button>
              );
            })}
          </nav>

          <div className="dlg-settings-content">
            {activeSection === "system" && isAdmin ? (
              <section
                className="dlg-settings-panel"
                aria-labelledby="systemSettingsTitle"
              >
                <h3 id="systemSettingsTitle" className="dlg-section-title">
                  系统设置
                </h3>
                <div
                  className={`dlg-sem-card dlg-sem-${semanticTone(semanticStatus)}`}
                >
                  <div className="dlg-sem-top">
                    <span>语义检索（按大意搜索）</span>
                    <strong>
                      <span className="dlg-dot" aria-hidden="true" />
                      {semanticStatusLabel(semantic?.status)}
                    </strong>
                  </div>
                  <dl>
                    <div>
                      <dt>模型</dt>
                      <dd>{semantic?.model_name ?? "未启用"}</dd>
                    </div>
                    <div>
                      <dt>维度</dt>
                      <dd>{semantic?.embedding_dimensions ?? "-"}</dd>
                    </div>
                    <div>
                      <dt>已处理</dt>
                      <dd>{semantic?.indexed_count ?? 0}</dd>
                    </div>
                    <div>
                      <dt>失败</dt>
                      <dd>{semantic?.failed_count ?? 0}</dd>
                    </div>
                  </dl>
                  {semantic?.last_error ? (
                    <p className="dlg-error">{semantic.last_error}</p>
                  ) : null}
                  <p className="dlg-sem-note">
                    关键词搜索始终可用。模型启动中或忙碌时，会暂时只按关键词查找。
                  </p>
                </div>
                <form className="dlg-settings-form" onSubmit={saveSystem}>
                  <label className="dlg-field" htmlFor="pollIntervalSeconds">
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
                        setSystemDraft((value) => ({
                          ...value,
                          pollSeconds: numberValue(event.target.value),
                        }))
                      }
                    />
                    <small>列表多久向服务器更新一次任务状态</small>
                  </label>
                  <label className="dlg-field" htmlFor="rssIntervalMinutes">
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
                        setSystemDraft((value) => ({
                          ...value,
                          rssMinutes: numberValue(event.target.value),
                        }))
                      }
                    />
                    <small>多久检查一次订阅源是否有新文章</small>
                  </label>
                  <div>
                    <button
                      className="dlg-btn dlg-btn-primary"
                      disabled={savingSystem}
                      type="submit"
                    >
                      {savingSystem ? "保存中…" : "保存设置"}
                    </button>
                  </div>
                </form>
              </section>
            ) : null}

            {activeSection === "users" && isAdmin ? (
              <section
                className="dlg-settings-panel"
                aria-labelledby="userSettingsTitle"
              >
                <div className="dlg-section-head">
                  <h3 id="userSettingsTitle" className="dlg-section-title">
                    用户管理
                  </h3>
                  <button
                    className="dlg-text-btn"
                    type="button"
                    onClick={onLoadUsers}
                  >
                    <RefreshCw size={12} aria-hidden="true" />
                    刷新
                  </button>
                </div>
                <form
                  className="dlg-user-create"
                  autoComplete="off"
                  onSubmit={createUser}
                >
                  <label className="dlg-field" htmlFor="newUserUsername">
                    用户名
                    <input
                      id="newUserUsername"
                      name="username"
                      autoComplete="off"
                      required
                      value={newUser.username}
                      onChange={(event) =>
                        setNewUser((value) => ({
                          ...value,
                          username: event.target.value,
                        }))
                      }
                    />
                  </label>
                  <label className="dlg-field" htmlFor="newUserPassword">
                    初始密码
                    <input
                      id="newUserPassword"
                      name="new-password"
                      autoComplete="new-password"
                      minLength={8}
                      required
                      type="password"
                      value={newUser.password}
                      onChange={(event) =>
                        setNewUser((value) => ({
                          ...value,
                          password: event.target.value,
                        }))
                      }
                    />
                  </label>
                  <label className="dlg-field" htmlFor="newUserRole">
                    角色
                    <select
                      id="newUserRole"
                      name="role"
                      value={newUser.role}
                      onChange={(event) =>
                        setNewUser((value) => ({
                          ...value,
                          role: event.target.value,
                        }))
                      }
                    >
                      <option value="user">普通用户</option>
                      <option value="admin">管理员</option>
                    </select>
                  </label>
                  <button
                    className="dlg-btn dlg-btn-primary"
                    disabled={
                      creating ||
                      !newUser.username.trim() ||
                      newUser.password.length < 8
                    }
                    type="submit"
                  >
                    {creating ? "添加中…" : "添加用户"}
                  </button>
                </form>
                <div className="dlg-user-list">
                  {users.length === 0 ? (
                    <p className="dlg-quiet dlg-user-empty">还没有用户</p>
                  ) : (
                    users.map((user) => {
                      const isSelf = user.user_id === currentUser?.user_id;
                      return (
                        <div
                          className={`dlg-user-row ${user.enabled ? "" : "dlg-off"}`}
                          key={user.user_id}
                        >
                          <span className="dlg-avatar" aria-hidden="true">
                            {user.username.slice(0, 1).toUpperCase()}
                          </span>
                          <div className="dlg-user-main">
                            <strong>
                              {user.username}
                              {isSelf ? <em>（你）</em> : null}
                            </strong>
                            <small>
                              {user.role === "admin" ? "管理员" : "普通用户"} ·{" "}
                              {user.enabled ? "启用" : "已停用"}
                            </small>
                          </div>
                          {isSelf ? null : (
                            <span className="dlg-user-acts">
                              <button
                                className="dlg-text-btn"
                                type="button"
                                onClick={() =>
                                  onToggleUser(user.user_id, !user.enabled)
                                }
                              >
                                {user.enabled ? "停用" : "启用"}
                              </button>
                              <button
                                className="dlg-text-btn"
                                type="button"
                                onClick={() =>
                                  onResetUserPassword(user.user_id)
                                }
                              >
                                重置密码
                              </button>
                              <button
                                className="dlg-text-btn dlg-text-danger"
                                type="button"
                                onClick={() =>
                                  onDeleteUser(user.user_id, user.username)
                                }
                              >
                                删除
                              </button>
                            </span>
                          )}
                        </div>
                      );
                    })
                  )}
                </div>
              </section>
            ) : null}

            {activeSection === "account" ? (
              <section
                className="dlg-settings-panel"
                aria-labelledby="accountSettingsTitle"
              >
                <h3 id="accountSettingsTitle" className="dlg-section-title">
                  账户安全
                </h3>
                <form
                  className="dlg-settings-form"
                  noValidate
                  onSubmit={changePassword}
                >
                  <input
                    className="dlg-visually-hidden"
                    tabIndex={-1}
                    autoComplete="username"
                    name="username"
                    value={currentUser?.username || ""}
                    readOnly
                    aria-hidden="true"
                  />
                  <label className="dlg-field" htmlFor="currentPassword">
                    当前密码
                    <input
                      id="currentPassword"
                      name="current-password"
                      autoComplete="current-password"
                      required
                      type="password"
                      value={passwords.current_password}
                      onChange={(event) =>
                        setPasswords((value) => ({
                          ...value,
                          current_password: event.target.value,
                        }))
                      }
                    />
                  </label>
                  <label className="dlg-field" htmlFor="newPassword">
                    新密码
                    <input
                      id="newPassword"
                      name="new-password"
                      autoComplete="new-password"
                      minLength={8}
                      required
                      type="password"
                      value={passwords.new_password}
                      onChange={(event) =>
                        setPasswords((value) => ({
                          ...value,
                          new_password: event.target.value,
                        }))
                      }
                    />
                    <small>至少 8 位</small>
                  </label>
                  {passwordError ? (
                    <p className="dlg-error" role="alert">
                      {passwordError}
                    </p>
                  ) : null}
                  <div>
                    <button
                      className="dlg-btn dlg-btn-primary"
                      disabled={changing}
                      type="submit"
                    >
                      {changing ? "保存中…" : "保存密码"}
                    </button>
                  </div>
                </form>
              </section>
            ) : null}
          </div>
        </div>
      </section>
    </DialogOverlay>
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

function semanticTone(status: string): "ok" | "warn" | "bad" | "idle" {
  if (status === "ready") return "ok";
  if (status === "indexing" || status === "degraded") return "warn";
  if (status === "unavailable") return "bad";
  return "idle";
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
