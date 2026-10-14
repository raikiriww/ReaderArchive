// Full prototype app: state owner, keyboard, three open modes, standalone reader tab.
const { useState, useEffect, useMemo, useRef, useCallback } = React;

const TWEAKS_KEY = "ra-proto-tweaks";
const TWEAK_DEFAULTS = { open: "popup", theme: "teal", density: "comfortable" };
function loadProtoTweaks() { try { return { ...TWEAK_DEFAULTS, ...JSON.parse(localStorage.getItem(TWEAKS_KEY) || "{}") }; } catch { return TWEAK_DEFAULTS; } }
function loadRecent() { try { return JSON.parse(sessionStorage.getItem("ra-proto-recent") || "[]"); } catch { return []; } }
function routeId() { const m = /#read=([^&]+)/.exec(location.hash); return m ? decodeURIComponent(m[1]) : null; }
function routeQuery() { const m = /[#&]q=([^&]+)/.exec(location.hash); return m ? decodeURIComponent(m[1]) : ""; }

function groupByDay(list) {
  const map = new Map();
  list.forEach((it) => { const k = dayGroup(it.at); if (!map.has(k)) map.set(k, []); map.get(k).push(it); });
  return [...map.entries()];
}

function useData() {
  const [data, setData] = useState(loadState);
  useEffect(() => { saveState(data); }, [data]);
  useEffect(() => {
    // Keep the list tab and reader tabs in sync.
    const onStorage = (e) => { if (e.key === STORE_KEY) setData(loadState()); };
    window.addEventListener("storage", onStorage);
    return () => window.removeEventListener("storage", onStorage);
  }, []);
  const setItems = useCallback((fn) => setData((d) => ({ ...d, items: typeof fn === "function" ? fn(d.items) : fn })), []);
  const update = useCallback((id, patch) => setItems((list) => list.map((it) => (it.id === id ? { ...it, ...(typeof patch === "function" ? patch(it) : patch) } : it))), [setItems]);
  return { data, setData, setItems, update };
}

function useToast() {
  const [toast, setToast] = useState(null);
  const timer = useRef(null);
  const show = useCallback((msg, undo) => { setToast({ msg, undo }); clearTimeout(timer.current); timer.current = setTimeout(() => setToast(null), 3600); }, []);
  const node = toast ? <div className="toast" role="status"><span>{toast.msg}</span>{toast.undo ? <button type="button" onClick={() => { toast.undo(); setToast(null); }}>撤销</button> : null}</div> : null;
  return [show, node];
}

function useConfirm() {
  const [req, setReq] = useState(null);
  const ask = useCallback((r) => new Promise((resolve) => setReq({ ...r, resolve })), []);
  const node = req ? <ConfirmDialog req={req} onDone={(v) => { req.resolve(v); setReq(null); }} /> : null;
  return [ask, node, Boolean(req)];
}

/* Shared item actions used by both the main app and the reader tab. */
function useItemActions({ items, setItems, update, showToast, ask }) {
  const simulate = useCallback((id, prepare) => {
    if (prepare) { update(id, { status: "manual_action_required", tab: "not_opened", action: "page.prepare_manually" }); return; }
    update(id, { status: "queued", step: null });
    setTimeout(() => update(id, { status: "running", step: "保存网页和下载视频" }), 900);
    setTimeout(() => update(id, { step: "提取正文、建立索引" }), 2000);
    setTimeout(() => update(id, (it) => {
      const fresh = it.title === it.url || it.title === it.url.replace(/^https?:\/\//, "");
      const title = fresh ? `新保存的页面 · ${hostOf(it.url)}` : it.title;
      const next = { ...it, status: "succeeded", title, body: it.body || "这是原型里模拟保存完成的页面。真实环境里这里会显示 SingleFile 快照。", size: it.size || 420, finishedAt: "2026-10-13T02:31", error: null, tab: null };
      return { ...next, files: it.files.length ? it.files : defaultFiles(next) };
    }), 3200);
  }, [update]);

  const toggleRead = useCallback((it) => {
    if (!it || it.status !== "succeeded") return;
    update(it.id, { read: !it.read });
    showToast(it.read ? "已标为未读" : "已标为已读", () => update(it.id, { read: it.read }));
  }, [update, showToast]);

  const remove = useCallback(async (it, after) => {
    const waiting = it.status === "manual_action_required";
    const ok = await ask({ title: waiting ? "取消等待并删除" : "删除存档", message: waiting ? "会关闭这个任务的处理页面，并删除任务和已有文件。" : "这条存档和它的文件都会被删除。", confirmLabel: waiting ? "取消并删除" : "删除", danger: true });
    if (!ok) return false;
    setItems((list) => list.filter((x) => x.id !== it.id));
    if (after) after();
    showToast("已删除");
    return true;
  }, [ask, setItems, showToast]);

  return { simulate, toggleRead, remove };
}

/* ======================= Main app ======================= */
function App() {
  const { data, setData, setItems, update } = useData();
  const { items, feeds, users, config } = data;
  const [authed, setAuthed] = useState(() => sessionStorage.getItem("ra-proto-out") !== "1");
  const [tweaks, setTweaks] = useState(loadProtoTweaks);
  const [view, setView] = useState({ kind: "inbox" });
  const [listFilter, setListFilter] = useState("all");
  const [sourceFilter, setSourceFilter] = useState("all");
  const [unreadOnly, setUnreadOnly] = useState(true);
  const [query, setQuery] = useState("");
  const [filters, setFilters] = useState(SEARCH_DEFAULTS);
  const [showPossible, setShowPossible] = useState(false);
  const [recent, setRecent] = useState(loadRecent);
  const [selectedId, setSelectedId] = useState(null);
  const [stickyIds, setStickyIds] = useState([]);
  const [readerOpen, setReaderOpen] = useState(false);
  const [listCollapsed, setListCollapsed] = useState(false);
  const [mode, setMode] = useState("archive");
  const [detailsOpen, setDetailsOpen] = useState(false);
  const [save, setSave] = useState(null);
  const [settings, setSettings] = useState(null);
  const [feedsOpen, setFeedsOpen] = useState(false);
  const [helpOpen, setHelpOpen] = useState(false);
  const [titleEditSignal, setTitleEditSignal] = useState(0);
  const [showToast, toastNode] = useToast();
  const [ask, confirmNode, confirming] = useConfirm();
  const searchRef = useRef(null);
  const tagInputRef = useRef(null);
  const actions = useItemActions({ items, setItems, update, showToast, ask });
  const openMode = tweaks.open;
  const currentUser = users.find((u) => u.role === "admin") || users[0] || { id: "u-admin", username: "admin", role: "admin" };

  useEffect(() => { try { localStorage.setItem(TWEAKS_KEY, JSON.stringify(tweaks)); } catch {} document.documentElement.dataset.theme = tweaks.theme; document.documentElement.dataset.density = tweaks.density; }, [tweaks]);
  useEffect(() => { setReaderOpen(false); setDetailsOpen(false); }, [openMode]);

  /* ---- derived ---- */
  const feedStats = useMemo(() => feeds.map((f) => ({ ...f, unread: items.filter((i) => i.feed === f.name && !i.read).length })), [feeds, items]);
  const tagCounts = useMemo(() => { const m = new Map(); items.forEach((i) => i.tags.forEach((t) => m.set(t, (m.get(t) || 0) + 1))); return [...m.entries()].sort((a, b) => b[1] - a[1]); }, [items]);
  const counts = useMemo(() => ({
    inbox: items.filter((i) => !i.read || i.status !== "succeeded").length,
    attention: items.filter((i) => i.status === "failed" || i.status === "manual_action_required").length,
    feedUnread: feedStats.reduce((n, f) => n + f.unread, 0),
  }), [items, feedStats]);

  const searching = Boolean(query.trim());
  const results = useMemo(() => (searching ? searchItems(items, query, filters) : []), [items, query, filters, searching]);

  const inView = useCallback((it) => {
    if (view.kind === "inbox") return !it.read || it.status !== "succeeded";
    if (view.kind === "feed") return it.source === "rss" && (!view.value || it.feed === view.value) && (!unreadOnly || !it.read);
    if (view.kind === "tag") return view.value.every((t) => it.tags.includes(t));
    if (sourceFilter !== "all" && it.source !== sourceFilter) return false;
    if (listFilter === "unread") return !it.read;
    if (listFilter === "issue") return it.status !== "succeeded" || Boolean(it.notice);
    return true;
  }, [view, unreadOnly, listFilter, sourceFilter]);

  const flat = useMemo(() => {
    const list = items.filter((it) => inView(it) || stickyIds.includes(it.id));
    if (view.kind === "inbox") return [...list].sort((a, b) => Number(a.status === "succeeded") - Number(b.status === "succeeded") || (a.at < b.at ? 1 : -1));
    return [...list].sort((a, b) => (a.at < b.at ? 1 : -1));
  }, [items, inView, stickyIds, view]);

  const groups = useMemo(() => {
    if (view.kind === "inbox") {
      const need = flat.filter((i) => i.status !== "succeeded");
      const rest = flat.filter((i) => i.status === "succeeded");
      return [...(need.length ? [["需要处理", need]] : []), ...groupByDay(rest)];
    }
    return groupByDay(flat);
  }, [flat, view]);

  const ordered = useMemo(() => {
    if (!searching) return groups.flatMap(([, g]) => g);
    const firstStrong = results.findIndex((r) => r.strength === "strong");
    return results.filter((r, i) => showPossible || !(r.strength === "possible" && firstStrong >= 0 && i > firstStrong)).map((r) => r.item);
  }, [groups, searching, results, showPossible]);

  const selected = items.find((i) => i.id === selectedId) || null;
  const selIndex = ordered.findIndex((i) => i.id === selectedId);
  const relatedTags = useMemo(() => {
    if (view.kind !== "tag") return [];
    const m = new Map();
    items.filter((it) => view.value.every((t) => it.tags.includes(t))).forEach((it) => it.tags.forEach((t) => { if (!view.value.includes(t)) m.set(t, (m.get(t) || 0) + 1); }));
    return [...m.entries()].sort((a, b) => b[1] - a[1]).slice(0, 6);
  }, [items, view]);

  const readerVisible = openMode === "split" ? Boolean(selected) : openMode === "popup" && readerOpen && Boolean(selected);

  /* ---- navigation ---- */
  function changeView(v) {
    setView(v); setQuery(""); setStickyIds([]); setSelectedId(null); setReaderOpen(false); setDetailsOpen(false); setListFilter("all"); setSourceFilter("all");
  }
  function select(id) {
    // Only the item being read stays pinned; anything that no longer fits the view leaves once you move on.
    setStickyIds([id]);
    setSelectedId(id);
  }
  function openTab(id) {
    select(id);
    const q = searching ? `&q=${encodeURIComponent(query.trim())}` : "";
    window.open(`prototype.html#read=${encodeURIComponent(id)}${q}`, "_blank");
  }
  function openItem(id, e) {
    if (e && (e.metaKey || e.ctrlKey || e.button === 1)) { openTab(id); return; }
    if (openMode === "tab") { openTab(id); return; }
    select(id);
    if (openMode === "popup") setReaderOpen(true);
  }
  function move(delta) {
    if (!ordered.length) return;
    const i = selIndex < 0 ? (delta > 0 ? 0 : ordered.length - 1) : Math.min(ordered.length - 1, Math.max(0, selIndex + delta));
    select(ordered[i].id);
  }
  function commitSearch(q) {
    const v = q.trim();
    if (!v) return;
    const next = [v, ...recent.filter((r) => r !== v)].slice(0, 6);
    setRecent(next);
    try { sessionStorage.setItem("ra-proto-recent", JSON.stringify(next)); } catch {}
  }
  function closeReader() {
    // Closing the reader drops items that no longer belong here (e.g. just marked read) and keeps the cursor nearby.
    if (!searching && selected && !inView(selected)) {
      const i = ordered.findIndex((x) => x.id === selected.id);
      const rest = ordered.filter((x) => x.id === selected.id || inView(x));
      const after = ordered.slice(i + 1).find((x) => inView(x)) || ordered.slice(0, i).reverse().find((x) => inView(x));
      setSelectedId(rest.length > 1 && after ? after.id : null);
    }
    setStickyIds([]);
    setReaderOpen(false);
  }
  function focusSearch() { closeReader(); requestAnimationFrame(() => { searchRef.current?.focus(); searchRef.current?.select(); }); }

  /* ---- item actions ---- */
  function submitSave({ url, tags, prepare }) {
    const id = `new-${Date.now()}`;
    const item = { id, url, title: url.replace(/^https?:\/\//, ""), renamed: false, status: "queued", source: "manual", feed: null, read: false, at: "2026-10-13T02:30", video: false, tags, body: "", size: 0, files: [], notice: null };
    setItems((list) => [item, ...list]);
    setSave(null);
    if (view.kind !== "inbox" || searching) changeView({ kind: "inbox" });
    setSelectedId(id);
    setStickyIds((s) => [...s, id]);
    actions.simulate(id, prepare);
    showToast(prepare ? "已创建任务。打开处理页面，处理好后点「处理完成」" : "已开始保存，完成后在「未读」里阅读");
  }
  function markAllRead() {
    const ids = flat.filter((i) => !i.read).map((i) => i.id);
    setItems((list) => list.map((it) => (ids.includes(it.id) ? { ...it, read: true } : it)));
    setStickyIds((s) => [...new Set([...s, ...ids])]);
    showToast(`已将 ${ids.length} 条标为已读`, () => setItems((list) => list.map((it) => (ids.includes(it.id) ? { ...it, read: false } : it))));
  }
  async function removeSelected() {
    if (!selected) return;
    const idx = ordered.findIndex((x) => x.id === selected.id);
    const nextId = ordered[idx + 1]?.id || ordered[idx - 1]?.id || null;
    await actions.remove(selected, () => { setSelectedId(nextId); setDetailsOpen(false); if (!nextId) setReaderOpen(false); });
  }

  /* ---- keyboard + paste ---- */
  useEffect(() => {
    function onKey(e) {
      const typing = /INPUT|TEXTAREA|SELECT/.test(document.activeElement?.tagName || "");
      const dialog = confirming || save || settings || feedsOpen || helpOpen;
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") { e.preventDefault(); if (!dialog) focusSearch(); return; }
      if (e.key === "Escape") {
        if (confirming) return;
        if (save) setSave(null); else if (settings) setSettings(null); else if (feedsOpen) setFeedsOpen(false); else if (helpOpen) setHelpOpen(false);
        else if (detailsOpen) setDetailsOpen(false); else if (openMode === "popup" && readerOpen) closeReader();
        else if (query && !typing) setQuery("");
        return;
      }
      if (typing || dialog || e.defaultPrevented || e.metaKey || e.ctrlKey || e.altKey) return;
      const k = e.key;
      const canAct = Boolean(selected) && (readerVisible || openMode !== "split");
      if (k === "j" || k === "ArrowDown") { e.preventDefault(); move(1); }
      else if (k === "k" || k === "ArrowUp") { e.preventDefault(); move(-1); }
      else if (k === "Enter" && selected) { e.preventDefault(); if (e.shiftKey || openMode === "tab") openTab(selected.id); else if (openMode === "popup") setReaderOpen(true); }
      else if (k === "e" && canAct) actions.toggleRead(selected);
      else if (k === "t" && readerVisible && selected.status === "succeeded") { e.preventDefault(); tagInputRef.current?.focus(); }
      else if (k === "r" && readerVisible) { e.preventDefault(); setTitleEditSignal((n) => n + 1); }
      else if (k === "v" && readerVisible) setMode((m) => (m === "archive" ? "text" : "archive"));
      else if (k === "i" && readerVisible) setDetailsOpen((v) => !v);
      else if (k === "o" && selected) showToast("在新标签打开原网页");
      else if (k === "n") { e.preventDefault(); setSave({ url: "" }); }
      else if (k === "/") { e.preventDefault(); focusSearch(); }
      else if (k === "[" && openMode === "split") setListCollapsed((v) => !v);
      else if (k === "?") setHelpOpen(true);
    }
    function onPaste(e) {
      if (/INPUT|TEXTAREA/.test(document.activeElement?.tagName || "") || save || settings || feedsOpen) return;
      const text = (e.clipboardData?.getData("text") || "").trim();
      if (/^https?:\/\/\S+$/.test(text)) { e.preventDefault(); setSave({ url: text }); }
    }
    window.addEventListener("keydown", onKey);
    window.addEventListener("paste", onPaste);
    return () => { window.removeEventListener("keydown", onKey); window.removeEventListener("paste", onPaste); };
  });

  if (!authed) return <LoginScreen onLogin={() => { sessionStorage.removeItem("ra-proto-out"); setAuthed(true); }} />;

  /* ---- list header per view ---- */
  const subtitle = view.kind === "inbox" ? "所有还没读的存档（手动保存和订阅），以及需要你处理的任务" : `${flat.length} 条`;
  const header = (
    <header className="list-head-wrap">
      <div className="list-head">
        <div className="list-title">
          <h1>{view.kind === "tag" ? <><Icon name="hash" size={17} />{viewLabel(view)}</> : view.kind === "feed" ? <><Icon name="rss" size={16} />{viewLabel(view)}</> : viewLabel(view)}</h1>
          <p>{subtitle}</p>
        </div>
        {view.kind === "all" ? (
          <div className="list-head-actions">
            <div className="mini-seg" aria-label="来源">
              {[["all", "全部来源"], ["manual", "手动保存"], ["rss", "订阅"]].map(([v, l]) => <button key={v} type="button" className={sourceFilter === v ? "on" : ""} onClick={() => setSourceFilter(v)}>{l}</button>)}
            </div>
            <div className="mini-seg" aria-label="状态">
              {[["all", "全部"], ["unread", "未读"], ["issue", "有问题"]].map(([v, l]) => <button key={v} type="button" className={listFilter === v ? "on" : ""} onClick={() => setListFilter(v)}>{l}</button>)}
            </div>
          </div>
        ) : null}
      </div>
      {view.kind === "tag" ? (
        <div className="scope-row">
          {view.value.length > 1 ? view.value.map((t) => <button key={t} className="chip-toggle on" type="button" onClick={() => setView((v) => ({ kind: "tag", value: v.value.filter((x) => x !== t) }))}>{t}<Icon name="x" size={12} /></button>) : null}
          {relatedTags.length ? <span className="scope-label">再加一个标签：</span> : null}
          {relatedTags.map(([t, n]) => <button key={t} className="chip-toggle" type="button" onClick={() => { setView((v) => ({ kind: "tag", value: [...v.value, t] })); setSelectedId(null); }}>+ {t}<span className="chip-count">{n}</span></button>)}
        </div>
      ) : null}
    </header>
  );

  const readerProps = selected ? {
    item: selected, items, allTags: tagCounts, mode, onMode: setMode, searchQuery: searching ? query : "",
    nav: { label: searching ? "搜索结果" : viewLabel(view), index: selIndex + 1, total: ordered.length, onPrev: () => move(-1), onNext: () => move(1) },
    onTags: (tags) => update(selected.id, { tags }),
    onRename: (title) => { update(selected.id, { title, renamed: true }); showToast("名称已保存"); },
    onToggleRead: () => actions.toggleRead(selected),
    detailsOpen, onDetails: (v) => setDetailsOpen((x) => (typeof v === "boolean" ? v : !x)),
    onRearchive: async (prepare) => {
      setDetailsOpen(false);
      actions.simulate(selected.id, prepare);
      showToast(prepare ? "已创建任务。打开处理页面，处理好后点「处理完成」" : "已开始重新归档");
    },
    onDelete: removeSelected,
    onOpenAction: () => { update(selected.id, { tab: "available" }); showToast("已在内置浏览器打开处理页面（新标签）"); },
    onResume: () => { actions.simulate(selected.id, false); showToast("正在保存你处理好的页面"); },
    onFiles: (files) => update(selected.id, { files }),
    onSwitchVersion: (id) => select(id),
    onConfirm: ask, onToast: showToast, tagInputRef, titleEditSignal,
    onOpenTab: () => openTab(selected.id),
  } : null;

  const wideList = openMode !== "split";
  return (
    <div className={`app2 open-${openMode} ${openMode === "split" && listCollapsed ? "list-collapsed" : ""}`}>
      <AppSidebar rail={openMode === "split"} view={view} onView={changeView} counts={counts} feeds={feedStats} tags={tagCounts} user={currentUser}
        onSave={() => setSave({ url: "" })} onSearch={focusSearch} onManageFeeds={() => setFeedsOpen(true)} onSettings={(s) => setSettings(s)}
        onLogout={() => { sessionStorage.setItem("ra-proto-out", "1"); setAuthed(false); }} onBrowser={() => showToast("在新标签打开内置浏览器桌面")} />
      <ListPane wide={wideList} view={view} groups={groups} flat={flat} searching={searching} query={query} results={results}
        showPossible={showPossible} onShowPossible={setShowPossible} selectedId={selectedId} onOpen={openItem}
        searchProps={{ inputRef: searchRef, query, onQuery: (q) => { setQuery(q); setShowPossible(false); }, onCommit: commitSearch, recent, onClearRecent: () => { setRecent([]); try { sessionStorage.removeItem("ra-proto-recent"); } catch {} } }}
        filterProps={{ filters, onFilters: setFilters, tags: tagCounts }} header={header} />
      {openMode === "split" ? <Reader container="split" {...(readerProps || { item: null })} listCollapsed={listCollapsed} onToggleList={() => setListCollapsed((v) => !v)} /> : null}
      {openMode === "popup" && readerOpen && readerProps ? (
        <div className="reader-pop-layer" onMouseDown={(e) => { if (e.target === e.currentTarget) closeReader(); }}>
          <div className="reader-pop"><Reader container="popup" {...readerProps} onClose={closeReader} /></div>
        </div>
      ) : null}
      {save ? <SaveDialog initialUrl={save.url} items={items} allTags={tagCounts} onClose={() => setSave(null)} onSubmit={submitSave} /> : null}
      {settings ? <SettingsDialog section={settings} onSection={setSettings} config={config} onConfig={(c) => setData((d) => ({ ...d, config: c }))} users={users} onUsers={(u) => setData((d) => ({ ...d, users: u }))} currentUser={currentUser} onClose={() => setSettings(null)} onConfirm={ask} onToast={showToast} /> : null}
      {feedsOpen ? <FeedsDialog feeds={feeds} onFeeds={(f) => setData((d) => ({ ...d, feeds: f }))} onRefresh={(f) => { setData((d) => ({ ...d, feeds: d.feeds.map((x) => (x.id === f.id ? { ...x, checked: "2026-10-13T02:31" } : x)) })); showToast(`「${f.name}」检查完成，创建 0 个存档任务`); }} onClose={() => setFeedsOpen(false)} onConfirm={ask} onToast={showToast} /> : null}
      {helpOpen ? <ShortcutHelp openMode={openMode} onClose={() => setHelpOpen(false)} /> : null}
      {confirmNode}
      {toastNode}
      <Tweaks tweaks={tweaks} setTweaks={setTweaks} onReset={() => { resetState(); location.reload(); }} />
    </div>
  );
}

/* ======================= Reader in its own tab ======================= */
function ReaderTab({ id }) {
  const { data, setItems, update } = useData();
  const { items } = data;
  const [showToast, toastNode] = useToast();
  const [ask, confirmNode] = useConfirm();
  const [mode, setMode] = useState("archive");
  const [detailsOpen, setDetailsOpen] = useState(false);
  const [titleEditSignal, setTitleEditSignal] = useState(0);
  const [currentId, setCurrentId] = useState(id);
  const tagInputRef = useRef(null);
  const actions = useItemActions({ items, setItems, update, showToast, ask });
  const item = items.find((i) => i.id === currentId) || null;
  const tweaks = loadProtoTweaks();
  const tagCounts = useMemo(() => { const m = new Map(); items.forEach((i) => i.tags.forEach((t) => m.set(t, (m.get(t) || 0) + 1))); return [...m.entries()].sort((a, b) => b[1] - a[1]); }, [items]);
  useEffect(() => { document.documentElement.dataset.theme = tweaks.theme; document.documentElement.dataset.density = tweaks.density; }, []);
  useEffect(() => { document.title = item ? `${item.title.slice(0, 40)} · Reader Archive` : "Reader Archive"; }, [item && item.title]);
  useEffect(() => {
    function onKey(e) {
      if (/INPUT|TEXTAREA|SELECT/.test(document.activeElement?.tagName || "") || e.metaKey || e.ctrlKey || !item) return;
      if (e.key === "e") actions.toggleRead(item);
      else if (e.key === "t") { e.preventDefault(); tagInputRef.current?.focus(); }
      else if (e.key === "r") { e.preventDefault(); setTitleEditSignal((n) => n + 1); }
      else if (e.key === "v") setMode((m) => (m === "archive" ? "text" : "archive"));
      else if (e.key === "i") setDetailsOpen((v) => !v);
      else if (e.key === "Escape") setDetailsOpen(false);
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  return (
    <div className="tab-page">
      <div className="tab-strip"><a href="prototype.html" className="tab-brand"><img src="favicon.svg" alt="" />Reader Archive</a><span>这是独立的阅读标签页。在这里改的标签、名称和已读状态，会同步到列表页。</span></div>
      {item ? (
        <Reader container="tab" item={item} items={items} allTags={tagCounts} mode={mode} onMode={setMode} searchQuery={routeQuery()}
          onTags={(tags) => update(item.id, { tags })} onRename={(title) => { update(item.id, { title, renamed: true }); showToast("名称已保存"); }}
          onToggleRead={() => actions.toggleRead(item)} detailsOpen={detailsOpen} onDetails={(v) => setDetailsOpen((x) => (typeof v === "boolean" ? v : !x))}
          onRearchive={(p) => { setDetailsOpen(false); actions.simulate(item.id, p); showToast(p ? "已创建任务，等待手动处理" : "已开始重新归档"); }}
          onDelete={() => actions.remove(item, () => setTimeout(() => window.close(), 400))}
          onOpenAction={() => { update(item.id, { tab: "available" }); showToast("已在内置浏览器打开处理页面"); }}
          onResume={() => actions.simulate(item.id, false)} onFiles={(files) => update(item.id, { files })} onSwitchVersion={setCurrentId}
          onConfirm={ask} onToast={showToast} tagInputRef={tagInputRef} titleEditSignal={titleEditSignal} />
      ) : <div className="list-empty"><p>这条存档不存在，可能已经被删除。</p><a className="text-btn" href="prototype.html">回到 Reader</a></div>}
      {confirmNode}
      {toastNode}
    </div>
  );
}

const rid = routeId();
ReactDOM.createRoot(document.getElementById("root")).render(rid ? <ReaderTab id={rid} /> : <App />);
