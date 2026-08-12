import { useState } from "react";
import "./login.css";

export function LoginPage({ onLogin, error = null }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [localError, setLocalError] = useState(null);

  const submit = async (event) => {
    event.preventDefault();
    if (submitting) return;
    setSubmitting(true);
    setLocalError(null);
    try {
      await onLogin({
        username,
        password,
        clientType: "WEB",
        deviceName: "点联 Web",
      });
    } catch (submitError) {
      setLocalError(submitError?.detail ?? submitError?.message ?? "登录失败，请稍后重试。");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <main className="dianlian-login">
      <section className="dianlian-login__panel">
        <div className="dianlian-login__brand" aria-label="点联">
          <img src="/assets/brand/dianlian-symbol.png" alt="" />
          <span>点联</span>
        </div>
        <header>
          <p>企业数字员工办公平台</p>
          <h1>登录点联办公室</h1>
          <span>进入企业后，找一位数字员工开始工作。</span>
        </header>
        <form onSubmit={submit}>
          <label>
            <span>账号</span>
            <input
              name="username"
              autoComplete="username"
              maxLength={200}
              value={username}
              onChange={(event) => setUsername(event.target.value)}
              placeholder="请输入企业账号"
              required
            />
          </label>
          <label>
            <span>密码</span>
            <input
              name="password"
              type="password"
              autoComplete="current-password"
              maxLength={200}
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              placeholder="请输入密码"
              required
            />
          </label>
          {(localError || error) ? <p className="dianlian-login__error" role="alert">{localError || error}</p> : null}
          <button type="submit" disabled={submitting}>
            {submitting ? "正在登录…" : "登录"}
          </button>
        </form>
        <footer>登录即代表你正在访问所属企业的授权工作空间</footer>
      </section>
      <aside aria-hidden="true">
        <div className="dianlian-login__orb dianlian-login__orb--one" />
        <div className="dianlian-login__orb dianlian-login__orb--two" />
        <div className="dianlian-login__office-card">
          <strong>你的 AI 同事，已经准备好了</strong>
          <span>平面出图 · 合同审核 · 项目报价</span>
        </div>
      </aside>
    </main>
  );
}
