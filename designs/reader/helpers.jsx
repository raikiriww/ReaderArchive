// Data shaping + formatting helpers for the Reader redesign prototype.
const NOW = new Date("2026-10-13T10:30:00+08:00");

function hostOf(url) {
  try { return new URL(url).hostname.replace(/^www\./, ""); } catch { return ""; }
}

function sourceName(item) {
  // Matches the app: RSS items show their feed, everything saved by hand shows 手动.
  if (item.source === "rss") return item.feed || "RSS";
  return "手动";
}

// Detected site for a URL that is about to be saved (save dialog only).
function urlSiteLabel(url) {
  const host = hostOf(url);
  if (/(^|\.)weibo\.(com|cn)$/.test(host)) return "微博";
  if (host === "mp.weixin.qq.com") return "公众号";
  if (host === "x.com") return "X";
  return host;
}

// Weibo extracted text starts with visibility/date/client noise; drop it for reading.
function cleanBody(item) {
  let body = item.body || "";
  body = body.replace(/^公开\s*\S*?\s*\d{2}-\d{1,2}-\d{1,2}\s*\d{1,2}:\d{2}\s*(发布于\s*\S+)?\s*(来自\s*(?:微博 weibo\.com|\S+))?\s*(已编辑)?/, "");
  return body.trim();
}

// Timestamps are stored in UTC.
function parseAt(at) { return new Date(at.replace(" ", "T") + ":00Z"); }

function dayDiff(date) {
  const a = new Date(NOW); a.setHours(0, 0, 0, 0);
  const b = new Date(date); b.setHours(0, 0, 0, 0);
  return Math.round((a - b) / 86400000);
}

function shortDate(at) {
  const d = parseAt(at);
  const diff = dayDiff(d);
  const hm = `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
  if (diff === 0) return hm;
  if (diff === 1) return "昨天";
  if (diff < 7) return `${diff} 天前`;
  if (d.getFullYear() === NOW.getFullYear()) return `${d.getMonth() + 1}月${d.getDate()}日`;
  return `${d.getFullYear()}/${d.getMonth() + 1}/${d.getDate()}`;
}

function fullDate(at) {
  const d = parseAt(at);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")} ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

function dayGroup(at) {
  const diff = dayDiff(parseAt(at));
  if (diff === 0) return "今天";
  if (diff === 1) return "昨天";
  if (diff < 7) return "本周";
  if (diff < 31) return "本月";
  return "更早";
}

// Extracted text has no paragraph breaks; regroup every few sentences for reading.
function paragraphs(text, per = 3) {
  const sentences = text.split(/(?<=[。！？])|(?<=[.!?])\s+/).filter((x) => x.trim());
  const out = [];
  for (let i = 0; i < sentences.length; i += per) out.push(sentences.slice(i, i + per).join(" ").replace(/([。！？])\s/g, "$1"));
  return out;
}

function highlight(text, q) {
  if (!q) return text;
  const parts = text.split(new RegExp(`(${q.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")})`, "ig"));
  return parts.map((p, i) => (p.toLowerCase() === q.toLowerCase() ? <mark key={i}>{p}</mark> : p));
}

function excerptAround(text, q, len = 90) {
  const i = text.toLowerCase().indexOf(q.toLowerCase());
  if (i < 0) return text.slice(0, len);
  const start = Math.max(0, i - 30);
  return (start ? "…" : "") + text.slice(start, start + len) + "…";
}

function buildItems() {
  return window.RA_ITEMS.map((it) => ({ ...it, body: it.body || "", size: 180 + ((it.title.length * 37) % 900) }));
}

Object.assign(window, { NOW, hostOf, sourceName, urlSiteLabel, cleanBody, parseAt, shortDate, fullDate, dayGroup, highlight, excerptAround, paragraphs, buildItems });
