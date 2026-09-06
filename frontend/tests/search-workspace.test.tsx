import { expect, test } from "bun:test";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderToStaticMarkup } from "react-dom/server";
import { archiveTask } from "./fixtures";
import { searchDefaults } from "../src/features/search/state";
import { SearchWorkspace } from "../src/features/search/SearchWorkspace";

// A reader deep link needs to fetch its result before it can restore the article.
// Its loading state must remain visible, including when the fetch cannot finish.
test("reader deep links show search loading content while restoring the article", () => {
  const previous = Object.getOwnPropertyDescriptor(globalThis, "window");
  Object.defineProperty(globalThis, "window", {
    configurable: true,
    value: { location: { href: `http://reader.local/?reader_search=${encodeURIComponent(JSON.stringify({ query: "缓存收费", selectedId: "article", reading: true }))}` } },
  });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  try {
    const html = renderToStaticMarkup(
      <QueryClientProvider client={client}>
        <SearchWorkspace open focusRequest={0} tags={[]} onClose={() => {}} onMarkRead={async () => {}} />
      </QueryClientProvider>,
    );
    expect(html).toContain("正在查找存档");
    expect(html).toContain('<header class="archive-search-heading">');
    expect(html).toContain('<div class="archive-search-workspace ">');
  } finally {
    client.clear();
    if (previous) Object.defineProperty(globalThis, "window", previous);
    else Reflect.deleteProperty(globalThis, "window");
  }
});

test("leading semantic answers remain visible before direct matches", () => {
  const previous = Object.getOwnPropertyDescriptor(globalThis, "window");
  Object.defineProperty(globalThis, "window", {
    configurable: true,
    value: { location: { href: `http://reader.local/?reader_search=${encodeURIComponent(JSON.stringify({ query: "缓存收费" }))}` } },
  });
  const client = new QueryClient();
  const possible = { excerpt: "激活请求也会收费", score: 1, kind: "semantic" as const, strength: "possible" as const, highlights: [] };
  client.setQueryData(["archive-search", "缓存收费", searchDefaults, 0], {
    items: [
      archiveTask({ task_id: "semantic-first", title: "最高相关答案", search_match: possible }),
      archiveTask({ task_id: "direct", title: "原词命中", search_match: { ...possible, kind: "body", strength: "strong" } }),
      archiveTask({ task_id: "semantic-later", title: "其余相关", search_match: possible }),
    ],
    total: 3, limit: 20, offset: 0, has_more: false, mode: "hybrid", total_is_exact: false,
    coverage: { total: 3, ready: 3, pending: 0, unavailable: 0 },
  });
  try {
    const html = renderToStaticMarkup(
      <QueryClientProvider client={client}>
        <SearchWorkspace open focusRequest={0} tags={[]} onClose={() => {}} onMarkRead={async () => {}} />
      </QueryClientProvider>,
    );
    const articles = [...html.matchAll(/<article class="archive-search-result [^>]*>/g)].map((match) => match[0]);
    expect(articles).toHaveLength(3);
    expect(articles[0]).not.toContain("hidden");
    expect(articles[1]).not.toContain("hidden");
    expect(articles[2]).toContain("hidden");
    expect(html).toContain("展开其余 1 条可能相关");
  } finally {
    client.clear();
    if (previous) Object.defineProperty(globalThis, "window", previous);
    else Reflect.deleteProperty(globalThis, "window");
  }
});
