import { describe, expect, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import { Highlighted } from "../src/features/search/Highlighted";
import type { SearchMatch } from "../src/features/search/api";

const match = (excerpt: string, highlights: SearchMatch["highlights"]): SearchMatch => ({ excerpt, highlights, score: 1, kind: "body" });
describe("search excerpts", () => {
  test("preserves server character offsets after emoji and escapes stored markup", () => {
    const html = renderToStaticMarkup(<Highlighted match={match("📚 备份 <script>bad</script>", [{ start: 2, end: 4 }])} fallback="" />);
    expect(html).toContain('📚 <mark tabindex="-1">备份</mark>');
    expect(html).toContain("&lt;script&gt;bad&lt;/script&gt;");
    expect(html).not.toContain("<script>");
  });
  test("invalid and overlapping highlight ranges never duplicate or lose text", () => {
    const html = renderToStaticMarkup(<Highlighted match={match("abcdef", [{ start: -1, end: 2 }, { start: 1, end: 3 }, { start: 2, end: 4 }, { start: 4, end: 10 }])} fallback="" />);
    expect(html).toBe('a<mark tabindex="-1">bc</mark>def');
  });
  test("metadata-only records retain a safe fallback", () => {
    expect(renderToStaticMarkup(<Highlighted fallback="https://example.com/?a=<b>" />)).toBe("https://example.com/?a=&lt;b&gt;");
  });
});
