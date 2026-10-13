import { type FormEvent, useState } from "react";
import { login } from "../../api/client";

export function LoginPage(): JSX.Element {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [message, setMessage] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    setMessage("");
    setSubmitting(true);
    try {
      await login(username.trim(), password);
      const next = new URLSearchParams(window.location.search).get("next");
      window.location.href = next?.startsWith("/") ? next : "/";
    } catch (error) {
      const status =
        typeof error === "object" && error !== null && "status" in error
          ? error.status
          : null;
      setMessage(
        status === 429 ? "尝试次数过多，请稍后再试" : "用户名或密码不正确",
      );
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="dlg-login-view">
      <form className="dlg-login-panel" onSubmit={submit}>
        <div className="dlg-login-brand">
          <img src="/static/favicon.svg" alt="" aria-hidden="true" />
          <div>
            <h1>Reader Archive</h1>
            <p>登录后继续使用网页存档服务</p>
          </div>
        </div>
        <label className="dlg-field" htmlFor="loginUsername">
          用户名
          <input
            id="loginUsername"
            name="username"
            autoComplete="username"
            // biome-ignore lint/a11y/noAutofocus: the login page has a single purpose
            autoFocus
            required
            value={username}
            onChange={(event) => setUsername(event.target.value)}
          />
        </label>
        <label className="dlg-field" htmlFor="loginPassword">
          密码
          <input
            id="loginPassword"
            name="password"
            autoComplete="current-password"
            required
            type="password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
          />
        </label>
        <button
          className="dlg-btn dlg-btn-primary dlg-btn-big"
          disabled={submitting}
          type="submit"
        >
          {submitting ? "登录中…" : "登录"}
        </button>
        <p className="dlg-error dlg-login-message" role="alert">
          {message}
        </p>
      </form>
    </main>
  );
}
