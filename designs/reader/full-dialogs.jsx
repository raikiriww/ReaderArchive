// Dialogs and secondary screens for the full prototype.
const { useState: useDlgState, useEffect: useDlgEffect, useRef: useDlgRef } = React;

function Overlay({ onClose, children, top }) {
  return (
    <div className={`overlay ${top ? "" : "center"}`} onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }} onKeyDown={(e) => { if (e.key === "Escape") { e.stopPropagation(); onClose(); } }}>
      {children}
    </div>
  );
}

/* ---------- Save ---------- */
function SaveDialog({ initialUrl, items, allTags, onClose, onSubmit }) {
  const [url, setUrl] = useDlgState(initialUrl);
  const [prepare, setPrepare] = useDlgState(false);
  const [tags, setTags] = useDlgState([]);
  const [busy, setBusy] = useDlgState(false);
  const clean = url.trim();
  const valid = /^https?:\/\/[^\s/]+\.[^\s]+/.test(clean);
  const existing = valid ? items.filter((i) => i.url === clean) : [];
  const submit = (e) => { e.preventDefault(); if (!valid || busy) return; setBusy(true); setTimeout(() => onSubmit({ url: clean, tags, prepare }), 350); };
  return (
    <Overlay onClose={onClose} top>
      <form className="dialog save-dialog" onSubmit={submit}>
        <h2>保存网页</h2>
        <div className={`url-field ${clean && !valid ? "bad" : ""}`}>
          <Icon name="link" size={16} />
          <input autoFocus value={url} placeholder="粘贴网址" onChange={(e) => setUrl(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) submit(e); }} />
        </div>
        {clean && !valid ? <p className="field-error">这不像一个完整的网址，请以 http:// 或 https:// 开头。</p> : null}
        {valid ? (
          <div className="detect">
            <span className="src-chip">{urlSiteLabel(clean)}</span>
            {existing.length ? <span className="dup"><Icon name="layers" size={13} />这个网址已保存过 {existing.length} 次（最近 {shortDate(existing[0].at)}），会另存一个新版本</span> : null}
          </div>
        ) : <p className="dialog-help">也可以在任意位置直接按 ⌘V 粘贴网址。</p>}
        {valid ? (
          <div className="save-tags">
            <span className="save-label">标签</span>
            {tags.map((t) => <button key={t} type="button" className="chip-toggle on" title="移除" onClick={() => setTags((c) => c.filter((x) => x !== t))}>#{t}<Icon name="x" size={11} /></button>)}
            <select className="tag-select" value="" onChange={(e) => { const v = e.target.value; if (v) setTags((c) => (c.includes(v) ? c : [...c, v])); }}>
              <option value="">{tags.length ? "再加一个…" : "添加标签（可选）"}</option>{allTags.map(([t]) => <option key={t} value={t}>{t}</option>)}
            </select>
          </div>
        ) : null}
        <label className="check prepare">
          <input type="checkbox" checked={prepare} onChange={(e) => setPrepare(e.target.checked)} />
          <span>保存前手动处理<small>先在内置浏览器里关弹窗、展开全文或登录，再保存那个页面。只对这一次保存生效。</small></span>
        </label>
        <div className="dialog-actions">
          <button className="btn" type="button" onClick={onClose}>取消</button>
          <button className="btn primary" type="submit" disabled={!valid || busy}>{busy ? "提交中…" : prepare ? "打开并等待处理" : "保存"}{busy ? null : <Kbd>⌘↩</Kbd>}</button>
        </div>
      </form>
    </Overlay>
  );
}

/* ---------- Confirm / input ---------- */
function ConfirmDialog({ req, onDone }) {
  const [value, setValue] = useDlgState("");
  const ok = req.kind === "input" ? value.length >= (req.minLength || 1) : true;
  return (
    <Overlay onClose={() => onDone(req.kind === "input" ? null : false)}>
      <form className="dialog confirm-dialog" onSubmit={(e) => { e.preventDefault(); if (ok) onDone(req.kind === "input" ? value : true); }}>
        <h2>{req.title}</h2>
        {req.message ? <p className="dialog-help">{req.message}</p> : null}
        {req.kind === "input" ? <label className="field">{req.label}<input autoFocus type={req.inputType || "text"} value={value} onChange={(e) => setValue(e.target.value)} />{req.minLength ? <small>至少 {req.minLength} 位</small> : null}</label> : null}
        <div className="dialog-actions">
          <button className="btn" type="button" onClick={() => onDone(req.kind === "input" ? null : false)}>取消</button>
          <button className={`btn ${req.danger ? "danger-fill" : "primary"}`} type="submit" autoFocus={req.kind !== "input"} disabled={!ok}>{req.confirmLabel || "确定"}</button>
        </div>
      </form>
    </Overlay>
  );
}

/* ---------- Settings ---------- */
function SettingsDialog({ section, onSection, config, onConfig, users, onUsers, currentUser, onClose, onConfirm, onToast }) {
  const isAdmin = currentUser.role === "admin";
  const [poll, setPoll] = useDlgState(config.poll_seconds);
  const [rss, setRss] = useDlgState(config.rss_minutes);
  const [nu, setNu] = useDlgState({ username: "", password: "", role: "user" });
  const [pw, setPw] = useDlgState({ cur: "", next: "" });
  const [pwError, setPwError] = useDlgState("");
  const sem = config.semantic;
  const semLabel = { ready: "可用", indexing: "处理中", degraded: "部分可用", unavailable: "不可用", disabled: "已关闭" }[sem.status] || "未知";
  const sections = [...(isAdmin ? [["system", "系统设置", "sliders"], ["users", "用户管理", "users"]] : []), ["account", "账户安全", "shield"]];

  async function resetPassword(u) {
    const v = await onConfirm({ kind: "input", title: `重置 ${u.username} 的密码`, message: "输入新的临时密码，让对方登录后自己修改。", label: "新密码", inputType: "password", minLength: 8, confirmLabel: "保存" });
    if (v) onToast("密码已重置");
  }
  async function removeUser(u) {
    if (await onConfirm({ title: "删除用户", message: `确定删除用户 ${u.username}？这个用户将无法再登录。`, confirmLabel: "删除", danger: true })) { onUsers(users.filter((x) => x.id !== u.id)); onToast("用户已删除"); }
  }

  return (
    <Overlay onClose={onClose}>
      <section className="dialog settings-dialog">
        <header className="settings-head"><h2>设置</h2><button className="ghost-icon" type="button" onClick={onClose}><Icon name="x" size={16} /></button></header>
        <div className="settings-body">
          <nav className="settings-nav">
            {sections.map(([id, label, icon]) => <button key={id} type="button" className={section === id ? "on" : ""} onClick={() => onSection(id)}><Icon name={icon} size={15} />{label}</button>)}
          </nav>
          <div className="settings-content">
            {section === "system" ? (
              <>
                <div className="sem-card">
                  <div className="sem-top"><span>按大意搜索</span><strong className={`sem-${sem.status}`}><span className="dot ok"></span>{semLabel}</strong></div>
                  <dl><div><dt>模型</dt><dd>{sem.model}</dd></div><div><dt>维度</dt><dd>{sem.dims}</dd></div><div><dt>已处理</dt><dd>{sem.indexed}</dd></div><div><dt>失败</dt><dd>{sem.failed}</dd></div></dl>
                  <p>关键词搜索始终可用。模型启动中或忙碌时，会暂时只按关键词查找。</p>
                </div>
                <form className="settings-form" onSubmit={(e) => { e.preventDefault(); onConfig({ ...config, poll_seconds: Math.max(1, poll), rss_minutes: Math.max(1, rss) }); onToast("设置已保存"); }}>
                  <label className="field">刷新间隔（秒）<input type="number" min="1" max="3600" value={poll} onChange={(e) => setPoll(Number(e.target.value))} /><small>列表多久向服务器更新一次任务状态</small></label>
                  <label className="field">RSS 检查间隔（分钟）<input type="number" min="1" max="1440" value={rss} onChange={(e) => setRss(Number(e.target.value))} /><small>多久检查一次订阅源是否有新文章</small></label>
                  <div><button className="btn primary" type="submit">保存设置</button></div>
                </form>
              </>
            ) : null}
            {section === "users" && isAdmin ? (
              <>
                <form className="user-create" onSubmit={(e) => { e.preventDefault(); if (!nu.username.trim() || nu.password.length < 8) return; onUsers([...users, { id: `u-${Date.now()}`, username: nu.username.trim(), role: nu.role, enabled: true }]); setNu({ username: "", password: "", role: "user" }); onToast("用户已添加"); }}>
                  <label className="field">用户名<input value={nu.username} onChange={(e) => setNu({ ...nu, username: e.target.value })} autoComplete="off" /></label>
                  <label className="field">初始密码<input type="password" value={nu.password} onChange={(e) => setNu({ ...nu, password: e.target.value })} autoComplete="new-password" /></label>
                  <label className="field">角色<select value={nu.role} onChange={(e) => setNu({ ...nu, role: e.target.value })}><option value="user">普通用户</option><option value="admin">管理员</option></select></label>
                  <button className="btn primary" type="submit" disabled={!nu.username.trim() || nu.password.length < 8}>添加用户</button>
                </form>
                <div className="user-list">
                  {users.map((u) => (
                    <div className="user-row" key={u.id}>
                      <span className="avatar">{u.username.slice(0, 1).toUpperCase()}</span>
                      <div><strong>{u.username}{u.id === currentUser.id ? <em>（你）</em> : null}</strong><small>{u.role === "admin" ? "管理员" : "普通用户"} · {u.enabled ? "启用" : "已停用"}</small></div>
                      {u.id !== currentUser.id ? (
                        <span className="user-acts">
                          <button className="text-btn small" type="button" onClick={() => { onUsers(users.map((x) => (x.id === u.id ? { ...x, enabled: !x.enabled } : x))); onToast(u.enabled ? "已停用" : "已启用"); }}>{u.enabled ? "停用" : "启用"}</button>
                          <button className="text-btn small" type="button" onClick={() => resetPassword(u)}>重置密码</button>
                          <button className="text-btn small danger" type="button" onClick={() => removeUser(u)}>删除</button>
                        </span>
                      ) : null}
                    </div>
                  ))}
                </div>
              </>
            ) : null}
            {section === "account" ? (
              <form className="settings-form" onSubmit={(e) => { e.preventDefault(); if (!pw.cur) { setPwError("请输入当前密码"); return; } if (pw.next.length < 8) { setPwError("新密码至少 8 位"); return; } setPwError(""); setPw({ cur: "", next: "" }); onToast("密码已修改"); }}>
                <label className="field">当前密码<input type="password" value={pw.cur} onChange={(e) => setPw({ ...pw, cur: e.target.value })} autoComplete="current-password" /></label>
                <label className="field">新密码<input type="password" value={pw.next} onChange={(e) => setPw({ ...pw, next: e.target.value })} autoComplete="new-password" /><small>至少 8 位</small></label>
                {pwError ? <p className="field-error">{pwError}</p> : null}
                <div><button className="btn primary" type="submit">保存密码</button></div>
              </form>
            ) : null}
          </div>
        </div>
      </section>
    </Overlay>
  );
}

/* ---------- Feeds management ---------- */
function FeedsDialog({ feeds, onFeeds, onRefresh, onClose, onConfirm, onToast }) {
  const [url, setUrl] = useDlgState("");
  const [busy, setBusy] = useDlgState(false);
  const [checking, setChecking] = useDlgState(null);
  const add = (e) => {
    e.preventDefault();
    const u = url.trim();
    if (!/^https?:\/\//.test(u) || busy) return;
    setBusy(true);
    setTimeout(() => {
      const name = hostOf(u) || "新订阅源";
      onFeeds([...feeds, { id: `f-${Date.now()}`, name, url: u, enabled: true, checked: "2026-10-13T02:30", error: null }]);
      setUrl(""); setBusy(false);
      onToast(`已添加「${name}」，创建了 3 个存档任务`);
    }, 700);
  };
  const check = (f) => { setChecking(f.id); setTimeout(() => { setChecking(null); onRefresh(f); }, 800); };
  return (
    <Overlay onClose={onClose}>
      <section className="dialog feeds-dialog">
        <header className="settings-head"><h2>订阅源</h2><button className="ghost-icon" type="button" onClick={onClose}><Icon name="x" size={16} /></button></header>
        <form className="feed-add" onSubmit={add}>
          <div className="url-field small"><Icon name="rss" size={15} /><input value={url} placeholder="RSS 地址，例如 https://example.com/feed.xml" onChange={(e) => setUrl(e.target.value)} /></div>
          <button className="btn primary" type="submit" disabled={!/^https?:\/\//.test(url.trim()) || busy}>{busy ? "添加中…" : "添加"}</button>
        </form>
        <p className="dialog-help">订阅源的新文章会自动保存成存档。想单独查看，可以在「全部存档」里把来源选成「订阅」。</p>
        <div className="feed-list">
          {feeds.length === 0 ? <p className="quiet-note">还没有订阅源</p> : feeds.map((f) => (
            <div className={`feed-row ${f.enabled ? "" : "off"}`} key={f.id}>
              <div className="feed-main">
                <span className="feed-name">{f.name}</span>
                <span className="feed-url">{f.url}</span>
                <span className="feed-meta">{f.enabled ? "启用" : "已停用"} · 上次检查 {f.checked ? fullDate(f.checked) : "尚未检查"}</span>
                {f.error ? <span className="field-error">{f.error}</span> : null}
              </div>
              <div className="feed-acts">
                <button className="text-btn small" type="button" disabled={checking === f.id || !f.enabled} onClick={() => check(f)}>{checking === f.id ? <><Icon name="loader" size={12} className="spin" />检查中</> : "立即检查"}</button>
                <label className="switch" title={f.enabled ? "停用" : "启用"}><input type="checkbox" checked={f.enabled} onChange={() => { onFeeds(feeds.map((x) => (x.id === f.id ? { ...x, enabled: !x.enabled } : x))); onToast(f.enabled ? "已停用，不再自动检查" : "已启用"); }} /><span></span></label>
                <button className="ghost-icon danger" type="button" title="删除" onClick={async () => { if (await onConfirm({ title: "删除订阅源", message: `删除后不再自动检查「${f.name}」。已经保存的文章会保留。`, confirmLabel: "删除", danger: true })) { onFeeds(feeds.filter((x) => x.id !== f.id)); onToast("已删除订阅源"); } }}><Icon name="trash" size={14} /></button>
              </div>
            </div>
          ))}
        </div>
      </section>
    </Overlay>
  );
}

function ShortcutHelp({ onClose, openMode }) {
  const rows = [
    ["J / K", "下一条 / 上一条"], ["Enter", openMode === "split" ? "—" : "打开当前条目"], ["Esc", "关闭阅读窗口 / 清除搜索"],
    ["E", "切换已读 / 未读"], ["T", "添加标签"], ["R", "修改名称"], ["V", "切换 原貌 / 正文"], ["I", "详情、文件、重新归档"],
    ["O", "打开原网页"], ["⇧ Enter", "在新标签页阅读"], ["N", "保存网页"], ["⌘V", "在任意位置粘贴网址即可保存"], ["/ 或 ⌘K", "搜索"],
    ...(openMode === "split" ? [["[", "收起 / 显示列表"]] : []), ["?", "显示这个面板"],
  ];
  return (
    <Overlay onClose={onClose}>
      <div className="dialog help-dialog"><h2>键盘快捷键</h2><dl>{rows.map(([k, v]) => <React.Fragment key={k}><dt><Kbd>{k}</Kbd></dt><dd>{v}</dd></React.Fragment>)}</dl></div>
    </Overlay>
  );
}

/* ---------- Login ---------- */
function LoginScreen({ onLogin }) {
  const [u, setU] = useDlgState("admin");
  const [p, setP] = useDlgState("");
  const [msg, setMsg] = useDlgState("");
  const [busy, setBusy] = useDlgState(false);
  const submit = (e) => {
    e.preventDefault();
    setMsg(""); setBusy(true);
    setTimeout(() => { setBusy(false); if (!u.trim() || p.length < 1) setMsg("用户名或密码不正确"); else onLogin(); }, 500);
  };
  return (
    <main className="login-view">
      <form className="login-panel" onSubmit={submit}>
        <div className="login-brand"><img src="favicon.svg" alt="" /><div><h1>Reader Archive</h1><p>登录后继续使用</p></div></div>
        <label className="field">用户名<input autoComplete="username" value={u} onChange={(e) => setU(e.target.value)} /></label>
        <label className="field">密码<input autoFocus type="password" autoComplete="current-password" value={p} onChange={(e) => setP(e.target.value)} /></label>
        <button className="btn primary big" type="submit" disabled={busy}>{busy ? "登录中…" : "登录"}</button>
        <p className="field-error" role="alert">{msg}</p>
        <p className="login-hint">原型：输入任意密码即可登录</p>
      </form>
    </main>
  );
}

/* ---------- Tweaks ---------- */
function Tweaks({ tweaks, setTweaks, onReset }) {
  const [open, setOpen] = useDlgState(false);
  const opt = (key, value, label) => <button type="button" className={tweaks[key] === value ? "on" : ""} onClick={() => setTweaks((t) => ({ ...t, [key]: value }))}>{label}</button>;
  return (
    <div className="tweaks">
      {open ? (
        <div className="tweaks-panel">
          <div className="tw-row"><span>打开方式</span><div className="tw-seg">{opt("open", "popup", "弹出窗口")}{opt("open", "tab", "新标签页")}{opt("open", "split", "窄侧栏")}</div></div>
          <div className="tw-row"><span>配色</span><div className="tw-seg">{opt("theme", "teal", "青绿")}{opt("theme", "paper", "纸墨")}{opt("theme", "night", "夜间")}</div></div>
          <div className="tw-row"><span>密度</span><div className="tw-seg">{opt("density", "comfortable", "舒适")}{opt("density", "compact", "紧凑")}</div></div>
          <button className="text-btn small" type="button" onClick={onReset}><Icon name="refresh" size={12} />恢复原型数据</button>
        </div>
      ) : null}
      <button type="button" className="tweaks-toggle" onClick={() => setOpen((v) => !v)}><Icon name="sliders" size={14} />Tweaks</button>
    </div>
  );
}

Object.assign(window, { SaveDialog, ConfirmDialog, SettingsDialog, FeedsDialog, ShortcutHelp, LoginScreen, Tweaks });
