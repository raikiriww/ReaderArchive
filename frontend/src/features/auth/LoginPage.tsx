import { type FormEvent, useState } from "react";
import { login } from "../../api/client";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";

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
      const status = typeof error === "object" && error !== null && "status" in error ? error.status : null;
      setMessage(status === 429 ? "尝试次数过多，请稍后再试" : "用户名或密码不正确");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="login-view">
      <form className="login-panel" onSubmit={submit}>
        <div className="login-brand">
          <img className="brand-mark" src="/static/favicon.svg" alt="" aria-hidden="true" />
          <div>
            <h1>Reader Archive</h1>
            <p>登录后继续使用网页存档服务</p>
          </div>
        </div>
        <label htmlFor="loginUsername">
          用户名
          <Input
            id="loginUsername"
            name="username"
            autoComplete="username"
            autoFocus
            required
            value={username}
            onChange={(event) => setUsername(event.target.value)}
          />
        </label>
        <label htmlFor="loginPassword">
          密码
          <Input
            id="loginPassword"
            name="password"
            autoComplete="current-password"
            required
            type="password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
          />
        </label>
        <Button disabled={submitting} type="submit">
          {submitting ? "登录中" : "登录"}
        </Button>
        <p className="login-message" role="alert">
          {message}
        </p>
      </form>
    </main>
  );
}
