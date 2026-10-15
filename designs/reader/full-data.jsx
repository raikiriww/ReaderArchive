// Prototype data layer: items, feeds, users, config, search simulation, cross-tab persistence.
const STORE_KEY = "ra-proto-state-v3";

function defaultFiles(it) {
  if (it.status !== "succeeded") return [];
  const files = [{ name: `${it.id}.html`, display: `${it.title.slice(0, 36)}.html`, tool: "singlefile", size: it.size * 1024 }];
  if (it.video) files.push({ name: `${it.id}.mp4`, display: "video.mp4", tool: "yt-dlp", size: 25800000 });
  return files;
}

function buildFullItems() {
  const base = buildItems();
  const notices = {
    d09: "网页已保存，视频未保存：HTTP Error 403: Forbidden",
  };
  const list = base.map((it) => ({
    ...it,
    finishedAt: it.at,
    notice: notices[it.id] || null,
    files: null,
  }));
  const demo = [
    { id: "demo-queued", url: "https://example.org/weekly/issue-121.html", title: "example.org/weekly/issue-121.html", status: "queued", source: "manual", read: false, at: "2026-10-13T02:27", tags: [], body: "", video: false, size: 0 },
    { id: "demo-run", url: "https://example.net/video/desk-setup", title: "example.net/video/desk-setup", status: "running", step: "保存网页和下载视频", source: "manual", read: false, at: "2026-10-13T02:24", tags: ["视频"], body: "", video: false, size: 0 },
    { id: "demo-wait", url: "https://example.com/members/article-42", title: "example.com/members/article-42", status: "manual_action_required", tab: "available", action: "page.prepare_manually", source: "manual", read: false, at: "2026-10-13T01:58", tags: [], body: "", video: false, size: 0 },
    { id: "demo-lost", url: "https://example.org/forum/thread/1024", title: "example.org/forum/thread/1024", status: "manual_action_required", tab: "missing", action: "page.login_required", source: "manual", read: false, at: "2026-10-12T23:10", tags: [], body: "", video: false, size: 0 },
    { id: "demo-vwait", url: "https://example.com/video/members-only", title: "example.com/video/members-only", status: "manual_action_required", tab: "available", action: "video.login_required", notice: "网页已保存，视频需要登录后下载", source: "manual", read: false, at: "2026-10-12T20:05", tags: [], body: "", video: false, size: 0 },
    { id: "demo-fail", url: "https://example.net/private/post/77", title: "example.net/private/post/77", status: "failed", error: "页面需要登录才能查看，SingleFile 保存下来的是登录页。", source: "manual", read: false, at: "2026-10-12T14:41", tags: [], body: "", video: false, size: 0 },
  ];
  return [...demo, ...list].map((it) => ({ renamed: false, feed: null, notice: null, ...it, files: it.files || defaultFiles(it) }));
}

const DEFAULT_FEEDS = [
  { id: "f-hn", name: "Hacker News Daily", url: "https://example.com/hn-daily/index.rss", enabled: true, checked: "2026-10-13T02:15", error: null },
  { id: "f-wk", name: "技术周刊", url: "https://example.org/weekly/feed.xml", enabled: true, checked: "2026-10-13T02:15", error: null },
];

const DEFAULT_USERS = [
  { id: "u-admin", username: "admin", role: "admin", enabled: true },
];

const DEFAULT_CONFIG = {
  desktop_url: "/browser/",
  poll_seconds: 4,
  rss_minutes: 30,
  semantic: { status: "ready", model: "Qwen3-Embedding-0.6B", dims: 1024, indexed: 17, failed: 0, error: null },
};

function loadState() {
  try {
    const raw = JSON.parse(localStorage.getItem(STORE_KEY) || "null");
    if (raw && Array.isArray(raw.items)) return raw;
  } catch {}
  return { items: buildFullItems(), feeds: DEFAULT_FEEDS, users: DEFAULT_USERS, config: DEFAULT_CONFIG };
}

