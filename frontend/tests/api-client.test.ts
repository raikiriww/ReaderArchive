import { beforeEach, describe, expect, test } from "bun:test";

const store = new Map<string, string>();
const locationState = {
  pathname: "/archive",
  search: "?tag=work",
  href: "http://reader.local/archive?tag=work",
};

Object.defineProperty(globalThis, "window", {
  configurable: true,
  value: {
    localStorage: {
      getItem: (key: string) => store.get(key) ?? null,
      setItem: (key: string, value: string) => {
        store.set(key, value);
      },
      removeItem: (key: string) => {
        store.delete(key);
      },
    },
    location: locationState,
  },
});

const { ApiError, TOKEN_KEY, getAccessToken, readGenerated, setAccessToken } = await import("../src/api/client");

describe("frontend API client helpers", () => {
  beforeEach(() => {
    store.clear();
    locationState.pathname = "/archive";
    locationState.search = "?tag=work";
    locationState.href = "http://reader.local/archive?tag=work";
  });

  test("stores and clears access tokens", () => {
    setAccessToken("token-1");
    expect(getAccessToken()).toBe("token-1");
    expect(store.get(TOKEN_KEY)).toBe("token-1");

    setAccessToken("");
    expect(getAccessToken()).toBe("");
    expect(store.has(TOKEN_KEY)).toBe(false);
  });

  test("returns generated data and accepts empty 204 responses", async () => {
    await expect(readGenerated(generatedResult({ ok: true }, 200))).resolves.toEqual({ ok: true });
    await expect(readGenerated(generatedResult(undefined, 204))).resolves.toBeUndefined();
  });

  test("throws API errors and redirects authentication failures to login", async () => {
    setAccessToken("token-2");

    await expect(readGenerated(generatedResult(undefined, 401, { detail: "未登录" }))).rejects.toEqual(
      new ApiError("未登录", 401),
    );

    expect(getAccessToken()).toBe("");
    expect(locationState.href).toBe("/login?next=%2Farchive%3Ftag%3Dwork");
  });
});

function generatedResult<T>(data: T | undefined, status: number, error?: unknown) {
  return Promise.resolve({
    data,
    error,
    request: new Request("http://reader.local/api"),
    response: new Response(null, { status }),
  });
}

describe("archive search API", () => {
  test("sends every filter before pagination and supports request cancellation", async () => {
    const { searchArchives } = await import("../src/features/search/api");
    const originalFetch = globalThis.fetch;
    let requestedUrl = "";
    let requestedOptions: RequestInit | undefined;
    globalThis.fetch = (async (input: RequestInfo | URL, options?: RequestInit) => {
      requestedUrl = String(input); requestedOptions = options;
      return new Response(JSON.stringify({ items: [], total: 0 }), { status: 200 });
    }) as typeof fetch;
    setAccessToken("search-token");
    const controller = new AbortController();
    try {
      await searchArchives("备份", { content_type: "web", source: "rss", date_from: "2026-01-01", tags: ["research", "中文"], include_read: false, exact: true, sort: "oldest" }, 40, controller.signal);
      const url = new URL(requestedUrl, "http://reader.local");
      expect(url.pathname).toBe("/api/v1/archive-search");
      expect(url.searchParams.get("q")).toBe("备份");
      expect(url.searchParams.getAll("tags")).toEqual(["research", "中文"]);
      expect(url.searchParams.get("source")).toBe("rss");
      expect(url.searchParams.get("content_type")).toBe("web");
      expect(url.searchParams.get("include_read")).toBe("false");
      expect(url.searchParams.get("exact")).toBe("true");
      expect(url.searchParams.get("sort")).toBe("oldest");
      expect(url.searchParams.get("offset")).toBe("40");
      expect(url.searchParams.get("date_from")).toMatch(/^202[56]-/);
      expect(requestedOptions?.signal).toBe(controller.signal);
      expect((requestedOptions?.headers as Record<string, string>).Authorization).toBe("Bearer search-token");
    } finally { globalThis.fetch = originalFetch; }
  });
  test("surfaces search failures instead of treating them as an empty result", async () => {
    const { searchArchives } = await import("../src/features/search/api");
    const originalFetch = globalThis.fetch;
    globalThis.fetch = (async () => new Response(JSON.stringify({ detail: "搜索暂不可用" }), { status: 503 })) as typeof fetch;
    try {
      await expect(searchArchives("备份", { content_type: "all", source: "", date_from: "", tags: [], include_read: true, exact: false, sort: "relevance" }, 0)).rejects.toEqual(new ApiError("搜索暂不可用", 503));
    } finally { globalThis.fetch = originalFetch; }
  });
});


describe("search connection failures", () => {
  test("uses Chinese connection guidance for search and reading while preserving cancellation", async () => {
    const { searchArchives, readSearchText } = await import("../src/features/search/api");
    const originalFetch = globalThis.fetch;
    const filters = { content_type: "all", source: "", date_from: "", tags: [], include_read: true, exact: false, sort: "relevance" } as const;
    const search = () => searchArchives("备份", { ...filters, tags: [] }, 0);
    try {
      globalThis.fetch = (async () => { throw new TypeError("Failed to fetch"); }) as typeof fetch;
      await expect(search()).rejects.toEqual(new ApiError("无法连接服务器，请检查网络后重试。", 0));
      await expect(readSearchText("task-1")).rejects.toEqual(new ApiError("无法连接服务器，请检查网络后重试。", 0));
      const cancelled = new DOMException("The operation was aborted.", "AbortError");
      globalThis.fetch = (async () => { throw cancelled; }) as typeof fetch;
      await expect(search()).rejects.toBe(cancelled);
      await expect(readSearchText("task-1")).rejects.toBe(cancelled);
    } finally { globalThis.fetch = originalFetch; }
  });
});

test("rearchive sends the manual choice and defaults to automatic", async () => {
  const { rearchiveTask } = await import("../src/api/client");
  const originalFetch = globalThis.fetch;
  const choices: boolean[] = [];
  globalThis.fetch = (async (_input: unknown, init?: RequestInit) => {
    choices.push(JSON.parse(String(init?.body)).prepare_manually);
    expect(new Headers(init?.headers).get("Content-Type")).toBe("application/json");
    return Response.json({ task_id: "existing-task" });
  }) as typeof fetch;
  try {
    await rearchiveTask("existing-task", true);
    await rearchiveTask("existing-task");
    expect(choices).toEqual([true, false]);
  } finally {
    globalThis.fetch = originalFetch;
  }
});
