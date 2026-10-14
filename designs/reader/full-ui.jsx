// UI components for the full prototype. State lives in full-app.jsx.
const { useState: useUiState, useEffect: useUiEffect, useRef: useUiRef } = React;

function viewLabel(view) {
  if (!view) return "";
  if (view.kind === "inbox") return "未读";
  if (view.kind === "recent") return "我的保存";
  if (view.kind === "all") return "全部存档";
  if (view.kind === "feed") return view.value || "订阅";
  if (view.kind === "tag") return view.value.join(" + ");
  return "";
}

function usePopover() {
  const [open, setOpen] = useUiState(null);
  const ref = useUiRef(null);
  useUiEffect(() => {
    if (!open) return undefined;
    const close = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(null); };
    const esc = (e) => { if (e.key === "Escape") setOpen(null); };
    // Clicks inside the snapshot iframe never reach this window; it only blurs.
    const blur = () => setOpen(null);
    window.addEventListener("mousedown", close);
    window.addEventListener("keydown", esc, true);
    window.addEventListener("blur", blur);
    return () => { window.removeEventListener("mousedown", close); window.removeEventListener("keydown", esc, true); window.removeEventListener("blur", blur); };
  }, [open]);
  return [open, setOpen, ref];
}

/* ================= Sidebar (full or icon rail) ================= */
function AppSidebar({ rail, view, onView, counts, feeds, tags, user, onSave, onSearch, onManageFeeds, onSettings, onLogout, onBrowser, onToggleRail }) {
  const [tagFilter, setTagFilter] = useUiState("");
  const [allTags, setAllTags] = useUiState(false);
  const [pop, setPop, popRef] = usePopover();
  const active = (kind, value) => view.kind === kind && (value === undefined || view.value === value || (Array.isArray(view.value) && view.value.length === 1 && view.value[0] === value));
  const shown = tags.filter(([t]) => t.toLowerCase().includes(tagFilter.trim().toLowerCase()));

  const item = (kind, value, icon, label, count, tone) => (
    <button key={`${kind}-${value || ""}`} type="button" className={`nav-item ${active(kind, value) ? "active" : ""}`} onClick={() => { onView({ kind, value }); setPop(null); }} data-tip={rail ? label : undefined}>
      <Icon name={icon} size={16} />
      <span className="nav-label">{label}</span>
      {count ? <span className={`nav-count ${tone || ""}`}>{count}</span> : null}
      {rail && count ? <span className={`rail-badge ${tone || ""}`}>{count > 99 ? "99+" : count}</span> : null}
    </button>
  );

  const tagList = (limit) => (
    <div className="tag-nav">
      {(limit ? shown.slice(0, limit) : shown).map(([t, n]) => (
        <button key={t} type="button" className={`nav-item tag-item ${active("tag", t) ? "active" : ""}`} onClick={() => { onView({ kind: "tag", value: [t] }); setPop(null); }}>
          <Icon name="hash" size={14} /><span className="nav-label">{t}</span><span className="nav-count quiet">{n}</span>
        </button>
      ))}
      {shown.length === 0 ? <p className="nav-empty">没有匹配的标签</p> : null}
    </div>
  );

  return (
    <aside className={`sidebar ${rail ? "rail" : ""}`}>
      <div className="brand-row">
        <img src="favicon.svg" alt="" className="brand-mark" />
        <span className="brand-name">Reader Archive</span>
        {onToggleRail ? <button className="ghost-icon collapse-btn" type="button" onClick={onToggleRail} data-tip={rail ? "展开侧栏" : "收起侧栏"}><Icon name="sidebar" size={16} /></button> : null}
      </div>

      <div className="sidebar-actions">
        <button className="save-btn" type="button" onClick={onSave} data-tip={rail ? "保存网页 N" : undefined}>
          <Icon name="plus" size={16} strokeWidth={2.2} /><span className="nav-label">保存网页</span><Kbd>N</Kbd>
        </button>
        <button className="search-btn" type="button" onClick={onSearch} data-tip={rail ? "搜索 ⌘K" : undefined}>
          <Icon name="search" size={15} /><span className="nav-label">搜索</span><Kbd>⌘K</Kbd>
        </button>
      </div>

      <nav className="nav-group">
        {item("inbox", undefined, "inbox", "未读", counts.inbox, counts.attention ? "alert" : "")}
        {item("all", undefined, "archive", "全部存档")}
      </nav>

      {rail ? (
        <nav className="nav-group">
          <div className="pop-anchor" ref={pop === "tags" ? popRef : undefined}>
            <button type="button" className={`nav-item ${view.kind === "tag" || pop === "tags" ? "active" : ""}`} onClick={() => setPop(pop === "tags" ? null : "tags")} data-tip="标签">
              <Icon name="hash" size={16} />
            </button>
            {pop === "tags" ? (
              <div className="flyout tall">
                <div className="flyout-head">标签</div>
                <input autoFocus className="tag-filter" placeholder="筛选标签，回车打开第一个" value={tagFilter} onChange={(e) => setTagFilter(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter" && shown[0]) { onView({ kind: "tag", value: [shown[0][0]] }); setPop(null); } }} />
                {tagList()}
              </div>
            ) : null}
          </div>
        </nav>
      ) : (
        <>
          <div className="nav-section tags-section">
            <div className="nav-section-head"><span>标签</span></div>
            <input className="tag-filter" placeholder="筛选标签" value={tagFilter} onChange={(e) => setTagFilter(e.target.value)} />
            {tagList(allTags || tagFilter ? 0 : 10)}
            {!tagFilter && shown.length > 10 ? <button className="nav-more" type="button" onClick={() => setAllTags((v) => !v)}>{allTags ? "收起" : `全部 ${shown.length} 个标签`}</button> : null}
          </div>
        </>
      )}

      <div className="sidebar-foot">
        <button className="nav-item" type="button" onClick={onManageFeeds} data-tip={rail ? "订阅源" : undefined}><Icon name="rss" size={16} /><span className="nav-label">订阅源</span></button>
        <button className="nav-item" type="button" onClick={onBrowser} data-tip={rail ? "内置浏览器" : undefined}><Icon name="globe" size={16} /><span className="nav-label">内置浏览器</span><Icon name="external" size={12} className="foot-ext" /></button>
        <button className="nav-item" type="button" onClick={() => onSettings("system")} data-tip={rail ? "设置" : undefined}><Icon name="settings" size={16} /><span className="nav-label">设置</span></button>
        <div className="pop-anchor" ref={pop === "user" ? popRef : undefined}>
          <button className="nav-item user-btn" type="button" onClick={() => setPop(pop === "user" ? null : "user")} data-tip={rail ? user.username : undefined}>
            <span className="avatar">{user.username.slice(0, 1).toUpperCase()}</span><span className="nav-label">{user.username}</span>
          </button>
          {pop === "user" ? (
            <div className="flyout up">
              <div className="flyout-user"><strong>{user.username}</strong><span>{user.role === "admin" ? "管理员" : "普通用户"}</span></div>
              <button type="button" className="menu-row" onClick={() => { setPop(null); onSettings("account"); }}><Icon name="key" size={14} />修改密码</button>
              <button type="button" className="menu-row" onClick={() => { setPop(null); onLogout(); }}><Icon name="logout" size={14} />退出登录</button>
            </div>
          ) : null}
        </div>
      </div>
    </aside>
  );
}

/* ================= List pane ================= */
function SearchBox({ inputRef, query, onQuery, onCommit, recent, onClearRecent }) {
  const [focus, setFocus] = useUiState(false);
  const showRecent = focus && !query && recent.length > 0;
  return (
    <div className="search-wrap">
      <div className="search-row">
        <Icon name="search" size={15} className="search-icon" />
        <input ref={inputRef} className="search-input" placeholder="搜索标题、正文、标签，或描述大意" value={query}
          onChange={(e) => onQuery(e.target.value)} onFocus={() => setFocus(true)} onBlur={() => setTimeout(() => setFocus(false), 150)}
          onKeyDown={(e) => {
            if (e.key === "Escape") { e.stopPropagation(); if (query) onQuery(""); else e.currentTarget.blur(); }
            if (e.key === "Enter") { e.stopPropagation(); onCommit(query); e.currentTarget.blur(); }
            if (e.key === "ArrowDown") { e.preventDefault(); e.stopPropagation(); e.currentTarget.blur(); }
          }} />
        {query ? <button className="ghost-icon" type="button" onClick={() => onQuery("")} title="清除 Esc"><Icon name="x" size={14} /></button> : <Kbd>⌘K</Kbd>}
      </div>
      {showRecent ? (
        <div className="recent-pop">
          <div className="recent-head">最近搜索<button type="button" onMouseDown={(e) => { e.preventDefault(); onClearRecent(); }}>清空</button></div>
          {recent.map((r) => <button key={r} type="button" onMouseDown={(e) => { e.preventDefault(); onQuery(r); onCommit(r); }}><Icon name="history" size={14} />{r}</button>)}
          <p>只保存在当前浏览器会话里</p>
        </div>
      ) : null}
    </div>
  );
}

function SearchFiltersBar({ filters, onFilters, tags, results, query }) {
  const [open, setOpen] = useUiState(false);
  const count = Number(filters.content_type !== "all") + Number(Boolean(filters.source)) + Number(Boolean(filters.date_from)) + filters.tags.length + Number(!filters.include_read) + Number(filters.exact);
  const set = (patch) => onFilters({ ...filters, ...patch });
  const strong = results.filter((r) => r.strength === "strong").length;
  return (
    <div className="search-filters">
      <div className="sf-line">
        <div className="mini-seg">
          {[["all", "全部"], ["web", "网页"], ["video", "视频"], ["file", "文件"]].map(([v, l]) => (
            <button key={v} type="button" className={filters.content_type === v ? "on" : ""} onClick={() => set({ content_type: v })}>{l}</button>
          ))}
        </div>
        <button type="button" className={`chip-toggle ${open || count ? "on" : ""}`} onClick={() => setOpen((v) => !v)}><Icon name="sliders" size={13} />筛选{count ? ` ${count}` : ""}</button>
        <select className="sort-select" value={filters.sort} onChange={(e) => set({ sort: e.target.value })} aria-label="排序">
          <option value="relevance">最相关</option><option value="newest">最新保存</option><option value="oldest">最早保存</option>
        </select>
      </div>
      {open ? (
        <div className="sf-panel">
          <label>来源<select value={filters.source} onChange={(e) => set({ source: e.target.value })}><option value="">全部来源</option><option value="manual">手动保存</option><option value="rss">RSS 订阅</option></select></label>
          <label>保存日期起<input type="date" value={filters.date_from} onChange={(e) => set({ date_from: e.target.value })} /></label>
          <label>标签<select value={filters.tags[0] || ""} onChange={(e) => set({ tags: e.target.value ? [e.target.value] : [] })}><option value="">全部标签</option>{tags.map(([t]) => <option key={t}>{t}</option>)}</select></label>
          <label className="check"><input type="checkbox" checked={!filters.include_read} onChange={(e) => set({ include_read: !e.target.checked })} />仅未读</label>
          <label className="check"><input type="checkbox" checked={filters.exact} onChange={(e) => set({ exact: e.target.checked })} />只匹配原词（或给短语加引号）</label>
          {count ? <button className="text-btn small" type="button" onClick={() => onFilters({ ...SEARCH_DEFAULTS, sort: filters.sort })}>清除筛选</button> : null}
        </div>
      ) : null}
      <p className="sf-notice">
        {filters.exact || /^".+"$/.test(query.trim()) ? "正在按原词查找。" : "结合关键词和内容大意查找。"}
        <span> 共 {results.length} 条{strong < results.length ? `，其中 ${results.length - strong} 条只是意思可能相关` : ""}。</span>
        <span className="sf-pending">12 篇正文正在准备，结果会陆续补齐。</span>
      </p>
    </div>
  );
}

function ListPane({ wide, view, groups, flat, searching, query, results, showPossible, onShowPossible, selectedId, onOpen, searchProps, filterProps, header }) {
  const listRef = useUiRef(null);
  useUiEffect(() => {
    const el = listRef.current?.querySelector(".row.selected");
    if (el) el.scrollIntoView({ block: "nearest" });
  }, [selectedId]);
  const q = query.trim().replace(/^"(.+)"$/, "$1");
  const firstStrong = results.findIndex((r) => r.strength === "strong");
  const collapsible = results.filter((r, i) => r.strength === "possible" && firstStrong >= 0 && i > firstStrong).length;

  return (
    <section className={`list-pane ${wide ? "wide" : ""}`}>
      <SearchBox {...searchProps} />
      {searching ? <SearchFiltersBar {...filterProps} results={results} query={query} /> : header}
      <div className="rows" ref={listRef} role="listbox">
        {searching ? (
          results.length === 0 ? (
            <div className="list-empty"><Icon name="search" size={26} /><p>没有找到「{q}」</p><small>试试更短的关键词、标题里的词，或者去掉筛选条件。</small></div>
          ) : (
            <>
              {results.map((r, i) => {
                const hidden = r.strength === "possible" && firstStrong >= 0 && i > firstStrong && !showPossible;
                if (hidden) return null;
                return <Row key={r.item.id} item={r.item} selected={r.item.id === selectedId} onOpen={(e) => onOpen(r.item.id, e)} query={q} match={r} showExcerpt />;
              })}
              {collapsible ? <button className="possible-toggle" type="button" onClick={() => onShowPossible(!showPossible)}>{showPossible ? "收起意思可能相关的结果" : `展开其余 ${collapsible} 条意思可能相关的结果`}</button> : null}
            </>
          )
        ) : flat.length === 0 ? (
          <div className="list-empty">
            {view.kind === "inbox" ? <><Icon name="checks" size={28} /><p>没有未读的存档</p><small>新保存的网页和新的订阅文章会出现在这里。</small></> : view.kind === "feed" ? <><Icon name="checks" size={28} /><p>订阅文章都读完了</p><small>关掉「只看未读」可以看已读的文章。</small></> : <p>这里还没有存档</p>}
          </div>
        ) : (
          groups.map(([label, group]) => (
            <div className="row-group" key={label}>
              <div className="group-label">{label}<span>{group.length}</span></div>
              {group.map((it) => <Row key={it.id} item={it} selected={it.id === selectedId} onOpen={(e) => onOpen(it.id, e)} showExcerpt={wide || it.source === "rss"} />)}
            </div>
          ))
        )}
        {!searching && flat.length > 0 ? <p className="list-foot">原型只包含最近 70 条存档。正式版滚动到底部会自动加载更多。</p> : null}
      </div>
    </section>
  );
}

function StatusPill({ item }) {
  if (item.status === "queued") return <span className="pill running"><Icon name="clock" size={12} />排队中</span>;
  if (item.status === "running") return <span className="pill running"><Icon name="loader" size={12} className="spin" />保存中</span>;
  if (item.status === "manual_action_required") return <span className="pill waiting"><Icon name="hand" size={12} />{item.tab === "missing" ? "处理页面已丢失" : "等你处理"}</span>;
  if (item.status === "failed") return <span className="pill failed"><Icon name="alert" size={12} />失败</span>;
  return null;
}

function Row({ item, selected, onOpen, query, match, showExcerpt }) {
  const body = cleanBody(item);
  const excerpt = match ? match.excerpt : body.replace(/^Daily Hacker News for \S+\s*/, "").slice(0, 140);
  const notDone = item.status !== "succeeded";
  const hl = match && match.kind === "semantic" ? match.hint : query;
  return (
    <button type="button" role="option" aria-selected={selected} className={`row ${selected ? "selected" : ""} ${item.read ? "read" : "unread"}`} onClick={onOpen} onAuxClick={(e) => { if (e.button === 1) onOpen(e); }}>
      <span className="row-dot" aria-hidden="true"></span>
      <span className="row-main">
        {match ? <span className={`match-label ${match.strength}`}>{MATCH_LABELS[match.kind]}{match.versions > 1 ? ` · ${match.versions} 个保存版本` : ""}</span> : null}
        <span className="row-top">
          <span className={`row-title ${notDone ? "mono" : ""}`}>{query && match && match.kind === "title" ? highlight(item.title, query) : item.title}</span>
          <span className="row-date">{shortDate(item.at)}</span>
        </span>
        {showExcerpt && excerpt && !notDone ? <span className="row-excerpt">{hl ? highlight(excerpt, hl) : excerpt}</span> : null}
        <span className="row-meta">
          {notDone ? <StatusPill item={item} /> : null}
          <span className="row-source">{sourceName(item)}</span>
          {item.tags.slice(0, 3).map((t) => <span className="row-tag" key={t}>#{t}</span>)}
          {item.video ? <Icon name="video" size={13} className="row-video" /> : null}
          {item.notice ? <Icon name="alert" size={12} className="row-warn" /> : null}
        </span>
      </span>
    </button>
  );
}

/* ================= Reader ================= */
function TagEditor({ item, allTags, onChange, inputRef }) {
  const [value, setValue] = useUiState("");
  const [open, setOpen] = useUiState(false);
  const [active, setActive] = useUiState(0);
  const has = new Set(item.tags.map((t) => t.toLowerCase()));
  const q = value.trim().toLowerCase();
  const matches = allTags.map(([t]) => t).filter((t) => !has.has(t.toLowerCase()) && (!q || t.toLowerCase().includes(q))).slice(0, 7);
  const canCreate = q && !allTags.some(([t]) => t.toLowerCase() === q) && !has.has(q);
  const options = [...matches, ...(canCreate ? [value.trim()] : [])];
  useUiEffect(() => { setValue(""); setOpen(false); }, [item.id]);
  useUiEffect(() => setActive(0), [value]);
  const add = (t) => { if (t && !has.has(t.toLowerCase())) onChange([...item.tags, t]); setValue(""); };
  return (
    <div className="tag-editor">
      {item.tags.map((t) => (
        <span className="tag" key={t}><span>#{t}</span><button type="button" aria-label={`移除 ${t}`} onClick={() => onChange(item.tags.filter((x) => x !== t))}><Icon name="x" size={11} strokeWidth={2.4} /></button></span>
      ))}
      <div className="tag-input-wrap">
        <input ref={inputRef} className="tag-input" value={value} placeholder="+ 标签  T" onChange={(e) => setValue(e.target.value)} onFocus={() => setOpen(true)} onBlur={() => setTimeout(() => setOpen(false), 120)}
          onKeyDown={(e) => {
            if (e.key === "ArrowDown") { e.preventDefault(); setActive((a) => Math.min(options.length - 1, a + 1)); }
            else if (e.key === "ArrowUp") { e.preventDefault(); setActive((a) => Math.max(0, a - 1)); }
            else if (e.key === "Enter") { e.preventDefault(); e.stopPropagation(); add(options[active] || value.trim()); }
            else if (e.key === "Backspace" && !value && item.tags.length) onChange(item.tags.slice(0, -1));
            else if (e.key === "Escape") { e.stopPropagation(); setValue(""); e.currentTarget.blur(); }
          }} />
        {open && options.length ? (
          <div className="tag-menu">
            {options.map((t, i) => (
              <button key={t} type="button" className={i === active ? "active" : ""} onMouseDown={(e) => { e.preventDefault(); add(t); }}>
                {i === matches.length && canCreate ? <><Icon name="plus" size={12} />新建「{t}」</> : <>#{t}<span>{(allTags.find(([x]) => x === t) || [])[1]}</span></>}
              </button>
            ))}
          </div>
        ) : null}
      </div>
    </div>
  );
}

// Stand-in for the archived SingleFile page. The real app shows the file in a script-free iframe.
function Snapshot({ item }) {
  const body = cleanBody(item);
  return (
    <div className="snap snap-article">
      <div className="art-site">{item.source === "rss" ? item.feed : hostOf(item.url)}<span className="snap-note">示例快照</span></div>
      <h1>{item.title}</h1>
      <div className="art-meta">{hostOf(item.url)} · {fullDate(item.at).slice(0, 10)}</div>
      {item.video ? <ArchivedPlayer note="网页里原来的播放器，换成了下载的视频" /> : null}
      {paragraphs(body).slice(0, 10).map((p, i) => <p key={i}>{p}</p>)}
    </div>
  );
}

// Stand-in for a <video controls> playing the yt-dlp download; the prototype has no real video.
function ArchivedPlayer({ note }) {
  return (
    <div className="archived-player" title="示例：播放下载的视频">
      <span className="ap-play" aria-hidden="true">▶</span>
      <span className="ap-bar" aria-hidden="true"><span></span></span>
      <span className="ap-note">{note}</span>
    </div>
  );
}

function VideoPane() {
  return (
    <div className="video-pane">
      <ArchivedPlayer note="下载的视频" />
    </div>
  );
}

function TextView({ item, query }) {
  const ref = useUiRef(null);
  const q = (query || "").trim().replace(/^"(.+)"$/, "$1");
  useUiEffect(() => {
    const mark = ref.current?.querySelector("mark");
    if (mark) mark.scrollIntoView({ block: "center" });
    else ref.current?.scrollTo(0, 0);
  }, [item.id, q]);
  const paras = paragraphs(cleanBody(item) || "");
  const hitCount = q ? paras.filter((p) => p.toLowerCase().includes(q.toLowerCase())).length : 0;
  return (
    <article className="text-view" lang="zh" ref={ref}>
      {q && hitCount ? <div className="hit-note">「{q}」在正文中出现在 {hitCount} 段，已跳到第一处</div> : null}
      <h1>{item.title}</h1>
      {paras.length ? paras.map((p, i) => <p key={i}>{q ? highlight(p, q) : p}</p>) : <p className="text-missing">这篇存档目前没有可阅读的正文。扫描版 PDF、视频不会提取文字，请看「原貌」。</p>}
      <p className="text-end">正文由存档自动提取。图片和排版请切换到「原貌」查看。</p>
    </article>
  );
}

function StatusPanel({ item, onOpenAction, onResume, onRetry, onDelete }) {
  if (item.status === "queued" || item.status === "running") {
    const stepIdx = item.status === "queued" ? 0 : 1;
    const steps = ["排队中", item.step || "保存网页", "提取正文、建立索引"];
    return (
      <div className="status-panel">
        <Icon name={item.status === "queued" ? "clock" : "loader"} size={26} className={`accent ${item.status === "running" ? "spin" : ""}`} />
        <h2>{item.status === "queued" ? "排队等待保存" : "正在保存"}</h2>
        <p className="mono-url">{item.url}</p>
        <ol className="steps">{steps.map((s, i) => <li key={s} className={i < stepIdx ? "done" : i === stepIdx ? "now" : ""}>{s}</li>)}</ol>
        <p className="hint">不用等待，可以继续看别的。保存完成后，这一条会变成可以阅读的状态。</p>
      </div>
    );
  }
  if (item.status === "manual_action_required") {
    const lost = item.tab === "missing";
    const notOpened = item.tab === "not_opened";
    const prepare = item.action === "page.prepare_manually";
    return (
      <div className="status-panel">
        <Icon name="hand" size={26} className="warn" />
        <h2>{prepare ? "等你在内置浏览器里处理这个网页" : "这个网站需要先登录"}</h2>
        <p>{prepare ? "关闭弹窗、展开全文或加载需要的内容后，回到这里点「处理完成」。Reader 会直接保存那个标签页当前的样子，不会重新加载。" : "在内置浏览器里登录这个网站，然后回到这里继续。登录状态会保留，以后保存同一个网站就不用再登录。"}</p>
        <div className={`tab-state ${lost ? "lost" : ""}`}><span className={`dot ${lost ? "bad" : notOpened ? "idle" : "ok"}`}></span>{lost ? "原来的处理页面已经丢失，重新打开后要再处理一次" : notOpened ? "处理页面还没打开" : "处理页面已连接"}</div>
        <div className="status-actions">
          <button className="btn" type="button" onClick={onOpenAction}><Icon name="globe" size={15} />{lost ? "重新打开处理页面" : notOpened ? "打开处理页面" : "切回处理页面"}</button>
          <button className="btn primary" type="button" disabled={lost || notOpened} onClick={onResume}><Icon name="check" size={15} />{prepare ? "处理完成，保存当前页面" : "已登录，继续保存"}</button>
        </div>
        <p className="hint">等待手动处理的任务不占用超时时间，也不会挡住其他保存。关掉 Reader 页面后，它也会一直等在这里。</p>
        <button className="link-danger" type="button" onClick={onDelete}>取消等待并删除</button>
      </div>
    );
  }
  return (
    <div className="status-panel">
      <Icon name="alert" size={26} className="danger" />
      <h2>保存失败</h2>
      <p className="err">{item.error}</p>
      <div className="status-actions">
        <button className="btn primary" type="button" onClick={() => onRetry(true)}><Icon name="hand" size={15} />手动处理后重试</button>
        <button className="btn" type="button" onClick={() => onRetry(false)}><Icon name="refresh" size={15} />直接重试</button>
        <a className="btn" href={item.url} target="_blank" rel="noreferrer"><Icon name="external" size={15} />原网页</a>
      </div>
      <button className="link-danger" type="button" onClick={onDelete}>删除这条记录</button>
    </div>
  );
}

function FileRow({ file, onRename, onDelete, onToast }) {
  const [editing, setEditing] = useUiState(false);
  const [value, setValue] = useUiState(file.display);
  const icon = file.tool === "yt-dlp" ? "video" : file.tool === "upload" ? "upload" : "page";
  const label = file.tool === "yt-dlp" ? "视频下载" : file.tool === "upload" ? "手动上传" : "网页存档";
  const commit = () => { const v = value.trim(); if (v && v !== file.display) onRename(v); setEditing(false); };
  return (
    <div className="file-row">
      <Icon name={icon} size={16} />
      <div>
        {editing ? <input className="file-edit" autoFocus value={value} onChange={(e) => setValue(e.target.value)} onBlur={commit} onKeyDown={(e) => { if (e.key === "Enter") { e.stopPropagation(); commit(); } if (e.key === "Escape") { e.stopPropagation(); setEditing(false); } }} /> : <strong title={file.name}>{file.display}</strong>}
        <small>{label} · {formatSize(file.size)}</small>
      </div>
      <span className="file-acts">
        <button className="ghost-icon" type="button" title="打开" onClick={() => onToast(`在新标签打开 ${file.display}`)}><Icon name="eye" size={14} /></button>
        <button className="ghost-icon" type="button" title="下载" onClick={() => onToast(`开始下载 ${file.display}`)}><Icon name="download" size={14} /></button>
        <button className="ghost-icon" type="button" title="改名" onClick={() => { setValue(file.display); setEditing(true); }}><Icon name="pencil" size={14} /></button>
        <button className="ghost-icon danger" type="button" title="删除" onClick={onDelete}><Icon name="trash" size={14} /></button>
      </span>
    </div>
  );
}

function DetailsDrawer({ item, onClose, onRearchive, onDelete, onFiles, onConfirm, onToast }) {
  const [manual, setManual] = useUiState(false);
  const fileRef = useUiRef(null);
  const statusText = { queued: "排队中", running: "处理中", manual_action_required: "等待手动处理", succeeded: "已完成", failed: "失败" }[item.status];
  const busy = item.status === "queued" || item.status === "running";
  const waiting = item.status === "manual_action_required";
  return (
    <aside className="drawer">
      <header><h3>存档详情</h3><button className="ghost-icon" type="button" onClick={onClose} title="关闭 I"><Icon name="x" size={16} /></button></header>
      {item.notice ? <section><div className="notice-card">{item.notice}</div></section> : null}
      <section>
        <div className="drawer-label">文件 <span className="drawer-label-acts"><button className="text-btn small" type="button" onClick={() => onToast("文件列表已刷新")}><Icon name="refresh" size={12} />刷新</button><button className="text-btn small" type="button" onClick={() => fileRef.current?.click()}><Icon name="upload" size={13} />上传</button></span></div>
        <input ref={fileRef} type="file" hidden onChange={(e) => { const f = e.target.files?.[0]; e.target.value = ""; if (f) { onFiles([...item.files, { name: f.name, display: f.name, tool: "upload", size: f.size }]); onToast("文件已上传"); } }} />
        {item.files.length === 0 ? <p className="quiet-note">还没有可查看的文件</p> : item.files.map((f, i) => (
          <FileRow key={f.name} file={f} onToast={onToast}
            onRename={(display) => { onFiles(item.files.map((x, j) => (j === i ? { ...x, display } : x))); onToast("文件名称已保存"); }}
            onDelete={async () => { if (await onConfirm({ title: "删除文件", message: `确定删除「${f.display}」？`, confirmLabel: "删除", danger: true })) { onFiles(item.files.filter((_, j) => j !== i)); onToast("文件已删除"); } }} />
        ))}
        {!item.video && item.status === "succeeded" && !item.notice ? <p className="quiet-note">这个网址没有视频，已跳过视频下载。</p> : null}
      </section>
      {!waiting ? (
        <section>
          <div className="drawer-label">重新归档</div>
          <p className="drawer-help">会替换这条存档的文件。名称、标签和已读状态保持不变。</p>
          <label className="check"><input type="checkbox" checked={manual} onChange={(e) => setManual(e.target.checked)} /><span>保存前手动处理<small>先在内置浏览器里关弹窗、展开全文，再保存</small></span></label>
          <button className="btn" type="button" disabled={busy} onClick={() => onRearchive(manual)}><Icon name="refresh" size={15} />{manual ? "打开并等待处理" : "重新归档"}</button>
        </section>
      ) : null}
      <section>
        <div className="drawer-label">信息</div>
        <dl className="kv">
          <dt>状态</dt><dd>{statusText}</dd>
          <dt>来源</dt><dd>{item.source === "rss" ? `RSS · ${item.feed}` : "手动保存"}</dd>
          <dt>保存于</dt><dd>{fullDate(item.at)}</dd>
          <dt>完成于</dt><dd>{item.status === "succeeded" ? fullDate(item.finishedAt || item.at) : "—"}</dd>
          <dt>网站</dt><dd>{hostOf(item.url)}</dd>
          <dt>已读</dt><dd>{item.read ? "是" : "否"}</dd>
          <dt>名称</dt><dd>{item.renamed ? "已手动修改" : "使用网页标题"}</dd>
        </dl>
      </section>
      <section className="drawer-danger">
        <button className="link-danger" type="button" disabled={item.status === "running"} onClick={onDelete}><Icon name="trash" size={14} />{waiting ? "取消等待并删除" : "删除这条存档"}</button>
      </section>
    </aside>
  );
}

function Reader(props) {
  const { item, items, container, nav, onClose, listCollapsed, onToggleList, onOpenTab, allTags, mode, onMode, searchQuery,
    onTags, onRename, onToggleRead, detailsOpen, onDetails, onRearchive, onDelete, onOpenAction, onResume, onFiles, onSwitchVersion, onConfirm, onToast, tagInputRef, titleEditSignal } = props;
  const [editing, setEditing] = useUiState(false);
  const [draft, setDraft] = useUiState("");
  const [menu, setMenu, menuRef] = usePopover();
  useUiEffect(() => { setEditing(false); setMenu(null); }, [item && item.id]);
  useUiEffect(() => { if (titleEditSignal && item && item.status === "succeeded") { setDraft(item.title); setEditing(true); } }, [titleEditSignal]);

  if (!item) {
    return (
      <section className="reader empty">
        <div className="reader-empty"><img src="favicon.svg" alt="" /><p>选一条存档开始阅读</p><div className="shortcut-hints"><span><Kbd>J</Kbd><Kbd>K</Kbd> 上下</span><span><Kbd>N</Kbd> 保存网页</span><span><Kbd>?</Kbd> 全部快捷键</span></div></div>
      </section>
    );
  }
  const done = item.status === "succeeded";
  const versions = done ? versionsOf(items, item) : [];
  const startEdit = () => { setDraft(item.title); setEditing(true); };
  const commit = () => { const v = draft.trim(); if (v && v !== item.title) onRename(v); setEditing(false); };

  return (
    <section className={`reader in-${container}`}>
      <header className="reader-head compact">
        <div className="reader-bar">
          {container === "popup" ? <button className="ghost-icon" type="button" onClick={onClose} title="关闭 Esc"><Icon name="x" size={17} /></button> : null}
          {container === "split" ? <button className={`ghost-icon ${listCollapsed ? "on" : ""}`} type="button" onClick={onToggleList} title={listCollapsed ? "显示列表 [" : "收起列表，给网页更多宽度 ["}><Icon name="panelLeft" size={16} /></button> : null}
          {nav ? (
            <div className="reader-nav" title={nav.label}>
              <button className="ghost-icon" type="button" onClick={nav.onPrev} disabled={nav.index <= 1} title="上一条 K"><Icon name="chevronDown" size={15} className="rot180" /></button>
              <button className="ghost-icon" type="button" onClick={nav.onNext} disabled={nav.index >= nav.total} title="下一条 J"><Icon name="chevronDown" size={15} /></button>
              <span className="nav-pos">{nav.index} / {nav.total}</span>
            </div>
          ) : null}
          {editing ? (
            <input className="title-edit" autoFocus value={draft} maxLength={200} onChange={(e) => setDraft(e.target.value)} onBlur={commit} onKeyDown={(e) => { if (e.key === "Enter") { e.stopPropagation(); commit(); } if (e.key === "Escape") { e.stopPropagation(); setEditing(false); } }} />
          ) : (
            <h1 className={`reader-title ${done ? "" : "mono"}`} onClick={done ? startEdit : undefined} title={done ? `${item.title}\n点击修改名称 R` : item.title}>{item.title}</h1>
          )}
          <div className="reader-tools">
            {done ? <button type="button" className={`read-state ${item.read ? "is-read" : ""}`} onClick={onToggleRead} title={item.read ? "标为未读 E" : "标为已读 E"}><span className="rs-dot"></span>{item.read ? "已读" : "未读"}</button> : null}
            {versions.length > 1 ? (
              <div className="pop-anchor" ref={menu === "versions" ? menuRef : undefined}>
                <button type="button" className="chip-toggle" onClick={() => setMenu(menu === "versions" ? null : "versions")}><Icon name="layers" size={13} />{versions.length} 个版本</button>
                {menu === "versions" ? (
                  <div className="menu right">
                    <div className="menu-title">同一网址的保存版本</div>
                    {versions.map((v, i) => <button key={v.id} type="button" className={v.id === item.id ? "on" : ""} onClick={() => { setMenu(null); onSwitchVersion(v.id); }}><Icon name={v.id === item.id ? "check" : "history"} size={14} />{fullDate(v.at)}{i === 0 ? <span className="menu-note">最新</span> : null}</button>)}
                  </div>
                ) : null}
              </div>
            ) : null}
            {done ? (
              <div className="seg">
                <button type="button" className={mode === "archive" ? "on" : ""} onClick={() => onMode("archive")} title="存档原貌 V"><Icon name="page" size={14} />原貌</button>
                <button type="button" className={mode === "text" ? "on" : ""} onClick={() => onMode("text")} title="提取的正文 V"><Icon name="text" size={14} />正文</button>
                {item.video ? <button type="button" className={mode === "video" ? "on" : ""} onClick={() => onMode("video")} title="下载的视频"><Icon name="video" size={14} />视频</button> : null}
              </div>
            ) : null}
            {done && container !== "tab" ? <button className="ghost-icon" type="button" title="在新标签页阅读" onClick={onOpenTab}><Icon name="maximize" size={15} /></button> : null}
            <button className={`ghost-icon ${detailsOpen ? "on" : ""}`} type="button" title="详情、文件、重新归档 I" onClick={onDetails}><Icon name="info" size={16} /></button>
            <div className="pop-anchor" ref={menu === "more" ? menuRef : undefined}>
              <button className="ghost-icon" type="button" title="更多" onClick={() => setMenu(menu === "more" ? null : "more")}><Icon name="more" size={16} /></button>
              {menu === "more" ? (
                <div className="menu right">
                  {done ? <button type="button" onClick={() => { setMenu(null); startEdit(); }}><Icon name="pencil" size={14} />修改名称<Kbd>R</Kbd></button> : null}
                  {done ? <button type="button" onClick={() => { setMenu(null); onToggleRead(); }}><Icon name="check" size={14} />{item.read ? "标为未读" : "标为已读"}<Kbd>E</Kbd></button> : null}
                  {done ? <button type="button" onClick={() => { setMenu(null); onToast("在新标签打开 SingleFile 文件"); }}><Icon name="file" size={14} />打开存档文件</button> : null}
                  <button type="button" onClick={() => { setMenu(null); onToast("已复制原网址"); }}><Icon name="link" size={14} />复制原网址</button>
                  {item.status !== "manual_action_required" ? <button type="button" onClick={() => { setMenu(null); onDetails(true); }}><Icon name="refresh" size={14} />重新归档…</button> : null}
                  <hr />
                  <button type="button" className="danger" disabled={item.status === "running"} onClick={() => { setMenu(null); onDelete(); }}><Icon name="trash" size={14} />{item.status === "manual_action_required" ? "取消等待并删除" : "删除"}</button>
                </div>
              ) : null}
            </div>
          </div>
        </div>
        <div className="reader-meta">
          <span className="src-chip">{sourceName(item)}</span>
          <span className="meta-date">{fullDate(item.at)}</span>
          <a href={item.url} target="_blank" rel="noreferrer" className="orig-link" title="打开原网页 O">原网页<Icon name="external" size={12} /></a>
          {done ? <span className="meta-sep"></span> : null}
          {done ? <TagEditor item={item} allTags={allTags} onChange={onTags} inputRef={tagInputRef} /> : null}
        </div>
      </header>
      <div className="reader-body">
        {!done ? (
          <StatusPanel item={item} onOpenAction={onOpenAction} onResume={onResume} onRetry={onRearchive} onDelete={onDelete} />
        ) : mode === "archive" || (mode === "video" && !item.video) ? (
          <div className="frame-wrap bare"><div className="frame"><Snapshot item={item} /></div></div>
        ) : mode === "video" ? (
          <VideoPane />
        ) : (
          <TextView item={item} query={searchQuery} />
        )}
        {detailsOpen ? <DetailsDrawer item={item} onClose={() => onDetails(false)} onRearchive={onRearchive} onDelete={onDelete} onFiles={onFiles} onConfirm={onConfirm} onToast={onToast} /> : null}
      </div>
    </section>
  );
}

Object.assign(window, { viewLabel, AppSidebar, ListPane, Reader, usePopover });