function saveState(state) {
  try { localStorage.setItem(STORE_KEY, JSON.stringify(state)); } catch {}
}

function resetState() {
  try { localStorage.removeItem(STORE_KEY); } catch {}
}

function versionsOf(items, item) {
  return items.filter((it) => it.url === item.url && it.status === "succeeded").sort((a, b) => (a.at < b.at ? 1 : -1));
}

function formatSize(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

/* ---------- search simulation (mirrors /archive-search semantics) ---------- */
const SEARCH_DEFAULTS = { content_type: "all", source: "", date_from: "", tags: [], include_read: true, exact: false, sort: "relevance" };

function searchItems(items, rawQuery, f) {
  const q = rawQuery.trim();
  if (!q) return [];
  const phrase = /^".+"$/.test(q) ? q.slice(1, -1) : null;
  const needle = (phrase || q).toLowerCase();
  const pool = items.filter((it) => {
    if (it.status !== "succeeded") return false;
    if (f.content_type === "web" && it.video) return false;
    if (f.content_type === "video" && !it.video) return false;
    if (f.content_type === "file" && !it.files.some((x) => x.tool === "upload")) return false;
    if (f.source && it.source !== f.source) return false;
    if (f.date_from && parseAt(it.at) < new Date(`${f.date_from}T00:00:00`)) return false;
    if (f.tags.length && !f.tags.every((t) => it.tags.includes(t))) return false;
    if (!f.include_read && it.read) return false;
    return true;
  });
  const results = [];
  pool.forEach((it) => {
    const body = cleanBody(it);
    let kind = null;
    if (it.title.toLowerCase().includes(needle)) kind = "title";
    else if (it.tags.some((t) => t.toLowerCase().includes(needle))) kind = "tag";
    else if (it.url.toLowerCase().includes(needle)) kind = "url";
    else if (body.toLowerCase().includes(needle)) kind = "body";
    if (kind) {
      const score = { title: 4, tag: 3, url: 2, body: 1 }[kind];
      results.push({ item: it, kind, strength: "strong", score, excerpt: kind === "body" ? excerptAround(body, needle, 120) : body.slice(0, 120) });
      return;
    }
    // "Similar meaning" stand-in: share at least two 2-char chunks with the query.
    if (f.exact || phrase || needle.length < 3) return;
    const chunks = [];
    for (let i = 0; i < needle.length - 1; i++) chunks.push(needle.slice(i, i + 2));
    const hit = [...new Set(chunks)].filter((c) => c.trim().length === 2 && body.toLowerCase().includes(c));
    if (hit.length >= 2) results.push({ item: it, kind: "semantic", strength: "possible", score: hit.length / 10, excerpt: excerptAround(body, hit[0], 120), hint: hit[0] });
  });
  // Group identical URLs into one result with a version count.
  const seen = new Map();
  const grouped = [];
  results.forEach((r) => {
    const prev = seen.get(r.item.url);
    if (prev) { prev.versions += 1; return; }
    const g = { ...r, versions: 1 };
    seen.set(r.item.url, g);
    grouped.push(g);
  });
  if (f.sort === "newest") grouped.sort((a, b) => (a.item.at < b.item.at ? 1 : -1));
  else if (f.sort === "oldest") grouped.sort((a, b) => (a.item.at > b.item.at ? 1 : -1));
  else grouped.sort((a, b) => b.score - a.score || (a.item.at < b.item.at ? 1 : -1));
  return grouped;
}

const MATCH_LABELS = { title: "标题命中", tag: "标签命中", url: "网址命中", body: "正文命中", semantic: "意思可能相关" };

Object.assign(window, { STORE_KEY, loadState, saveState, resetState, versionsOf, formatSize, SEARCH_DEFAULTS, searchItems, MATCH_LABELS, defaultFiles });
